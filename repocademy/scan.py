"""Walk a checkout and pick the files worth teaching."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

LANG_BY_EXT = {".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
               ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript"}
OTHER_LANGS = {".go": "Go", ".rs": "Rust", ".java": "Java", ".rb": "Ruby", ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++",
               ".cs": "C#", ".php": "PHP", ".swift": "Swift", ".kt": "Kotlin", ".scala": "Scala", ".sh": "Shell",
               ".html": "HTML", ".css": "CSS", ".scss": "CSS", ".vue": "Vue", ".svelte": "Svelte", ".lua": "Lua"}
SKIP_DIRS = {".git", "node_modules", "dist", "build", "out", "coverage", "vendor", "third_party", "__pycache__", ".venv", "venv",
             "env", ".tox", ".nox", ".mypy_cache", ".pytest_cache", "site-packages", ".next", ".nuxt", "bower_components",
             ".idea", ".vscode", "target", "_build", ".github", "htmlcov", "static", "assets", "fixtures"}
MAX_FILE_BYTES = 400_000
MAX_FILES = 2500
_MINIFIED = re.compile(r"\.min\.(js|css)$|\.bundle\.js$|-bundle\.js$")


@dataclass
class SourceFile:
    path: str  # posix, repo-relative
    lang: str
    text: str
    role: str


def role_of(path: str) -> str:
    p = "/" + path.lower()
    name = p.rsplit("/", 1)[-1]
    if re.search(r"/(tests?|__tests__|spec|specs|testing)/", p) or re.match(r"(test_.*|.*_test)\.py$", name) or re.search(r"\.(test|spec|test-d|bench)\.[jt]sx?$", name) or re.search(r"/(test-d|type-tests?|__mocks__)/", p) or name == "conftest.py":
        return "test"
    if re.search(r"/(examples?|samples?|demos?|benchmarks?|bench)/", p) or re.match(r"(benchmarks?|bench)\.[jt]s$|benchmarks?\.py$", name):
        return "example"
    if re.search(r"/(docs?|documentation)/", p):
        return "docs"
    if re.search(r"(^|/)(setup\.py|noxfile\.py|fabfile\.py|conf\.py|gulpfile\.js|gruntfile\.js|webpack\.config\.[jt]s|rollup\.config\.[jt]s|vite\.config\.[jt]s|jest\.config\.[jt]s|babel\.config\.js|eslint\.config\.[jt]s|\.eslintrc\.js|karma\.conf\.js)$", p):
        return "config"
    return "source"


def scan(root: Path) -> tuple[list[SourceFile], dict]:
    """Returns (parsable files, stats). Never follows symlinks."""
    files: list[SourceFile] = []
    lang_lines: dict[str, int] = {}
    all_files = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for fn in sorted(filenames):
            full = Path(dirpath) / fn
            if full.is_symlink():
                continue
            rel = full.relative_to(root).as_posix()
            all_files += 1
            ext = full.suffix.lower()
            lang = LANG_BY_EXT.get(ext)
            if lang is None:
                if ext in OTHER_LANGS:
                    try:
                        n = full.read_bytes()[:MAX_FILE_BYTES].count(b"\n")
                    except OSError:
                        n = 0
                    lang_lines[OTHER_LANGS[ext]] = lang_lines.get(OTHER_LANGS[ext], 0) + n
                continue
            if _MINIFIED.search(fn) or fn.endswith(".d.ts"):
                continue
            try:
                size = full.stat().st_size
                if size > MAX_FILE_BYTES:
                    continue
                text = full.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if lang == "javascript" and text.count("\n") < 3 and len(text) > 3000:  # minified one-liner
                continue
            pretty = {"python": "Python", "javascript": "JavaScript", "typescript": "TypeScript"}[lang]
            lang_lines[pretty] = lang_lines.get(pretty, 0) + text.count("\n") + 1
            if len(files) < MAX_FILES:
                files.append(SourceFile(rel, lang, text, role_of(rel)))
    return files, {"files_total": all_files, "files_parsed": len(files), "lang_lines": lang_lines}


def read_text(root: Path, rel: str, limit: int = 200_000) -> str | None:
    """Read a repo file safely (no escaping the checkout, no symlinks)."""
    try:
        full = (root / rel).resolve()
        if not str(full).startswith(str(root.resolve()) + os.sep) or (root / rel).is_symlink() or not full.is_file():
            return None
        return full.read_text(encoding="utf-8", errors="replace")[:limit]
    except (OSError, ValueError):
        return None
