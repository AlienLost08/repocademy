"""'Try it' exercises.

The server never runs repository code. We only pick *self-contained* functions (they use nothing but
built-ins, the standard library and their own arguments) and a real example call taken from the repo's
own tests or doctests. The learner predicts the result, then runs it in their own browser
(Pyodide for Python, a Web Worker for JavaScript).
"""

from __future__ import annotations

import ast
import builtins
import re
import sys
import textwrap

from .graph import RepoGraph
from .model import Symbol

_PY_BUILTINS = set(dir(builtins)) | {"__name__", "__file__"}
_STDLIB = set(getattr(sys, "stdlib_module_names", ()))
_JS_GLOBALS = {"Array", "Object", "String", "Number", "Boolean", "Math", "JSON", "Date", "RegExp", "Error", "TypeError",
               "RangeError", "Map", "Set", "WeakMap", "Symbol", "parseInt", "parseFloat", "isNaN", "isFinite", "undefined",
               "NaN", "Infinity", "encodeURIComponent", "decodeURIComponent", "encodeURI", "decodeURI", "escape", "unescape",
               "Promise", "BigInt", "console", "arguments", "this", "true", "false", "null"}
_BAD_CALLS = re.compile(r"\b(open|exec|eval|compile|__import__|input|subprocess|socket|os\.system|os\.remove|os\.environ|getenv|shutil|requests\.|urlopen|fetch|XMLHttpRequest|require|process\.|fs\.|time\.|random\.|now\(|today\(|threading|warnings\.warn)\b")


def _py_free_names(fn: ast.FunctionDef) -> set[str]:
    bound = {a.arg for a in fn.args.args + fn.args.kwonlyargs + fn.args.posonlyargs}
    if fn.args.vararg:
        bound.add(fn.args.vararg.arg)
    if fn.args.kwarg:
        bound.add(fn.args.kwarg.arg)
    loads = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Name):
            if isinstance(n.ctx, (ast.Store, ast.Del)):
                bound.add(n.id)
            else:
                loads.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n is not fn:
            bound.add(n.name)
        elif isinstance(n, ast.arg):
            bound.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            bound.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                bound.add((a.asname or a.name).split(".")[0])
    return loads - bound - _PY_BUILTINS


def _literal_call(node: ast.Call) -> bool:
    try:
        for a in node.args:
            ast.literal_eval(a)
        for k in node.keywords:
            if k.arg is None:
                return False
            ast.literal_eval(k.value)
    except (ValueError, SyntaxError, TypeError):
        return False
    return True


def _parametrized_calls(fn: ast.FunctionDef, names: set[str]) -> list[tuple[str, int]]:
    """Expand @pytest.mark.parametrize("a, b", [(1, 2), ...]) into concrete calls of functions in `names`."""
    table: list[dict] = []
    for d in fn.decorator_list:
        if isinstance(d, ast.Call) and ast.unparse(d.func).endswith("parametrize") and len(d.args) >= 2:
            try:
                argnames = ast.literal_eval(d.args[0])
                values = ast.literal_eval(d.args[1])
            except (ValueError, SyntaxError, TypeError):
                continue
            argnames = [a.strip() for a in (argnames.split(",") if isinstance(argnames, str) else argnames)]
            rows = []
            for v in list(values)[:4]:
                v = v if len(argnames) > 1 else (v,)
                if isinstance(v, (tuple, list)) and len(v) == len(argnames):
                    rows.append(dict(zip(argnames, v)))
            table = rows if not table else table
    if not table:
        return []
    out = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            nm = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if nm not in names or n.keywords:
                continue
            for row in table:
                args = []
                for a in n.args:
                    if isinstance(a, ast.Name) and a.id in row:
                        args.append(repr(row[a.id]))
                    else:
                        try:
                            args.append(repr(ast.literal_eval(a)))
                        except (ValueError, SyntaxError, TypeError):
                            args = None
                            break
                if args is not None:
                    call = f"{nm}({', '.join(args)})"
                    if len(call) <= 140:
                        out.append((call, n.lineno))
    return out


