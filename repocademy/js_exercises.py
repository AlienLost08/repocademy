"""'Predict, then run' exercises for JavaScript and TypeScript.

We look for small top-level functions that only use their arguments, JS built-ins, module constants and
other small helpers from the same file. TypeScript is turned into plain JavaScript by deleting type syntax
with tree-sitter (and the result must parse as JavaScript, otherwise we skip it). Example calls come from
the repository's own tests, so inputs are realistic. Nothing runs on the server: the browser executes the
code in a Web Worker with a timeout.
"""

from __future__ import annotations

import re

import tree_sitter_javascript as _tsjs
import tree_sitter_typescript as _tsts
from tree_sitter import Language, Node, Parser

from .graph import RepoGraph

_JS = Language(_tsjs.language())
_TS = Language(_tsts.language_typescript())

JS_GLOBALS = {"Array", "Object", "String", "Number", "Boolean", "Math", "JSON", "Date", "RegExp", "Error", "TypeError",
              "RangeError", "SyntaxError", "Map", "Set", "WeakMap", "WeakSet", "Symbol", "parseInt", "parseFloat", "isNaN",
              "isFinite", "undefined", "NaN", "Infinity", "encodeURIComponent", "decodeURIComponent", "encodeURI",
              "decodeURI", "Promise", "BigInt", "arguments", "this", "true", "false", "null", "globalThis", "Reflect",
              "Uint8Array", "ArrayBuffer", "DataView", "TextEncoder", "TextDecoder", "Intl", "URL", "URLSearchParams",
              "structuredClone", "Proxy", "Function", "Int32Array", "Float64Array"}
_KW = {"function", "return", "var", "let", "const", "if", "else", "for", "while", "do", "switch", "case", "break",
       "continue", "new", "typeof", "instanceof", "in", "of", "throw", "try", "catch", "finally", "delete", "void",
       "default", "async", "await", "yield", "class", "extends", "super", "static", "get", "set", "export", "import"}
_BAD = re.compile(r"\b(require|import\(|process\.|fs\.|fetch|XMLHttpRequest|eval|Function\(|setTimeout|setInterval|"
                  r"Date\.now|Math\.random|new Date\(\)|crypto|document\.|window\.|globalThis\.|console\.|await|"
                  r"Buffer|stream|http)\b")
_TYPE_NODES = {"type_annotation", "type_parameters", "type_arguments", "accessibility_modifier", "override_modifier",
               "readonly", "type_predicate_annotation", "asserts_annotation", "omitting_type_annotation",
               "opting_type_annotation"}
_DROP_DECLS = {"type_alias_declaration", "interface_declaration", "ambient_declaration", "enum_declaration"}
_LIT = r"(?:'[^'\n]*'|\"[^\"\n]*\"|`[^`$\n]*`|-?\d+(?:\.\d+)?(?:e\d+)?|true|false|null|undefined|NaN|Infinity|\[[^\[\]\n]*\]|\{[^{}\n]*\}|/[^/\n]+/[gimsuy]*)"


def _t(n: Node) -> str:
    return n.text.decode("utf-8", "replace")


def _parse(code: str, ts: bool):
    return Parser(_TS if ts else _JS).parse(code.encode("utf-8")).root_node


def _has_error(n: Node) -> bool:
    if n.type == "ERROR" or n.is_missing:
        return True
    return any(_has_error(c) for c in n.children)


def strip_types(code: str) -> str | None:
    """TypeScript -> JavaScript by deleting type-only syntax. Returns None when unsure."""
    root = _parse(code, True)
    if _has_error(root):
        return None
    b = code.encode("utf-8")
    cuts: list[tuple[int, int, bytes]] = []

    def walk(n: Node):
        t = n.type
        if t in _TYPE_NODES or t in _DROP_DECLS:
            cuts.append((n.start_byte, n.end_byte, b""))
            return
        if t in ("as_expression", "satisfies_expression"):
            expr = n.named_children[0]
            cuts.append((expr.end_byte, n.end_byte, b""))
            walk(expr)
            return
        if t == "non_null_expression":
            cuts.append((n.end_byte - 1, n.end_byte, b""))
        if t == "optional_parameter":  # (x?: T) -> (x)
            for c in n.children:
                if c.type == "?":
                    cuts.append((c.start_byte, c.end_byte, b""))
        for c in n.children:
            walk(c)

    walk(root)
    cuts.sort(key=lambda x: x[0], reverse=True)
    out = b
    last = len(b) + 1
    for s, e, rep in cuts:
        if e > last:  # overlapping cut already applied
            continue
        out = out[:s] + rep + out[e:]
        last = s
    js = out.decode("utf-8", "replace")
    js = re.sub(r"^\s*export\s+(default\s+)?", "", js, flags=re.M)
    if _has_error(_parse(js, False)):
        return None
    return js


def _idents(code: str) -> tuple[set[str], set[str]]:
    """(identifiers read, names declared) in a JS snippet, ignoring property names and object keys."""
    root = _parse(code, False)
    used, declared = set(), set()

    def walk(n: Node):
        t = n.type
        if t == "identifier":
            p = n.parent
            if p is not None and p.type in ("variable_declarator", "function_declaration", "class_declaration",
                                             "formal_parameters", "catch_clause", "function_expression") and \
                    (p.child_by_field_name("name") == n or p.type in ("formal_parameters", "catch_clause")):
                declared.add(_t(n))
            elif p is not None and p.type in ("assignment_pattern", "rest_pattern", "array_pattern") and n == p.named_children[0]:
                declared.add(_t(n))
            elif p is not None and p.type == "arrow_function" and p.child_by_field_name("parameter") == n:
                declared.add(_t(n))
            else:
                used.add(_t(n))
        elif t in ("shorthand_property_identifier_pattern",):
            declared.add(_t(n))
        elif t == "shorthand_property_identifier":
            used.add(_t(n))
        for c in n.named_children:
            walk(c)

    walk(root)
    return used, declared


