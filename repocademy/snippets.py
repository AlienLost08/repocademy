"""Cut real code out of files, with real line numbers, for the course pages."""

from __future__ import annotations

import re

from .model import Symbol

MAX_LINES = 36


def doc_summary(doc: str, max_len: int = 220) -> str:
    """First meaningful sentence of a docstring / JSDoc, without rst/markdown noise."""
    if not doc:
        return ""
    lines = []
    for ln in doc.strip().splitlines():
        s = ln.strip()
        if not s:
            if lines:
                break
            continue
        if re.fullmatch(r"[~=\-^*#_]{3,}", s):  # rst underline
            lines = []
            continue
        if re.fullmatch(r"[\w.]+", s) and not lines:  # "requests.sessions" title line
            continue
        if s.startswith((":param", ":return", ":rtype", ":raises", "@", "Args:", "Returns:", "Usage::", ">>>", "..")):
            break
        lines.append(s)
    text = " ".join(lines)
    text = re.sub(r":(class|func|meth|attr|data|exc|mod|ref|obj):`~?([^`]+)`", r"`\2`", text)
    text = re.sub(r"``([^`]+)``", r"`\1`", text)
    text = re.sub(r"`([^`<]+?)\s*<[^>`]+>`_?", r"`\1`", text)  # rst `Request <Request>` refs
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    first = m.group(1) if m and len(m.group(1)) >= 20 else text
    if len(first) > max_len:
        first = first[: max_len - 1].rsplit(" ", 1)[0] + "…"
    return first


def lines_of(text: str) -> list[str]:
    return text.splitlines()


def _leading_comment_start(src: list[str], start: int) -> int:
    """Include a JSDoc / comment block directly above a symbol."""
    i = start - 2
    if i < 0 or not src[i].strip().endswith(("*/", "//")) and not src[i].strip().startswith("//"):
        return start
    while i >= 0 and (src[i].strip().startswith(("/*", "*", "//")) or src[i].strip().endswith("*/")):
        if src[i].strip().startswith("/*"):
            return i + 1
        i -= 1
    return i + 2


def symbol_snippet(src: list[str], sym: Symbol, children: list[Symbol] | None = None, max_lines: int = MAX_LINES) -> dict:
    """Returns {"lines": [[n, text] | [None, "…"]], "start", "end", "truncated"}.

    Classes are shown as an outline: header + docstring + one signature line per method.
    """
    start = _leading_comment_start(src, sym.start) if sym.file.endswith((".js", ".ts", ".tsx", ".mjs", ".cjs", ".jsx")) else sym.start
    end = min(sym.end, len(src))
    out: list[list] = []
    if sym.kind == "class" and children and (end - start + 1) > max_lines:
        first_child = min(c.start for c in children)
        head_end = min(first_child - 1, start + 20)
        for n in range(start, head_end + 1):
            out.append([n, src[n - 1]])
        shown = 0
        for c in sorted(children, key=lambda c: c.start):
            if shown >= 14:
                out.append([None, f"    … {len(children) - shown} more methods"])
                break
            sig_line = c.start
            # skip decorators so we show the def line
            while sig_line <= c.end and not re.search(r"\b(def|function|async|get|set|static)\b|\w+\s*\(", src[sig_line - 1]):
                sig_line += 1
            if sig_line > c.end:
                sig_line = c.start
            if out and out[-1][0] is not None and out[-1][0] != sig_line - 1:
                out.append([None, "…"])
            out.append([sig_line, src[sig_line - 1]])
            shown += 1
        return {"lines": _dedent(out), "start": start, "end": end, "truncated": True}
    n_lines = end - start + 1
    stop = end if n_lines <= max_lines else start + max_lines - 1
    for n in range(start, stop + 1):
        out.append([n, src[n - 1]])
    if stop < end:
        out.append([None, f"… {end - stop} more lines"])
    return {"lines": _dedent(out), "start": start, "end": end, "truncated": stop < end}


def window(src: list[str], focus: int, sym: Symbol, before: int = 8, after: int = 6) -> dict:
    """Lines around a call site, clipped to the enclosing symbol, always including the signature line."""
    start, end = sym.start, min(sym.end, len(src))
    lo, hi = max(start, focus - before), min(end, focus + after)
    out = []
    if lo > start:
        out.append([start, src[start - 1]])
        if lo > start + 1:
            out.append([None, "…"])
    for n in range(lo, hi + 1):
        out.append([n, src[n - 1]])
    if hi < end:
        out.append([None, "…"])
    return {"lines": _dedent(out), "start": start, "end": end, "truncated": True, "focus": focus}


def _dedent(rows: list[list]) -> list[list]:
    texts = [t for n, t in rows if n is not None and t.strip()]
    if not texts:
        return rows
    pad = min(len(t) - len(t.lstrip()) for t in texts)
    if pad == 0:
        return rows
    return [[n, t[pad:] if n is not None and len(t) >= pad and not t[:pad].strip() else t] for n, t in rows]
