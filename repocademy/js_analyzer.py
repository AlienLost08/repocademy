"""JavaScript / TypeScript static analysis with tree-sitter (no code is executed)."""

from __future__ import annotations

import re

import tree_sitter_javascript as _tsjs
import tree_sitter_typescript as _tsts
from tree_sitter import Language, Node, Parser

from .model import CallSite, Import, Module, Symbol

_LANGS = {
    "javascript": Language(_tsjs.language()),
    "typescript": Language(_tsts.language_typescript()),
    "tsx": Language(_tsts.language_tsx()),
}
_FUNC_TYPES = {"function_expression", "arrow_function", "function", "generator_function", "generator_function_declaration"}
_TODO = re.compile(r"(?://|/\*|\*)\s*(TODO|FIXME|XXX|HACK)\b[:\s]*(.*)", re.I)


def _t(node: Node | None) -> str:
    return node.text.decode("utf-8", "replace") if node is not None else ""


def _clean_comment(c: str) -> str:
    c = re.sub(r"^/\*\*?|\*/$", "", c.strip())
    lines = [re.sub(r"^\s*\*\s?|^\s*//\s?", "", ln) for ln in c.splitlines()]
    out = []
    for ln in lines:
        if ln.strip().startswith("@"):  # stop at JSDoc tags but keep the prose
            if ln.strip().startswith(("@param", "@return", "@returns", "@private", "@public", "@api", "@type")):
                continue
        out.append(ln.rstrip())
    return "\n".join(out).strip()


def _doc_before(node: Node) -> str:
    prev = node.prev_named_sibling
    if prev is not None and prev.type == "comment" and node.start_point[0] - prev.end_point[0] <= 1:
        txt = _t(prev)
        if txt.startswith("/*") or txt.startswith("//"):
            # merge consecutive // lines
            parts = [txt]
            p = prev.prev_named_sibling
            while txt.startswith("//") and p is not None and p.type == "comment" and _t(p).startswith("//") and prev.start_point[0] - p.end_point[0] <= 1:
                parts.insert(0, _t(p))
                prev, p = p, p.prev_named_sibling
            return _clean_comment("\n".join(parts))
    return ""


def _call_text(fn: Node) -> str:
    if fn.type == "identifier":
        return _t(fn)
    if fn.type == "member_expression":
        obj, prop = fn.child_by_field_name("object"), fn.child_by_field_name("property")
        if obj is None or prop is None:
            return ""
        if obj.type in ("identifier", "this", "super"):
            return f"{_t(obj)}.{_t(prop)}"
        if obj.type == "member_expression":
            inner = _call_text(obj)
            return f"{inner}.{_t(prop)}" if inner else f"?.{_t(prop)}"
        return f"?.{_t(prop)}"
    return ""


def _calls(body: Node | None) -> list[CallSite]:
    out: list[CallSite] = []
    if body is None:
        return out
    stack = [(body, False)]
    while stack:
        n, err = stack.pop()
        if n.type in ("class_declaration", "class"):
            continue
        err = err or n.type in ("catch_clause", "throw_statement")
        if n.type in ("call_expression", "new_expression"):
            fn = n.child_by_field_name("function") or n.child_by_field_name("constructor")
            if fn is not None:
                name = _call_text(fn)
                # fn.call(ctx, …) / fn.apply(ctx, …) invoke fn itself
                if name.count(".") >= 1 and name.rsplit(".", 1)[1] in ("call", "apply", "bind") and not name.startswith("?"):
                    name = name.rsplit(".", 1)[0].replace(".prototype.", ".")
                if name and name != "require":
                    out.append(CallSite(name, n.start_point[0] + 1, err))
        elif n.type == "member_expression" and ".prototype." in _t(n) and n.parent is not None and n.parent.type != "member_expression":
            # `bind(Axios.prototype.request, ctx)`: a method handed over to be called later
            txt = _call_text(n)
            if txt and not txt.startswith("?"):
                out.append(CallSite(txt.replace(".prototype.", "."), n.start_point[0] + 1, err))
        stack.extend((c, err) for c in reversed(n.named_children))
    out.sort(key=lambda c: c.line)
    return out


def _new_name(v: Node | None) -> str | None:
    """`new Foo(...)` -> "Foo"; `await new Foo()` too."""
    while v is not None and v.type in ("await_expression", "parenthesized_expression", "as_expression", "non_null_expression"):
        v = v.named_children[0] if v.named_children else None
    if v is not None and v.type == "new_expression":
        c = v.child_by_field_name("constructor")
        if c is not None:
            name = _call_text(c)
            return name or None
    return None


