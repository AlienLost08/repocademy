from repocademy.builder import build_from_checkout
from repocademy.fetch import RepoRef
from repocademy.facts import check_claims, facts_for, load_graph
from repocademy.retrieval import Index, Chunk, _stem


def _graph(py_repo, tmp_path):
    out = tmp_path / "out"
    build_from_checkout(py_repo, RepoRef("t", "tinyhttp"), "abc", "main", out)
    return load_graph(out), out


def test_facts_list_callers_and_callees(py_repo, tmp_path):
    g, _ = _graph(py_repo, tmp_path)
    sid = g.resolve("Session.send")
    line = facts_for(g, [sid])[0]
    assert "Called by `Session.request` [src/tinyhttp/sessions.py:" in line
    assert "`HTTPAdapter.send`" in line  # self.adapter = HTTPAdapter() -> typed field resolves the method


def test_wrong_caller_claim_is_corrected(py_repo, tmp_path):
    g, _ = _graph(py_repo, tmp_path)
    text = "Merging happens in `merge_setting`, which is called by `Session.send`. Done."
    fixed, fixes, allowed = check_claims(text, g, set())
    assert "`merge_setting` is called by `Session.request` [src/tinyhttp/sessions.py:" in fixed
    assert "called by `Session.send`" not in fixed
    assert len(fixes) == 1 and allowed


def test_true_claims_are_left_alone(py_repo, tmp_path):
    g, _ = _graph(py_repo, tmp_path)
    text = "`Session.request` calls `Session.send` to hand the request on. `get` calls `request`."
    fixed, fixes, _ = check_claims(text, g, set())
    assert fixed == text and fixes == []


def test_wrong_membership_is_corrected(py_repo, tmp_path):
    g, _ = _graph(py_repo, tmp_path)
    text = "Settings are combined by the `merge_setting` method of the `Session` class."
    fixed, fixes, _ = check_claims(text, g, set())
    assert "a module-level function in `src/tinyhttp/utils.py`" in fixed and fixes


def test_unconfirmable_claim_is_dropped(py_repo, tmp_path):
    g, _ = _graph(py_repo, tmp_path)
    text = "The adapter is ready. `handle_error` is called by `get`."
    fixed, fixes, _ = check_claims(text, g, set())
    assert "handle_error" not in fixed or "Session.send" in fixed
    assert fixes


def test_typed_receiver_edges(py_repo, tmp_path):
    g, _ = _graph(py_repo, tmp_path)
    assert g.calls(g.resolve("Session.send"), g.resolve("HTTPAdapter.send"))
    assert g.calls(g.resolve("request"), g.resolve("Session.request"))  # `with sessions.Session() as session`


def _idx():
    mk = lambda i, f, t, txt, s="": Chunk(str(i), f, 1, 10, t, txt, s)
    return Index([
        mk(1, "pkg/cookies.py", "RequestsCookieJar", "class RequestsCookieJar(CookieJar):\n    def set(self, name, value): ..."),
        mk(2, "pkg/sessions.py", "Session.get_adapter", "def get_adapter(self, url):\n    for prefix, adapter in self.adapters.items(): ..."),
        mk(3, "pkg/sessions.py", "Session.request", "def request(self, method, url):\n    return self.send(prep)"),
        mk(4, "tests/test_cookies.py", "test_cookie_jar_stores_cookies", "def test_cookie_jar_stores_cookies():\n    jar = RequestsCookieJar()"),
        mk(5, "pkg/sessions.py", "SessionRedirectMixin.resolve_redirects", "def resolve_redirects(self, resp, req):\n    while url: ..."),
    ])


def test_hybrid_search_file_names_synonyms_and_tests():
    idx = _idx()
    assert idx.search("How are cookies stored between requests?")[0][1].file == "pkg/cookies.py"
    assert idx.search("How does a session decide which adapter to use?")[0][1].title == "Session.get_adapter"
    assert idx.search("where are redirects followed")[0][1].title == "SessionRedirectMixin.resolve_redirects"
    assert idx.search("which test covers the cookie jar?")[0][1].file.startswith("tests/")
    assert _stem("cookies") == _stem("cookie")


def test_wrong_side_claim_outside_focus_is_dropped_not_rewritten(py_repo, tmp_path):
    g, _ = _graph(py_repo, tmp_path)
    text = "The session is created first. Merging happens in `merge_setting`, which is called by `Session.send`."
    fixed, fixes, _ = check_claims(text, g, set(), focus={g.resolve("Session.request")})
    assert fixed.strip() == "The session is created first."
    assert fixes and "removed" in fixes[0]["fix"]
