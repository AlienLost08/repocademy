"""Developer diagnostics: print entry points, front door, trace and counts for cached clones."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from repocademy.analyze import analyze_repo
from repocademy.builder import build_from_checkout
from repocademy.fetch import RepoRef

for slug in sys.argv[1:]:
    root = Path("cache/repos") / slug
    owner, name = slug.split("__")
    t = time.time()
    c = build_from_checkout(root, RepoRef(owner, name), "sha", "main", Path("/tmp/diag") / slug)
    print(f"=== {slug} ({time.time()-t:.1f}s) entry={c['entry_files']}")
    for ch in c["chapters"]:
        secs = [s["symbol"] for s in ch.get("sections", [])]
        print(f"  {ch['num']:>2} {ch['kind']:<9} {ch['title'][:40]:<40} q={len(ch['quiz']):<2} ex={len([e for e in ch.get('exercises', []) if e['type'].endswith('_run')])} {secs[:6]}")
    tr = [x for x in c["chapters"] if x["kind"] == "trace"]
    if tr:
        print("  TRACE", " → ".join([tr[0]["trace"][0]["caller"]] + [s["callee"] + ("?" if s["weak"] else "") for s in tr[0]["trace"]]))
