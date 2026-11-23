"""Shared fixtures: tiny Python and JavaScript repositories written to a temp dir (no network)."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PY_REPO = {
    "README.md": """# tinyhttp\n\nA tiny HTTP client used to test Repocademy.\n\n```python\nimport tinyhttp\nr = tinyhttp.get("https://example.com")\n```\n""",
    "pyproject.toml": """[project]\nname = "tinyhttp"\ndescription = "A tiny HTTP client"\ndependencies = ["urllib3>=2"]\nlicense = {text = "MIT"}\n""",
    "src/tinyhttp/__init__.py": '''"""tinyhttp: a tiny HTTP client."""
from .api import get, request
from .sessions import Session
''',
    "src/tinyhttp/api.py": '''"""The public helpers people call first."""
from . import sessions


def request(method, url, **kwargs):
    """Send a request with a throwaway session."""
    with sessions.Session() as session:
        return session.request(method=method, url=url, **kwargs)


def get(url, **kwargs):
    """Send a GET request."""
    return request("get", url, **kwargs)
''',
    "src/tinyhttp/sessions.py": '''"""Sessions keep settings between requests."""
from .adapters import HTTPAdapter
from .utils import merge_setting


class Base:
    """Shared plumbing."""

    def close(self):
        return None


class Session(Base):
    """A session object that keeps headers and an adapter."""

    def __init__(self):
        self.headers = {}
        self.adapter = HTTPAdapter()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def request(self, method, url, headers=None):
        """Build the request and send it."""
        merged = merge_setting(headers, self.headers)
        prepared = {"method": method.upper(), "url": url, "headers": merged}
        return self.send(prepared)

    def send(self, prepared):
        """Hand the prepared request to the adapter."""
        try:
            return self.adapter.send(prepared)
        except ValueError:
            return self.handle_error(prepared)

    def handle_error(self, prepared):
        return None
''',
    "src/tinyhttp/adapters.py": '''"""Transport adapters talk to the network."""
import urllib3


class HTTPAdapter:
    """Sends prepared requests."""

    def send(self, request):
        """Pretend to send the request and build a response."""
        if request["method"] == "GET":
            status = 200
        else:
            status = 405
        return {"status": status, "url": request["url"]}
''',
    "src/tinyhttp/utils.py": '''"""Small pure helpers."""
import re

_WS = re.compile(r"\\s+")


def merge_setting(request_setting, session_setting):
    """Merge a per-request setting over the session one."""
    if session_setting is None:
        return request_setting
    if request_setting is None:
        return session_setting
    merged = dict(session_setting)
    merged.update(request_setting)
    return merged


def squash(text):
    """Collapse runs of whitespace.

    >>> squash("a   b")
    'a b'
    """
    if text is None:
        return ""
    return _WS.sub(" ", text).strip()


def clamp(value, low, high):
    """Clamp value into [low, high]."""
    if value < low:
        return low
    if value > high:
        return high
    return value
''',
    "tests/test_utils.py": '''import pytest
from tinyhttp.utils import clamp, merge_setting, squash


@pytest.mark.parametrize("v, expected", [(5, 5), (-1, 0), (99, 10)])
def test_clamp(v, expected):
    assert clamp(v, 0, 10) == expected


def test_merge():
    assert merge_setting({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}
    assert squash("x  y") == "x y"
''',
}

JS_REPO = {
    "README.md": "# minirouter\n\nA tiny router.\n",
    "package.json": '{"name": "minirouter", "description": "A tiny router", "main": "index.js", "license": "MIT", "scripts": {"test": "mocha"}, "dependencies": {"debug": "^4"}}',
    "index.js": "'use strict';\nmodule.exports = require('./lib/app');\n",
    "lib/app.js": textwrap.dedent('''\
        'use strict';
        var Router = require('./router');
        var utils = require('./utils');

        /**
         * Create an application.
         */
        exports = module.exports = createApplication;

        function createApplication() {
          var app = function (req, res) { app.handle(req, res); };
          app.router = new Router();
          return app;
        }

        var app = {};

        /**
         * Dispatch a request into the router.
         */
        app.handle = function handle(req, res) {
          var path = utils.normalize(req.url);
          return this.router.dispatch(path, req, res);
        };
        '''),
    "lib/router.js": textwrap.dedent('''\
        'use strict';
        var utils = require('./utils');

        /** A list of routes. */
        class Router {
          constructor() {
            this.stack = [];
          }

          /** Find the first matching route and call it. */
          dispatch(path, req, res) {
            for (const layer of this.stack) {
              if (utils.matches(layer.path, path)) {
                return layer.fn(req, res);
              }
            }
            return null;
          }
        }

        module.exports = Router;
        '''),
    "lib/utils.js": textwrap.dedent('''\
        'use strict';

        /** Lower-case a path and strip the trailing slash. */
        function normalize(path) {
          if (!path) {
            return '/';
          }
          var p = path.toLowerCase();
          if (p.length > 1 && p.endsWith('/')) {
            p = p.slice(0, -1);
          }
          return p;
        }

        /** True when two paths match. */
        function matches(a, b) {
          return normalize(a) === normalize(b);
        }

        module.exports = { normalize, matches };
        '''),
    "test/utils.test.js": "const { normalize } = require('../lib/utils');\nnormalize('/A/');\n",
}


def write_tree(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


@pytest.fixture()
def py_repo(tmp_path: Path) -> Path:
    return write_tree(tmp_path / "tinyhttp", PY_REPO)


@pytest.fixture()
def js_repo(tmp_path: Path) -> Path:
    return write_tree(tmp_path / "minirouter", JS_REPO)
