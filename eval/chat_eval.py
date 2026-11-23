"""Time and inspect 'ask the repo' answers with the configured chat model.

python eval/chat_eval.py [course_root]   (default /tmp/diag; courses must be built there)
Prints time to first token, total time, citations and graph corrections for each question, then medians.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from repocademy.ask import _ANSWERS, ask  # noqa: E402
from repocademy.llm import get_llm  # noqa: E402

QUESTIONS = [
    ("psf__requests", "How does a Session pick the adapter for a URL?"),
    ("psf__requests", "Where are redirects followed?"),
    ("psf__requests", "How are cookies stored between requests?"),
    ("psf__requests", "Who calls get_adapter?"),
    ("pallets__flask", "How does the request context get pushed?"),
    ("pallets__flask", "Where are blueprints registered?"),
    ("expressjs__express", "How does res.send set the content type?"),
    ("axios__axios", "How are interceptors run before a request?"),
]


def main(root="/tmp/diag"):
    llm = get_llm("chat")
    print("model:", llm.label if llm else None)
    ft, tot = [], []
    out = []
    for slug, q in QUESTIONS:
        d = Path(root) / slug
        course = json.loads((d / "course.json").read_text())
        _ANSWERS.clear()
        final = None
        for ev in ask(course, d, q, llm):
            if ev["type"] == "final":
                final = ev
        ft.append(final.get("first_token_ms") or 0)
        tot.append(final.get("total_ms") or 0)
        out.append({"repo": slug, "q": q, **{k: final.get(k) for k in ("text", "first_token_ms", "total_ms", "corrections", "removed")},
                    "citations": [f"{c['file']}:{c['start']}" for c in final["citations"]]})
        print(f"\n[{slug}] {q}\n  first token {final.get('first_token_ms')} ms, total {final.get('total_ms')} ms, "
              f"{len(final['citations'])} citations, {len(final.get('corrections') or [])} corrections, {final['removed']} removed")
        print("  " + final["text"].replace("\n", "\n  "))
        for c in final.get("corrections") or []:
            print("  CORRECTED:", c["claim"], "->", c["fix"])
    print(f"\nmedian first token {statistics.median(ft)} ms, median total {statistics.median(tot)} ms, max total {max(tot)} ms")
    Path("eval/chat_eval_last.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:])
