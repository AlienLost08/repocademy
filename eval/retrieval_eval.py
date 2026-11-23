"""Retrieval benchmark: does the right code show up in the top 3 for natural questions?

Each case lists acceptable answers: a chunk title (symbol) or a file path suffix. Hand-written by reading the
source of each repository. Run after building the courses:  python eval/retrieval_eval.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from repocademy.ask import load_index  # noqa: E402

CASES = {
    "psf__requests": [
        ("How are cookies stored between requests?", ["cookies.py"]),
        ("How does a Session decide which adapter sends a request?", ["Session.get_adapter"]),
        ("Where are redirects followed?", ["SessionRedirectMixin.resolve_redirects"]),
        ("How is basic auth added to a request?", ["HTTPBasicAuth", "HTTPBasicAuth.__call__", "_basic_auth_str"]),
        ("What happens when I call requests.get?", ["get", "request"]),
        ("How does requests retry failed connections?", ["HTTPAdapter.__init__", "HTTPAdapter"]),
        ("Where is the response body decoded as JSON?", ["Response.json"]),
        ("How are proxies picked from environment variables?", ["get_environ_proxies", "resolve_proxies", "should_bypass_proxies", "SessionRedirectMixin.rebuild_proxies"]),
        ("How do I set a timeout on a request?", ["HTTPAdapter.send", "adapters.py", "Session.request", "TimeoutSauce"]),
        ("Which exception is raised for a 404 response?", ["Response.raise_for_status", "HTTPError"]),
    ],
    "pallets__flask": [
        ("How does Flask match a URL to a view function?", ["Flask.dispatch_request", "AppContext.match_request", "App.add_url_rule", "Scaffold.add_url_rule", "Flask.add_url_rule"]),
        ("Where are blueprints registered?", ["App.register_blueprint", "Blueprint.register", "Flask.register_blueprint"]),
        ("How are sessions stored in cookies?", ["SecureCookieSessionInterface", "SecureCookieSessionInterface.save_session", "SecureCookieSessionInterface.open_session", "SecureCookieSession"]),
        ("How does the request context get pushed?", ["AppContext.push", "RequestContext.push", "Flask.request_context"]),
        ("How are errors turned into responses?", ["Flask.handle_user_exception", "Flask.handle_exception", "Flask.handle_http_exception"]),
        ("How does render_template find templates?", ["render_template", "DispatchingJinjaLoader", "DispatchingJinjaLoader.get_source", "templating.py"]),
    ],
    "expressjs__express": [
        ("How does res.send set the content type?", ["res.send"]),
        ("How are routes registered with app.get?", ["app.route", "app.use", "application.js"]),
        ("How does express parse the query string?", ["compileQueryParser", "parseExtendedQueryString", "req.query"]),
        ("How does res.json serialize objects?", ["res.json", "stringify"]),
        ("How is the view engine chosen when rendering?", ["app.render", "View", "View.lookup", "view.js"]),
    ],
    "axios__axios": [
        ("How are interceptors run before a request?", ["Axios._request", "InterceptorManager", "InterceptorManager.use"]),
        ("How does axios pick the adapter, xhr or http?", ["getAdapter", "adapters.js"]),
        ("How is a request cancelled?", ["CancelToken", "CancelToken.constructor", "CanceledError", "isCancel", "throwIfCancellationRequested"]),
        ("How are default headers merged?", ["mergeConfig", "AxiosHeaders.concat", "Axios._request", "flattenHeaders"]),
        ("How does axios transform the response data to JSON?", ["transformData", "transformResponse", "defaults/index.js"]),
    ],
}


def ok(chunk, answers):
    return any(chunk.title == a or chunk.file.endswith(a) for a in answers)


def main(root: str = "/tmp/diag"):
    h1 = h3 = n = 0
    misses = []
    for slug, cases in CASES.items():
        idx = load_index(Path(root) / slug)
        for q, ans in cases:
            hits = [c for _, c in idx.search(q, k=6)]
            n += 1
            if hits and ok(hits[0], ans):
                h1 += 1
            if any(ok(c, ans) for c in hits[:3]):
                h3 += 1
            else:
                misses.append((slug, q, [c.title for c in hits[:3]]))
    print(f"hit@1 {h1}/{n}   hit@3 {h3}/{n}")
    for m in misses:
        print("  miss:", m)


if __name__ == "__main__":
    main(*sys.argv[1:])
