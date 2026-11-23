import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch, py_repo):
    monkeypatch.setenv("REPOCADEMY_LLM", "off")
    import app.server as server
    from repocademy.builder import build_from_checkout
    from repocademy.fetch import RepoRef

    monkeypatch.setattr(server, "DATA", tmp_path / "data")
    monkeypatch.setattr(server, "SHOWCASE", tmp_path / "showcase")
    build_from_checkout(py_repo, RepoRef("t", "tinyhttp"), "abc123", "main", tmp_path / "data" / "courses" / "t__tinyhttp")
    return TestClient(server.app)


def test_health_and_index(client):
    assert client.get("/api/health").json()["ok"] is True
    r = client.get("/")
    assert r.status_code == 200 and "Repocademy" in r.text
    assert client.get("/c/t__tinyhttp").status_code == 200


def test_courses_listing_and_fetch(client):
    lst = client.get("/api/courses").json()
    assert [c["slug"] for c in lst] == ["t__tinyhttp"]
    assert lst[0]["questions"] > 5
    c = client.get("/api/courses/t__tinyhttp").json()
    assert c["chapters"][0]["kind"] == "overview"
    assert client.get("/api/courses/..%2Fetc").status_code == 404
    assert client.get("/api/courses/nope").status_code == 404


def test_build_validation_and_cache(client):
    assert client.post("/api/build", json={"url": "https://gitlab.com/a/b"}).status_code == 400
    r = client.post("/api/build", json={"url": "https://github.com/t/tinyhttp"}).json()
    assert r == {"job": None, "slug": "t__tinyhttp", "cached": True}


def test_ask_streams_sse(client):
    with client.stream("POST", "/api/courses/t__tinyhttp/ask", json={"question": "where is merge_setting?"}) as r:
        body = "".join(r.iter_text())
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    assert events[0]["type"] == "sources" and events[-1]["type"] == "final"
    assert client.post("/api/courses/t__tinyhttp/narrate").status_code == 409  # no model configured
