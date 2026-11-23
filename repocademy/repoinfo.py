"""README and manifest facts: description, install/run commands, dependencies, entry points."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

NODE_BUILTINS = {"assert", "buffer", "child_process", "cluster", "crypto", "dgram", "dns", "events", "fs", "http", "http2", "https",
                 "net", "os", "path", "perf_hooks", "process", "querystring", "readline", "stream", "string_decoder", "timers",
                 "tls", "tty", "url", "util", "v8", "vm", "worker_threads", "zlib", "async_hooks", "module"}
STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}


def find_readme(root: Path) -> tuple[str, str]:
    for name in ("README.md", "README.rst", "README.markdown", "README.txt", "README", "readme.md", "Readme.md"):
        p = root / name
        if p.is_file() and not p.is_symlink():
            return name, p.read_text(encoding="utf-8", errors="replace")[:200_000]
    return "", ""


def readme_description(text: str) -> str:
    """First real prose paragraph (skips badges, headings, HTML, rst directives)."""
    paras = re.split(r"\n\s*\n", text)
    for p in paras:
        s = p.strip()
        if not s or s.startswith(("#", "<", "[![", "![", ".. ", "|", "```", "=", "-", ":", "*", ">")):
            if s.startswith(">") and len(s) > 40:
                s = s.lstrip("> ").strip()
            else:
                continue
        if re.fullmatch(r"[=\-~^#*]+", s.splitlines()[-1].strip() or "x") and len(s.splitlines()) <= 2:
            continue
        s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)
        s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
        s = re.sub(r"`([^`]+)`_", r"\1", s)
        s = re.sub(r"\s+", " ", s).strip()
        if len(s) >= 40 and not s.lower().startswith(("copyright", "license", "build status")):
            return s[:600]
    return ""


def readme_code_blocks(text: str) -> list[tuple[str, str, int]]:
    """[(lang, code, line)] from fenced markdown or rst '::' / code-block sections."""
    out = []
    for m in re.finditer(r"```(\w*)[^\n]*\n(.*?)```", text, re.S):
        out.append((m.group(1).lower(), m.group(2).rstrip(), text[: m.start()].count("\n") + 1))
    for m in re.finditer(r"(?:\.\. code-block:: (\w+)|::)\s*\n\n((?:[ \t]+.*\n|\n)+)", text):
        code = "\n".join(ln[4:] if ln.startswith("    ") else ln.strip() for ln in m.group(2).rstrip().splitlines())
        out.append(((m.group(1) or "").lower(), code.strip(), text[: m.start()].count("\n") + 1))
    return out


def commands_from_readme(text: str) -> list[str]:
    cmds = []
    for _lang, code, _ln in readme_code_blocks(text):
        for line in code.splitlines():
            s = line.strip().lstrip("$ ").strip()
            if re.match(r"^(pip|pipx|uv|poetry|python|python3|npm|npx|yarn|pnpm|bun|node|git clone|make|cargo|go )\b", s) and len(s) < 120:
                if s not in cmds:
                    cmds.append(s)
    return cmds[:6]


def usage_example(text: str, lang: str) -> tuple[str, int] | None:
    want = {"python": ("python", "py", "pycon", ""), "javascript": ("js", "javascript", "jsx", "ts", "typescript", ""),
            "typescript": ("ts", "typescript", "js", "javascript", "")}[lang]
    for blang, code, ln in readme_code_blocks(text):
        if blang in want and len(code.splitlines()) >= 2 and not re.match(r"^\s*(\$|pip|npm|yarn|pnpm)", code):
            if lang == "python" and not re.search(r"\bimport\b|>>>", code):
                continue
            if lang != "python" and not re.search(r"\b(require|import|const|let|var)\b", code):
                continue
            return code[:1500], ln
    return None


def manifests(root: Path) -> dict:
    info: dict = {"name": "", "description": "", "dependencies": [], "dev_dependencies": [], "scripts": {}, "entry": [],
                  "main": None, "bin": {}, "test_command": None, "test_framework": None, "license": None}
    pp = root / "pyproject.toml"
    if pp.is_file() and not pp.is_symlink():
        try:
            d = tomllib.loads(pp.read_text(encoding="utf-8", errors="replace"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            d = {}
        proj = d.get("project", {}) or d.get("tool", {}).get("poetry", {})
        info["name"] = proj.get("name", "") or info["name"]
        info["description"] = proj.get("description", "") or info["description"]
        deps = proj.get("dependencies", [])
        if isinstance(deps, dict):
            deps = list(deps)
        info["dependencies"] = [re.split(r"[\s<>=!~;\[]", x)[0] for x in deps if isinstance(x, str) and x.lower() != "python"]
        for name, target in (proj.get("scripts", {}) or {}).items():
            if isinstance(target, str):
                info["entry"].append({"name": name, "target": target})
        if "pytest" in json.dumps(d.get("tool", {})):
            info["test_framework"] = "pytest"
    for fn in ("setup.cfg", "setup.py"):
        p = root / fn
        if p.is_file() and not p.is_symlink():
            t = p.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"['\"]?([\w-]+)\s*=\s*([\w.]+:[\w.]+)['\"]?", t[t.find("console_scripts"):] if "console_scripts" in t else ""):
                info["entry"].append({"name": m.group(1), "target": m.group(2)})
    pj = root / "package.json"
    if pj.is_file() and not pj.is_symlink():
        try:
            d = json.loads(pj.read_text(encoding="utf-8", errors="replace"))
        except ValueError:
            d = {}
        info["name"] = d.get("name", "") or info["name"]
        info["description"] = d.get("description", "") or info["description"]
        info["dependencies"] = list((d.get("dependencies") or {}).keys())
        info["dev_dependencies"] = list((d.get("devDependencies") or {}).keys())
        info["scripts"] = {k: v for k, v in (d.get("scripts") or {}).items() if isinstance(v, str)}
        main = d.get("main") or (d.get("exports") if isinstance(d.get("exports"), str) else None)
        if isinstance(d.get("exports"), dict):
            e = d["exports"].get(".") or d["exports"]
            if isinstance(e, dict):
                main = main or e.get("require") or e.get("import") or e.get("default")
            elif isinstance(e, str):
                main = main or e
        info["main"] = main
        b = d.get("bin")
        info["bin"] = {info["name"] or "cli": b} if isinstance(b, str) else (b or {})
        if "test" in info["scripts"]:
            info["test_command"] = "npm test"
            for fw in ("jest", "mocha", "vitest", "ava", "tap", "jasmine", "node --test"):
                if fw in info["scripts"]["test"]:
                    info["test_framework"] = fw
                    break
        info["license"] = d.get("license") if isinstance(d.get("license"), str) else None
    if info["test_framework"] is None and ((root / "tox.ini").is_file() or (root / "pytest.ini").is_file() or (root / "conftest.py").is_file() or (root / "tests" / "conftest.py").is_file()):
        info["test_framework"] = "pytest"
    if info["test_framework"] == "pytest" and not info["test_command"]:
        info["test_command"] = "python -m pytest"
    lic = next((p for p in ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENSE.rst", "COPYING") if (root / p).is_file()), None)
    if lic and not info["license"]:
        head = (root / lic).read_text(encoding="utf-8", errors="replace")[:400]
        for name in ("MIT", "Apache", "BSD", "GPL", "MPL", "ISC", "Unlicense"):
            if name.lower() in head.lower():
                info["license"] = {"Apache": "Apache-2.0"}.get(name, name)
                break
    return info
