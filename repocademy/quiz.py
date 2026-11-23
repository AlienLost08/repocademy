"""Deterministic quiz generators. Every question is built from facts in the code, never from a model.

Question shapes (all graded instantly in the browser):
  mcq       {prompt, options[], answer: index, explain}
  bug       {prompt, code (mutated lines), options[] (line numbers), answer: index, explain, original, mutated}
  order     {prompt, items[] (shuffled), answer: [indices in correct order], explain}
  line      {prompt, file, answer: int, tolerance, explain}
"""

from __future__ import annotations

import ast
import random
import re
import textwrap

from .graph import RepoGraph
from .model import Symbol
from .snippets import doc_summary

# (pattern, replacement, human description); applied to one line only
_MUTATIONS = [
    (r" is not None", " is None", "`is not None` was flipped to `is None`"),
    (r" is None", " is not None", "`is None` was flipped to `is not None`"),
    (r" not in ", " in ", "`not in` was flipped to `in`"),
    (r"(?<=[\w)\]'\"]) in (?=[\w(\['\"])", " not in ", "`in` was flipped to `not in`"),
    (r"!==", "===", "`!==` was flipped to `===`"),
    (r"===", "!==", "`===` was flipped to `!==`"),
    (r"(?<![=!<>])==(?!=)", "!=", "`==` was flipped to `!=`"),
    (r"!=(?!=)", "==", "`!=` was flipped to `==`"),
    (r"<=", "<", "`<=` was changed to `<` (an off-by-one)"),
    (r">=", ">", "`>=` was changed to `>` (an off-by-one)"),
    (r"(?<![<\-=])<(?![=<])", "<=", "`<` was changed to `<=` (an off-by-one)"),
    (r"(?<![\-=>])>(?![=>])", ">=", "`>` was changed to `>=` (an off-by-one)"),
    (r" and ", " or ", "`and` was swapped for `or`"),
    (r" or ", " and ", "`or` was swapped for `and`"),
    (r"&&", "||", "`&&` was swapped for `||`"),
    (r"\|\|", "&&", "`||` was swapped for `&&`"),
    (r"\bif not ", "if ", "the `not` was dropped from the condition"),
    (r"\bif \(!", "if (", "the `!` was dropped from the condition"),
    (r"\bTrue\b", "False", "`True` was changed to `False`"),
    (r"\bFalse\b", "True", "`False` was changed to `True`"),
    (r"\btrue\b", "false", "`true` was changed to `false`"),
    (r"\bfalse\b", "true", "`false` was changed to `true`"),
    (r"\+ 1\b", "- 1", "`+ 1` was changed to `- 1`"),
    (r"- 1\b", "+ 1", "`- 1` was changed to `+ 1`"),
]
_COND = re.compile(r"^\s*(if|elif|while|return|else if|} else if|assert)\b|\?|&&|\|\|| and | or ")


def _in_string(line: str, pos: int) -> bool:
    before = line[:pos]
    for q in ("'", '"', "`"):
        if before.count(q) % 2 == 1:
            return True
    return "#" in before or "//" in before


def _display(sym: Symbol) -> str:
    return sym.qualname


def string_lines(src_lines: list[str], is_python: bool) -> set[int]:
    """Line numbers that sit inside multi-line strings, docstrings or block comments (never mutate those)."""
    out: set[int] = set()
    text = "\n".join(src_lines)
    if is_python:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return out
        for n in ast.walk(tree):
            if isinstance(n, (ast.Constant, ast.JoinedStr)) and isinstance(getattr(n, "value", ""), (str, bytes, list)) or isinstance(n, ast.JoinedStr):
                if getattr(n, "end_lineno", None) and n.end_lineno > n.lineno:
                    out.update(range(n.lineno, n.end_lineno + 1))
                elif isinstance(n, ast.Expr):
                    pass
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
                out.update(range(n.lineno, (n.end_lineno or n.lineno) + 1))
    else:
        for m in re.finditer(r"/\*[\s\S]*?\*/|`[^`]*`", text):
            a = text.count("\n", 0, m.start()) + 1
            b = a + m.group(0).count("\n")
            out.update(range(a, b + 1))
    return out


