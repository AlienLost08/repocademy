"""Optional AI narration for chapters, fenced in by the facts.

The model only gets facts we computed (names, files, docstrings, call relations) and must write a short
intro. Every `backticked` name it writes must exist in the repository, otherwise the text is rejected and
the deterministic template stays. The verdicts, code, quizzes and links never come from the model.
"""

from __future__ import annotations

import re

from .llm import LLM

SYSTEM = ("You write the opening lines of a chapter in a course that teaches a codebase to a new developer. "
          "Use ONLY the facts provided. Wrap every code name in backticks, spelled exactly as in the facts. "
          "Write 2 plain sentences, at most 50 words. Start with the most important code name listed in THIS chapter's facts, "
          "never with 'This chapter', 'In this chapter' or 'Welcome'. Say what the code does and why a reader should care. "
          "Only say a class has a method if the facts list it as that class's method. "
          "No headings, lists, greetings, line numbers or hype words like crucial, powerful, robust, delve, intricate.")
_BAD = re.compile(r"(?i)\b(as an ai|i'm|i am|i think|in this course we|let me|sorry|without a docstring|best clues)\b|^#|\n\s*[-*] ")
_HYPE = r"(?:crucial|essential|vital|key|powerful|robust|intricate|seamless|pivotal)"
_FILLER = [(re.compile(r"(?i)\bplays an? " + _HYPE + r" role in\b"), "handles"),
           (re.compile(r"(?i)\b(provides|offers|has|includes|defines) " + _HYPE + r"\s+"), r"\1 "),
           (re.compile(r"(?i)\b" + _HYPE + r",?\s+and\s+"), ""),
           (re.compile(r"(?i)\b(an?|the|its|their|this) " + _HYPE + r"\s+"), r"\1 "),
           (re.compile(r"(?i)\bwe delve into\b"), "we look at"), (re.compile(r"(?i)\bdelves? into\b"), "covers")]
_GENERIC = re.compile(r"(?i)^(?:this|the) chapter|^welcome|^chapter\b|\bin (?:this )?chapter\b|\bin chapter \d")
_IN_CLASS = re.compile(r"`(?P<c>[A-Z][\w$]*)`\s+class\b[^.]*?\b(?:includes|contains|has|provides|offers|defines|exposes|with)\b(?P<rest>[^.]*)")
_IN_FILE = re.compile(r"`(?P<f>[\w./-]+\.(?:py|js|ts|mjs|cjs|tsx))`\s+(?:file\s+)?(?:contains|defines|includes|holds|has)\b(?P<rest>[^.]*)")


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
    desc = f" ({r['description']})" if r.get("description") and ch["kind"] == "overview" else ""
    lines = [f"Repository: {r['owner']}/{r['name']}" + desc,
             f"Chapter {ch['num']}: {ch['title']}: {ch['subtitle']}"]
    if ch.get("files"):
        lines.append("Files: " + ", ".join(f"`{f}`" for f in ch["files"][:6]))
    if ch["kind"] == "trace":
        lines.append("Call path: " + " -> ".join(f"`{x}`" for x in [ch["trace"][0]["caller"]] + [s["callee"] for s in ch["trace"]]))
    for s in ch.get("sections", [])[:6]:
        lead = "" if "without a docstring" in s["lead"] else s["lead"]
        lines.append(f"- `{s['symbol']}` ({s['kind']} in `{s['file']}`)" + (f": {lead}" if lead else ""))
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


def structure_problems(text: str, course: dict) -> list[str]:
    """Claims about where code lives, checked against the parsed source: "`C` class includes `m`" needs C.m,
    "`file.py` contains `X`" needs X defined in that file."""
    syms = course.get("symbols", [])
    quals = {s["name"] for s in syms}
    by_name: dict[str, list[dict]] = {}
    for s in syms:
        by_name.setdefault(s["name"].rsplit(".", 1)[-1], []).append(s)
    bad = []
    for m in _IN_CLASS.finditer(text):
        cls = m.group("c")
        if cls not in quals:
            continue
        for name in re.findall(r"`([\w$#]+)(?:\(\))?`", m.group("rest")):
            if f"{cls}.{name}" in quals or name not in by_name:
                continue
            # a known symbol that is not a member of this class (e.g. a module-level helper)
            if all("." not in x["name"] or not x["name"].startswith(cls + ".") for x in by_name[name]):
                bad.append(f"{name} is not part of {cls}")
    for m in _IN_FILE.finditer(text):
        f = m.group("f")
        files = {s["file"] for s in syms}
        full = next((x for x in files if x == f or x.endswith("/" + f)), None)
        if not full:
            continue
        for name in re.findall(r"`([\w$#.]+)(?:\(\))?`", m.group("rest")):
            cands = [x for x in syms if x["name"] == name or x["name"].rsplit(".", 1)[-1] == name]
            if cands and not any(x["file"] == full for x in cands):
                bad.append(f"{name} is not defined in {f}")
    return bad


