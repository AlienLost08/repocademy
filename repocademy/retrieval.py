"""Code search for 'Ask the repo': BM25 over function/class-sized chunks, with identifier-aware tokens."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

_STOP = set("""a an the of to in on for and or is are was be by with as at it this that these those from how what where which who
why when does do did can could should would i you we they my your our their me us them there here into about over under
then than so if not no yes use used using uses get gets work works working happen happens file files code function functions
method methods class classes repo repository module modules""".split())


def split_ident(text: str) -> list[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    return [t for t in re.split(r"[^A-Za-z0-9]+", text.lower()) if t]


def _stem(t: str) -> str:
    if len(t) > 4 and t.endswith("ie"):  # cookie / cookies -> cooky
        return t[:-2] + "y"
    for suf in ("ing", "ers", "ies", "ed", "es", "er", "s"):
        if len(t) > len(suf) + 2 and t.endswith(suf):
            return t[: -len(suf)] + ("y" if suf == "ies" else "")
    return t


# Plain-English words people use -> words code uses. Kept small and generic (no repo-specific entries).
SYNONYMS = {
    "decide": ["get", "select", "choose"], "pick": ["get", "select", "choose"], "choose": ["get", "select"],
    "select": ["get", "choose"], "find": ["get", "lookup", "resolve", "search"], "follow": ["resolve", "redirect"],
    "store": ["jar", "save", "set", "persist"], "save": ["store", "persist", "dump"], "persist": ["store", "save"],
    "error": ["exception", "raise", "handle", "fail"], "exception": ["error", "raise"], "fail": ["error", "exception", "retry"],
    "404": ["status", "raise", "http"], "status": ["code"], "cancel": ["abort", "cancel"], "abort": ["cancel"],
    "merge": ["merge", "concat", "combine", "update"], "combine": ["merge", "concat"],
    "add": ["set", "apply", "prepare", "attach", "use"], "attach": ["add", "set", "apply"],
    "register": ["add", "register", "mount", "use"], "mount": ["register", "add"],
    "parse": ["parse", "decode", "load"], "decode": ["parse", "load", "decode"], "serialize": ["stringify", "dump", "encode"],
    "start": ["init", "run", "create"], "create": ["make", "new", "init", "build"], "build": ["make", "create", "prepare"],
    "config": ["setting", "option", "config"], "setting": ["config", "option"], "option": ["config", "setting"],
    "url": ["route", "path", "url"], "route": ["url", "path", "rule"], "view": ["render", "template", "view"],
    "template": ["render", "template", "view"], "login": ["auth"], "password": ["auth", "credential"],
    "retry": ["retry", "backoff"], "timeout": ["timeout"], "header": ["header"], "send": ["send", "dispatch", "request"],
    "run": ["run", "call", "execute", "dispatch"], "transform": ["transform", "convert", "map"],
    "interceptor": ["interceptor", "handler"], "handle": ["handle", "dispatch", "process"],
}


def _syn(term: str) -> list[str]:
    return [_stem(x) for x in SYNONYMS.get(term, [])]


def tokens(text: str) -> list[str]:
    return [_stem(t) for t in split_ident(text) if t not in _STOP and len(t) > 1]


@dataclass
class Chunk:
    id: str
    file: str
    start: int
    end: int
    title: str  # symbol qualname or "module"/"README"
    text: str  # code
    summary: str = ""


class Index:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.tf: list[Counter] = []
        df: Counter = Counter()
        for c in chunks:
            tf = Counter(tokens(c.text))
            for t in tokens(c.title + " " + c.file.replace("/", " ")) * 3:
                tf[t] += 1
            for t in tokens(c.summary) * 2:
                tf[t] += 1
            self.tf.append(tf)
            df.update(tf.keys())
        self.title_toks = [{_stem(t) for t in split_ident(c.title.replace("module ", "")) if len(t) > 1 and t not in ("init", "call")}
                           if c.title != "README" else set() for c in chunks]
        self.file_toks = [{_stem(t) for t in split_ident(c.file.rsplit("/", 1)[-1].rsplit(".", 1)[0]) if len(t) > 2 and t not in ("index", "init", "main", "utils", "util")}
                          for c in chunks]
        self.n = len(chunks)
        self.avg = sum(sum(t.values()) for t in self.tf) / max(1, self.n)
        self.idf = {t: math.log(1 + (self.n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def search(self, query: str, k: int = 6) -> list[tuple[float, Chunk]]:
        """Hybrid ranking: BM25 over code + docs, plus identifier, symbol-name and file-name matching, plus a few
        plain-English -> code synonyms (at half weight). Test code is down-weighted unless the question is about tests."""
        q = tokens(query)
        raw = [_stem(t) for t in split_ident(query) if len(t) > 1]  # stop words kept: "get" matters in names
        expanded = [t for t in {x for w in q for x in _syn(w)} if t not in q]
        qset = set(q) | set(raw)
        qall = qset | set(expanded)
        idents = set(re.findall(r"[A-Za-z_][\w.]*[A-Za-z0-9_]", query))
        idents |= {x.split(".", 1)[1] for x in list(idents) if "." in x}  # requests.get -> get, a.B.c -> B.c
        want_tests = bool(re.search(r"(?i)\btest", query))
        scores = []
        for i, tf in enumerate(self.tf):
            dl = sum(tf.values())
            s = 0.0
            norm = 1.2 * (0.25 + 0.75 * dl / self.avg)
            for t in q:
                f = tf.get(t, 0)
                if f:
                    s += self.idf.get(t, 0) * f * 2.2 / (f + norm)
            for t in expanded:
                f = tf.get(t, 0)
                if f:
                    s += 0.5 * self.idf.get(t, 0) * f * 2.2 / (f + norm)
            c = self.chunks[i]
            # symbol-name match: how much of the chunk's own name is in the question (definition beats mention)
            title_toks = self.title_toks[i]
            if title_toks:
                matched = [t for t in title_toks if t in qall]
                if matched:
                    w = sum(self.idf.get(t, 1.0) * (1.0 if t in qset else 0.6) for t in matched)
                    s += 2.0 * len(matched) / len(title_toks) + 0.45 * w
            # file-name match: "cookies" -> cookies.py
            if self.file_toks[i] & qall:
                s += 1.5
            if c.title in idents or c.title.rsplit(".", 1)[-1] in idents and len(c.title.rsplit(".", 1)[-1]) > 3:
                s += 6
            if any(c.file.endswith(x) for x in idents if "/" in x or x.endswith((".py", ".js", ".ts"))):
                s += 4
            if s > 0:
                low = c.file.lower()
                if ("test" in low or "/spec" in low) and not want_tests:
                    s *= 0.4
                if c.title == "README":
                    s *= 0.7
                scores.append((s, c))
        scores.sort(key=lambda x: -x[0])
        # at most 2 chunks per file so answers cite a spread of code
        out, per_file = [], Counter()
        for s, c in scores:
            if per_file[c.file] >= 2:
                continue
            per_file[c.file] += 1
            out.append((s, c))
            if len(out) >= k:
                break
        return out
