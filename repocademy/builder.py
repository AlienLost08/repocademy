"""The pipeline: clone -> scan -> analyse -> map -> plan -> save. Cached per commit."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from . import __version__
from .analyze import analyze_files
from .fetch import clone, parse_repo_url
from .graph import build_graph
from .planner import Planner
from .repoinfo import find_readme, manifests
from .retrieval import Chunk
from .scan import scan
from .snippets import doc_summary

SCHEMA = 3
Progress = Callable[[str, str, dict | None], None]


def _noop(stage: str, msg: str, data: dict | None = None):
    pass


def course_dir(root: Path, slug: str) -> Path:
    return root / "courses" / slug


def graph_json(g, chapters: list[dict]) -> dict:
    ch_of = {}
    for c in chapters:
        if c["kind"] in ("module", "frontdoor"):
            for f in c["files"]:
                ch_of.setdefault(f, c["num"])
    nodes = []
    for p, m in g.modules.items():
        if m.role != "source":
            continue
        nodes.append({"id": p, "label": p.rsplit("/", 1)[-1], "dir": p.rsplit("/", 1)[0] if "/" in p else "", "lines": m.lines,
                      "rank": round(g.module_rank.get(p, 0), 4), "chapter": ch_of.get(p), "lang": m.lang,
                      "symbols": len(m.symbols), "summary": doc_summary(m.doc)})
    ids = {n["id"] for n in nodes}
    w = {}
    for a, b, _ in g.imports:
        if a in ids and b in ids and a != b:
            w[(a, b, "imports")] = w.get((a, b, "imports"), 0) + 1
    for e in g.calls:
        a, b = g.symbols[e.src].file, g.symbols[e.dst].file
        if a in ids and b in ids and a != b:
            w[(a, b, "calls")] = w.get((a, b, "calls"), 0) + 1
    edges = [{"source": a, "target": b, "kind": k, "weight": v} for (a, b, k), v in w.items()]
    return {"nodes": nodes, "edges": edges}


def calls_json(g) -> dict:
    """Symbol-level call graph for grounding chat answers: who calls what, at which line."""
    syms = {sid: [s.qualname, s.file, s.start, s.end, s.kind, s.parent] for sid, s in g.symbols.items()
            if g.modules[s.file].role in ("source", "example")}
    edges = [[e.src, e.dst, e.line, int(e.weak)] for e in g.calls if e.src in syms and e.dst in syms]
    return {"symbols": syms, "edges": edges}


def chunks_for(g, files_text: dict[str, str], readme: tuple[str, str]) -> list[dict]:
    out = []
    for p, m in g.modules.items():
        if m.role not in ("source", "test", "example"):
            continue
        lines = files_text.get(p, "").splitlines()
        if m.doc:
            out.append(Chunk(f"{p}::<module>", p, 1, min(len(lines), 30), "module " + p.rsplit("/", 1)[-1], "\n".join(lines[:30]), doc_summary(m.doc)))
        for s in m.symbols:
            end = s.end if s.kind != "class" else min(s.end, s.start + 25)
            end = min(end, s.start + 59, len(lines))
            if m.role == "test" and not s.name.startswith("test"):
                continue
            out.append(Chunk(s.id, p, s.start, end, s.qualname, "\n".join(lines[s.start - 1: end]), doc_summary(s.doc)))
    name, text = readme
    if text:
        lines = text.splitlines()
        for i in range(0, min(len(lines), 400), 40):
            out.append(Chunk(f"{name}::{i + 1}", name, i + 1, min(i + 40, len(lines)), "README", "\n".join(lines[i: i + 40])))
    return [c.__dict__ for c in out]


def build_course(url: str, data_root: Path, progress: Progress = _noop, refresh: bool = False) -> dict:
    t0 = time.time()
    ref = parse_repo_url(url)
    progress("clone", f"Cloning {ref.owner}/{ref.name} (shallow)…")
    path, sha, branch = clone(ref, data_root / "repos", refresh=refresh)
    out_dir = course_dir(data_root, ref.slug)
    cached = out_dir / "course.json"
    if cached.exists() and not refresh:
        c = json.loads(cached.read_text())
        if c.get("repo", {}).get("sha") == sha and c.get("schema") == SCHEMA:
            progress("done", "Loaded from cache", {"cached": True})
            return c
    course = build_from_checkout(path, ref, sha, branch, out_dir, progress)
    course["build_seconds"] = round(time.time() - t0, 2)
    (out_dir / "course.json").write_text(json.dumps(course))
    nq = sum(len(c["quiz"]) for c in course["chapters"])
    progress("done", f"{len(course['chapters'])} chapters, {nq} quiz questions in {course['build_seconds']}s",
             {"chapters": len(course["chapters"]), "questions": nq})
    return course


def build_from_checkout(path: Path, ref, sha: str, branch: str, out_dir: Path, progress: Progress = _noop) -> dict:
    """Analyse an already checked-out tree (no network) and write course.json + index.json to out_dir."""
    t0 = time.time()
    progress("scan", "Reading files…")
    files, stats = scan(path)
    progress("parse", f"Parsing {len(files)} files with ast / tree-sitter…", {"files": len(files)})
    mods = analyze_files(files)
    nsym = sum(len(m.symbols) for m in mods)
    progress("map", f"Mapping {nsym} functions and classes: imports, calls, entry points…", {"symbols": nsym})
    g = build_graph(mods)
    files_text = {f.path: f.text for f in files}
    readme = find_readme(path)
    man = manifests(path)
    progress("plan", f"Found {len(g.calls)} call edges. Planning chapters, quizzes and exercises…", {"calls": len(g.calls)})
    planner = Planner(g, files_text, stats, ref, sha, branch, readme, man)
    plan = planner.build()
    chapters = plan["chapters"]
    course = {
        "schema": SCHEMA, "version": __version__, "slug": ref.slug,
        "repo": {"owner": ref.owner, "name": ref.name, "url": ref.url, "sha": sha, "branch": branch,
                 "description": man.get("description") or "", "license": man.get("license")},
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "build_seconds": None, "main_lang": planner.main_lang,
        "stats": chapters[0].get("stats", {}), "chapters": chapters,
        "graph": graph_json(g, chapters), "entry_files": plan["entry_files"],
        "symbols": [{"id": s.id, "name": s.qualname, "file": s.file, "start": s.start, "kind": s.kind}
                    for s in g.symbols.values() if g.modules[s.file].role == "source"],
        "narration": {"status": "none", "model": None},
    }
    course["build_seconds"] = round(time.time() - t0, 2)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.json").write_text(json.dumps(chunks_for(g, files_text, readme)))
    (out_dir / "calls.json").write_text(json.dumps(calls_json(g)))
    (out_dir / "course.json").write_text(json.dumps(course))
    return course
