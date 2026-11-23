"""Build courses through the running server's API and print what each one teaches (front door, trace, counts).

Usage: python scripts/verify_repos.py owner/repo [owner/repo ...] [--refresh] [--base http://127.0.0.1:8800]
"""
import json
import sys
import time
import urllib.request

args = [a for a in sys.argv[1:] if not a.startswith("--")]
BASE = next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--base"), "http://127.0.0.1:8800")
if BASE in args:
    args.remove(BASE)
refresh = "--refresh" in sys.argv


def call(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=300))


for repo in args:
    t = time.time()
    r = call("/api/build", {"url": f"https://github.com/{repo}", "refresh": refresh})
    slug = r.get("slug")
    if not r.get("cached"):
        while True:
            time.sleep(0.5)
            j = call(f"/api/jobs/{r['job']}")
            if j["status"] == "error":
                print(f"=== {repo}: ERROR {j['error']}")
                break
            if j["status"] == "done":
                slug = j["slug"]
                break
    c = call(f"/api/courses/{slug}")
    chs = c["chapters"]
    fd = next((x for x in chs if x["kind"] == "frontdoor"), None)
    tr = next((x for x in chs if x["kind"] == "trace"), None)
    nq = sum(len(x["quiz"]) for x in chs)
    qtypes = {}
    for x in chs:
        for q in x["quiz"]:
            qtypes[q["type"]] = qtypes.get(q["type"], 0) + 1
    nex = sum(len(x.get("exercises", [])) for x in chs)
    print(f"=== {repo} ({c.get('main_lang')}) built in {c.get('build_seconds')}s (wall {time.time() - t:.1f}s): "
          f"{len(chs)} chapters, {nq} questions {qtypes}, {nex} runnable exercises")
    if fd:
        print("  front door:", ", ".join(s["symbol"] for s in fd["sections"]))
    if tr:
        print("  trace:", " → ".join([tr["trace"][0]["caller"]] + [s["callee"] + ("?" if s["weak"] else "") for s in tr["trace"]]))
    print("  chapters:", " | ".join(x["title"] for x in chs))