def _local_types(body: Node | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if body is None:
        return out
    stack = [body]
    while stack:
        n = stack.pop()
        if n.type in ("class_declaration", "class"):
            continue
        if n.type == "variable_declarator":
            nm, val = n.child_by_field_name("name"), n.child_by_field_name("value")
            ctor = _new_name(val)
            if ctor and nm is not None and nm.type == "identifier":
                out.setdefault(_t(nm), ctor)
        elif n.type == "assignment_expression":
            left, right = n.child_by_field_name("left"), n.child_by_field_name("right")
            ctor = _new_name(right)
            if ctor and left is not None:
                lt = _t(left)
                if lt.startswith("this.") and lt.count(".") == 1:
                    out.setdefault(lt, ctor)
                elif left.type == "identifier":
                    out.setdefault(lt, ctor)
        stack.extend(n.named_children)
    return out


def _params(fn: Node) -> str:
    p = fn.child_by_field_name("parameters") or fn.child_by_field_name("parameter")
    s = _t(p) if p is not None else "()"
    if not s.startswith("("):
        s = f"({s})"
    return re.sub(r"\s+", " ", s)


def _string_value(n: Node | None) -> str | None:
    if n is None or n.type not in ("string", "template_string"):
        return None
    return _t(n).strip("'\"`")


def _require_of(n: Node | None) -> str | None:
    if n is not None and n.type == "call_expression":
        fn = n.child_by_field_name("function")
        if fn is not None and _t(fn) == "require":
            args = n.child_by_field_name("arguments")
            if args is not None and args.named_child_count:
                return _string_value(args.named_children[0])
    return None


def analyze_js(path: str, text: str, lang: str = "javascript") -> Module:
    lines = text.count("\n") + 1
    mod = Module(path=path, lang=lang, lines=lines)
    for i, line in enumerate(text.splitlines(), 1):
        m = _TODO.search(line)
        if m and len(mod.todos) < 20:
            mod.todos.append((i, (m.group(1).upper() + ": " + m.group(2).strip().rstrip("*/").strip())[:160]))
    grammar = "tsx" if path.endswith(".tsx") else ("typescript" if lang == "typescript" else "javascript")
    if grammar == "javascript" and path.endswith(".jsx"):
        grammar = "javascript"
    tree = Parser(_LANGS[grammar]).parse(text.encode("utf-8"))
    root = tree.root_node
    if text.startswith("#!"):
        mod.is_main = True
    # module doc: first comment of the file (skipping license-ish banners is hard; keep the first block)
    for c in root.named_children[:3]:
        if c.type == "comment":
            d = _clean_comment(_t(c))
            if d and not re.match(r"(?i)^(module dependencies|!|copyright|\(c\)|license|eslint|@license|MIT|jshint|global\b)", d) and "copyright" not in d.lower()[:300]:
                mod.doc = d
                break
        elif c.type not in ("expression_statement",):
            break

    def add_symbol(name: str, qual: str, kind: str, node: Node, fn: Node | None, doc_node: Node, parent: Symbol | None = None, bases=None):
        body = fn.child_by_field_name("body") if fn is not None else None
        if kind == "class":
            sig = f"class {name}" + (f" extends {bases[0]}" if bases else "")
        else:
            sig = f"{'async ' if fn is not None and _t(fn).startswith('async') else ''}function {qual}{_params(fn) if fn is not None else '()'}"
        sym = Symbol(id=f"{path}::{qual}", name=name, qualname=qual, kind=kind, file=path,
                     start=doc_node.start_point[0] + 1 if doc_node.type == "export_statement" else node.start_point[0] + 1,
                     end=node.end_point[0] + 1, signature=sig, doc=_doc_before(doc_node), bases=bases or [],
                     calls=_calls(body) if kind != "class" else [], parent=parent.id if parent else None,
                     types=_local_types(body) if kind != "class" else {})
        mod.symbols.append(sym)
        if parent is not None:  # this.router = new Router() -> field type on the class
            for k, v in sym.types.items():
                if k.startswith("this."):
                    parent.types.setdefault(k, v)
        return sym

    def add_class(node: Node, doc_node: Node, exported: bool):
        name = _t(node.child_by_field_name("name")) or "default"
        bases = []
        for ch in node.named_children:
            if ch.type == "class_heritage":
                b = ch.named_children[0] if ch.named_children else None
                if b is not None and b.type == "extends_clause":
                    b = b.named_children[0] if b.named_children else None
                if b is not None:
                    bases.append(_t(b))
        cls = add_symbol(name, name, "class", node, None, doc_node, bases=bases)
        cls.exported = exported
        body = node.child_by_field_name("body")
        for m in (body.named_children if body is not None else []):
            if m.type == "method_definition":
                mname = _t(m.child_by_field_name("name"))
                add_symbol(mname, f"{name}.{mname}", "method", m, m, m, parent=cls)
            elif m.type in ("field_definition", "public_field_definition"):
                prop = m.child_by_field_name("property") or m.child_by_field_name("name")
                val = m.child_by_field_name("value")
                if prop is not None and val is not None:
                    if val.type in ("arrow_function", "function_expression"):
                        mname = _t(prop)
                        add_symbol(mname, f"{name}.{mname}", "method", m, val, m, parent=cls)
                    else:
                        ctor = _new_name(val)
                        if ctor:
                            cls.types.setdefault("this." + _t(prop), ctor)
        return cls

    def handle_decl(node: Node, doc_node: Node, exported: bool):
        t = node.type
        if t in ("function_declaration", "generator_function_declaration"):
            name = _t(node.child_by_field_name("name")) or "default"
            s = add_symbol(name, name, "function", node, node, doc_node)
            s.exported = exported
            if exported:
                mod.exports.append(name)
        elif t in ("class_declaration", "abstract_class_declaration", "class"):
            c = add_class(node, doc_node, exported)
            if exported:
                mod.exports.append(c.name)
        elif t in ("lexical_declaration", "variable_declaration"):
            for d in node.named_children:
                if d.type != "variable_declarator":
                    continue
                nm, val = d.child_by_field_name("name"), d.child_by_field_name("value")
                req = _require_of(val)
                if req is not None:
                    if nm is not None and nm.type == "identifier":
                        mod.imports.append(Import(module=req, alias=_t(nm), line=d.start_point[0] + 1))
                    elif nm is not None and nm.type == "object_pattern":
                        names = []
                        for p in nm.named_children:
                            if p.type == "shorthand_property_identifier_pattern":
                                names.append((_t(p), _t(p)))
                            elif p.type == "pair_pattern":
                                names.append((_t(p.child_by_field_name("key")), _t(p.child_by_field_name("value"))))
                        mod.imports.append(Import(module=req, names=names, line=d.start_point[0] + 1))
                    continue
                if val is not None and val.type == "member_expression" and _require_of(val.child_by_field_name("object")) is not None:
                    src = _require_of(val.child_by_field_name("object"))
                    mod.imports.append(Import(module=src, names=[(_t(val.child_by_field_name("property")), _t(nm))], line=d.start_point[0] + 1))
                    continue
                if nm is not None and nm.type == "object_pattern" and val is not None and val.type == "identifier":
                    for pp in nm.named_children:  # const {Axios, create} = axios
                        if pp.type == "shorthand_property_identifier_pattern":
                            mod.values.setdefault(_t(pp), f"{_t(val)}.{_t(pp)}")
                        elif pp.type == "pair_pattern":
                            k, v = pp.child_by_field_name("key"), pp.child_by_field_name("value")
                            if k is not None and v is not None and v.type == "identifier":
                                mod.values.setdefault(_t(v), f"{_t(val)}.{_t(k)}")
                if nm is not None and nm.type == "identifier" and val is not None and val.type in ("call_expression", "new_expression"):
                    callee = val.child_by_field_name("function") or val.child_by_field_name("constructor")
                    ct = _call_text(callee) if callee is not None else ""
                    if ct:
                        mod.values.setdefault(_t(nm), ct)
                if nm is not None and nm.type == "identifier" and val is not None:
                    if val.type in _FUNC_TYPES:
                        s = add_symbol(_t(nm), _t(nm), "function", node if len(node.named_children) == 1 else d, val, doc_node)
                        s.exported = exported
                        if exported:
                            mod.exports.append(_t(nm))
                    elif val.type == "class":
                        c = add_class(val, doc_node, exported)
                        if exported:
                            mod.exports.append(c.name)
        elif t == "expression_statement":
            e = node.named_children[0] if node.named_children else None
            if e is None or e.type != "assignment_expression":
                if e is not None and e.type == "call_expression" and _require_of(e):
                    mod.imports.append(Import(module=_require_of(e), line=node.start_point[0] + 1))
                return
            left, right = e.child_by_field_name("left"), e.child_by_field_name("right")
            lt = _t(left)
            # `exports = module.exports = createApplication` -> treat like `module.exports = createApplication`
            while right is not None and right.type == "assignment_expression":
                if _t(right.child_by_field_name("left")) in ("module.exports", "exports"):
                    lt = "module.exports"
                right = right.child_by_field_name("right")
            req = _require_of(right)
            if lt in ("module.exports", "exports"):
                if right is not None and right.type == "identifier":
                    mod.default_export = _t(right)
                elif right is not None and right.type in _FUNC_TYPES:
                    nm = _t(right.child_by_field_name("name")) or "module.exports"
                    add_symbol(nm, nm, "function", node, right, node).exported = True
                    mod.default_export = nm
                elif right is not None and right.type == "object":
                    for pr in right.named_children:
                        if pr.type == "shorthand_property_identifier":
                            mod.exports.append(_t(pr))
                        elif pr.type == "pair":
                            k, v = pr.child_by_field_name("key"), pr.child_by_field_name("value")
                            if v is not None and v.type in _FUNC_TYPES:
                                add_symbol(_t(k), _t(k), "function", pr, v, pr).exported = True
                            mod.exports.append(_t(k))
                        elif pr.type == "method_definition":
                            k = _t(pr.child_by_field_name("name"))
                            add_symbol(k, k, "function", pr, pr, pr).exported = True
                            mod.exports.append(k)
                elif req is not None:
                    mod.imports.append(Import(module=req, alias="module.exports", line=node.start_point[0] + 1))
                return
            if left is not None and left.type == "member_expression":
                qual = re.sub(r"\s+", "", lt).replace(".prototype.", ".")
                name = qual.rsplit(".", 1)[-1]
                is_exp = lt.startswith(("exports.", "module.exports."))
                if req is not None:
                    mod.imports.append(Import(module=req, alias=qual, line=node.start_point[0] + 1))
                    if is_exp:
                        mod.exports.append(name)
                    return
                if right is not None and right.type in _FUNC_TYPES:
                    if is_exp:
                        qual = name
                    s = add_symbol(name, qual, "method" if "." in qual else "function", node, right, node)
                    s.exported = is_exp
                    if is_exp:
                        mod.exports.append(name)
                elif is_exp and right is not None and right.type == "identifier":
                    mod.exports.append(name)

    for node in root.named_children:
        if node.type == "import_statement":
            src = _string_value(node.child_by_field_name("source"))
            if src is None:
                continue
            imp = Import(module=src, line=node.start_point[0] + 1)
            for cl in node.named_children:
                if cl.type != "import_clause":
                    continue
                for part in cl.named_children:
                    if part.type == "identifier":
                        imp.names.append(("default", _t(part)))
                    elif part.type == "namespace_import":
                        ids = [c for c in part.named_children if c.type == "identifier"]
                        if ids:
                            imp.alias = _t(ids[0])
                    elif part.type == "named_imports":
                        for spec in part.named_children:
                            if spec.type == "import_specifier":
                                nm, al = spec.child_by_field_name("name"), spec.child_by_field_name("alias")
                                imp.names.append((_t(nm), _t(al) if al is not None else _t(nm)))
            mod.imports.append(imp)
        elif node.type == "export_statement":
            decl = node.child_by_field_name("declaration")
            src = _string_value(node.child_by_field_name("source"))
            if decl is not None:
                handle_decl(decl, node, True)
                if "default" in _t(node)[:15]:
                    mod.default_export = mod.symbols[-1].name if mod.symbols else None
            elif src is not None:  # export { a } from './x'  /  export * from './x'
                names = []
                for ch in node.named_children:
                    if ch.type == "export_clause":
                        for spec in ch.named_children:
                            nm, al = spec.child_by_field_name("name"), spec.child_by_field_name("alias")
                            names.append((_t(nm), _t(al) if al is not None else _t(nm)))
                            mod.exports.append(_t(al) if al is not None else _t(nm))
                mod.imports.append(Import(module=src, names=names or [("*", "*")], line=node.start_point[0] + 1))
            else:
                for ch in node.named_children:
                    if ch.type == "export_clause":
                        for spec in ch.named_children:
                            al, nm0 = spec.child_by_field_name("alias"), spec.child_by_field_name("name")
                            if al is not None and _t(al) == "default":  # export { axios as default }
                                mod.default_export = _t(nm0)
                                continue
                            mod.exports.append(_t(al if al is not None else nm0))
                    elif ch.type == "identifier":
                        mod.default_export = _t(ch)
        else:
            handle_decl(node, node, False)
    return mod