_DROP_SENTENCE = re.compile(r"(?i)\b(?:this|the) chapter\b|\bin (?:this )?chapter\b|^welcome\b|\b(?:is|are) (?:crucial|essential|vital|key|important|pivotal) (?:for|to|in)\b|\bis used for (?:any|every|developers?)\b")


def drop_generic(text: str) -> str:
    """Remove sentences that talk about the chapter instead of the code, or only praise it."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z`])", text.strip())
    kept = [p for p in parts if not _DROP_SENTENCE.search(p)]
    return " ".join(kept).strip()


def final_check(text: str, course: dict, allowed: set[str]) -> str | None:
    """Re-check a stored intro with the current rules; returns the cleaned text or None to rewrite it."""
    t = drop_generic(polish(text, {}))
    if len(t) < 40:
        return None
    ok, _bad = check(t, allowed)
    if not ok or structure_problems(t, course):
        return None
    if len(set(re.split(r"(?<=[.!?])\s+", t))) < len(re.split(r"(?<=[.!?])\s+", t)):  # repeated sentences
        return None
    return t


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
    for pat, rep in _FILLER:
        t = pat.sub(rep, t)
    t = re.sub(r"\b([Aa])n ([b-df-hj-np-tv-z])", r"\1 \2", t)
    t = re.sub(r"\b([Aa]) ([aeio])", r"\1n \2", t)
    t = re.sub(r"\b(?:we|We) delve into\b", "we look at", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return trim(t[:1].upper() + t[1:], 3)


def narrate_chapter(llm: LLM, course: dict, ch: dict, allowed: set[str]) -> tuple[str | None, list[str]]:
    facts = facts_for(course, ch)
    allowed = allowed | {n.strip() for n in re.findall(r"`([^`]+)`", facts)}
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": facts + "\n\nWrite the chapter introduction now."}]
    problems: list[str] = []
    for attempt in range(3):
        try:
            text = llm.chat(msgs, max_tokens=120, temperature=0.2 if attempt == 0 else 0.0)
        except Exception as e:  # network / model errors -> keep the template
            return None, [f"error: {type(e).__name__}"]
        text = polish(re.sub(r"\s+", " ", text).strip().strip('"'), ch)
        if attempt < 2 and _GENERIC.search(text):
            problems.append("rejected (generic opener)")
            msgs.append({"role": "assistant", "content": text})
            msgs.append({"role": "user", "content": "Don't open with 'This chapter' or 'Welcome'. Start with a code name from the facts and say what it does. 2 sentences."})
            continue
        text = drop_generic(text)
        ok, bad = check(text, allowed)
        if ok:
            bad = structure_problems(text, course)
            if not bad:
                if len(set(re.split(r"(?<=[.!?])\s+", text))) < len(re.split(r"(?<=[.!?])\s+", text)):
                    bad = ["repeats itself"]
                else:
                    return text, problems
            problems.append(f"rejected ({'; '.join(bad[:2])})")
            msgs.append({"role": "assistant", "content": text})
            msgs.append({"role": "user", "content": "That is wrong: " + "; ".join(bad[:3]) +
                         ". Rewrite it, only attributing methods and files as the facts state."})
            continue
        problems.append(f"rejected ({', '.join(bad[:3])})")
        msgs.append({"role": "assistant", "content": text})
        if bad == ["length/style"]:
            msgs.append({"role": "user", "content": "Rewrite it as 2 plain sentences, under 50 words, starting with a code name, no lists or headings."})
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
