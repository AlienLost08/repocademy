from repocademy.ask import ask, fallback_answer, validate_citations
from repocademy.builder import build_from_checkout
from repocademy.fetch import RepoRef
from repocademy.narrate import allowed_names, check, trim
from repocademy.retrieval import Chunk, Index, split_ident


def test_split_ident():
    assert split_ident("getHTTPAdapter merge_setting") == ["get", "http", "adapter", "merge", "setting"]


def _course(py_repo, tmp_path):
    out = tmp_path / "out"
    return build_from_checkout(py_repo, RepoRef("t", "tinyhttp"), "abc123", "main", out), out


def test_retrieval_finds_the_right_code(py_repo, tmp_path):
    from repocademy.ask import load_index
    _, out = _course(py_repo, tmp_path)
    idx = load_index(out)
    top = idx.search("how are session headers merged?")[0][1]
    assert top.file == "src/tinyhttp/sessions.py" or top.title == "merge_setting"
    top = idx.search("Where does the adapter send the request")[0][1]
    assert top.file == "src/tinyhttp/adapters.py"
    # test files are down-weighted unless the question asks about tests
    assert idx.search("clamp")[0][1].file == "src/tinyhttp/utils.py"


def test_validate_citations_drops_invented_lines():
    hits = [Chunk(id="1", file="a.py", start=10, end=20, title="f", text="x\n" * 11)]
    text = "It merges here [a.py:12] and also [a.py:99] and [b.py:3]."
    cleaned, cites, removed = validate_citations(text, hits, "https://github.com/o/r", "sha")
    assert "[a.py:12]" in cleaned and "a.py:99" not in cleaned and "b.py" not in cleaned
    assert removed == 2
    assert cites[0]["url"] == "https://github.com/o/r/blob/sha/a.py#L12"


def test_ask_without_llm_returns_grounded_sources(py_repo, tmp_path):
    course, out = _course(py_repo, tmp_path)
    events = list(ask(course, out, "What does Session.send do?", None))
    kinds = [e["type"] for e in events]
    assert kinds[0] == "sources" and kinds[-1] == "final"
    assert any(s["file"] == "src/tinyhttp/sessions.py" for s in events[0]["sources"])
    assert "search result" in events[-1]["text"]


def test_ask_with_fake_llm_keeps_only_valid_citations(py_repo, tmp_path):
    course, out = _course(py_repo, tmp_path)

    class Fake:
        label = "fake"

        def stream(self, msgs, **kw):
            yield "It hands off to the adapter [src/tinyhttp/sessions.py:35] (made up: [src/tinyhttp/nope.py:1])."

        def chat(self, msgs, **kw):
            return "".join(self.stream(msgs))

    final = list(ask(course, out, "What does Session.send do?", Fake()))[-1]
    assert "sessions.py:35" in final["text"] and "nope.py" not in final["text"]
    assert final["removed"] == 1


def test_fallback_answer_empty():
    assert "couldn't find" in fallback_answer([])


def test_narration_check_rejects_invented_names(py_repo, tmp_path):
    course, _ = _course(py_repo, tmp_path)
    ok_names = allowed_names(course)
    good = "The `Session` class keeps headers, and `Session.send` hands the request to `HTTPAdapter`."
    bad = "The `ConnectionPool` class retries requests through `Session.send`."
    assert check(good, ok_names) == (True, [])
    ok, problems = check(bad, ok_names)
    assert not ok and problems == ["ConnectionPool"]
    assert check("As an AI, I think this is great code for you.", ok_names)[0] is False


def test_trim_drops_cut_off_sentence():
    assert trim("One sentence. Two sentence. And a cut") == "One sentence. Two sentence."


def test_polish_removes_filler_openers():
    from repocademy.narrate import polish
    ch = {"title": "Exceptions", "subtitle": "What can go wrong"}
    assert polish("Chapter 6: Exceptions This chapter covers errors. B. C. D.", ch) == "This chapter covers errors. B. C."
    assert polish('In Chapter 2, "The front door: API," we look at the core. B.', ch) == "This chapter covers the core. B."
    assert polish("In Chapter 4, Models, we delve into models. B.", ch) == "This chapter covers models. B."
    assert polish("Welcome to flask, a framework. B.", {"title": "Welcome to flask"}) == "Welcome to flask, a framework. B."


def test_structure_check_rejects_wrong_membership():
    from repocademy.narrate import structure_problems
    course = {"symbols": [{"name": "Session", "file": "s.py"}, {"name": "Session.send", "file": "s.py"},
                          {"name": "merge_setting", "file": "s.py"}, {"name": "Response", "file": "m.py"}]}
    assert structure_problems("The `Session` class provides `send`.", course) == []
    assert structure_problems("The `Session` class includes `merge_setting`.", course)
    assert structure_problems("`m.py` contains `Session`.", course)


def test_polish_strips_hype_keeps_grammar():
    from repocademy.narrate import polish
    assert polish("It is a robust and flexible system. It plays a crucial role in routing.", {}) == \
        "It is a flexible system. It handles routing."