_STR_CACHE: dict[int, set[int]] = {}


def mutate_symbol(src_lines: list[str], sym: Symbol, rng: random.Random) -> dict | None:
    """Plant one realistic bug in a short function. Returns a 'bug' question or None."""
    if sym.kind == "class" or not (4 <= sym.loc <= 32):
        return None
    key = id(src_lines)
    if key not in _STR_CACHE:
        _STR_CACHE[key] = string_lines(src_lines, sym.file.endswith(".py"))
    skip = _STR_CACHE[key]
    body = list(range(sym.start, min(sym.end, len(src_lines)) + 1))
    cands = []
    for n in body[1:]:
        line = src_lines[n - 1]
        st = line.strip()
        if n in skip or not st or st.startswith(("#", "//", "*", "/*", "@")):
            continue
        if not _COND.search(line):
            continue
        for pat, rep, desc in _MUTATIONS:
            for m in re.finditer(pat, line):
                if _in_string(line, m.start()):
                    continue
                if "=>" in line[max(0, m.start() - 1): m.end() + 1]:
                    continue
                cands.append((n, line[: m.start()] + rep + line[m.end():], desc))
                break
    if not cands:
        return None
    rng.shuffle(cands)
    for n, new_line, desc in cands:
        if sym.file.endswith(".py"):
            code = "\n".join(src_lines[sym.start - 1: sym.end])
            mutated = code.splitlines()
            mutated[n - sym.start] = new_line
            try:
                ast.parse(textwrap.dedent("\n".join(mutated)))
            except SyntaxError:
                continue
        code_lines = [ln for ln in body if src_lines[ln - 1].strip() and ln not in skip
                      and not src_lines[ln - 1].strip().startswith(("#", "//", "*", "/*", "@"))]
        others = [ln for ln in code_lines if ln != n and ln != sym.start]
        if len(others) < 3:
            continue
        rng.shuffle(others)
        opts = sorted(others[:3] + [n])
        rows = [[ln, new_line if ln == n else src_lines[ln - 1]] for ln in body]
        return {
            "type": "bug", "symbol": sym.id, "file": sym.file,
            "prompt": f"We planted one bug in `{_display(sym)}`. Which line is wrong?",
            "code": rows, "options": [f"Line {x}" for x in opts], "answer": opts.index(n),
            "original": src_lines[n - 1].strip(), "mutated": new_line.strip(),
            "explain": f"Line {n}: {desc}. The real code reads `{src_lines[n - 1].strip()}`.",
        }
    return None


def _pick_distractors(pool: list[str], correct: str, k: int, rng: random.Random) -> list[str]:
    seen = {correct}
    out = []
    for p in pool:
        if p not in seen:
            seen.add(p)
            out.append(p)
    rng.shuffle(out)
    return out[:k]


def _mcq(prompt: str, correct: str, distractors: list[str], explain: str, rng: random.Random, **extra) -> dict | None:
    if len(distractors) < 2:
        return None
    opts = distractors[:3] + [correct]
    rng.shuffle(opts)
    return {"type": "mcq", "prompt": prompt, "options": opts, "answer": opts.index(correct), "explain": explain, **extra}


def q_which_file(g: RepoGraph, sym: Symbol, files_pool: list[str], rng: random.Random) -> dict | None:
    summ = doc_summary(sym.doc)
    if len(summ) < 25:
        return None
    masked = re.sub(rf"\b{re.escape(sym.name)}\b", "this", summ)
    d = _pick_distractors([f for f in files_pool if f != sym.file], sym.file, 3, rng)
    return _mcq(f"Which file handles this? “{masked}”", sym.file, d,
                f"That's `{sym.qualname}` in `{sym.file}` (line {sym.start}).", rng, symbol=sym.id, kind="which_file")


