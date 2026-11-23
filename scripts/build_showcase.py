"""Pre-build the showcase courses shipped in ./showcase so the demo opens instantly.

Usage:  python scripts/build_showcase.py [owner/repo ...]
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


def main(repos: list[str]) -> None:
    work = ROOT / "cache"
    out_root = ROOT / "showcase"
    out_root.mkdir(exist_ok=True)
    llm = get_llm("narrate")
    for url in repos:
        t0 = time.time()
        course = build_course(url, work, refresh=True)
        src = work / "courses" / course["slug"]
        if llm is not None:
            narrate_course(course, llm, progress=lambda i, n: print(f"  narrating chapter {i}/{n}", end="\r"))
            (src / "course.json").write_text(json.dumps(course))
        dst = out_root / course["slug"]
        dst.mkdir(exist_ok=True)
        for name in ("course.json", "index.json"):
            shutil.copy2(src / name, dst / name)
        n = course.get("narration", {})
        print(f"{url}: {len(course['chapters'])} chapters, "
              f"{sum(len(c['quiz']) for c in course['chapters'])} questions, "
              f"narration {n.get('accepted', 0)} accepted / {n.get('rejected', 0)} kept as template, "
              f"{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main(sys.argv[1:] or DEFAULT)
