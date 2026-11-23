import ast
import random
import textwrap

from repocademy.analyze import analyze_repo
from repocademy.exercises import python_exercises
from repocademy.js_exercises import js_exercises, strip_types
from repocademy.model import Symbol
from repocademy.quiz import mutate_symbol, string_lines

FN = '''def pick(items, limit):
    """Pick items.

    if limit > 0 and items == []: this docstring line must never be mutated
    """
    out = []
    for x in items:
        if x > limit and x != 0:
            out.append(x)
    if len(out) == 0:
        return None
    return out
'''


def test_string_lines_cover_docstrings():
    lines = FN.splitlines()
    s = string_lines(lines, True)
    assert {2, 3, 4, 5} <= s
    assert 8 not in s


def test_mutations_are_parseable_and_never_in_docstrings():
    lines = FN.splitlines()
    sym = Symbol(id="m.py::pick", name="pick", qualname="pick", kind="function", file="m.py", start=1, end=len(lines))
    seen = set()
    for seed in range(40):
        q = mutate_symbol(lines, sym, random.Random(seed))
        assert q is not None
        n = int(q["options"][q["answer"]].split()[1])
        assert n not in {2, 3, 4, 5}
        seen.add(n)
        code = "\n".join(t for _, t in q["code"])
        ast.parse(textwrap.dedent(code))
        assert q["mutated"] != q["original"]
        assert len(q["options"]) == 4
    assert seen <= {7, 8, 10}


def test_python_exercises_use_real_test_calls(py_repo):
    g, _, files = analyze_repo(py_repo)
    files_text = {f.path: f.text for f in files}
    ex = python_exercises(g, files_text)
    by = {e["symbol"].split("::")[1]: e for e in ex}
    assert "clamp" in by and "merge_setting" in by
    calls = [c["call"] for c in by["clamp"]["calls"]]
    assert "clamp(-1, 0, 10)" in calls  # expanded from pytest.mark.parametrize
    if "squash" in by:  # module-level constants travel with the function so it runs standalone
        assert "_WS = re.compile" in by["squash"]["code"]
    assert all(e["type"] == "python_run" for e in ex)


def test_js_exercises(js_repo):
    g, _, files = analyze_repo(js_repo)
    ex = js_exercises(g, {f.path: f.text for f in files})
    assert any(e["symbol"].endswith("::normalize") for e in ex)


def test_bug_options_are_never_comment_lines():
    src = '''def f(x):
    # if x == 1 this is a comment
    if x == 1:
        return 2
    # another comment
    y = x + 1
    return y
'''.splitlines()
    sym = Symbol(id="m.py::f", name="f", qualname="f", kind="function", file="m2.py", start=1, end=len(src))
    for seed in range(20):
        q = mutate_symbol(src, sym, random.Random(seed))
        if q:
            assert all(int(o.split()[1]) not in (2, 5) for o in q["options"])


def test_strip_types_turns_typescript_into_javascript():
    ts = "export const clamp = <T extends number>(v: T, lo: number, hi?: number): number => (v < lo ? lo : (v as number)) ;\ninterface X { a: string }\n"
    js = strip_types(ts)
    assert js is not None
    assert ":" not in js.split("?")[0] and "interface" not in js and "as number" not in js and "export" not in js
    assert "(v, lo, hi)" in js


def test_ts_exercise_from_tests(tmp_path):
    from conftest import write_tree
    root = write_tree(tmp_path / "tsrepo", {
        "package.json": '{"name": "tsrepo", "exports": "./dist/index.js"}',
        "src/index.ts": "const UNITS: string[] = ['B', 'KB'];\n\nexport function pretty(n: number): string {\n  if (n < 1024) {\n    return `${n} ${UNITS[0]}`;\n  }\n  return `${Math.round(n / 1024)} ${UNITS[1]}`;\n}\n",
        "test/index.test.ts": "import {pretty} from '../src/index';\nexpect(pretty(2048)).toBe('2 KB');\n",
    })
    g, _, files = analyze_repo(root)
    ex = js_exercises(g, {f.path: f.text for f in files})
    assert len(ex) == 1 and ex[0]["calls"][0]["call"] == "pretty(2048)"
    assert "UNITS = ['B', 'KB']" in ex[0]["code"] and ": number" not in ex[0]["code"]
