"""Turn per-file analyses into a repository map: resolved imports, a call graph and importance scores."""

from __future__ import annotations

import posixpath
from collections import defaultdict
from dataclasses import dataclass, field

from .model import Module, Symbol

# method names too generic to resolve by name alone
COMMON = {"get", "set", "add", "run", "call", "send", "read", "write", "close", "open", "init", "update", "append", "extend",
          "items", "keys", "values", "copy", "pop", "push", "join", "split", "format", "load", "dump", "loads", "dumps",
          "start", "stop", "emit", "on", "off", "once", "then", "catch", "map", "filter", "reduce", "find", "next", "apply",
          "bind", "handle", "render", "parse", "process", "main", "test", "setup", "teardown", "__init__", "toString",
          "constructor", "default", "create", "delete", "remove", "clear", "reset", "resolve", "reject", "use", "list",
          "match", "replace", "lower", "upper", "strip", "encode", "decode", "insert", "index", "count", "sort", "error",
          "warn", "info", "debug", "log", "flush", "wait", "exec", "execute", "value", "name", "data", "json", "text"}
JS_EXT = (".js", ".ts", ".tsx", ".mjs", ".cjs", ".jsx", ".mts", ".cts")


@dataclass
class Edge:
    src: str
    dst: str
    line: int
    weak: bool = False  # resolved by unique name only
    error_path: bool = False


@dataclass
class RepoGraph:
    modules: dict[str, Module]
    symbols: dict[str, Symbol]
    calls: list[Edge] = field(default_factory=list)
    imports: list[tuple[str, str, int]] = field(default_factory=list)  # (src file, dst file, line)
    inherits: list[tuple[str, str]] = field(default_factory=list)
    external: dict[str, int] = field(default_factory=dict)  # external package -> import count
    rank: dict[str, float] = field(default_factory=dict)
    module_rank: dict[str, float] = field(default_factory=dict)
    namespaces: dict[str, dict] = field(default_factory=dict)
    lookup: object = None  # (file, name) -> ("symbol", id) | ("module", path) | ("ext", pkg) | None

    def callees(self, sid: str) -> list[Edge]:
        return [e for e in self._out.get(sid, [])]

    def callers(self, sid: str) -> list[Edge]:
        return [e for e in self._in.get(sid, [])]

    def index(self):
        self._out = defaultdict(list)
        self._in = defaultdict(list)
        for e in self.calls:
            self._out[e.src].append(e)
            self._in[e.dst].append(e)


def python_dotted(paths: list[str]) -> dict[str, str]:
    """Map python file path -> dotted module name, honouring packages (__init__.py) and src/ layouts."""
    pyset = set(paths)
    out = {}
    for p in paths:
        parts = p[:-3].split("/")
        # climb while the parent directory is a package
        i = len(parts) - 1
        while i > 0 and "/".join(parts[:i]) + "/__init__.py" in pyset:
            i -= 1
        mod_parts = parts[i:]
        if mod_parts[-1] == "__init__":
            mod_parts = mod_parts[:-1] or parts[i - 1:i]
        out[p] = ".".join(mod_parts)
    return out


def _resolve_js_path(src_file: str, spec: str, files: set[str]) -> str | None:
    if not spec.startswith("."):
        return None
    base = posixpath.normpath(posixpath.join(posixpath.dirname(src_file), spec))
    stem = base
    for ext in JS_EXT:
        if base.endswith(ext):
            stem = base[: -len(ext)]
    cands = [base] + [stem + e for e in JS_EXT] + [base + "/index" + e for e in JS_EXT]
    for c in cands:
        if c in files:
            return c
    return None


def _ext_pkg(spec: str, lang: str) -> str | None:
    if lang == "python":
        return spec.split(".")[0] if spec else None
    if spec.startswith((".", "/")):
        return None
    if spec.startswith("node:"):
        return spec[5:].split("/")[0]
    parts = spec.split("/")
    return "/".join(parts[:2]) if spec.startswith("@") else parts[0]


