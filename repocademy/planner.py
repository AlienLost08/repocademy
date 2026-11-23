"""Plan a course from the repository map: chapters, sections, diagrams, quizzes and exercises.

Everything here is deterministic: the same commit always produces the same course.
"""

from __future__ import annotations

import math
import posixpath
import random
import re
from collections import Counter, defaultdict, deque

from . import quiz as Q
from .exercises import js_exercises, python_exercises
from .graph import RepoGraph
from .model import Symbol
from .repoinfo import NODE_BUILTINS, STDLIB, commands_from_readme, readme_description, usage_example
from .snippets import doc_summary, symbol_snippet, window

MAX_MODULE_CHAPTERS = 7
DIR_HINTS = {"src": "the source code", "lib": "the library code", "tests": "the test suite", "test": "the test suite",
             "docs": "documentation", "doc": "documentation", "examples": "runnable examples", "example": "runnable examples",
             "scripts": "helper scripts", "bin": "command-line launchers", "benchmarks": "performance benchmarks",
             "tools": "developer tools", "packages": "the packages of a monorepo", "app": "the application", "server": "server code",
             "client": "client code", "api": "the API layer", "cli": "the command-line interface", "utils": "shared helpers",
             "types": "type definitions", "typings": "type definitions", "ext": "extensions", "contrib": "community extras",
             "e2e": "end-to-end tests", "spec": "the test suite", "__tests__": "the test suite"}


def _human(stem: str) -> str:
    stem = re.sub(r"^_+|\.(py|js|ts|tsx|mjs|cjs|jsx)$", "", stem)
    words = re.sub(r"([a-z])([A-Z])", r"\1 \2", stem).replace("_", " ").replace("-", " ").split()
    return " ".join(w.capitalize() if w.islower() else w for w in words) or stem


