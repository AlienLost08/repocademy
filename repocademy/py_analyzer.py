"""Python static analysis with the standard-library `ast` module (no code is executed)."""

from __future__ import annotations

import ast
import re

from .model import CallSite, Import, Module, Symbol

_TODO = re.compile(r"#\s*(TODO|FIXME|XXX|HACK)\b[:\s]*(.*)", re.I)


def _call_name(node: ast.AST) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    elif isinstance(node, ast.Call):  # foo().bar -> "foo().bar" is too fuzzy; keep the attr only
        parts.append("?")
    else:
        return None
    return ".".join(reversed(parts))


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    try:
        args = ast.unparse(node.args)
    except Exception:  # pragma: no cover - ast.unparse is robust on parsed code
        args = "..."
    ret = ""
    if node.returns is not None:
        try:
            ret = " -> " + ast.unparse(node.returns)
        except Exception:  # pragma: no cover
            ret = ""
    prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
    return f"{prefix}{node.name}({args}){ret}"


class _CallCollector(ast.NodeVisitor):
    def __init__(self):
        self.calls: list[CallSite] = []
        self.in_except = 0

    def visit_Call(self, node: ast.Call):
        name = _call_name(node.func)
        if name:
            self.calls.append(CallSite(name, node.lineno, self.in_except > 0))
        self.generic_visit(node)

    def visit_ExceptHandler(self, node):  # noqa: N802
        self.in_except += 1
        self.generic_visit(node)
        self.in_except -= 1

    def visit_Raise(self, node):  # noqa: N802
        self.in_except += 1
        self.generic_visit(node)
        self.in_except -= 1

    # nested classes are their own symbols; nested functions stay part of the parent
    def visit_ClassDef(self, node):  # noqa: N802
        return


def _calls_in(node: ast.AST) -> list[CallSite]:
    c = _CallCollector()
    for child in ast.iter_child_nodes(node):
        c.visit(child)
    return c.calls


def _ctor_name(v: ast.AST) -> str | None:
    """`Foo(...)` / `mod.Foo(...)` -> "Foo" / "mod.Foo" when the callee looks like a class (CapWords)."""
    if isinstance(v, ast.Call):
        n = _call_name(v.func)
        if n and n.split(".")[-1][:1].isupper():
            return n
    return None


def _local_types(fn: ast.AST) -> dict[str, str]:
    out: dict[str, str] = {}
    for n in ast.walk(fn):
        if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
            ctor = _ctor_name(n.value)
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            for tg in targets:
                if ctor and isinstance(tg, ast.Name):
                    out.setdefault(tg.id, ctor)
                elif ctor and isinstance(tg, ast.Attribute) and isinstance(tg.value, ast.Name) and tg.value.id in ("self", "cls"):
                    out.setdefault(f"self.{tg.attr}", ctor)
        elif isinstance(n, (ast.With, ast.AsyncWith)):
            for it in n.items:
                ctor = _ctor_name(it.context_expr)
                if ctor and isinstance(it.optional_vars, ast.Name):
                    out.setdefault(it.optional_vars.id, ctor)
    return out


def analyze_python(path: str, text: str, dotted: str = "") -> Module:
    lines = text.count("\n") + 1
    mod = Module(path=path, lang="python", lines=lines, dotted=dotted)
    for i, line in enumerate(text.splitlines(), 1):
        m = _TODO.search(line)
        if m and len(mod.todos) < 20:
            mod.todos.append((i, (m.group(1).upper() + ": " + m.group(2).strip())[:160]))
    try:
        tree = ast.parse(text, filename=path)
    except (SyntaxError, ValueError):
        return mod
    mod.doc = (ast.get_docstring(tree) or "").strip()
    if text.startswith("#!"):
        mod.is_main = True

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mod.imports.append(Import(module=a.name, alias=a.asname or a.name.split(".")[0], line=node.lineno,
                                          names=[] if a.asname else [("__module_root__", a.name.split(".")[0])]))
        elif isinstance(node, ast.ImportFrom):
            mod.imports.append(Import(module=node.module or "", level=node.level or 0, line=node.lineno,
                                      names=[(a.name, a.asname or a.name) for a in node.names]))

    for node in tree.body:
        if isinstance(node, ast.If):
            t = node.test
            if (isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) and t.left.id == "__name__"
                    and any(isinstance(c, ast.Constant) and c.value == "__main__" for c in t.comparators)):
                mod.is_main = True
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for tg in targets:
                if isinstance(tg, ast.Name) and tg.id == "__all__" and isinstance(node.value, (ast.List, ast.Tuple)):
                    mod.exports = [e.value for e in node.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]

    def add_func(node, parent: Symbol | None):
        qual = f"{parent.qualname}.{node.name}" if parent else node.name
        sym = Symbol(id=f"{path}::{qual}", name=node.name, qualname=qual, kind="method" if parent else "function",
                     file=path, start=min([node.lineno] + [d.lineno for d in node.decorator_list]), end=node.end_lineno or node.lineno,
                     signature=_signature(node), doc=(ast.get_docstring(node) or "").strip(),
                     decorators=[ast.unparse(d) for d in node.decorator_list], calls=_calls_in(node),
                     parent=parent.id if parent else None, types=_local_types(node))
        mod.symbols.append(sym)
        if parent is not None:  # self.x = Foo() anywhere in the class -> field type on the class
            for k, v in sym.types.items():
                if k.startswith("self."):
                    parent.types.setdefault(k, v)

    def add_class(node: ast.ClassDef, parent: Symbol | None):
        qual = f"{parent.qualname}.{node.name}" if parent else node.name
        bases = []
        for b in node.bases:
            try:
                bases.append(ast.unparse(b))
            except Exception:  # pragma: no cover
                pass
        sym = Symbol(id=f"{path}::{qual}", name=node.name, qualname=qual, kind="class", file=path,
                     start=min([node.lineno] + [d.lineno for d in node.decorator_list]), end=node.end_lineno or node.lineno,
                     signature=f"class {node.name}" + (f"({', '.join(bases)})" if bases else ""),
                     doc=(ast.get_docstring(node) or "").strip(), bases=bases,
                     decorators=[ast.unparse(d) for d in node.decorator_list], parent=parent.id if parent else None)
        mod.symbols.append(sym)
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                add_func(child, sym)
            elif isinstance(child, ast.ClassDef):
                add_class(child, sym)
        # class-level calls (e.g. decorators, attribute defaults) are rare; ignore

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add_func(node, None)
        elif isinstance(node, ast.ClassDef):
            add_class(node, None)
    return mod
