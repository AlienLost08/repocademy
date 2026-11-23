import json
import re

from repocademy.builder import build_from_checkout
from repocademy.fetch import RepoRef

URL = re.compile(r"^https://github\.com/t/[\w-]+/blob/abc123/[\w./-]+#L\d+(-L\d+)?$")


def _build(root, tmp_path, name):
    out = tmp_path / "out"
    c = build_from_checkout(root, RepoRef("t", name), "abc123", "main", out)
    assert (out / "course.json").exists() and (out / "index.json").exists()
    assert json.loads((out / "course.json").read_text())["slug"] == f"t__{name}"
    return c


def _check_course(c):
    kinds = [ch["kind"] for ch in c["chapters"]]
    assert kinds[0] == "overview" and kinds[-1] == "next" and "trace" in kinds and "tests" in kinds
    assert [ch["num"] for ch in c["chapters"]] == list(range(1, len(kinds) + 1))
    for ch in c["chapters"]:
        assert ch["minutes"] >= 2
        for s in ch.get("sections", []):
            assert URL.match(s["github"]), s["github"]
            rows = s["code"]["rows"] if isinstance(s["code"], dict) else s["code"]
            nums = [r[0] for r in rows if r[0] is not None]
            assert nums == sorted(nums)
        for q in ch["quiz"]:
            assert q["type"] in {"mcq", "bug", "order", "line"}
            if q["type"] == "line":
                assert isinstance(q["answer"], int) and q["answer"] > 0
            elif q["type"] in {"mcq", "bug"}:
                assert 0 <= q["answer"] < len(q["options"])
                assert len(set(q["options"])) == len(q["options"])
            assert q["explain"]
    nodes = {n["id"] for n in c["graph"]["nodes"]}
    assert all(e["source"] in nodes and e["target"] in nodes for e in c["graph"]["edges"])


def test_python_course(py_repo, tmp_path):
    c = _build(py_repo, tmp_path, "tinyhttp")
    _check_course(c)
    assert c["main_lang"] == "python"
    ex = [e for ch in c["chapters"] for e in ch.get("exercises", []) if e["type"] == "python_run"]
    assert ex and all(URL.match(e["github"]) for e in ex)
    trace = next(ch for ch in c["chapters"] if ch["kind"] == "trace")
    hops = [(s["caller"], s["callee"]) for s in trace["trace"]]
    assert hops[:3] == [("get", "request"), ("request", "Session.request"), ("Session.request", "Session.send")]
    assert ("Session.send", "Session.handle_error") not in hops  # error handling is not the story
    front = next(ch for ch in c["chapters"] if ch["kind"] == "frontdoor")
    assert {s["symbol"] for s in front["sections"]} >= {"get", "Session"}
    over = c["chapters"][0]
    assert any(d["name"] == "urllib3" for d in over["dependencies"])


def test_js_course(js_repo, tmp_path):
    c = _build(js_repo, tmp_path, "minirouter")
    _check_course(c)
    assert c["main_lang"] == "javascript"
    trace = next(ch for ch in c["chapters"] if ch["kind"] == "trace")
    assert trace["trace"][0]["caller"] == "createApplication"
