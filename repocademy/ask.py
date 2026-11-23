"""'Ask the repo': retrieve real code, answer from it, and keep only citations that point at retrieved code."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator
from pathlib import Path

from .llm import LLM
from .facts import check_claims, facts_for, load_graph
from .retrieval import Chunk, Index, tokens

_INDEX_CACHE: dict[str, Index] = {}
_CITE = re.compile(r"\[([\w./@+-]+\.\w+|README[\w.]*):(\d+)(?:-(\d+))?\]")

SYSTEM = ("You explain the {repo} codebase to a developer. Use ONLY the code excerpts and call-graph facts given. "
          "Cite every claim with [path:line] copied from an excerpt header or a fact. Wrap code names in backticks. "
          "Only say A calls B if the facts or code show it. If the excerpts don't answer the question, say so. "
          "Answer in 2-4 short sentences, under 90 words.")
_ANSWERS: dict[tuple, list[dict]] = {}


def load_index(course_dir: Path) -> Index:
    key = str(course_dir)
    p = course_dir / "index.json"
    if key not in _INDEX_CACHE:
        raw = json.loads(p.read_text()) if p.exists() else []
        _INDEX_CACHE[key] = Index([Chunk(**c) for c in raw])
    return _INDEX_CACHE[key]


def _window(c: Chunk, question: str, max_lines: int = 16) -> tuple[int, list[str]]:
    """The most relevant slice of a chunk: its first line (signature) plus the densest run of question words."""
    lines = c.text.splitlines()
    if len(lines) <= max_lines:
        return c.start, lines
    terms = {t for t in tokens(question)}
    score = [sum(1 for t in tokens(ln) if t in terms) for ln in lines]
    best, best_i = -1, 1
    for i in range(1, len(lines) - max_lines + 2):
        v = sum(score[i: i + max_lines - 1])
        if v > best:
            best, best_i = v, i
    if best <= 0 or best_i == 1:
        return c.start, lines[:max_lines]
    return c.start + best_i - 1, [lines[0]] + ["…"] + lines[best_i: best_i + max_lines - 2]


def _excerpt(c: Chunk, question: str = "", max_lines: int = 16) -> str:
    first, lines = _window(c, question, max_lines)
    rows = []
    n = c.start
    for i, ln in enumerate(lines):
        if ln == "…":
            rows.append("   …")
            n = first
            continue
        rows.append(f"{n}: {ln}")
        n += 1
    return f"### [{c.file}:{c.start}-{c.end}] {c.title}\n" + "\n".join(rows)


def validate_citations(text: str, hits: list[Chunk], repo_url: str, sha: str,
                       extra: list[tuple[str, int]] | None = None) -> tuple[str, list[dict], int]:
    """Keep citations that fall inside a retrieved chunk (±2 lines) or at a call-graph fact we supplied; drop the rest."""
    cites, removed = [], 0
    extra_set = set(extra or [])

    def repl(m):
        nonlocal removed
        path, a = m.group(1), int(m.group(2))
        b = int(m.group(3)) if m.group(3) else a
        ok = (path, a) in extra_set or any(c.file == path and c.start - 2 <= a <= c.end + 2 for c in hits)
        if ok:
            cites.append({"file": path, "start": a, "end": b, "url": f"{repo_url}/blob/{sha}/{path}#L{a}" + (f"-L{b}" if b != a else "")})
            return f"[{path}:{a}" + (f"-{b}" if b != a else "") + "]"
        removed += 1
        return ""

    cleaned = _CITE.sub(repl, text)
    return re.sub(r"[ \t]+([.,;])", r"\1", cleaned).strip(), cites, removed


def fallback_answer(hits: list[Chunk]) -> str:
    if not hits:
        return "I couldn't find code matching that. Try naming a function, class or file (for example `Session.send`)."
    out = ["Here's where the code that matches your question lives:"]
    for c in hits[:4]:
        desc = f": {c.summary}" if c.summary else ""
        out.append(f"- **`{c.title}`**{desc} [{c.file}:{c.start}-{c.end}]")
    out.append("\n(No language model is configured, so this is a search result rather than a written answer.)")
    return "\n".join(out)


def _sources(hits: list[Chunk], repo: dict, question: str) -> list[dict]:
    out = []
    for c in hits:
        first, lines = _window(c, question, 10)
        rows, n = [], c.start
        for ln in lines:
            if ln == "…":
                rows.append([None, "…"])
                n = first + 1
                continue
            rows.append([n, ln])
            n += 1
        out.append({"file": c.file, "start": c.start, "end": c.end, "title": c.title, "summary": c.summary,
                    "rows": rows[:10],
                    "url": f"{repo['url']}/blob/{repo['sha']}/{c.file}#L{c.start}-L{c.end}"})
    return out


def _norm_q(q: str) -> str:
    return " ".join(re.findall(r"[\w.]+", q.lower()))


def ask(course: dict, course_dir: Path, question: str, llm: LLM | None, history: list[dict] | None = None,
        lock=None) -> Iterator[dict]:
    """Stream events: sources (immediately), status, tokens, final. `lock` (optional) guards the model and is
    taken only after the sources are out, so retrieved code shows instantly even while intros are being written."""
    t0 = time.time()
    repo = course["repo"]
    key = (str(course_dir), repo.get("sha"), _norm_q(question), llm.label if llm else None)
    if key in _ANSWERS and not history:
        for ev in _ANSWERS[key]:
            yield {**ev, "cached": True}
        return
    idx = load_index(course_dir)
    hits = [c for _s, c in idx.search(question, k=6)]
    events: list[dict] = []
    ev = {"type": "sources", "sources": _sources(hits, repo, question), "ms": int((time.time() - t0) * 1000)}
    events.append(ev)
    yield ev
    g = load_graph(course_dir)
    hit_ids = {c.id for c in hits}
    if llm is None or not hits:
        text = fallback_answer(hits)
        cleaned, cites, removed = validate_citations(text, hits, repo["url"], repo["sha"])
        ev = {"type": "final", "text": cleaned, "citations": cites, "removed": removed, "model": None, "corrections": []}
        yield ev
        return
    top = hits[:3]
    # graph facts for the symbols we show, plus any symbol the question names
    ids = [c.id for c in top if g and c.id in g.symbols]
    if g:
        for name in re.findall(r"[A-Za-z_][\w.]*[A-Za-z0-9_]", question):
            sid = g.resolve(name, hit_ids) if (len(name) > 3 and ("_" in name or "." in name or name[:1].isupper() or name in g.by_name)) else None
            if sid and sid not in ids:
                ids.append(sid)
    facts = facts_for(g, ids[:4]) if g else []
    allowed_extra = [(f, int(n)) for line in facts for f, n in re.findall(r"\[([^\]:]+):(\d+)\]", line)]
    context = "\n\n".join(_excerpt(c, question) for c in top)
    if facts:
        context += "\n\n### Call-graph facts (from static analysis)\n" + "\n".join("- " + f for f in facts)
    msgs = [{"role": "system", "content": SYSTEM.format(repo=f"{repo['owner']}/{repo['name']}")}]
    for h in (history or [])[-2:]:
        if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str):
            msgs.append({"role": h["role"], "content": h["content"][:600]})
    msgs.append({"role": "user", "content": f"{context}\n\nQuestion: {question}"})
    buf = []
    first_token_ms = None
    acquired = False
    if lock is not None:
        acquired = lock.acquire(blocking=False)
        if not acquired:
            yield {"type": "status", "text": "the model is busy writing chapter intros; waiting for it…"}
            acquired = lock.acquire(timeout=90)
            if not acquired:
                text = fallback_answer(hits)
                cleaned, cites, removed = validate_citations(text, hits, repo["url"], repo["sha"])
                yield {"type": "final", "text": cleaned, "citations": cites, "removed": removed, "model": None,
                       "corrections": [], "error": "busy"}
                return
    try:
        for piece in llm.stream(msgs, max_tokens=220, purpose="chat"):
            if first_token_ms is None:
                first_token_ms = int((time.time() - t0) * 1000)
            buf.append(piece)
            yield {"type": "token", "text": piece}
    except Exception as e:  # model down mid-answer: fall back to search results
        if not buf:
            text = fallback_answer(hits)
            cleaned, cites, removed = validate_citations(text, hits, repo["url"], repo["sha"])
            yield {"type": "final", "text": cleaned, "citations": cites, "removed": removed, "model": None,
                   "corrections": [], "error": type(e).__name__}
            return
    finally:
        if acquired:
            lock.release()
    text = "".join(buf)
    text, corrections, extra = check_claims(text, g, hit_ids | set(ids))
    cleaned, cites, removed = validate_citations(text, hits, repo["url"], repo["sha"], allowed_extra + extra)
    if not cites:  # an answer with no valid citation gets the evidence attached explicitly
        cleaned += "\n\nSources: " + " ".join(f"[{c.file}:{c.start}-{c.end}]" for c in hits[:3])
        cleaned, cites, more = validate_citations(cleaned, hits, repo["url"], repo["sha"], allowed_extra + extra)
        removed += more
    ev = {"type": "final", "text": cleaned, "citations": cites, "removed": removed, "model": llm.label,
          "corrections": corrections, "first_token_ms": first_token_ms, "total_ms": int((time.time() - t0) * 1000)}
    events.append(ev)
    if len(_ANSWERS) > 500:
        _ANSWERS.clear()
    _ANSWERS[key] = events
    yield ev
