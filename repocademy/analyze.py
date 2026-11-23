"""Run the right analyser on every scanned file."""

from __future__ import annotations

from pathlib import Path

from .graph import RepoGraph, build_graph
from .js_analyzer import analyze_js
from .model import Module
from .py_analyzer import analyze_python
from .scan import scan


def analyze_files(files) -> list[Module]:
    mods = []
    for f in files:
        if f.lang == "python":
            m = analyze_python(f.path, f.text)
        else:
            try:
                m = analyze_js(f.path, f.text, f.lang)
            except Exception:  # pragma: no cover - tree-sitter is error tolerant; be defensive anyway
                m = Module(path=f.path, lang=f.lang, lines=f.text.count("\n") + 1)
        m.role = f.role
        mods.append(m)
    return mods


def analyze_repo(root: Path) -> tuple[RepoGraph, dict, list]:
    files, stats = scan(root)
    mods = analyze_files(files)
    g = build_graph(mods)
    return g, stats, files