def _module_tables(text: str) -> tuple[dict[str, str], dict[str, str]]:
    """(stdlib import lines by local name, simple builtin-only assignments by name) for one module."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}, {}
    std, assigns = {}, {}
    for n in tree.body:
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split(".")[0] in _STDLIB:
                    std[a.asname or a.name.split(".")[0]] = ast.unparse(ast.Import(names=[a]))
        elif isinstance(n, ast.ImportFrom) and not n.level and (n.module or "").split(".")[0] in _STDLIB:
            for a in n.names:
                if a.name != "*":
                    std[a.asname or a.name] = f"from {n.module} import {a.name}" + (f" as {a.asname}" if a.asname else "")
        elif isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            used = {x.id for x in ast.walk(n.value) if isinstance(x, ast.Name)}
            seg = ast.get_source_segment(text, n) or ""
            if not (used - _PY_BUILTINS) and len(seg) <= 400:
                assigns[n.targets[0].id] = seg
    return std, assigns


def _py_examples(g: RepoGraph, files_text: dict[str, str], names: set[str]) -> dict[str, list[tuple[str, str, int]]]:
    """name -> [(call source, test file, line)] for calls with only literal arguments, from tests and doctests."""
    out: dict[str, list] = {}
    for path, m in g.modules.items():
        if m.lang != "python":
            continue
        text = files_text.get(path, "")
        if m.role == "test":
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for fn in ast.walk(tree):
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for call, ln in _parametrized_calls(fn, names):
                        out.setdefault(call.split("(", 1)[0], []).append((call, path, ln))
            for n in ast.walk(tree):
                if isinstance(n, ast.Call):
                    f = n.func
                    nm = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
                    if nm in names and _literal_call(n):
                        call = ast.unparse(n)
                        if isinstance(f, ast.Attribute):
                            call = nm + call[len(ast.unparse(f)):]
                        if len(call) <= 140:
                            out.setdefault(nm, []).append((call, path, n.lineno))
        for i, line in enumerate(text.splitlines(), 1):  # doctests anywhere
            mm = re.match(r"\s*>>> ((\w+)\(.*\))\s*$", line)
            if mm and mm.group(2) in names:
                try:
                    node = ast.parse(mm.group(1), mode="eval").body
                except SyntaxError:
                    continue
                if isinstance(node, ast.Call) and _literal_call(node):
                    out.setdefault(mm.group(2), []).append((mm.group(1), path, i))
    return out


def python_exercises(g: RepoGraph, files_text: dict[str, str], focus: list[str] | None = None, limit: int = 12) -> list[dict]:
    cands: dict[str, tuple[Symbol, str, list[str]]] = {}
    for path, m in g.modules.items():
        if m.lang != "python" or m.role != "source":
            continue
        text = files_text.get(path, "")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        stdlib_aliases, simple_assigns = _module_tables(text)
        local_funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        # names pulled in from sibling modules (e.g. `from .compat import quote, basestring`) that are really stdlib/builtins
        for imp in m.imports:
            if imp.resolved and imp.resolved in files_text and g.modules[imp.resolved].lang == "python":
                o_std, o_assign = _module_tables(files_text[imp.resolved])
                for name, local in imp.names:
                    if name in o_std and local not in stdlib_aliases:
                        line = o_std[name]
                        stdlib_aliases[local] = line if local == name else line + f"\n{local} = {name}"
                    elif name in o_assign and local not in simple_assigns:
                        simple_assigns[local] = o_assign[name] if local == name else o_assign[name] + f"\n{local} = {name}"
        for name, fn in local_funcs.items():
            if fn.decorator_list or len(fn.body) == 0 or (fn.end_lineno or 0) - fn.lineno > 45:
                continue
            src = ast.get_source_segment(text, fn) or ""
            if _BAD_CALLS.search(src) or "yield" in src or "await" in src:
                continue
            free = _py_free_names(fn)
            helpers = []
            ok = True
            for f in sorted(free):
                if f in stdlib_aliases:
                    continue
                if f in local_funcs and f != name:
                    hf = local_funcs[f]
                    hfree = _py_free_names(hf) - set(stdlib_aliases)
                    hsrc = ast.get_source_segment(text, hf) or ""
                    if not hfree and not hf.decorator_list and not _BAD_CALLS.search(hsrc):
                        helpers.append(f)
                        continue
                if f in simple_assigns:  # module constants / builtin aliases: inlined below
                    continue
                ok = False
                break
            if not ok:
                continue
            consts = [simple_assigns[f] for f in sorted(free) if f not in stdlib_aliases and f not in helpers and f in simple_assigns]
            sid = f"{path}::{name}"
            if sid not in g.symbols:
                continue
            imports = sorted({stdlib_aliases[f] for f in free if f in stdlib_aliases} |
                             {stdlib_aliases[x] for h in helpers for x in _py_free_names(local_funcs[h]) if x in stdlib_aliases})
            parts = imports + consts + [ast.get_source_segment(text, local_funcs[h]) for h in helpers] + [src]
            cands[name] = (g.symbols[sid], "\n\n".join(p for p in parts if p), helpers)
    examples = _py_examples(g, files_text, set(cands))
    out = []
    order = sorted(cands.values(), key=lambda c: -(g.rank.get(c[0].id, 0) + (1 if focus and c[0].file in focus else 0)))
    for sym, code, _helpers in order:
        ex = examples.get(sym.name)
        if not ex:
            continue
        seen = set()
        calls = []
        for call, tf, ln in ex:
            if call not in seen:
                seen.add(call)
                calls.append({"call": call, "from": tf, "line": ln})
        out.append({"type": "python_run", "symbol": sym.id, "title": f"Predict what `{calls[0]['call']}` returns",
                    "file": sym.file, "start": sym.start, "end": sym.end, "code": textwrap.dedent(code),
                    "calls": calls[:4], "lang": "python"})
        if len(out) >= limit:
            break
    return out


def js_exercises(g: RepoGraph, files_text: dict[str, str], limit: int = 8) -> list[dict]:
    """Self-contained top-level JS functions, with literal example calls found in the test files."""
    cands = {}
    for path, m in g.modules.items():
        if m.lang not in ("javascript",) or m.role != "source":
            continue
        src_lines = files_text.get(path, "").splitlines()
        tops = {s.name: s for s in m.symbols if s.kind == "function" and s.parent is None and "." not in s.qualname}
        for name, s in tops.items():
            if s.loc > 40:
                continue
            code = "\n".join(src_lines[s.start - 1: s.end])
            if _BAD_CALLS.search(code) or "await" in code:
                continue
            body = re.sub(r"//.*|/\*[\s\S]*?\*/|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`", "''", code)
            idents = set(re.findall(r"(?<![.\w$])([A-Za-z_$][\w$]*)\b(?!\s*:)", body))
            declared = set(re.findall(r"\b(?:var|let|const|function)\s+([A-Za-z_$][\w$]*)", body))
            params = set(re.findall(r"[A-Za-z_$][\w$]*", s.signature.split("(", 1)[1] if "(" in s.signature else ""))
            kw = {"function", "return", "var", "let", "const", "if", "else", "for", "while", "do", "switch", "case", "break",
                  "continue", "new", "typeof", "instanceof", "in", "of", "throw", "try", "catch", "finally", "delete", "void",
                  "default", "async", "await", "yield", "class", "extends", "super", "static", "get", "set"}
            free = idents - declared - params - kw - _JS_GLOBALS
            helpers = [f for f in free if f in tops and f != name and tops[f].loc <= 30]
            if free - set(helpers):
                continue
            hcode = ["\n".join(src_lines[tops[h].start - 1: tops[h].end]) for h in sorted(helpers)]
            cands[name] = (s, "\n\n".join(hcode + [code]))
    examples: dict[str, list] = {}
    lit = r"(?:'[^'\n]*'|\"[^\"\n]*\"|-?\d+(?:\.\d+)?|true|false|null|undefined|\[[^\[\]\n]*\]|\{[^{}\n]*\})"
    for path, m in g.modules.items():
        if m.role != "test":
            continue
        for i, line in enumerate(files_text.get(path, "").splitlines(), 1):
            for name in cands:
                for mm in re.finditer(rf"(?<![\w$.])(?:\w+\.)?{re.escape(name)}\(((?:\s*{lit}\s*,?)*)\)", line):
                    call = f"{name}({mm.group(1).strip()})"
                    examples.setdefault(name, []).append({"call": call, "from": path, "line": i})
    out = []
    for name, (s, code) in sorted(cands.items(), key=lambda kv: -g.rank.get(kv[1][0].id, 0)):
        ex = examples.get(name)
        if not ex:
            continue
        uniq = list({e["call"]: e for e in ex}.values())[:4]
        out.append({"type": "js_run", "symbol": s.id, "title": f"Predict what `{uniq[0]['call']}` returns", "file": s.file,
                    "start": s.start, "end": s.end, "code": code, "calls": uniq, "lang": "javascript"})
        if len(out) >= limit:
            break
    return out
