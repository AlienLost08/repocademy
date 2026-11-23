"""Re-check stored chapter intros with the current rules; clean them or rewrite the ones that fail.

Usage: python scripts/fix_intros.py showcase/psf__requests [more course dirs]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from repocademy.llm import get_llm  # noqa: E402
from repocademy.narrate import allowed_names, final_check, narrate_chapter  # noqa: E402

llm = get_llm("narrate")
for d in sys.argv[1:]:
    f = Path(d) / "course.json"
    c = json.loads(f.read_text())
    allowed = allowed_names(c)
    for ch in c["chapters"]:
        n = ch.get("narrative")
        if not n:
            continue
        t = final_check(n["text"], c, allowed)
        if t is None and llm is not None:
            t, probs = narrate_chapter(llm, c, ch, allowed)
            print(f"  [{d}] ch{ch['num']} rewritten: {t!r} {probs}")
        elif t != n["text"]:
            print(f"  [{d}] ch{ch['num']} cleaned: {t!r}")
        if t:
            ch["narrative"]["text"] = t
        else:
            ch.pop("narrative", None)
    nar = c.setdefault("narration", {})
    nar["accepted"] = sum(1 for ch in c["chapters"] if ch.get("narrative"))
    nar["rejected"] = sum(1 for ch in c["chapters"] if not ch.get("narrative") and ch["kind"] != "next")
    f.write_text(json.dumps(c))
    print(d, "accepted", nar["accepted"], "template", nar["rejected"])