def _top_level(code: str, ts: bool) -> tuple[dict[str, str], dict[str, str]]:
    """(functions, constants) defined at the top level of a file: name -> source statement."""
    root = _parse(code, ts)
    funcs, consts = {}, {}
    for n in root.named_children:
        node = n
        if n.type == "export_statement":
            d = n.child_by_field_name("declaration")
            if d is None:
                continue
            node = d
        if node.type in ("function_declaration",):
            nm = node.child_by_field_name("name")
            if nm is not None:
                funcs[_t(nm)] = _t(node)
        elif node.type in ("lexical_declaration", "variable_declaration") and len(node.named_children) == 1:
            d = node.named_children[0]
            nm, val = d.child_by_field_name("name"), d.child_by_field_name("value")
            if nm is None or val is None or nm.type != "identifier":
                continue
            if val.type in ("arrow_function", "function_expression", "function"):
                funcs[_t(nm)] = _t(node)
            elif val.type in ("string", "number", "regex", "array", "object", "template_string", "true", "false", "null",
                              "new_expression", "call_expression", "binary_expression", "unary_expression", "member_expression"):
                consts[_t(nm)] = _t(node)
        elif node.type == "expression_statement":  # exports.foo = function foo() {}
            e = node.named_children[0] if node.named_children else None
            if e is not None and e.type == "assignment_expression":
                left, right = e.child_by_field_name("left"), e.child_by_field_name("right")
                lt = _t(left)
                m = re.fullmatch(r"(?:module\.)?exports\.([A-Za-z_$][\w$]*)", lt)
                if m and right is not None and right.type in ("function_expression", "arrow_function", "function"):
                    funcs[m.group(1)] = f"const {m.group(1)} = {_t(right)};"
    return funcs, consts


def _closure(name: str, funcs: dict[str, str], consts: dict[str, str], ts: bool) -> tuple[list[str], int] | None:
    """Source of `name` plus every helper/constant it needs, or None if it needs anything else."""
    order, seen, queue = [], set(), [name]
    total = 0
    while queue:
        n = queue.pop()
        if n in seen:
            continue
        seen.add(n)
        src = funcs.get(n) or consts.get(n)
        if src is None:
            return None
        if ts:
            src = strip_types(src)
            if src is None:
                return None
        src = re.sub(r"^\s*export\s+(default\s+)?", "", src)
        src = re.sub(r"\b(?:module\.)?exports\.([A-Za-z_$][\w$]*)", r"\1", src)
        if _BAD.search(src):
            return None
        total += src.count("\n") + 1
        if total > 70:
            return None
        used, declared = _idents(src)
        free = used - declared - JS_GLOBALS - _KW - {n}
        for f in free:
            if f in funcs or f in consts:
                queue.append(f)
            else:
                return None
        order.append((n, src))
    # constants first, then helpers, then the function itself last
    order.sort(key=lambda x: (x[0] not in consts, x[0] == name))
    return [s for _, s in order], total


def _examples(g: RepoGraph, files_text: dict[str, str], names: set[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    if not names:
        return out
    pat = re.compile(rf"(?<![\w$])(?:[A-Za-z_$][\w$]*\.)?({'|'.join(map(re.escape, sorted(names, key=len, reverse=True)))})"
                     rf"\(((?:\s*{_LIT}\s*,?)*)\)")
    for path, m in g.modules.items():
        if m.role != "test" and not path.endswith((".md",)):
            continue
        for i, line in enumerate(files_text.get(path, "").splitlines(), 1):
            if line.lstrip().startswith(("//", "*", "import ", "const {")):
                continue
            for mm in pat.finditer(line):
                args = mm.group(2).strip().rstrip(",").strip()
                if len(args) > 90:
                    continue
                call = f"{mm.group(1)}({args})"
                lst = out.setdefault(mm.group(1), [])
                if call not in {e["call"] for e in lst}:
                    lst.append({"call": call, "from": path, "line": i})
    return out


def js_exercises(g: RepoGraph, files_text: dict[str, str], limit: int = 8) -> list[dict]:
    cands: dict[str, tuple] = {}
    for path, m in g.modules.items():
        if m.lang not in ("javascript", "typescript") or m.role != "source" or path.endswith(".d.ts"):
            continue
        text = files_text.get(path, "")
        ts = m.lang == "typescript"
        try:
            funcs, consts = _top_level(text, ts)
        except Exception:  # pragma: no cover - parser edge cases
            continue
        by_name = {s.name: s for s in m.symbols if s.parent is None and s.kind == "function"}
        for name in funcs:
            s = by_name.get(name)
            if s is None or s.loc > 40 or name in cands:
                continue
            got = _closure(name, funcs, consts, ts)
            if not got:
                continue
            parts, _ = got
            cands[name] = (s, "\n\n".join(parts))
    examples = _examples(g, files_text, set(cands))
    out = []
    for name, (s, code) in sorted(cands.items(), key=lambda kv: -g.rank.get(kv[1][0].id, 0)):
        ex = examples.get(name)
        if not ex:
            continue
        out.append({"type": "js_run", "symbol": s.id, "title": f"Predict what `{ex[0]['call']}` returns", "file": s.file,
                    "start": s.start, "end": s.end, "code": code, "calls": ex[:4], "lang": "javascript",
                    "from_typescript": g.modules[s.file].lang == "typescript"})
        if len(out) >= limit:
            break
    return out