def build_graph(modules: list[Module]) -> RepoGraph:
    mods = {m.path: m for m in modules}
    syms: dict[str, Symbol] = {}
    for m in modules:
        for s in m.symbols:
            syms[s.id] = s
    g = RepoGraph(mods, syms)
    files = set(mods)

    py_paths = [p for p, m in mods.items() if m.lang == "python"]
    dotted = python_dotted(py_paths)
    for p, d in dotted.items():
        mods[p].dotted = d
    by_dotted: dict[str, str] = {}
    for p, d in dotted.items():
        # prefer source over tests when names collide
        if d not in by_dotted or mods[by_dotted[d]].role != "source":
            by_dotted[d] = p

    top: dict[str, dict[str, str]] = defaultdict(dict)  # file -> top-level name -> symbol id
    methods_by_name: dict[str, list[str]] = defaultdict(list)
    for s in syms.values():
        if s.parent is None or (s.kind == "method" and "." in s.qualname and mods[s.file].lang != "python" and s.parent is None):
            top[s.file].setdefault(s.qualname, s.id)
        if "." in s.qualname and s.parent is None:  # JS `app.handle = function`
            top[s.file].setdefault(s.qualname, s.id)
        if s.kind in ("method", "function") and mods[s.file].role == "source":
            methods_by_name[s.name].append(s.id)

    by_qual: dict[str, list[str]] = defaultdict(list)
    for s in syms.values():
        if mods[s.file].role == "source" and "." in s.qualname and s.parent is None:
            by_qual[s.qualname].append(s.id)

    # 1) resolve imports and build each module's namespace: name -> ("module", path) | ("symbol", id) | ("ext", pkg)
    ns: dict[str, dict[str, tuple[str, str]]] = {p: {} for p in mods}
    pending_from: list[tuple[str, str, str, str]] = []  # (file, local, target module path, imported name)
    for p, m in mods.items():
        for imp in m.imports:
            target = None
            if m.lang == "python":
                if imp.level:
                    pkg = m.dotted.split(".") if p.endswith("__init__.py") else m.dotted.split(".")[:-1]
                    if imp.level > 1:
                        pkg = pkg[: len(pkg) - (imp.level - 1)]
                    base = ".".join([x for x in pkg + ([imp.module] if imp.module else []) if x])
                else:
                    base = imp.module
                target = by_dotted.get(base)
                if imp.names and imp.names[0][0] != "__module_root__":
                    for name, local in imp.names:
                        if name == "*":
                            if target:
                                pending_from.append((p, "*", target, "*"))
                            continue
                        sub = by_dotted.get(f"{base}.{name}" if base else name)
                        if sub:
                            ns[p][local] = ("module", sub)
                            g.imports.append((p, sub, imp.line))
                        elif target:
                            pending_from.append((p, local, target, name))
                        elif base and not imp.level:
                            ns[p][local] = ("ext", _ext_pkg(base, "python"))
                    if target:
                        g.imports.append((p, target, imp.line))
                    elif not imp.level and base:
                        pkg = _ext_pkg(base, "python")
                        if pkg:
                            g.external[pkg] = g.external.get(pkg, 0) + 1
                else:
                    if imp.alias and imp.names and imp.names[0][0] == "__module_root__":
                        root_t = by_dotted.get(imp.module.split(".")[0])
                        if root_t:
                            ns[p][imp.alias] = ("module", root_t)
                        if target:
                            ns[p].setdefault("__dotted__:" + imp.module, ("module", target))
                    elif imp.alias:
                        ns[p][imp.alias] = ("module", target) if target else ("ext", _ext_pkg(imp.module, "python"))
                    if target:
                        g.imports.append((p, target, imp.line))
                    else:
                        pkg = _ext_pkg(imp.module, "python")
                        if pkg:
                            g.external[pkg] = g.external.get(pkg, 0) + 1
            else:
                target = _resolve_js_path(p, imp.module, files)
                if target:
                    g.imports.append((p, target, imp.line))
                else:
                    pkg = _ext_pkg(imp.module, m.lang)
                    if pkg:
                        g.external[pkg] = g.external.get(pkg, 0) + 1
                if imp.alias and imp.alias != "module.exports":
                    if target:
                        dm = mods[target].default_export
                        if dm and dm in top[target]:
                            ns[p][imp.alias] = ("symbol", top[target][dm])
                        else:
                            ns[p][imp.alias] = ("module", target)
                    else:
                        ns[p][imp.alias] = ("ext", imp.module)
                for name, local in imp.names:
                    if not target:
                        ns[p][local] = ("ext", imp.module)
                    elif name == "default":
                        dm = mods[target].default_export
                        ns[p][local] = ("symbol", top[target][dm]) if dm and dm in top[target] else ("module", target)
                    elif name == "*":
                        pending_from.append((p, "*", target, "*"))
                    else:
                        pending_from.append((p, local, target, name))
                imp.resolved = target
            if m.lang == "python":
                imp.resolved = target

    def lookup_in(path: str, name: str, depth: int = 0):
        if name in top[path]:
            return ("symbol", top[path][name])
        if name in ns[path]:
            return ns[path][name]
        if depth < 3:
            for (f, local, tgt, nm) in pending_from:
                if f == path and local == "*" and tgt != path:
                    r = lookup_in(tgt, name, depth + 1)
                    if r:
                        return r
        return None

    for _ in range(3):  # re-exports can chain (package __init__ -> api -> sessions)
        for f, local, tgt, name in pending_from:
            if local == "*":
                continue
            r = lookup_in(tgt, name)
            if r and r[0] != "ext":
                ns[f][local] = r
    g.namespaces = ns
    g.lookup = lookup_in

    # 2) resolve calls
    def method_of(class_id: str, name: str, seen=None) -> str | None:
        cls = syms.get(class_id)
        if cls is None:
            return None
        cand = f"{class_id}.{name}"
        if cand in syms:
            return cand
        seen = seen or set()
        seen.add(class_id)
        for b in cls.bases:
            r = resolve_name(cls.file, b.split("[")[0])
            if r and r[0] == "symbol" and r[1] not in seen:
                found = method_of(r[1], name, seen)
                if found:
                    return found
        return None

    def resolve_name(path: str, dotted_name: str):
        parts = dotted_name.split(".")
        head = lookup_in(path, parts[0])
        if mods[path].lang == "python" and len(parts) > 1:
            for k in range(len(parts) - 1, 0, -1):
                key = "__dotted__:" + ".".join(parts[:k])
                if key in ns[path]:
                    head, parts = ns[path][key], [".".join(parts[:k])] + parts[k:]
                    break
        if head is None:
            if dotted_name in top[path]:
                return ("symbol", top[path][dotted_name])
            return None
        for part in parts[1:]:
            if head[0] == "module":
                nxt = lookup_in(head[1], part)
                if nxt is None and mods[head[1]].lang == "python":
                    sub = by_dotted.get(mods[head[1]].dotted + "." + part)
                    nxt = ("module", sub) if sub else None
                head = nxt
            elif head[0] == "symbol":
                s = syms[head[1]]
                if s.kind == "class":
                    mid = method_of(s.id, part)
                    head = ("symbol", mid) if mid else None
                else:
                    head = None
            else:
                return head
            if head is None:
                return None
        return head

    def class_of(path: str, ctor: str) -> str | None:
        r = resolve_name(path, ctor)
        if r and r[0] == "symbol" and syms[r[1]].kind == "class":
            return r[1]
        return None

    def typed_receiver(s: Symbol, cls: Symbol | None, parts: list[str]) -> str | None:
        """Resolve `x.m()` when `x = Foo()` / `new Foo()` earlier, and `self.x.m()` when the class set `self.x = Foo()`."""
        if len(parts) == 2 and parts[0] in s.types:
            cid = class_of(s.file, s.types[parts[0]])
            return method_of(cid, parts[1]) if cid else None
        if len(parts) == 3 and parts[0] in ("self", "this") and cls is not None:
            key = f"{parts[0]}.{parts[1]}"
            c, seen = cls, set()
            while c is not None and c.id not in seen:  # field may be set in a base class
                seen.add(c.id)
                if key in c.types:
                    cid = class_of(c.file, c.types[key])
                    return method_of(cid, parts[2]) if cid else None
                base = next((resolve_name(c.file, b.split("[")[0]) for b in c.bases), None)
                c = syms.get(base[1]) if base and base[0] == "symbol" else None
        return None

    for s in syms.values():
        m = mods[s.file]
        cls = syms.get(s.parent) if s.parent else None
        obj_prefix = s.qualname.rsplit(".", 1)[0] if ("." in s.qualname and s.parent is None) else None
        seen_dst: dict[str, Edge] = {}
        for c in s.calls:
            dst = None
            weak = False
            parts = c.name.split(".")
            typed = typed_receiver(s, cls, parts)
            if typed:
                dst = typed
            elif parts[0] in ("self", "this", "cls") and len(parts) == 2:
                if cls is not None:
                    dst = method_of(cls.id, parts[1])
                elif obj_prefix:
                    dst = top[s.file].get(f"{obj_prefix}.{parts[1]}")
            elif parts[0] == "super" and len(parts) == 2 and cls is not None:
                for b in cls.bases:
                    r = resolve_name(cls.file, b)
                    if r and r[0] == "symbol":
                        dst = method_of(r[1], parts[1])
                        break
            elif parts[0] != "?":
                r = resolve_name(s.file, c.name)
                if r and r[0] == "symbol":
                    dst = r[1]
                elif r is None and len(parts) == 2 and m.lang != "python":
                    dst = top[s.file].get(c.name)
            if dst is None and len(parts) == 2 and parts[0] not in ("self", "this", "cls", "super", "?"):
                # JS objects built across files: `app.init()` -> the `app.init = function` defined in another module
                same = [x for x in by_qual.get(c.name, []) if x != s.id]
                if len(same) == 1:
                    dst, weak = same[0], True
            if dst is None and len(parts) == 2 and parts[0] not in ("self", "this", "cls", "super", "?"):
                # `adapter.send(...)` where `adapter` is a local variable: try classes named like the variable
                recv = parts[0].lower().strip("_")
                if len(recv) >= 3 and lookup_in(s.file, parts[0]) is None:
                    best = None
                    for cid, cs in syms.items():
                        if cs.kind == "class" and mods[cs.file].role == "source" and (cs.name.lower() == recv or cs.name.lower().endswith(recv)):
                            mid = method_of(cid, parts[1])
                            exact = cs.name.lower() == recv
                            if mid and (best is None or (exact, syms[mid].loc) > best[1]):
                                best = (mid, (exact, syms[mid].loc))
                    exact_hit = bool(best and best[1][0])
                    best = best[0] if best else None
                    if best and best != s.id:
                        dst, weak = best, not exact_hit  # `signer.unsign()` with a class named Signer is a safe bet
            if dst is None and len(parts) >= 2 and parts[-1] not in COMMON and len(parts[-1]) >= 4:
                cands = [x for x in methods_by_name.get(parts[-1], []) if x != s.id]
                if len(cands) == 1 and (parts[0] in ("self", "this", "?") or lookup_in(s.file, parts[0]) is None or lookup_in(s.file, parts[0])[0] != "ext"):
                    dst, weak = cands[0], True
            if dst and dst != s.id:
                if dst not in seen_dst:
                    seen_dst[dst] = Edge(s.id, dst, c.line, weak, c.error_path)
                    g.calls.append(seen_dst[dst])
                else:  # prefer the happy-path / strongly-resolved call site for the hand-off line
                    e0 = seen_dst[dst]
                    if (e0.error_path and not c.error_path) or (e0.weak and not weak):
                        e0.line, e0.error_path, e0.weak = c.line, e0.error_path and c.error_path, e0.weak and weak
        if s.kind == "class":
            for b in s.bases:
                r = resolve_name(s.file, b.split("[")[0])
                if r and r[0] == "symbol":
                    g.inherits.append((s.id, r[1]))
    g.index()
    _rank(g)
    return g


