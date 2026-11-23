"""Optional AI narration for chapters, fenced in by the facts.

The model only gets facts we computed (names, files, docstrings, call relations) and must write a short
intro. Every `backticked` name it writes must exist in the repository, otherwise the text is rejected and
the deterministic template stays. The verdicts, code, quizzes and links never come from the model.
"""

from __future__ import annotations

import re

from .llm import LLM

SYSTEM = ("You write short, accurate introductions for chapters of a course that teaches a codebase to a new developer. "
          "Use ONLY the facts provided. Wrap every code name in backticks, spelled exactly as in the facts. "
          "Write 2 or 3 plain sentences, at most 70 words. No headings, no lists, no greetings, no line numbers.")
_BAD = re.compile(r"(?i)\b(as an ai|i'm|i am|i think|in this course we|let me|sorry)\b|^#|\n\s*[-*] ")


def allowed_names(course: dict) -> set[str]:
    ok = {course["repo"]["name"], course["repo"]["owner"]}
    for s in course.get("symbols", []):
        ok.add(s["name"])
        ok.update(s["name"].split("."))
        ok.add(s["file"])
        ok.add(s["file"].rsplit("/", 1)[-1])
    for ch in course["chapters"]:
        for f in ch.get("files", []):
            ok.add(f)
            ok.add(f.rsplit("/", 1)[-1])
            ok.add(f.rsplit("/", 1)[-1].rsplit(".", 1)[0])
        for d in ch.get("dependencies", []) or []:
            ok.add(d["name"])
    for n in course.get("graph", {}).get("nodes", []):
        ok.add(n["dir"])
        ok.add(n["dir"].rsplit("/", 1)[-1])
    return {x for x in ok if x}


def check(text: str, allowed: set[str]) -> tuple[bool, list[str]]:
    text = text.strip()
    if not (40 <= len(text) <= 900) or _BAD.search(text):
        return False, ["length/style"]
    bad = []
    for name in re.findall(r"`([^`]+)`", text):
        n = name.strip().rstrip("()")
        n = re.sub(r"\(.*\)$", "", n)
        if n not in allowed and n.split(".")[-1] not in allowed and not n.endswith("/") and n.rstrip("/") not in allowed:
            bad.append(name)
    return (not bad), bad


def facts_for(course: dict, ch: dict) -> str:
    r = course["repo"]
    lines = [f"Repository: {r['owner']}/{r['name']}" + (f" ({r['description']})" if r.get("description") else ""),
             f"Chapter {ch['num']}: {ch['title']}: {ch['subtitle']}"]
    if ch.get("files"):
        lines.append("Files: " + ", ".join(f"`{f}`" for f in ch["files"][:6]))
    if ch["kind"] == "trace":
        lines.append("Call path: " + " -> ".join(f"`{x}`" for x in [ch["trace"][0]["caller"]] + [s["callee"] for s in ch["trace"]]))
    for s in ch.get("sections", [])[:6]:
        lines.append(f"- `{s['symbol']}` ({s['kind']} in `{s['file']}`): {s['lead']}")
        for f in s.get("facts", [])[1:3]:
            lines.append(f"    {f}")
    if ch["kind"] == "overview":
        lines.append("Languages: " + ", ".join(f"{x['name']} {x['pct']}%" for x in ch.get("languages", [])))
        if ch.get("dependencies"):
            lines.append("Main outside libraries: " + ", ".join(f"`{d['name']}`" for d in ch["dependencies"][:4]))
        lines.append("Top-level folders: " + ", ".join(f"`{t['path']}` ({t['hint']})" for t in ch.get("layout", [])[:6]))
    if ch["kind"] == "tests":
        lines.append(f"Test command: `{ch.get('test_command')}`; framework: {ch.get('test_framework') or 'unknown'}")
    return "\n".join(lines)


def trim(text: str, max_sentences: int = 4) -> str:
    """Keep whole sentences only (drops a sentence cut off by the token limit)."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z`])", text.strip())
    if parts and not re.search(r"[.!?]$", parts[-1]):
        parts = parts[:-1]
    return " ".join(parts[:max_sentences]).strip()


def polish(text: str, ch: dict) -> str:
    """Drop the filler small models like to open with ("In Chapter 3, we delve into…")."""
    t = text.strip()
    m = re.match(r"^Chapter\s+\d+\s*[:.-]\s*", t)
    if m:  # "Chapter 6: Exceptions This chapter…" -> drop the heading the model repeated
        t = t[m.end():]
        for head in (ch.get("title", "").replace("`", ""), ch.get("subtitle", "").replace("`", "")):
            if head and t.lower().startswith(head.lower()):
                t = t[len(head):].lstrip(" :.-")
    t = re.sub(r'^In (?:this )?[Cc]hapter(?:\s+\d+)?,?\s*(?:"[^"]{1,80}"|[^,"]{1,60})?,?\s*we\s+(?:delve into|explore|dive into|look at)\s+',
               "This chapter covers ", t)
    t = re.sub(r"\b(?:we|We) delve into\b", "we look at", t)
    t = re.sub(r"\bdelves into\b", "covers", t)
    return trim(t[:1].upper() + t[1:], 3)


def narrate_chapter(llm: LLM, course: dict, ch: dict, allowed: set[str]) -> tuple[str | None, list[str]]:
    facts = facts_for(course, ch)
    allowed = allowed | {n.strip() for n in re.findall(r"`([^`]+)`", facts)}
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": facts + "\n\nWrite the chapter introduction now."}]
    problems: list[str] = []
    for attempt in range(2):
        try:
            text = llm.chat(msgs, max_tokens=160, temperature=0.2 if attempt == 0 else 0.0)
        except Exception as e:  # network / model errors -> keep the template
            return None, [f"error: {type(e).__name__}"]
        text = polish(re.sub(r"\s+", " ", text).strip().strip('"'), ch)
        ok, bad = check(text, allowed)
        if ok:
            return text, problems
        problems.append(f"rejected ({', '.join(bad[:3])})")
        msgs.append({"role": "assistant", "content": text})
        if bad == ["length/style"]:
            msgs.append({"role": "user", "content": "Rewrite it as 2 or 3 plain sentences, under 70 words, no lists or headings."})
        else:
            msgs.append({"role": "user", "content": "Some names you used are not in the facts: " + ", ".join(bad[:5]) +
                         ". Rewrite using only names from the facts."})
    return None, problems


def narrate_course(course: dict, llm: LLM, save=None, progress=None, lock=None) -> dict:
    """Narrate every chapter. `lock` (optional) is held per chapter, so chat requests can interleave."""
    allowed = allowed_names(course)
    course["narration"] = {"status": "running", "model": llm.label, "accepted": 0, "rejected": 0}
    if save:
        save(course)
    for ch in course["chapters"]:
        if ch["kind"] == "next":
            continue
        if progress:
            progress(ch["num"], len(course["chapters"]))
        if lock is not None:
            with lock:
                text, problems = narrate_chapter(llm, course, ch, allowed)
        else:
            text, problems = narrate_chapter(llm, course, ch, allowed)
        if text:
            ch["narrative"] = {"text": text, "model": llm.label}
            course["narration"]["accepted"] += 1
        else:
            course["narration"]["rejected"] += 1
        if save:
            save(course)
    course["narration"]["status"] = "done"
    if save:
        save(course)
    return course
