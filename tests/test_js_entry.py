import json
import textwrap

from repocademy.builder import build_from_checkout
from repocademy.fetch import RepoRef
from repocademy.js_exercises import _closure, _pure_literal
from repocademy.repoinfo import js_entries


def _write(root, files):
    for path, text in files.items():
        p = root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))


def test_js_entries_from_package_json():
    d = {"exports": {".": {"import": "./dist/index.mjs", "require": "./dist/index.cjs"}}, "main": "index.js",
         "bin": {"tool": "./bin/cli.js"}}
    assert js_entries(d) == ["dist/index.mjs", "dist/index.cjs", "index.js", "bin/cli.js"]


def test_export_as_default_front_door_and_prototype_trace(tmp_path):
    _write(tmp_path, {
        "package.json": json.dumps({"name": "minix", "exports": "./dist/minix.js"}),
        "lib/minix.js": """
            import Minix from './core/Minix.js';
            function createInstance(config) {
              const context = new Minix(config);
              const instance = Minix.prototype.request.bind(context);
              return instance;
            }
            const minix = createInstance({});
            export { minix as default };
        """,
        "lib/core/Minix.js": """
            import dispatch from './dispatch.js';
            class Minix {
              constructor(config) { this.defaults = config; }
              request(config) {
                const merged = Object.assign({}, this.defaults, config);
                return this._request(merged);
              }
              _request(config) {
                let chain = [];
                chain.push(config);
                return dispatch(config);
              }
            }
            export default Minix;
        """,
        "lib/core/dispatch.js": """
            export default function dispatch(config) {
              const headers = config.headers || {};
              return { status: 200, headers, url: config.url };
            }
        """,
    })
    c = build_from_checkout(tmp_path, RepoRef("o", "minix"), "sha", "main", tmp_path / "out")
    front = next(ch for ch in c["chapters"] if ch["kind"] == "frontdoor")
    names = [s["symbol"] for s in front["sections"]]
    assert names[0] in ("createInstance", "Minix")
    assert "createInstance" in names
    tr = next(ch for ch in c["chapters"] if ch["kind"] == "trace")
    path = [tr["trace"][0]["caller"]] + [s["callee"] for s in tr["trace"]]
    assert path[0] == "createInstance"
    assert "Minix.request" in path and "Minix._request" in path


def test_js_closure_orders_constants_before_use():
    funcs = {"isBuffer": "function isBuffer(v) { return isFunction(v); }"}
    consts = {"typeOfTest": "const typeOfTest = (t) => (x) => typeof x === t;",
              "isFunction": "const isFunction = typeOfTest('function');"}
    parts, _ = _closure("isBuffer", funcs, consts, False)
    joined = "\n".join(parts)
    assert joined.index("const typeOfTest") < joined.index("const isFunction") < joined.index("function isBuffer")


def test_example_args_must_be_pure_literals():
    assert _pure_literal("'a', 1, {k: [true, null]}")
    assert not _pure_literal("{ str: buf.toString() }")
    assert not _pure_literal("someVar")