def _pagerank(nodes: list[str], edges: list[tuple[str, str, float]], iters: int = 40, d: float = 0.85) -> dict[str, float]:
    if not nodes:
        return {}
    n = len(nodes)
    idx = {x: i for i, x in enumerate(nodes)}
    out_w = [0.0] * n
    adj = defaultdict(list)
    for a, b, w in edges:
        if a in idx and b in idx and a != b:
            adj[idx[b]].append((idx[a], w))
            out_w[idx[a]] += w
    pr = [1.0 / n] * n
    for _ in range(iters):
        dangling = sum(pr[i] for i in range(n) if out_w[i] == 0)
        new = [(1 - d) / n + d * dangling / n] * n
        for j in range(n):
            s = 0.0
            for i, w in adj.get(j, ()):
                s += pr[i] * w / out_w[i]
            new[j] += d * s
        pr = new
    return {nodes[i]: pr[i] for i in range(n)}


def _rank(g: RepoGraph):
    src_syms = [s for s in g.symbols.values() if g.modules[s.file].role == "source"]
    nodes = [s.id for s in src_syms]
    edges = [(e.src, e.dst, 0.4 if e.weak else 1.0) for e in g.calls]
    # methods feed their class, classes are as important as their busiest methods
    for s in src_syms:
        if s.parent:
            edges.append((s.id, s.parent, 0.3))
    pr = _pagerank(nodes, edges)
    if pr:
        mx = max(pr.values())
        for sid, v in pr.items():
            s = g.symbols[sid]
            bonus = 1.0
            if s.exported or s.name in g.modules[s.file].exports:
                bonus += 0.6
            if s.doc:
                bonus += 0.25
            if not s.public:
                bonus -= 0.35
            bonus += min(s.loc, 80) / 400
            g.rank[sid] = v / mx * bonus
    mod_nodes = [p for p, m in g.modules.items() if m.role == "source"]
    mpr = _pagerank(mod_nodes, [(a, b, 1.0) for a, b, _ in g.imports])
    for p in mod_nodes:
        sym_sum = sum(g.rank.get(s.id, 0) for s in g.modules[p].symbols)
        g.module_rank[p] = mpr.get(p, 0) * len(mod_nodes) * 0.5 + sym_sum
