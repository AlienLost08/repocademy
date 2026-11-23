"""Ground chat answers in the static call graph.

1. `facts_for` turns 'who calls X / what X calls / where X lives' into short lines for the prompt.
2. `check_claims` reads the model's answer, finds call and membership claims about code names
   ("`A` is called by `B`", "`A` calls `B`", "the `f` method of the `C` class") and checks each one against
   the graph. A wrong claim is replaced by what the graph actually says, with a citation to the call site.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

_CACHE: dict[str, "CallGraph"] = {}
_NAME = re.compile(r"`([A-Za-z_$#][\w$#.]*?)(?:\(\))?`")
_PASSIVE = re.compile(r"\b(?:is|are|gets|being|was)?\s*(?:called|invoked|used|triggered|reached|run)\s+(?:from|by|within|inside)\b", re.I)
_ACTIVE = re.compile(r"\b(?:calls|invokes|is calling|hands? (?:it |this |the \w+ )?off to|delegates? to|passes (?:it|this|the \w+(?: \w+)?) (?:on )?to)\b", re.I)
_MEMBER = [
    re.compile(r"`(?P<m>[\w$#]+)(?:\(\))?`\s+(?:method|function)\s+(?:of|in|on|from)\s+(?:the\s+)?(?:`(?P<c>[\w$]+)`(?:\s+class)?|(?P<c2>[A-Z][\w$]*)\s+class)"),
    re.compile(r"`(?P<c>[\w$]+)`\s+class(?:'s|\s+has\s+an?|\s+(?:includes|contains|defines|provides)\s+(?:an?|the)?)\s*`(?P<m>[\w$#]+)(?:\(\))?`(?:\s+method|\s+function)?"),
]
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z`*])")


@dataclass
class CallGraph:
    symbols: dict[str, list]  # id -> [qualname, file, start, end, kind, parent]
    edges: list[list]  # [src, dst, line, weak]
    out: dict = field(default_factory=lambda: defaultdict(list))
    inn: dict = field(default_factory=lambda: defaultdict(list))
    by_qual: dict = field(default_factory=lambda: defaultdict(list))
    by_name: dict = field(default_factory=lambda: defaultdict(list))

    def __post_init__(self):
        for e in self.edges:
            self.out[e[0]].append(e)
            self.inn[e[1]].append(e)
        for sid, (qual, *_rest) in self.symbols.items():
            self.by_qual[qual].append(sid)
            self.by_name[qual.rsplit(".", 1)[-1]].append(sid)

    def q(self, sid: str) -> str:
        return self.symbols[sid][0]

    def where(self, sid: str) -> tuple[str, int]:
        return self.symbols[sid][1], self.symbols[sid][2]

    def resolve(self, name: str, prefer: set[str] | None = None) -> str | None:
        name = name.strip().rstrip("()")
        for cand in (self.by_qual.get(name, []), self.by_name.get(name.rsplit(".", 1)[-1], [])):
            if len(cand) == 1:
                return cand[0]
            if prefer:
                mine = [c for c in cand if c in prefer]
                if len(mine) == 1:
                    return mine[0]
            if cand and name in self.by_qual:
                break  # several symbols share this exact name: don't guess
        return None

    def calls(self, a: str, b: str) -> bool:
        return any(e[1] == b for e in self.out.get(a, []))


def load_graph(course_dir: Path) -> CallGraph | None:
    key = str(course_dir)
    if key not in _CACHE:
        p = course_dir / "calls.json"
        if not p.exists():
            return None
        d = json.loads(p.read_text())
        _CACHE[key] = CallGraph(d["symbols"], d["edges"])
    return _CACHE[key]


def facts_for(g: CallGraph, ids: list[str], limit: int = 4) -> list[str]:
    lines = []
    for sid in ids:
        if sid not in g.symbols:
            continue
        qual, file, start, _end, kind, parent = g.symbols[sid]
        where = f"{kind} defined at [{file}:{start}]" + (f", a method of `{g.q(parent)}`" if parent in g.symbols else "")
        callers = [e for e in g.inn.get(sid, []) if e[0] in g.symbols][:limit]
        callees = [e for e in g.out.get(sid, []) if e[1] in g.symbols][:limit]
        parts = [f"`{qual}`: {where}."]
        if callers:
            parts.append("Called by " + ", ".join(f"`{g.q(e[0])}` [{g.symbols[e[0]][1]}:{e[2]}]" for e in callers) + ".")
        else:
            parts.append("No callers found in the repository.")
        if callees:
            parts.append("Calls " + ", ".join(f"`{g.q(e[1])}`" for e in callees) + ".")
        lines.append(" ".join(parts))
    return lines


def _callers_sentence(g: CallGraph, sid: str) -> tuple[str, list[tuple[str, int]]]:
    es = [e for e in g.inn.get(sid, []) if e[0] in g.symbols][:3]
    if not es:  # maybe called dynamically (callbacks, registries): we can't confirm, so the claim is dropped
        return "", []
    cites = [(g.symbols[e[0]][1], e[2]) for e in es]
    names = ", ".join(f"`{g.q(e[0])}` [{g.symbols[e[0]][1]}:{e[2]}]" for e in es)
    return f"`{g.q(sid)}` is called by {names}.", cites


def _callees_sentence(g: CallGraph, sid: str) -> tuple[str, list[tuple[str, int]]]:
    es = [e for e in g.out.get(sid, []) if e[1] in g.symbols][:4]
    if not es:
        return "", []
    cites = [(g.symbols[sid][1], e[2]) for e in es]
    names = ", ".join(f"`{g.q(e[1])}` [{g.symbols[sid][1]}:{e[2]}]" for e in es)
    return f"`{g.q(sid)}` calls {names}.", cites


def check_claims(text: str, g: CallGraph | None, prefer: set[str]) -> tuple[str, list[dict], list[tuple[str, int]]]:
    """Returns (corrected text, corrections, extra allowed citations (file, line))."""
    if g is None:
        return text, [], []
    out, fixes, allowed = [], [], []
    for para in text.split("\n"):
        sents = _SENT.split(para)
        new = []
        for sent in sents:
            repl = None
            # membership: "the `get_adapter` method of the `Session` class"
            for pat in _MEMBER:
                m = pat.search(sent)
                if not m:
                    continue
                meth, cls = m.group("m"), m.group("c") or m.groupdict().get("c2")
                mid, cid = g.resolve(meth, prefer), g.resolve(cls, prefer)
                if cid and g.symbols[cid][4] == "class":
                    members = {g.q(x).rsplit(".", 1)[-1] for x, v in g.symbols.items() if v[5] == cid}
                    if meth not in members:
                        if mid and g.symbols[mid][5] != cid:
                            owner = g.symbols[mid][5]
                            real = f"a method of `{g.q(owner)}`" if owner in g.symbols else f"a module-level function in `{g.symbols[mid][1]}`"
                            fixed_part = f"`{g.q(mid)}` ({real}) [{g.symbols[mid][1]}:{g.symbols[mid][2]}]"
                            allowed.append((g.symbols[mid][1], g.symbols[mid][2]))
                            fixes.append({"claim": m.group(0), "fix": fixed_part})
                            sent = sent[:m.start()] + fixed_part + sent[m.end():]
                break
            if repl is None:
                names = [(mm.start(), mm.group(1)) for mm in _NAME.finditer(sent)]
                pm, am = _PASSIVE.search(sent), _ACTIVE.search(sent)
                rel = pm or am
                if rel and len(names) >= 2:
                    before = [n for pos, n in names if pos < rel.start()]
                    after = [n for pos, n in names if pos > rel.end()]
                    if before and after:
                        subj = g.resolve(before[-1], prefer)
                        objs = [g.resolve(n, prefer) for n in after[:3]]
                        objs = [o for o in objs if o]
                        if subj and objs:
                            if pm is rel:
                                wrong = [o for o in objs if not g.calls(o, subj)]
                                if len(wrong) == len(objs):
                                    fixed, c = _callers_sentence(g, subj)
                                    repl = fixed
                                    allowed += c
                            else:
                                wrong = [o for o in objs if not g.calls(subj, o)]
                                if len(wrong) == len(objs):
                                    fixed, c = _callees_sentence(g, subj)
                                    repl = fixed
                                    allowed += c
                            if repl is not None:
                                fixes.append({"claim": sent.strip(), "fix": repl or "(removed: the call graph can't confirm it)"})
            if repl is not None:
                if repl:
                    new.append(repl)
            else:
                new.append(sent)
        out.append(" ".join(new))
    return "\n".join(out), fixes, allowed
