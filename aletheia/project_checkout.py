"""A small, exact, throwaway copy of the part of a project the local tier works on.

His projects are not small repositories: Money_Machine is ~640 MB (renders,
concept art) and Shorts-pipeline ~1 GB, and the laptop the local tier runs on
has 16 GB and another worker driving a browser. `local_repair.run_charter`
clones the whole repository, which is fine for a small one and impossible for
these. So this module:

1. resolves the branch to its EXACT commit with `git ls-remote` (anonymous, no
   API rate limit),
2. reads the file list with sizes from GitHub's tree API (anonymous for a public
   repository; the token only when there is one and this is not a rehearsal),
3. checks out, blobless and sparse, only the project's folder (a charter's
   `path`) and never a media file or anything over `MAX_BLOB_KB`,
4. and copies that into a MIRROR repository with one commit, so the repair
   tier's worktrees, branches and commits happen in a directory nobody else
   owns. The mirror records the real commit it mirrors (`base_sha`): a pull
   request is published against THAT commit, never the mirror's own.

READS ONLY. Nothing here pushes, fetches into, or configures any repository of
his; every directory it makes lives under the throwaway root that
`investigation` guards (never Aletheia's live checkout). His credentials never
reach git: the clone is anonymous and the environment is scrubbed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath

from aletheia import investigation as inv

ACTOR = "aletheia-work"
MAX_BLOB_KB = 512
MAX_CHECKOUT_MB = 60
GIT_TIMEOUT_S = 300
API = "https://api.github.com"
MEDIA = (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".wav", ".mp3", ".flac", ".aac", ".m4a", ".ogg",
         ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".psd", ".exr", ".heic",
         ".zip", ".tar", ".gz", ".7z", ".rar", ".pdf", ".bin", ".onnx", ".pt", ".pth", ".safetensors",
         ".ckpt", ".glb", ".gltf", ".fbx", ".blend", ".usdz", ".ttf", ".otf", ".woff", ".woff2", ".ico",
         ".mp4.part", ".npy", ".npz", ".parquet", ".sqlite", ".db")
_SAFE_REPO = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+")
_SAFE_BRANCH = re.compile(r"(?!-)[A-Za-z0-9._/-]{1,200}")


class CheckoutRefused(RuntimeError):
    """Said in a sentence: why this project is not checked out locally."""


def _env() -> dict:
    env = {k: v for k, v in os.environ.items() if not inv._SECRET_ENV.search(k)}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    return env


def _git(args: list[str], cwd: Path | None = None, *, timeout: int = GIT_TIMEOUT_S,
         identity: tuple[str, str] | None = None) -> tuple[int, str]:
    from aletheia import proc
    env = _env()
    if identity:
        env.update(GIT_AUTHOR_NAME=identity[0], GIT_COMMITTER_NAME=identity[0],
                   GIT_AUTHOR_EMAIL=identity[1], GIT_COMMITTER_EMAIL=identity[1])
    done = subprocess.run(["git", "--no-pager", *args], cwd=str(cwd) if cwd else None, capture_output=True,
                          timeout=timeout, env=env, creationflags=proc.hidden_flags())
    return done.returncode, (done.stdout + done.stderr).decode("utf-8", "replace")


def api_get(path: str):
    """One GitHub READ. The token only outside a rehearsal and only when stored;
    otherwise anonymous (public repositories). None when it cannot be read."""
    try:
        from aletheia import gh, intercom
        if not intercom.rehearsing() and gh.token():
            return gh.request("GET", path)
    except Exception:  # noqa: BLE001 - fall through to an anonymous read
        pass
    req = urllib.request.Request(API + path, headers={"Accept": "application/vnd.github+json",
                                                      "User-Agent": "aletheia-local-work"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def raw_file(full_name: str, ref: str, path: str, *, limit: int = 200_000) -> str | None:
    """A public file's text at an exact ref (no API budget spent). None if unreadable."""
    if not _SAFE_REPO.fullmatch(str(full_name or "")):
        return None
    url = f"https://raw.githubusercontent.com/{full_name}/{urllib.request.quote(ref, safe='')}/" \
          f"{urllib.request.quote(path)}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "aletheia-local-work"}),
                                    timeout=30) as response:
            data = response.read(limit + 1)
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    return data[:limit].decode("utf-8", "replace")


def resolve_branch(full_name: str, branch: str) -> str:
    if not _SAFE_REPO.fullmatch(str(full_name or "")):
        raise CheckoutRefused("a repository is owner/name")
    if not _SAFE_BRANCH.fullmatch(str(branch or "")):
        raise CheckoutRefused("that branch name is not safe to use")
    code, out = _git(["ls-remote", f"https://github.com/{full_name}.git", f"refs/heads/{branch}"], timeout=60)
    sha = out.split()[0] if code == 0 and out.strip() else ""
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise CheckoutRefused(f"{full_name} has no branch {branch} that can be read anonymously")
    return sha


def tree(full_name: str, sha: str) -> dict:
    """{"files": [{"path", "size"}], "truncated": bool} for an exact commit."""
    data = api_get(f"/repos/{full_name}/git/trees/{sha}?recursive=1")
    if not isinstance(data, dict) or not isinstance(data.get("tree"), list):
        raise CheckoutRefused(f"the file list of {full_name} could not be read")
    files = [{"path": str(t.get("path")), "size": int(t.get("size") or 0)} for t in data["tree"]
             if isinstance(t, dict) and t.get("type") == "blob"]
    return {"files": files, "truncated": bool(data.get("truncated"))}


def _under(path: str, subdir: str) -> bool:
    sub = str(subdir or "").strip("/")
    return not sub or path == sub or path.startswith(sub + "/")


