"""'Ask the repo': retrieve real code, answer from it, and keep only citations that point at retrieved code."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

from .llm import LLM
from .retrieval import Chunk, Index

_INDEX_CACHE: dict[str, Index] = {}
_CITE = re.compile(r"\[([\w./@+-]+\.\w+|README[\w.]*):(\d+)(?:-(\d+))?\]")

SYSTEM = ("You are a guide to the {repo} codebase. Answer the question using ONLY the code excerpts. "
          "After each claim, cite the excerpt it comes from as [path:line], copying a path and line from the excerpt "
          "headers, e.g. 'Redirects are followed in `resolve_redirects` [src/pkg/sessions.py:159].' "
          "If the excerpts don't answer it, say so and point to the closest excerpt. Be concise: under 120 words.")


def load_index(course_dir: Path) -> Index:
    key = str(course_dir)
    p = course_dir / "index.json"
    if key not in _INDEX_CACHE:
        raw = json.loads(p.read_text()) if p.exists() else []
        _INDEX_CACHE[key] = Index([Chunk(**c) for c in raw])
    return _INDEX_CACHE[key]


def _excerpt(c: Chunk, max_lines: int = 32) -> str:
    lines = c.text.splitlines()[:max_lines]
    body = "\n".join(f"{c.start + i}: {ln}" for i, ln in enumerate(lines))
    return f"### [{c.file}:{c.start}-{c.start + len(lines) - 1}] {c.title}\n{body}"


def validate_citations(text: str, hits: list[Chunk], repo_url: str, sha: str) -> tuple[str, list[dict], int]:
    """Keep citations that fall inside a retrieved chunk (±2 lines); drop the rest."""
    cites, removed = [], 0

    def repl(m):
        nonlocal removed
        path, a = m.group(1), int(m.group(2))
        b = int(m.group(3)) if m.group(3) else a
        for c in hits:
            if c.file == path and c.start - 2 <= a <= c.end + 2:
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


def ask(course: dict, course_dir: Path, question: str, llm: LLM | None, history: list[dict] | None = None) -> Iterator[dict]:
    idx = load_index(course_dir)
    hits = [c for _s, c in idx.search(question, k=6)]
    repo = course["repo"]
    yield {"type": "sources", "sources": [{"file": c.file, "start": c.start, "end": c.end, "title": c.title,
                                           "url": f"{repo['url']}/blob/{repo['sha']}/{c.file}#L{c.start}-L{c.end}"} for c in hits]}
    if llm is None or not hits:
        text = fallback_answer(hits)
        cleaned, cites, removed = validate_citations(text, hits, repo["url"], repo["sha"])
        yield {"type": "final", "text": cleaned, "citations": cites, "removed": removed, "model": None}
        return
    context = "\n\n".join(_excerpt(c) for c in hits[:4])
    msgs = [{"role": "system", "content": SYSTEM.format(repo=f"{repo['owner']}/{repo['name']}")}]
    for h in (history or [])[-4:]:
        if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str):
            msgs.append({"role": h["role"], "content": h["content"][:1200]})
    msgs.append({"role": "user", "content": f"Code excerpts:\n\n{context}\n\nQuestion: {question}"})
    buf = []
    try:
        for piece in llm.stream(msgs, max_tokens=320):
            buf.append(piece)
            yield {"type": "token", "text": piece}
    except Exception as e:  # model down mid-answer: fall back to search results
        if not buf:
            text = fallback_answer(hits)
            cleaned, cites, removed = validate_citations(text, hits, repo["url"], repo["sha"])
            yield {"type": "final", "text": cleaned, "citations": cites, "removed": removed, "model": None, "error": type(e).__name__}
            return
    cleaned, cites, removed = validate_citations("".join(buf), hits, repo["url"], repo["sha"])
    if not cites:  # an answer with no valid citation gets the evidence attached explicitly
        cleaned += "\n\nSources: " + " ".join(f"[{c.file}:{c.start}-{c.end}]" for c in hits[:3])
        cleaned, cites, more = validate_citations(cleaned, hits, repo["url"], repo["sha"])
        removed += more
    yield {"type": "final", "text": cleaned, "citations": cites, "removed": removed, "model": llm.label}
