"""Pre-build the showcase courses shipped in ./showcase so the demo opens instantly.

Usage:  python scripts/build_showcase.py [owner/repo ...] [--refresh]
(--refresh re-clones; intros from an earlier build of the same commit are reused.)
Needs network access to github.com (shallow clone). Narration uses a local model through Ollama
when one is available (set REPOCADEMY_LLM=off to skip it).
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from repocademy.builder import build_course  # noqa: E402
from repocademy.llm import get_llm  # noqa: E402
from repocademy.narrate import narrate_course  # noqa: E402

DEFAULT = ["psf/requests", "pallets/flask", "expressjs/express"]


def reuse_narration(course: dict, old_path: Path) -> int:
    """Keep accepted intros from a previous build of the same commit (chapters matched by id + title)."""
    if not old_path.exists():
        return 0
    old = json.loads(old_path.read_text())
    if old.get("repo", {}).get("sha") != course["repo"]["sha"]:
        return 0
    prev = {(c["id"], c["title"]): c.get("narrative") for c in old["chapters"]}
    n = 0
    for ch in course["chapters"]:
        nar = prev.get((ch["id"], ch["title"]))
        if nar:
            ch["narrative"] = nar
            n += 1
    if n:
        course["narration"] = dict(old.get("narration", {}))
    return n


def main(repos: list[str]) -> None:
    work = ROOT / "cache"
    out_root = ROOT / "showcase"
    out_root.mkdir(exist_ok=True)
    llm = get_llm("narrate")
    for url in repos:
        t0 = time.time()
        course = build_course(url, work, refresh="--refresh" in sys.argv)
        src = work / "courses" / course["slug"]
        if reuse_narration(course, out_root / course["slug"] / "course.json"):
            (src / "course.json").write_text(json.dumps(course))
        elif llm is not None:
            narrate_course(course, llm, progress=lambda i, n: print(f"  narrating chapter {i}/{n}", end="\r"))
            (src / "course.json").write_text(json.dumps(course))
        dst = out_root / course["slug"]
        dst.mkdir(exist_ok=True)
        for name in ("course.json", "index.json", "calls.json"):
            shutil.copy2(src / name, dst / name)
        n = course.get("narration", {})
        print(f"{url}: {len(course['chapters'])} chapters, "
              f"{sum(len(c['quiz']) for c in course['chapters'])} questions, "
              f"narration {n.get('accepted', 0)} accepted / {n.get('rejected', 0)} kept as template, "
              f"{time.time() - t0:.0f}s")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args or DEFAULT)