def q_calls(g: RepoGraph, sym: Symbol, pool: list[Symbol], rng: random.Random) -> dict | None:
    callees = [g.symbols[e.dst] for e in g.callees(sym.id) if not e.weak and e.dst in g.symbols]
    if not callees:
        return None
    correct = callees[rng.randrange(len(callees))]
    called = {c.qualname for c in callees} | {sym.qualname}
    d = _pick_distractors([p.qualname for p in pool if p.qualname not in called and p.name != correct.name], correct.qualname, 3, rng)
    line = next(e.line for e in g.callees(sym.id) if e.dst == correct.id)
    return _mcq(f"Which of these does `{sym.qualname}` call directly?", correct.qualname, d,
                f"`{sym.qualname}` calls `{correct.qualname}` on line {line} of `{sym.file}`.", rng, symbol=sym.id, kind="calls")


def q_caller(g: RepoGraph, sym: Symbol, pool: list[Symbol], rng: random.Random) -> dict | None:
    callers = [g.symbols[e.src] for e in g.callers(sym.id) if not e.weak and g.modules[g.symbols[e.src].file].role == "source"]
    if not callers:
        return None
    correct = callers[rng.randrange(len(callers))]
    calling = {c.qualname for c in callers} | {sym.qualname}
    d = _pick_distractors([p.qualname for p in pool if p.qualname not in calling], correct.qualname, 3, rng)
    line = next(e.line for e in g.callers(sym.id) if e.src == correct.id)
    return _mcq(f"Who calls `{sym.qualname}`?", correct.qualname, d,
                f"`{correct.qualname}` calls it on line {line} of `{correct.file}`.", rng, symbol=sym.id, kind="caller")


def q_inherits(g: RepoGraph, sym: Symbol, class_pool: list[str], rng: random.Random) -> dict | None:
    if sym.kind != "class" or not sym.bases:
        return None
    base = sym.bases[0]
    if base in ("object", "Exception") and len(sym.bases) == 1:
        return None
    d = _pick_distractors([c for c in class_pool if c != sym.name and c not in sym.bases], base, 3, rng)
    return _mcq(f"What does the class `{sym.name}` inherit from?", base, d,
                f"`{sym.signature}` (line {sym.start} of `{sym.file}`).", rng, symbol=sym.id, kind="inherits")


def q_role(g: RepoGraph, path: str, files: list[str], rng: random.Random) -> dict | None:
    summ = doc_summary(g.modules[path].doc)
    if len(summ) < 25:
        return None
    others = []
    for f in files:
        if f != path:
            s = doc_summary(g.modules[f].doc)
            if len(s) >= 25 and s != summ:
                others.append(s)
    d = _pick_distractors(others, summ, 3, rng)
    return _mcq(f"What is `{path}` mainly responsible for?", summ, d, f"From the module's own docstring, line 1 of `{path}`.", rng, kind="role", file=path)


def q_trace_order(steps: list[dict], rng: random.Random) -> dict | None:
    if len(steps) < 3:
        return None
    names = [s["callee"] for s in steps[:6]]
    order = list(range(len(names)))
    shuffled = order[:]
    for _ in range(5):
        rng.shuffle(shuffled)
        if shuffled != order:
            break
    items = [names[i] for i in shuffled]
    answer = [shuffled.index(i) for i in order]
    return {"type": "order", "prompt": "Put the hand-offs in the order they happen.", "items": items, "answer": answer,
            "explain": " → ".join(names)}


def q_find_line(step: dict) -> dict:
    return {"type": "line", "prompt": f"In `{step['file']}`, on which line does `{step['caller']}` hand off to `{step['callee']}`?",
            "file": step["file"], "answer": step["line"], "tolerance": 0,
            "explain": f"Line {step['line']}: `{step['code_line'].strip()}`"}


def q_defined(g: RepoGraph, sym: Symbol, files_pool: list[str], rng: random.Random) -> dict | None:
    d = _pick_distractors([f for f in files_pool if f != sym.file], sym.file, 3, rng)
    return _mcq(f"Which file defines `{sym.qualname}`?", sym.file, d,
                f"`{sym.qualname}` is defined on line {sym.start} of `{sym.file}`.", rng, symbol=sym.id, kind="defined")
