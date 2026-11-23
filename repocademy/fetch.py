"""Safe shallow clone of a public GitHub repository.

Only https://github.com/<owner>/<repo> URLs are accepted. Nothing from the repo is ever executed:
we clone with symlinks disabled, no hooks, no LFS smudge and no submodules, then only *read* files.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_URL = re.compile(
    r"^\s*(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?(?:[#?].*)?\s*$"
)
_SHORT = re.compile(r"^\s*([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100})\s*$")
MAX_REPO_MB = 400


class FetchError(Exception):
    pass


@dataclass
class RepoRef:
    owner: str
    name: str

    @property
    def slug(self) -> str:
        return f"{self.owner}__{self.name}".lower()

    @property
    def url(self) -> str:
        return f"https://github.com/{self.owner}/{self.name}"


def parse_repo_url(text: str) -> RepoRef:
    """Accepts 'https://github.com/psf/requests', 'github.com/psf/requests.git', 'psf/requests'.

    Deeper paths like /tree/main/... are rejected on purpose (we teach whole repos).
    """
    t = (text or "").strip()
    t = re.sub(r"/(tree|blob)/.*$", "", t)
    m = _URL.match(t) or _SHORT.match(t)
    if not m:
        raise FetchError("Please paste a public GitHub repository URL, like https://github.com/psf/requests")
    owner, name = m.group(1), m.group(2)
    if name in {".", ".."} or name.startswith("."):
        raise FetchError("That doesn't look like a repository name.")
    return RepoRef(owner, name)


def _git(args: list[str], cwd: Path | None = None, timeout: int = 120) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1", "GIT_ASKPASS": "/bin/true"}
    try:
        out = subprocess.run(["git", "-c", "core.symlinks=false", "-c", "core.hooksPath=/dev/null",
                              "-c", "protocol.file.allow=never", *args],
                             cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise FetchError("Cloning took too long. Is the repository very large?") from e
    if out.returncode != 0:
        msg = out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "git failed"
        if "not found" in msg.lower() or "could not read" in msg.lower() or "authentication" in msg.lower():
            raise FetchError("Repository not found. It must be public on github.com.")
        raise FetchError(msg)
    return out.stdout.strip()


def _size_mb(path: Path) -> float:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total / 1e6


def clone(ref: RepoRef, dest_root: Path, refresh: bool = False) -> tuple[Path, str, str]:
    """Shallow-clone into dest_root/<slug>. Returns (path, commit sha, branch)."""
    dest = dest_root / ref.slug
    if dest.exists() and refresh:
        shutil.rmtree(dest)
    if not (dest / ".git").exists():
        if dest.exists():
            shutil.rmtree(dest)
        dest_root.mkdir(parents=True, exist_ok=True)
        _git(["clone", "--depth", "1", "--single-branch", "--no-tags", "--recurse-submodules=no", ref.url + ".git", str(dest)])
        if _size_mb(dest) > MAX_REPO_MB:
            shutil.rmtree(dest, ignore_errors=True)
            raise FetchError(f"Repository is larger than {MAX_REPO_MB} MB; try a smaller one.")
    sha = _git(["rev-parse", "HEAD"], cwd=dest)
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=dest)
    return dest, sha, branch


def remote_head(ref: RepoRef) -> str | None:
    """Current HEAD sha on GitHub without cloning (used to decide if a cached course is stale)."""
    try:
        out = _git(["ls-remote", ref.url + ".git", "HEAD"], timeout=20)
        return out.split()[0] if out else None
    except FetchError:
        return None
