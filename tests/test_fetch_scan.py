import os

import pytest

from repocademy.fetch import FetchError, parse_repo_url
from repocademy.scan import read_text, role_of, scan


@pytest.mark.parametrize("text, owner, name", [
    ("https://github.com/psf/requests", "psf", "requests"),
    ("github.com/psf/requests.git", "psf", "requests"),
    ("psf/requests", "psf", "requests"),
    ("https://github.com/pallets/flask/tree/main/src", "pallets", "flask"),
    ("https://github.com/expressjs/express/blob/master/index.js", "expressjs", "express"),
])
def test_parse_repo_url_accepts(text, owner, name):
    ref = parse_repo_url(text)
    assert (ref.owner, ref.name) == (owner, name)
    assert ref.url == f"https://github.com/{owner}/{name}"


@pytest.mark.parametrize("text", [
    "", "https://gitlab.com/a/b", "file:///etc/passwd", "../../etc", "https://github.com/a/..",
    "git@github.com:a/b.git; rm -rf /", "https://github.com/a/b c",
])
def test_parse_repo_url_rejects(text):
    with pytest.raises(FetchError):
        parse_repo_url(text)


def test_slug_is_lowercase_and_safe():
    assert parse_repo_url("Textualize/Rich").slug == "textualize__rich"


@pytest.mark.parametrize("path, role", [
    ("src/pkg/core.py", "source"),
    ("tests/test_core.py", "test"),
    ("lib/foo.test.js", "test"),
    ("test-d/index.test-d.ts", "test"),
    ("examples/demo.py", "example"),
    ("docs/conf.py", "docs"),
])
def test_role_of(path, role):
    assert role_of(path) == role


def test_scan_skips_symlinks_and_vendor(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("def f():\n    return 1\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("function x(){}\n")
    secret = tmp_path.parent / "outside_secret.py"
    secret.write_text("SECRET = 1\n")
    os.symlink(secret, tmp_path / "pkg" / "link.py")
    files, stats = scan(tmp_path)
    paths = {f.path for f in files}
    assert paths == {"pkg/a.py"}
    assert read_text(tmp_path, "pkg/link.py") is None
    assert read_text(tmp_path, "../outside_secret.py") is None