def plan(files: list[dict], subdir: str = "") -> dict:
    """What would be checked out, and what not. Pure."""
    keep, skipped = [], []
    for f in files:
        if not _under(f["path"], subdir):
            continue
        low = f["path"].lower()
        if low.endswith(MEDIA) or f["size"] > MAX_BLOB_KB * 1024:
            skipped.append(f)
        else:
            keep.append(f)
    total = sum(f["size"] for f in keep)
    python_tests = [f["path"] for f in keep if f["path"].endswith(".py")
                    and (PurePosixPath(f["path"]).name.startswith("test_") or "/tests/" in "/" + f["path"])]
    node = [f["path"] for f in keep if PurePosixPath(f["path"]).name == "package.json"]
    return {"keep": [f["path"] for f in keep], "skipped": len(skipped), "bytes": total,
            "python_tests": python_tests[:50], "package_json": node[:5],
            "fits": total <= MAX_CHECKOUT_MB * 1024 * 1024 and bool(keep)}


def checkout(full_name: str, branch: str, *, subdir: str = "", root: Path | None = None) -> dict:
    """A mirror repository of the project folder at the branch's exact commit.

    Returns {"path", "subdir", "base_sha", "branch", "repo", "files", "python_tests",
    "package_json", "skipped", "seconds"}. Raises CheckoutRefused with the reason."""
    started = time.monotonic()
    sha = resolve_branch(full_name, branch)
    listing = tree(full_name, sha)
    chosen = plan(listing["files"], subdir)
    if not chosen["keep"]:
        raise CheckoutRefused(f"{full_name}@{branch} has nothing under {subdir or 'its root'} to work on")
    if not chosen["fits"]:
        raise CheckoutRefused(f"the part of {full_name} to work on is {chosen['bytes'] // (1024 * 1024)} MB, "
                              f"more than the {MAX_CHECKOUT_MB} MB the local tier checks out")
    base = Path(root) if root else inv.worktrees_root()
    base.mkdir(parents=True, exist_ok=True)
    scratch = inv._guard_worktree(Path(tempfile.mkdtemp(prefix="project-", dir=str(base))))
    clone = scratch / "clone"
    mirror = scratch / "mirror"
    code, said = _git(["clone", "--quiet", "--depth", "1", "--filter=blob:none", "--no-checkout",
                       "--branch", branch, "--", f"https://github.com/{full_name}.git", str(clone)])
    if code != 0:
        shutil.rmtree(scratch, ignore_errors=True)
        raise CheckoutRefused(f"could not read {full_name}@{branch}: {inv.clean(said, 200)}")
    patterns = ["/" + p for p in chosen["keep"]]
    listfile = scratch / "sparse.txt"
    listfile.write_text("\n".join(patterns) + "\n", encoding="utf-8")
    steps = (["sparse-checkout", "init", "--no-cone"], ["sparse-checkout", "set", "--no-cone", "--stdin"],
             ["checkout", "--quiet", sha])
    for args in steps:
        if "--stdin" in args:
            from aletheia import proc
            done = subprocess.run(["git", "--no-pager", *args], cwd=str(clone), input=listfile.read_bytes(),
                                  capture_output=True, timeout=GIT_TIMEOUT_S, env=_env(),
                                  creationflags=proc.hidden_flags())
            code, said = done.returncode, (done.stdout + done.stderr).decode("utf-8", "replace")
        else:
            code, said = _git(args, clone)
        if code != 0:
            shutil.rmtree(scratch, ignore_errors=True)
            raise CheckoutRefused(f"could not check out {full_name}@{branch}: {inv.clean(said, 200)}")
    shutil.copytree(clone, mirror, ignore=shutil.ignore_patterns(".git"))
    shutil.rmtree(clone, ignore_errors=True)
    for args in (["init", "--quiet", "-b", "mirror"], ["add", "--all"],
                 ["commit", "--quiet", "-m", f"mirror of {full_name}@{sha[:12]} ({subdir or 'root'})"]):
        code, said = _git(args, mirror, identity=("Thea (local work)", "thea@localhost"))
        if code != 0:
            shutil.rmtree(scratch, ignore_errors=True)
            raise CheckoutRefused(f"could not make the local mirror: {inv.clean(said, 200)}")
    return {"path": str(mirror), "scratch": str(scratch), "subdir": str(subdir or "").strip("/"),
            "base_sha": sha, "branch": branch, "repo": full_name, "files": len(chosen["keep"]),
            "python_tests": chosen["python_tests"], "package_json": chosen["package_json"],
            "skipped": chosen["skipped"], "seconds": round(time.monotonic() - started, 1)}


def clone_local(source: Path, *, root: Path | None = None) -> dict:
    """A throwaway clone of a LOCAL checkout's committed HEAD (Aletheia's own code,
    for verifying a capability): no network, nothing of the source is moved."""
    started = time.monotonic()
    base = Path(root) if root else inv.worktrees_root()
    base.mkdir(parents=True, exist_ok=True)
    scratch = inv._guard_worktree(Path(tempfile.mkdtemp(prefix="self-", dir=str(base))))
    target = scratch / "repo"
    code, said = _git(["clone", "--quiet", "--no-hardlinks", "--depth", "1", Path(source).resolve().as_uri(),
                       str(target)])
    if code != 0:
        shutil.rmtree(scratch, ignore_errors=True)
        raise CheckoutRefused(f"could not clone her own code: {inv.clean(said, 200)}")
    code, head = _git(["rev-parse", "HEAD"], target)
    return {"path": str(target), "scratch": str(scratch), "base_sha": head.strip().splitlines()[-1] if code == 0 else "",
            "seconds": round(time.monotonic() - started, 1)}


def discard(view: dict | None) -> None:
    if view and view.get("scratch"):
        shutil.rmtree(view["scratch"], ignore_errors=True)
