"""Plain data structures shared by the analysers, the planner and the course builder."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CallSite:
    name: str  # raw callee text, e.g. "self.send", "sessions.Session", "merge_setting"
    line: int
    error_path: bool = False  # inside an except/catch block


@dataclass
class Symbol:
    id: str  # "<file>::<qualname>"
    name: str
    qualname: str
    kind: str  # function | method | class
    file: str
    start: int
    end: int
    signature: str = ""
    doc: str = ""
    bases: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    calls: list[CallSite] = field(default_factory=list)
    parent: str | None = None  # class symbol id for methods
    exported: bool = False
    # local variable -> constructor/class name it was built from (`x = Foo()`, `const x = new Foo()`);
    # on classes, keys like "self.adapter" / "this.router" record field types set in methods
    types: dict[str, str] = field(default_factory=dict)

    @property
    def loc(self) -> int:
        return self.end - self.start + 1

    @property
    def public(self) -> bool:
        return not self.name.startswith("_") or (self.name.startswith("__") and self.name.endswith("__") and self.name == "__init__")


@dataclass
class Import:
    module: str  # raw module text: "requests.sessions", "./router", ".utils"
    names: list[tuple[str, str]] = field(default_factory=list)  # (imported name, local alias); ("*", "*") for star
    alias: str | None = None  # "import x as y" / "const y = require('x')"
    line: int = 0
    level: int = 0  # python relative-import level
    resolved: str | None = None  # internal file path when the import points inside the repo


@dataclass
class Module:
    path: str  # repo-relative posix path
    lang: str  # python | javascript | typescript
    lines: int
    doc: str = ""
    dotted: str = ""  # python dotted module name
    imports: list[Import] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)  # names a module exposes (__all__, module.exports.x)
    default_export: str | None = None  # JS: module.exports = <name>
    is_main: bool = False  # has `if __name__ == "__main__"` or a shebang
    todos: list[tuple[int, str]] = field(default_factory=list)
    role: str = "source"  # source | test | example | docs | config
    values: dict[str, str] = field(default_factory=dict)  # top-level `const x = make(...)` -> "make"
