"""Capture README / Devpost screenshots from a running server (default http://127.0.0.1:8800).

Usage: python scripts/screenshots.py [base_url]
Needs `playwright` plus a Chrome/Chromium install. Writes PNGs to docs/screenshots/.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8800"
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
PY, JS, AX, FRESH = "psf__requests", "expressjs__express", "axios__axios", "https://github.com/karpathy/micrograd"
CHAT_Q = "How does a Session pick the adapter for a URL?"


def course(slug):
    return json.load(urllib.request.urlopen(f"{BASE}/api/courses/{slug}"))


def main():
    import shutil  # the "fresh build" shot needs a repo without a built course
    shutil.rmtree(Path(__file__).resolve().parent.parent / "cache" / "courses" / "karpathy__micrograd", ignore_errors=True)
    req = course(PY)
    errors = []
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception:
            browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(BASE + "/")
        page.evaluate("localStorage.clear()")
        page.reload()
        page.wait_for_selector("#cards .card")
        page.wait_for_timeout(800)
        page.screenshot(path=OUT / "01-home.png")

        # live build of a repo that has no course yet
        page.fill("#urlInput", FRESH)
        page.click("#urlForm button[type=submit]")
        page.wait_for_selector("#buildOverlay:not(.hidden)")
        page.wait_for_selector('#pipeline li[data-k="plan"].active, #pipeline li[data-k="plan"].done', timeout=60_000)
        page.wait_for_timeout(250)
        page.screenshot(path=OUT / "02-fresh-build.png")
        page.wait_for_url("**/c/**", timeout=120_000)
        page.wait_for_selector(".chlist li")
        page.wait_for_timeout(800)

        def chapter(slug, num, wait=900):
            page.goto(f"{BASE}/c/{slug}#ch{num}")
            page.wait_for_selector(".chlist li")
            page.wait_for_timeout(wait)

        chs = req["chapters"]
        chapter(PY, 1)
        page.screenshot(path=OUT / "03-overview.png")

        tr = next(c for c in chs if c["kind"] == "trace")
        chapter(PY, tr["num"], 1500)
        page.screenshot(path=OUT / "04-trace.png")

        mod = next(c for c in chs if c["kind"] == "module")
        chapter(PY, mod["num"], 1500)
        page.locator("#sec0").scroll_into_view_if_needed()
        page.evaluate("document.querySelector('#sec0').scrollIntoView({block: 'start'}); window.scrollBy(0, -80)")
        page.wait_for_timeout(500)
        page.screenshot(path=OUT / "05-code-section.png")

        # a "find the bug" question, answered correctly
        bug_ch = next(c for c in chs if any(q["type"] == "bug" for q in c["quiz"]))
        chapter(PY, bug_ch["num"])
        qi = next(i for i, q in enumerate(bug_ch["quiz"]) if q["type"] == "bug")
        q = page.locator(".q").nth(qi)
        q.scroll_into_view_if_needed()
        q.locator(".opt").nth(bug_ch["quiz"][qi]["answer"]).click()
        page.wait_for_timeout(600)
        q.evaluate("el => { el.scrollIntoView({block: 'start'}); window.scrollBy(0, -70); }")
        page.wait_for_timeout(300)
        page.screenshot(path=OUT / "06-find-the-bug.png")

        # runnable exercise (Pyodide loads from the jsDelivr CDN on first use)
        ex_ch = next(c for c in chs if any(e["type"] == "python_run" for e in c.get("exercises", [])))
        chapter(PY, ex_ch["num"])
        ex = page.locator(".ex").first
        ex.scroll_into_view_if_needed()
        ex.locator(".pred").fill("None")
        ex.locator(".run").click()
        page.wait_for_selector(".ex .ex-out.ok, .ex .ex-out.err", timeout=120_000)
        page.wait_for_timeout(500)
        ex.evaluate("el => { el.scrollIntoView({block: 'start'}); window.scrollBy(0, -70); }")
        page.wait_for_timeout(300)
        page.screenshot(path=OUT / "07-exercise.png")

        chapter(PY, 1)
        page.click("#openMap")
        page.wait_for_timeout(3500)
        page.screenshot(path=OUT / "08-architecture-map.png")
        page.click("#mapClose")

        tr_js = next(c for c in course(JS)["chapters"] if c["kind"] == "trace")
        chapter(JS, tr_js["num"], 1500)
        page.screenshot(path=OUT / "09-express-trace.png")

        page.set_viewport_size({"width": 1440, "height": 1120})
        chapter(PY, 1)
        page.click("#openChat")
        page.fill("#chatInput", CHAT_Q)
        page.press("#chatInput", "Enter")
        page.wait_for_selector("#chatLog .ans.fin", timeout=240_000)
        page.wait_for_timeout(600)
        page.evaluate("document.querySelector('#chatLog').scrollTop = 1e6")
        page.wait_for_timeout(300)
        page.screenshot(path=OUT / "10-ask-the-repo.png")
        page.set_viewport_size({"width": 1440, "height": 900})
        print("chat answer:", page.locator("#chatLog .msg.bot .ans").last.inner_text())
        page.click("#chatClose")

        tr_ax = next(c for c in course(AX)["chapters"] if c["kind"] == "trace")
        chapter(AX, tr_ax["num"], 1500)
        page.screenshot(path=OUT / "11-axios-trace.png")

        page.click("#themeBtn")
        chapter(PY, tr["num"], 1200)
        page.screenshot(path=OUT / "12-light-mode.png")
        page.click("#themeBtn")

        m = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
        m.on("pageerror", lambda e: errors.append(str(e)))
        m.goto(f"{BASE}/c/{PY}#ch{tr['num']}")
        m.wait_for_selector("#chToggle")
        m.wait_for_timeout(1200)
        m.screenshot(path=OUT / "13-mobile.png")
        browser.close()
    print("console errors:", errors or "none")
    for f in sorted(OUT.glob("*.png")):
        print(f)


if __name__ == "__main__":
    main()