class Planner:
    def __init__(self, g: RepoGraph, files_text: dict[str, str], stats: dict, ref, sha: str, branch: str,
                 readme: tuple[str, str], manifest: dict):
        self.g, self.text, self.stats, self.ref, self.sha, self.branch = g, files_text, stats, ref, sha, branch
        self.readme_name, self.readme = readme
        self.man = manifest
        self.rng = random.Random(sha)
        self.src_cache: dict[str, list[str]] = {}
        self.used_q: set[str] = set()
        self.used_bug: set[str] = set()
        self.source_files = [p for p, m in g.modules.items() if m.role == "source"]
        self.main_lang = self._main_lang()
        self.ranked = sorted((s for s in g.symbols.values() if g.modules[s.file].role == "source"),
                             key=lambda s: -g.rank.get(s.id, 0))

    # ---------- helpers ----------
    def lines(self, path: str) -> list[str]:
        if path not in self.src_cache:
            self.src_cache[path] = self.text.get(path, "").splitlines()
        return self.src_cache[path]

    def link(self, path: str, start: int | None = None, end: int | None = None) -> str:
        u = f"{self.ref.url}/blob/{self.sha}/{path}"
        if start:
            u += f"#L{start}" + (f"-L{end}" if end and end != start else "")
        return u

    def _main_lang(self) -> str:
        c = Counter()
        for p in self.source_files:
            m = self.g.modules[p]
            c[m.lang] += m.lines
        return c.most_common(1)[0][0] if c else "python"

    def kind_word(self, s: Symbol) -> str:
        if s.kind == "class":
            return "class"
        if s.kind == "method":
            return "method"
        return "function"

    def children(self, cls: Symbol) -> list[Symbol]:
        return [s for s in self.g.modules[cls.file].symbols if s.parent == cls.id]

    # ---------- entry points ----------
    def main_package(self) -> str | None:
        c = Counter()
        for p in self.source_files:
            m = self.g.modules[p]
            if m.lang == "python" and m.dotted:
                c[m.dotted.split(".")[0]] += m.lines
        return c.most_common(1)[0][0] if c else None

    def _js_source_for(self, target: str) -> str | None:
        """Map a package.json target (often a build output like dist/index.js) back to a source file."""
        g = self.g
        t = posixpath.normpath(target)
        stem, ext = posixpath.splitext(t)
        exts = [".js", ".ts", ".mjs", ".cjs", ".tsx", ".jsx", ".mts"]
        dirs = stem.split("/")
        variants = [stem]
        if len(dirs) > 1 and dirs[0] in ("dist", "distribution", "build", "out", "lib", "esm", "cjs", "umd", "es"):
            rest = "/".join(dirs[1:])
            for sub in ("esm", "cjs", "node", "browser", "umd", "es"):
                if rest.startswith(sub + "/"):
                    rest = rest[len(sub) + 1:]
            for root in ("src", "source", "lib", ""):
                variants.append(f"{root}/{rest}".lstrip("/"))
        for v in variants:
            for e in ([ext] if ext else []) + exts:
                if v + e in g.modules:
                    return v + e
            for e in exts:
                if f"{v}/index{e}" in g.modules:
                    return f"{v}/index{e}"
        return None

    def _js_entry(self, syms: list[Symbol], files: list[str]) -> tuple[list[Symbol], list[str]]:
        g = self.g
        targets = list(self.man.get("js_entries") or [])
        if self.man.get("main"):
            targets.append(self.man["main"].lstrip("./"))
        targets += ["index.js", "index.ts", "src/index.ts", "src/index.js", "source/index.ts", "source/index.js",
                    "lib/index.js", "lib/index.ts", "src/main.ts", "main.js"]
        start = []
        for t in targets:
            p = self._js_source_for(t) if t not in g.modules else t
            if p and p not in start and g.modules[p].role == "source":
                start.append(p)
            if len(start) >= 2:
                break

        self._primary = set()

        def add_symbol_id(sid, primary=False):
            if sid in g.symbols:
                syms.append(g.symbols[sid])
                if primary:
                    self._primary.add(sid)
                # `axios.all = function …` members of the exported object are part of the API too
                pre = g.symbols[sid].qualname + "."
                for x in g.modules[g.symbols[sid].file].symbols:
                    if x.qualname.startswith(pre) and x.parent is None and x.public:
                        syms.append(x)

        def visit(path, depth=0):
            if depth > 4 or path in files:
                return
            files.append(path)
            m = g.modules[path]
            fwd = next((i for i in m.imports if i.alias == "module.exports" and i.resolved), None)
            if fwd:  # index.js: module.exports = require('./lib/x')
                visit(fwd.resolved, depth + 1)
                return
            names = ([m.default_export] if m.default_export else []) + list(m.exports)
            for n in names:
                sid = f"{path}::{n}"
                is_default = n == m.default_export
                if sid in g.symbols:
                    add_symbol_id(sid, is_default)
                    continue
                if n in m.values:  # const axios = createInstance(defaults); export default axios
                    head, _, attr = m.values[n].partition(".")
                    r = g.lookup(path, head) if g.lookup else None
                    if r and r[0] == "module" and attr:  # const {Axios} = axios  (axios = another module's default)
                        tgt = r[1]
                        r = g.lookup(tgt, attr)
                        if r is None:  # axios.Axios = Axios inside that module
                            r = g.lookup(tgt, attr) or next((("symbol", x.id) for x in g.modules[tgt].symbols
                                                              if x.qualname.endswith("." + attr) and x.parent is None), None)
                    if r and r[0] == "symbol" and (not attr or head not in m.values):
                        add_symbol_id(r[1], is_default)
                    for x in m.symbols:  # axios.all = function …
                        if x.qualname.startswith(n + ".") and x.parent is None and x.public:
                            syms.append(x)
                    continue
                r = g.lookup(path, n) if g.lookup else None
                if r and r[0] == "symbol":
                    add_symbol_id(r[1], is_default)
                elif r and r[0] == "module" and n == m.default_export:
                    visit(r[1], depth + 1)
            for imp in m.imports:  # export * from './x'
                if imp.resolved and imp.names == [("*", "*")]:
                    visit(imp.resolved, depth + 1)

        for p in start:
            visit(p)
        # thin front door (a single factory): add the busiest public pieces of the modules it wires together
        uniq = {s.id for s in syms}
        if len(uniq) < 4 and files:
            near = {dst for src, dst, _ in g.imports if src in files and g.modules[dst].role == "source"}
            # members of the objects the factory wires up (`app.use`, `res.send`) or classes
            extra = [s for s in self.ranked if s.file in near and s.public and s.id not in uniq
                     and (s.kind == "class" or ("." in s.qualname and s.parent is None))]
            syms.extend(extra[: 6 - len(uniq)])
        return syms, files

    def entry_symbols(self) -> tuple[list[Symbol], list[str], str]:
        """(front-door symbols, entry files, how we found them)"""
        g = self.g
        syms: list[Symbol] = []
        files: list[str] = []
        how = ""
        if self.main_lang == "python":
            pkg = self.main_package()
            init = next((p for p in self.source_files if g.modules[p].dotted == pkg and p.endswith("__init__.py")), None)
            if init:
                files.append(init)
                ns = g.namespaces.get(init, {})
                names = g.modules[init].exports or [k for k in ns if not k.startswith("_") and not k.startswith("__dotted__")]
                for n in names:
                    v = ns.get(n) or (g.lookup(init, n) if g.lookup else None)
                    if v and v[0] == "symbol" and v[1] in g.symbols:
                        syms.append(g.symbols[v[1]])
                how = f"names re-exported by `{init}`"
            for e in self.man.get("entry", []):
                mod, _, fn = e["target"].partition(":")
                path = next((p for p, m in g.modules.items() if m.dotted == mod), None)
                if path:
                    sid = f"{path}::{fn}"
                    if sid in g.symbols:
                        syms.append(g.symbols[sid])
                        files.append(path)
        else:
            syms, files = self._js_entry(syms, files)
            how = f"what `{files[0]}` exports" if files else ""
        # de-duplicate, rank, keep public
        out, seen_ids = [], set()
        primary = set(getattr(self, "_primary", set()))
        pkg = re.sub(r"[^a-z0-9]", "", self.ref.name.lower())
        primary |= {s.id for s in syms if s.kind == "class" and s.name.lower() == pkg}  # `Flask`, `Axios`, `Ky`
        self._primary = primary
        for s in sorted(syms, key=lambda s: (s.id not in primary, -g.rank.get(s.id, 0))):
            if s.id not in seen_ids:
                seen_ids.add(s.id)
                out.append(s)
        if not out:  # fall back to the most important public symbols
            out = [s for s in self.ranked if s.public and s.parent is None][:5]
            how = "the most-used public functions and classes"
            files = sorted({s.file for s in out})
        return out, list(dict.fromkeys(files)), how

    # ---------- the trace ----------
    def trace(self, starts: list[Symbol], max_hops: int = 6) -> list[dict]:
        g = self.g
        memo: dict[str, int] = {}

        def depth(sid: str, stack: frozenset, d: int) -> int:
            if d >= max_hops + 2:
                return 0
            if sid in memo:
                return memo[sid]
            best = 0
            for e in g.callees(sid)[:25]:
                if e.dst in stack or g.modules[g.symbols[e.dst].file].role != "source" or g.symbols[e.dst].kind == "class":
                    continue
                best = max(best, 1 + depth(e.dst, stack | {e.dst}, d + 1))
            memo[sid] = best
            return best

        reach_memo: dict[str, int] = {}

        def reach(sid: str) -> int:
            """How much of the codebase sits downstream (3 hops, happy path): orchestrators beat leaf utilities."""
            if sid in reach_memo:
                return reach_memo[sid]
            seen_r, frontier = {sid}, [sid]
            for _ in range(3):
                nxt = []
                for x in frontier:
                    for e in g.callees(x):
                        if e.error_path or e.dst in seen_r or g.modules[g.symbols[e.dst].file].role != "source":
                            continue
                        seen_r.add(e.dst)
                        nxt.append(e.dst)
                frontier = nxt
            reach_memo[sid] = len(seen_r) - 1
            return reach_memo[sid]

        cands = []
        entry_ids = {s.id for s in starts}
        primary = getattr(self, "_primary", set())
        pool_syms = list(starts[:8]) + [s for s in self.ranked[:12] if s.id not in entry_ids]
        for s in pool_syms:
            pool = [s] + (self.children(s) if s.kind == "class" else [])
            for p in pool:
                if p.name.startswith("_") and p.name != "__call__":
                    continue
                bonus = 1.0 if p.id in entry_ids and p.kind == "function" else (0.4 if s.id in entry_ids else 0)
                bonus += 1.5 if p.id in primary else 0
                cands.append((depth(p.id, frozenset([p.id]), 0), g.rank.get(p.id, 0) + bonus / 3, p))
        if not cands:
            return []
        # a good story: deep enough to cross the architecture, starting from something important
        cands.sort(key=lambda x: -(min(x[0], 5) + x[1] * 3 + (1.5 if x[0] >= 3 else 0) + 0.5 * math.log2(1 + reach(x[2].id))))
        cur = cands[0][2]
        steps, seen = [], {cur.id}
        for _ in range(max_hops):
            opts = []
            for e in g.callees(cur.id):
                dst = g.symbols[e.dst]
                if e.dst in seen or g.modules[dst.file].role != "source" or dst.kind == "class":
                    continue
                dd = memo.get(e.dst, depth(e.dst, frozenset(seen | {e.dst}), 0))
                score = g.rank.get(e.dst, 0) * 3 + min(dd, 3) * 0.7 + dst.loc / 120 - (0.35 if e.weak else 0)
                score += 0.6 * math.log2(1 + reach(e.dst))  # follow the flow, not the helper everybody calls
                score -= 0.06 * min(len(g.callers(e.dst)), 20)
                if re.match(r"^_?(is|has|assert|validate|ensure|check|to)[A-Z_]", dst.name) and dst.loc < 25:
                    score -= 1.0  # small predicates/validators are detours, not the story
                score += 1.0 if dst.file != cur.file else 0  # prefer hops that move through the architecture
                score -= 0.6 if not dst.public else 0
                score -= 2.0 if e.error_path else 0  # follow the happy path, not error handling
                opts.append((score, e, dst))
            if not opts:
                break
            opts.sort(key=lambda x: -x[0])
            _, e, dst = opts[0]
            if e.error_path and len(steps) >= 2:
                break  # only error handling left: the happy path ends here
            if e.weak and len(steps) >= 3:
                break  # don't end a good story on a guess
            src = self.lines(cur.file)
            steps.append({"caller": cur.qualname, "caller_id": cur.id, "callee": dst.qualname, "callee_id": dst.id,
                          "file": cur.file, "line": e.line, "code_line": src[e.line - 1] if e.line <= len(src) else "",
                          "weak": e.weak})
            seen.add(dst.id)
            cur = dst
        return steps

    # ---------- chapter units ----------
    def units(self, entry_files: list[str], entry_syms: list[Symbol]) -> list[dict]:
        g = self.g
        # call-distance from the front door, per file
        dist: dict[str, int] = {}
        q = deque((s.id, 0) for s in entry_syms)
        seen = {s.id for s in entry_syms}
        while q:
            sid, d = q.popleft()
            f = g.symbols[sid].file
            dist[f] = min(dist.get(f, 99), d)
            for e in g.callees(sid):
                if e.dst not in seen:
                    seen.add(e.dst)
                    q.append((e.dst, d + 1))
        for a, b, _ in g.imports:
            if a in entry_files:
                dist.setdefault(b, 3)
        cands = []
        for p in self.source_files:
            m = g.modules[p]
            real = [s for s in m.symbols if s.loc >= 3]
            if p.endswith("__init__.py") and len(real) < 2:
                continue
            if p in entry_files and len(real) < 2:
                continue
            if not real:
                continue
            cands.append(p)
        # group files of sub-packages / sub-folders with 3+ candidates into one unit
        by_dir = defaultdict(list)
        for p in cands:
            by_dir[posixpath.dirname(p)].append(p)
        if entry_files:
            main_dir = posixpath.dirname(sorted(entry_files, key=lambda f: f.count("/"))[0])
        else:
            main_dir = min((posixpath.dirname(p) for p in cands), key=lambda d: d.count("/"), default="")
        if main_dir == "" and cands and not any("/" not in p for p in cands):  # e.g. index.js at root, code in lib/
            main_dir = Counter(posixpath.dirname(p) for p in cands if p.count("/") == 1).most_common(1)[0][0] if any(p.count("/") == 1 for p in cands) else ""
        units = []
        for d, ps in by_dir.items():
            if d != main_dir and len(ps) >= 3 and len(cands) > 12:
                units.append({"files": sorted(ps, key=lambda p: -g.module_rank.get(p, 0))[:5], "dir": d})
            else:
                for p in ps:
                    units.append({"files": [p], "dir": None})
        for u in units:
            u["score"] = sum(g.module_rank.get(p, 0) for p in u["files"])
            u["dist"] = min(dist.get(p, 99) for p in u["files"])
            u["lines"] = sum(g.modules[p].lines for p in u["files"])
            u["nsyms"] = sum(1 for p in u["files"] for s in g.modules[p].symbols if s.loc >= 3 and s.public)
        units.sort(key=lambda u: -u["score"])
        big = [u for u in units if u["lines"] >= 60 and u["nsyms"] >= 2]
        small = [u for u in units if u not in big]
        chosen = big[:MAX_MODULE_CHAPTERS]
        rest = big[MAX_MODULE_CHAPTERS:]
        chosen.sort(key=lambda u: (u["dist"], -u["score"]))
        return chosen, small, rest

    # ---------- sections ----------
    def section_for(self, s: Symbol, chapter_no: int, focus_line: int | None = None, title: str | None = None) -> dict:
        g = self.g
        src = self.lines(s.file)
        snip = window(src, focus_line, s) if focus_line else symbol_snippet(src, s, self.children(s) if s.kind == "class" else None)
        callers = [e for e in g.callers(s.id) if g.modules[g.symbols[e.src].file].role == "source"]
        test_callers = [e for e in g.callers(s.id) if g.modules[g.symbols[e.src].file].role == "test"]
        callees = [e for e in g.callees(s.id)]
        facts = []
        facts.append(f"Defined in `{s.file}`, lines {s.start}–{s.end} ({s.loc} lines).")
        if s.bases:
            facts.append("Inherits from " + ", ".join(f"`{b}`" for b in s.bases) + ".")
        if s.decorators:
            facts.append("Decorated with " + ", ".join(f"`@{d}`" for d in s.decorators[:3]) + ".")
        if callers:
            names = list(dict.fromkeys(g.symbols[e.src].qualname for e in callers))
            facts.append("Called by " + ", ".join(f"`{n}`" for n in names[:4]) + (f" and {len(names) - 4} more" if len(names) > 4 else "") + ".")
        if callees:
            names = list(dict.fromkeys(g.symbols[e.dst].qualname for e in callees))
            facts.append("Calls " + ", ".join(f"`{n}`" for n in names[:5]) + (f" and {len(names) - 5} more" if len(names) > 5 else "") + ".")
        if s.kind == "class":
            kids = [c for c in self.children(s) if c.public or c.name == "__init__"]
            if kids:
                top_kids = list(dict.fromkeys(c.name for c in sorted(kids, key=lambda c: -g.rank.get(c.id, 0))))
                facts.append(f"Has {len(set(c.name for c in kids))} methods, including " + ", ".join(f"`{n}`" for n in top_kids[:4]) + ".")
        if test_callers:
            tfiles = sorted({g.symbols[e.src].file for e in test_callers})
            facts.append(f"Exercised by {len(test_callers)} test(s) in " + ", ".join(f"`{t}`" for t in tfiles[:2]) + ".")
        summary = doc_summary(s.doc, 300)
        if summary:
            lead = summary
        elif s.kind == "class":
            lead = f"`{s.name}` is a class in `{posixpath.basename(s.file)}` (it has no docstring, so read the code for intent)."
        else:
            lead = f"`{s.qualname}` is a {self.kind_word(s)} without a docstring; its name, callers and callees are the best clues."
        importance = ""
        n_in = len({e.src for e in callers})
        if n_in >= 5:
            importance = f"This is one of the busiest pieces of the codebase: {n_in} other functions call it."
        elif s.exported:
            importance = "It's part of the public API, so users of the library touch it directly."
        return {
            "id": s.id, "title": title or f"`{s.qualname}`", "symbol": s.qualname, "kind": s.kind, "file": s.file,
            "start": s.start, "end": s.end, "signature": s.signature, "lang": g.modules[s.file].lang,
            "code": snip["lines"], "focus": snip.get("focus"), "truncated": snip["truncated"],
            "github": self.link(s.file, snip["start"], snip["end"]), "lead": lead, "facts": facts, "importance": importance,
            "chapter": chapter_no,
        }

    def pick_sections(self, files: list[str], limit: int = 5) -> list[Symbol]:
        g = self.g
        syms = [s for p in files for s in g.modules[p].symbols if s.loc >= 3]
        syms.sort(key=lambda s: -g.rank.get(s.id, 0))
        chosen: list[Symbol] = []
        per_class = Counter()
        per_file = Counter()
        for s in syms:
            if len(chosen) >= limit:
                break
            if not s.public and g.rank.get(s.id, 0) < 0.25:
                continue
            if s.name.startswith("__") and s.name != "__init__":
                continue
            if s.parent:
                if per_class[s.parent] >= 2:
                    continue
                if s.name == "__init__" and s.parent not in [c.id for c in chosen]:
                    continue
            if len(files) > 1 and per_file[s.file] >= max(2, limit // len(files) + 1):
                continue
            chosen.append(s)
            per_file[s.file] += 1
            if s.parent:
                per_class[s.parent] += 1
        # keep the reading order natural: by file order, then line
        order = {p: i for i, p in enumerate(files)}
        return sorted(chosen, key=lambda s: (order.get(s.file, 0), s.start))

    # ---------- quizzes ----------
    def chapter_quiz(self, syms: list[Symbol], files: list[str], want: int = 5) -> list[dict]:
        g = self.g
        pool = self.ranked[:80]
        file_pool = [p for p in self.source_files if p not in files] or self.source_files
        class_pool = [s.name for s in self.ranked if s.kind == "class"][:40]
        out = []
        gens = []
        for s in syms:
            gens += [("which_file", s), ("calls", s), ("caller", s), ("inherits", s), ("bug", s)]
        for f in files:
            gens.append(("role", f))
        self.rng.shuffle(gens)
        kinds = Counter()
        for kind, obj in gens:
            if len(out) >= want:
                break
            if kinds[kind] >= (2 if kind != "bug" else 1):
                continue
            key = f"{kind}:{obj if isinstance(obj, str) else obj.id}"
            if key in self.used_q:
                continue
            q = None
            if kind == "which_file":
                q = Q.q_which_file(g, obj, file_pool + [p for p in files if p != obj.file], self.rng)
            elif kind == "calls":
                q = Q.q_calls(g, obj, pool, self.rng)
            elif kind == "caller":
                q = Q.q_caller(g, obj, pool, self.rng)
            elif kind == "inherits":
                q = Q.q_inherits(g, obj, class_pool, self.rng)
            elif kind == "role":
                q = Q.q_role(g, obj, self.source_files, self.rng)
            elif kind == "bug":
                q = self.bug_for([obj] + [c for c in self.children(obj)] if obj.kind == "class" else [obj])
            if q:
                self.used_q.add(key)
                kinds[kind] += 1
                out.append(q)
        for s in syms:  # filler that always works
            if len(out) >= min(want, 3):
                break
            key = f"defined:{s.id}"
            if key not in self.used_q and len(self.source_files) >= 4:
                q = Q.q_defined(g, s, file_pool, self.rng)
                if q:
                    self.used_q.add(key)
                    out.append(q)
        if not any(q["type"] == "bug" for q in out):
            extra = [c for s in syms for c in ([s] + (self.children(s) if s.kind == "class" else []))]
            extra += [s for f in files for s in g.modules[f].symbols]
            b = self.bug_for(extra)
            if b:
                out.append(b)
        return out

    def bug_for(self, syms: list[Symbol]) -> dict | None:
        for s in sorted(syms, key=lambda s: -self.g.rank.get(s.id, 0)):
            if s.id in self.used_bug or s.kind == "class":
                continue
            b = Q.mutate_symbol(self.lines(s.file), s, self.rng)
            if b:
                self.used_bug.add(s.id)
                b["github"] = self.link(s.file, s.start, s.end)
                b["lang"] = self.g.modules[s.file].lang
                return b
        return None

    # ---------- diagram ----------
    def chapter_diagram(self, syms: list[Symbol]) -> dict:
        g = self.g
        ids = {s.id for s in syms}
        nodes = {s.id: {"id": s.id, "label": s.qualname, "file": s.file, "main": True, "kind": s.kind} for s in syms}
        edges = []
        for s in syms:
            subj = [s] + (self.children(s) if s.kind == "class" else [])
            for x in subj:
                for e in g.callees(x.id)[:8]:
                    d = g.symbols[e.dst]
                    if g.modules[d.file].role != "source":
                        continue
                    if len(nodes) < 16 or e.dst in nodes:
                        nodes.setdefault(e.dst, {"id": e.dst, "label": d.qualname, "file": d.file, "main": e.dst in ids, "kind": d.kind})
                        edges.append({"source": s.id, "target": e.dst, "kind": "calls"})
                for e in g.callers(x.id)[:4]:
                    c = g.symbols[e.src]
                    if g.modules[c.file].role != "source":
                        continue
                    if len(nodes) < 16 or e.src in nodes:
                        nodes.setdefault(e.src, {"id": e.src, "label": c.qualname, "file": c.file, "main": e.src in ids, "kind": c.kind})
                        edges.append({"source": e.src, "target": s.id, "kind": "calls"})
        uniq = {(e["source"], e["target"]): e for e in edges if e["source"] != e["target"]}
        return {"nodes": list(nodes.values()), "edges": list(uniq.values())}

    # ---------- the whole course ----------
    def build(self) -> dict:
        g = self.g
        entry_syms, entry_files, entry_how = self.entry_symbols()
        chosen, small, rest = self.units(entry_files, entry_syms)
        chapters: list[dict] = []

        # 1. overview
        chapters.append(self.overview_chapter(entry_files))
        # 2. front door
        fd_syms = entry_syms[:5]
        if fd_syms:
            secs = [self.section_for(s, 2) for s in fd_syms]
            usage = usage_example(self.readme, self.main_lang) if self.readme else None
            intro = (f"Everything a user of **{self.ref.name}** touches first. We found these by reading {entry_how}. "
                     f"Start here: every other chapter is something these call, directly or indirectly.")
            chapters.append({"kind": "frontdoor", "title": "The front door", "subtitle": "The public API: where users come in",
                             "intro": intro, "files": entry_files, "sections": secs,
                             "usage": {"code": usage[0], "line": usage[1], "file": self.readme_name,
                                       "github": self.link(self.readme_name, usage[1])} if usage else None,
                             "quiz": self.chapter_quiz(fd_syms, entry_files, 4), "diagram": self.chapter_diagram(fd_syms)})
        # 3. trace
        steps = self.trace(entry_syms or self.ranked[:5])
        trace_ch = None
        if len(steps) >= 2:
            secs = []
            first = g.symbols[steps[0]["caller_id"]]
            for i, st in enumerate(steps):
                caller = g.symbols[st["caller_id"]]
                sec = self.section_for(caller, 0, focus_line=st["line"], title=f"Step {i + 1}: `{st['caller']}` → `{st['callee']}`")
                sec["lead"] = (f"`{st['caller']}` hands off to `{st['callee']}` on line {st['line']}"
                               + (f" of `{st['file']}`." if True else "")
                               + (" (this hop was resolved by name)." if st["weak"] else ""))
                d = doc_summary(caller.doc)
                if d:
                    sec["lead"] += f" What `{caller.qualname}` is for: {d}"
                secs.append(sec)
            last = g.symbols[steps[-1]["callee_id"]]
            end_sec = self.section_for(last, 0, title=f"Where it lands: `{last.qualname}`")
            secs.append(end_sec)
            tq = [x for x in [Q.q_trace_order(steps, self.rng)] if x]
            for st in self.rng.sample(steps, min(2, len(steps))):
                tq.append(Q.q_find_line(st))
            b = self.bug_for([g.symbols[s["callee_id"]] for s in steps])
            if b:
                tq.append(b)
            path = " → ".join(f"`{s}`" for s in [steps[0]["caller"]] + [x["callee"] for x in steps])
            trace_ch = {"kind": "trace", "title": f"Follow one call: `{first.qualname}`",
                        "subtitle": (lambda n: f"{len(steps)} hand-offs across {n} file{'s' if n != 1 else ''}")(len({s['file'] for s in steps} | {last.file})),
                        "intro": f"Let's follow what really happens when you call `{first.qualname}`, hop by hop, using the call graph: {path}.",
                        "files": sorted({s["file"] for s in steps} | {last.file}), "sections": secs, "trace": steps,
                        "quiz": tq, "diagram": {"nodes": [{"id": s, "label": g.symbols[s].qualname, "file": g.symbols[s].file, "main": True, "kind": g.symbols[s].kind}
                                                          for s in [steps[0]["caller_id"]] + [x["callee_id"] for x in steps]],
                                                "edges": [{"source": x["caller_id"], "target": x["callee_id"], "kind": "calls"} for x in steps]}}
            chapters.append(trace_ch)
        # 4. module chapters
        for u in chosen:
            syms = self.pick_sections(u["files"])
            if not syms:
                continue
            if u["dir"]:
                title = _human(posixpath.basename(u["dir"]))
                docs = [doc_summary(g.modules[p].doc) for p in u["files"]]
                subtitle = next((d for d in docs if d), f"The `{u['dir']}/` package: {len(u['files'])} files working together")
            else:
                p = u["files"][0]
                title = _human(posixpath.basename(p).rsplit(".", 1)[0])
                top3 = sorted(syms, key=lambda s: -g.rank.get(s.id, 0))[:3]
                subtitle = doc_summary(g.modules[p].doc) or ("Key pieces: " + ", ".join(f"`{s.qualname}`" for s in top3))
            chapters.append({"kind": "module", "title": title, "subtitle": subtitle, "files": u["files"], "intro": self.module_intro(u["files"], syms),
                             "sections": [self.section_for(s, 0) for s in syms], "quiz": self.chapter_quiz(syms, u["files"]),
                             "diagram": self.chapter_diagram(syms)})
        # 5. supporting cast
        if small:
            files = [p for u in sorted(small, key=lambda u: -u["score"])[:6] for p in u["files"]][:6]
            syms = []
            for p in files:
                syms += self.pick_sections([p], 1)
            if syms:
                chapters.append({"kind": "module", "title": "Supporting cast", "subtitle": "Small helpers the main pieces lean on",
                                 "files": files, "intro": self.module_intro(files, syms[:6]), "sections": [self.section_for(s, 0) for s in syms[:6]],
                                 "quiz": self.chapter_quiz(syms[:6], files, 4), "diagram": self.chapter_diagram(syms[:6])})
        # 6. tests
        tch = self.tests_chapter([s for c in chapters for s in c.get("sections", [])])
        if tch:
            chapters.append(tch)
        # 7. next steps + final exam
        chapters.append(self.next_chapter(chapters, rest))

        # exercises: attach to the chapter that covers the function's file
        ex = (python_exercises(g, self.text) if self.main_lang == "python" else []) + js_exercises(g, self.text)
        for e in ex:
            e["github"] = self.link(e["file"], e["start"], e["end"])
            target = next((c for c in chapters if c["kind"] == "module" and e["file"] in c["files"]), None) or \
                next((c for c in chapters if c["kind"] == "next"), chapters[-1])
            target.setdefault("exercises", [])
            if len(target["exercises"]) < 3:
                target["exercises"].append(e)
        for i, c in enumerate(chapters, 1):
            c["num"] = i
            c["id"] = f"ch{i}"
            c.setdefault("exercises", [])
            c.setdefault("quiz", [])
            c.setdefault("sections", [])
            for s in c["sections"]:
                s["chapter"] = i
            c["minutes"] = max(2, round(len(c["sections"]) * 1.5 + len(c["quiz"]) * 0.5 + len(c["exercises"]) * 1))
            c["narrative"] = None
        return {"chapters": chapters, "entry_files": entry_files, "entry_symbols": [s.id for s in entry_syms]}

    def module_intro(self, files: list[str], syms: list[Symbol]) -> str:
        g = self.g
        fs = ", ".join(f"`{f}`" for f in files)
        parts = [f"This chapter walks through {fs}."]
        docs = [doc_summary(g.modules[f].doc, 260) for f in files]
        docs = [d for d in docs if d]
        if docs:
            parts.append(docs[0])
        fset = set(files)
        users = Counter(a for a, b, _ in g.imports if b in fset and a not in fset and g.modules[a].role == "source")
        deps = Counter(b for a, b, _ in g.imports if a in fset and b not in fset and g.modules[b].role == "source")
        for e in g.calls:
            a, b = g.symbols[e.src].file, g.symbols[e.dst].file
            if g.modules[a].role != "source" or g.modules[b].role != "source":
                continue
            if b in fset and a not in fset:
                users[a] += 1
            elif a in fset and b not in fset:
                deps[b] += 1
        rel = []
        if users:
            rel.append("it's used by " + ", ".join(f"`{posixpath.basename(u)}`" for u, _ in users.most_common(3)))
        if deps:
            rel.append("it leans on " + ", ".join(f"`{posixpath.basename(d)}`" for d, _ in deps.most_common(3)))
        if rel:
            parts.append("In the architecture, " + " and ".join(rel) + ".")
        parts.append(f"You'll meet {len(syms)} key pieces, in reading order: " + ", ".join(f"`{s.qualname}`" for s in syms) + ".")
        return " ".join(parts)

    def overview_chapter(self, entry_files: list[str]) -> dict:
        g = self.g
        langs = self.stats["lang_lines"]
        total = sum(langs.values()) or 1
        lang_list = [{"name": k, "lines": v, "pct": round(100 * v / total)} for k, v in sorted(langs.items(), key=lambda kv: -kv[1])][:6]
        # external deps used by source code (not stdlib / node builtins)
        ext = Counter()
        for p in self.source_files:
            m = g.modules[p]
            for imp in m.imports:
                if imp.resolved:
                    continue
                if m.lang == "python":
                    if imp.level:
                        continue
                    top = imp.module.split(".")[0]
                    if top and top not in STDLIB and top != self.main_package():
                        ext[top] += 1
                else:
                    spec = imp.module
                    if spec.startswith((".", "/")):
                        continue
                    pkg = spec[5:] if spec.startswith("node:") else ("/".join(spec.split("/")[:2]) if spec.startswith("@") else spec.split("/")[0])
                    if pkg not in NODE_BUILTINS:
                        ext[pkg] += 1
        deps = [{"name": k, "uses": v} for k, v in ext.most_common(8)]
        # top-level layout
        layout = defaultdict(lambda: {"files": 0, "lines": 0, "roles": Counter()})
        for p, m in g.modules.items():
            top = p.split("/")[0] if "/" in p else "(root files)"
            layout[top]["files"] += 1
            layout[top]["lines"] += m.lines
            layout[top]["roles"][m.role] += 1
        tree = []
        for name, v in sorted(layout.items(), key=lambda kv: -kv[1]["lines"]):
            role = v["roles"].most_common(1)[0][0]
            hint = DIR_HINTS.get(name.lower()) or {"source": "source code", "test": "tests", "example": "examples", "docs": "documentation", "config": "build and tooling config"}[role]
            if any(f.startswith(name + "/") for f in entry_files):
                hint += " (the front door lives here)"
            tree.append({"path": name, "files": v["files"], "lines": v["lines"], "role": role, "hint": hint})
        desc = self.man.get("description") or ""
        rd = readme_description(self.readme) if self.readme else ""
        cmds = commands_from_readme(self.readme) if self.readme else []
        stats = {"files": self.stats["files_total"], "parsed": self.stats["files_parsed"], "symbols": len(g.symbols),
                 "calls": len(g.calls), "source_files": len(self.source_files),
                 "test_files": sum(1 for m in g.modules.values() if m.role == "test")}
        intro = (f"**{self.ref.owner}/{self.ref.name}**" + (f": {desc}" if desc else "") + "\n\n" + (rd if rd and rd != desc else ""))
        quiz = []
        if lang_list and len(lang_list) >= 1:
            main = lang_list[0]["name"]
            opts = [main] + [x for x in ["Python", "JavaScript", "TypeScript", "Go", "Rust", "Java"] if x != main][:3]
            self.rng.shuffle(opts)
            quiz.append({"type": "mcq", "kind": "warmup", "prompt": "Warm-up: which language is most of this repo written in?",
                         "options": opts, "answer": opts.index(main), "explain": f"{lang_list[0]['pct']}% of the code lines are {main}."})
        if len(deps) >= 2:
            top = deps[0]["name"]
            pool = [d["name"] for d in deps[1:]] + ["lodash", "numpy", "react", "django", "axios", "pydantic"]
            d = [x for x in dict.fromkeys(pool) if x != top][:3]
            opts = d + [top]
            self.rng.shuffle(opts)
            quiz.append({"type": "mcq", "kind": "deps", "prompt": "Which outside library does the source code import most often?",
                         "options": opts, "answer": opts.index(top), "explain": f"`{top}` is imported {deps[0]['uses']} times across the source files."})
        test_dirs = [t for t in tree if t["role"] == "test"]
        if test_dirs and len(tree) >= 3:
            correct = test_dirs[0]["path"]
            opts = [correct] + [t["path"] for t in tree if t["path"] != correct][:3]
            self.rng.shuffle(opts)
            quiz.append({"type": "mcq", "kind": "layout", "prompt": "Where do the tests live?", "options": opts,
                         "answer": opts.index(correct), "explain": f"`{correct}/` holds {test_dirs[0]['files']} test files."})
        if entry_files and len(self.source_files) >= 4:
            correct = entry_files[0]
            others = [p for p in sorted(self.source_files, key=lambda p: -g.module_rank.get(p, 0)) if p not in entry_files][:3]
            if len(others) >= 2:
                opts = others + [correct]
                self.rng.shuffle(opts)
                quiz.append({"type": "mcq", "kind": "entry", "prompt": "Which file is the front door users import first?", "options": opts,
                             "answer": opts.index(correct), "explain": f"`{correct}` is where the public API is exposed."})
        return {"kind": "overview", "title": f"Welcome to {self.ref.name}", "subtitle": "What it is, how it's laid out, and how to run it",
                "intro": intro.strip(), "files": [], "sections": [], "languages": lang_list, "dependencies": deps,
                "layout": tree, "commands": cmds, "stats": stats, "quiz": quiz, "license": self.man.get("license"),
                "readme": {"file": self.readme_name, "github": self.link(self.readme_name)} if self.readme_name else None}

    def tests_chapter(self, sections: list[dict]) -> dict | None:
        g = self.g
        tests = [m for m in g.modules.values() if m.role == "test"]
        if not tests:
            return None
        test_funcs = [s for m in tests for s in m.symbols if s.name.startswith("test") and s.kind in ("function", "method")]
        js_tests = 0
        for m in tests:
            if m.lang != "python":
                js_tests += len(re.findall(r"(?m)^\s*(?:it|test)\s*\(", self.text.get(m.path, "")))
        n_tests = len(test_funcs) + js_tests
        fw = self.man.get("test_framework") or ("pytest" if any("pytest" in i.module for m in tests for i in m.imports) else
                                                ("mocha" if js_tests and "describe(" in "".join(self.text.get(m.path, "")[:2000] for m in tests) else None))
        cmd = self.man.get("test_command") or ("python -m pytest" if fw == "pytest" else ("npm test" if self.main_lang != "python" else "python -m unittest"))
        # tests that exercise symbols taught in earlier chapters
        taught = {s["id"] for s in sections}
        picks = []
        for s in test_funcs:
            hits = [e for e in g.callees(s.id) if e.dst in taught]
            if hits and 4 <= s.loc <= 30:
                picks.append((len(hits), s, hits))
        picks.sort(key=lambda x: (-x[0], x[1].loc))
        secs = []
        for _n, s, hits in picks[:3]:
            sec = self.section_for(s, 0)
            sec["lead"] = f"This test exercises " + ", ".join(f"`{g.symbols[h.dst].qualname}`" for h in hits[:3]) + ", which you met earlier."
            secs.append(sec)
        if not secs:  # JS tests are usually anonymous callbacks; show the biggest test file's head
            m = max(tests, key=lambda m: m.lines)
            src = self.lines(m.path)
            secs.append({"id": m.path, "title": f"`{m.path}`", "symbol": m.path, "kind": "file", "file": m.path, "start": 1,
                         "end": min(len(src), 30), "signature": "", "lang": m.lang, "code": [[i + 1, src[i]] for i in range(min(len(src), 30))],
                         "focus": None, "truncated": len(src) > 30, "github": self.link(m.path, 1, min(len(src), 30)),
                         "lead": f"The largest test file ({m.lines} lines).", "facts": [], "importance": ""})
        files = sorted({m.path for m in tests}, key=lambda p: -g.modules[p].lines)
        q = []
        opts = list(dict.fromkeys([cmd, "npm start", "python setup.py install", "make deploy", "pip install ."]))[:4]
        if cmd not in opts:
            opts[0] = cmd
        self.rng.shuffle(opts)
        q.append({"type": "mcq", "kind": "tests", "prompt": "Which command runs the test suite?", "options": opts, "answer": opts.index(cmd),
                  "explain": f"`{cmd}`" + (f" (the project uses {fw})." if fw else ".")})
        if picks:
            _n, s, hits = picks[0]
            target = g.symbols[hits[0].dst]
            others = [x[1].qualname for x in picks[1:] if hits[0].dst not in {h.dst for h in x[2]}]
            others += [t.qualname for t in test_funcs if t.id != s.id][:20]
            d = [o for o in dict.fromkeys(others) if o != s.qualname][:3]
            mq = Q._mcq(f"Which test exercises `{target.qualname}`?", s.qualname, d, f"`{s.qualname}` in `{s.file}` calls it on line {hits[0].line}.", self.rng, kind="tests")
            if mq:
                q.append(mq)
        return {"kind": "tests", "title": "How it's tested", "subtitle": f"{n_tests} tests across {len(tests)} files" + (f", run with {fw}" if fw else ""),
                "intro": f"Tests are the best documentation of intended behaviour. Run them with `{cmd}`.", "files": files[:6],
                "sections": secs, "quiz": q, "test_command": cmd, "test_framework": fw,
                "exercises": [{"type": "local", "title": "Run the tests yourself",
                               "steps": [f"git clone --depth 1 {self.ref.url}", f"cd {self.ref.name}",
                                         ("python -m pip install -e . pytest" if self.main_lang == "python" else "npm install"), cmd]}]}

    def next_chapter(self, chapters: list[dict], rest: list[dict]) -> dict:
        g = self.g
        todos = []
        for p in self.source_files:
            for ln, t in g.modules[p].todos:
                todos.append({"file": p, "line": ln, "text": t, "github": self.link(p, ln)})
        big = sorted((s for s in self.ranked if s.kind != "class"), key=lambda s: -s.loc)[:5]
        undocumented = [s for s in self.ranked[:60] if not s.doc and s.public and s.kind != "class" and s.loc >= 8][:5]
        covered = {f for c in chapters for f in c.get("files", [])}
        further = [p for p in sorted(self.source_files, key=lambda p: -g.module_rank.get(p, 0)) if p not in covered][:8]
        # final exam: fresh questions from across the codebase
        exam = []
        pool = [s for s in self.ranked[:40]]
        self.rng.shuffle(pool)
        for s in pool:
            if len(exam) >= 4:
                break
            q = Q.q_which_file(g, s, self.source_files, self.rng) if f"which_file:{s.id}" not in self.used_q else None
            if q:
                self.used_q.add(f"which_file:{s.id}")
                exam.append(q)
        for s in pool:
            if len(exam) >= 4:
                break
            if f"defined:{s.id}" not in self.used_q and f"which_file:{s.id}" not in self.used_q:
                q = Q.q_defined(g, s, self.source_files, self.rng)
                if q:
                    self.used_q.add(f"defined:{s.id}")
                    exam.append(q)
        for _ in range(2):
            b = self.bug_for(pool)
            if b:
                exam.append(b)
        return {"kind": "next", "title": "Your turn: where to go next", "subtitle": "Open questions, big functions, and a final exam",
                "intro": "You've toured the main paths. Here's where a newcomer can dig in, and a final exam built from parts of the code you haven't been quizzed on yet.",
                "files": [], "sections": [],
                "todos": todos[:12], "big": [{"symbol": s.qualname, "file": s.file, "start": s.start, "lines": s.loc, "github": self.link(s.file, s.start, s.end)} for s in big],
                "undocumented": [{"symbol": s.qualname, "file": s.file, "start": s.start, "github": self.link(s.file, s.start, s.end)} for s in undocumented],
                "further": [{"file": p, "lines": g.modules[p].lines, "summary": doc_summary(g.modules[p].doc), "github": self.link(p)} for p in further],
                "quiz": exam}
