from repocademy.analyze import analyze_repo
from repocademy.js_analyzer import analyze_js
from repocademy.py_analyzer import analyze_python
from conftest import JS_REPO, PY_REPO


def test_python_symbols_docs_and_calls():
    m = analyze_python("src/tinyhttp/sessions.py", PY_REPO["src/tinyhttp/sessions.py"], "tinyhttp.sessions")
    names = {s.qualname for s in m.symbols}
    assert {"Session", "Session.request", "Session.send", "Base.close"} <= names
    sess = next(s for s in m.symbols if s.qualname == "Session")
    assert sess.bases == ["Base"]
    send = next(s for s in m.symbols if s.qualname == "Session.send")
    calls = {c.name: c for c in send.calls}
    assert calls["self.handle_error"].error_path is True
    assert calls["self.adapter.send"].error_path is False
    assert m.doc.startswith("Sessions keep settings")


def test_js_exports_classes_and_member_functions():
    m = analyze_js("lib/app.js", JS_REPO["lib/app.js"])
    names = {s.qualname for s in m.symbols}
    assert {"createApplication", "app.handle"} <= names
    assert m.default_export == "createApplication"
    r = analyze_js("lib/router.js", JS_REPO["lib/router.js"])
    assert {"Router", "Router.dispatch"} <= {s.qualname for s in r.symbols}
    assert r.default_export == "Router"
    u = analyze_js("lib/utils.js", JS_REPO["lib/utils.js"])
    assert set(u.exports) >= {"normalize", "matches"}
    assert next(s for s in u.symbols if s.name == "normalize").doc.startswith("Lower-case")


def test_python_graph_resolution(py_repo):
    g, _, _ = analyze_repo(py_repo)
    edges = {(e.src.split("::")[1], e.dst.split("::")[1]): e for e in g.calls}
    assert ("get", "request") in edges                      # same-module call
    assert ("request", "Session") in edges                  # alias.module.attr
    assert ("Session.request", "Session.send") in edges     # self.method
    assert ("Session.request", "merge_setting") in edges    # from-import
    assert ("Session.__exit__", "Base.close") in edges      # inherited method
    assert edges[("Session.send", "Session.handle_error")].error_path
    assert ("src/tinyhttp/sessions.py::Session", "src/tinyhttp/sessions.py::Base") in {(a, b) for a, b in g.inherits}
    # the most central symbols rank above leaf helpers
    assert g.rank["src/tinyhttp/sessions.py::Session.request"] > g.rank["src/tinyhttp/utils.py::clamp"]


def test_js_graph_resolution(js_repo):
    g, _, _ = analyze_repo(js_repo)
    edges = {(e.src.split("::")[1], e.dst.split("::")[1]) for e in g.calls}
    assert ("createApplication", "app.handle") in edges     # cross-object member function
    assert ("app.handle", "normalize") in edges             # require()'d module attribute
    assert ("matches", "normalize") in edges
    assert ("createApplication", "Router") in edges         # `new Router()`
