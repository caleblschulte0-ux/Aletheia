"""Git sync — how the Core keeps the repo, its shared memory, fresh.

The working copy is Aletheia's durable memory (§108): commands arrive as
commits, receipts leave as commits, and ChatGPT/the wall read whatever is
pushed. Until now "sync with GitHub stays git's job (the operator
pulls/pushes)" — which in practice meant a voice command could sit in
`exchange/commands/` forever because nobody ran `git pull` on the PC.
This module makes sync the Core's job.

Design rules:

- **Plain git, the operator's own credentials.** No tokens of ours, no
  API. If `git push` cannot authenticate, that is an honest DEGRADED
  state to journal and report, never something to work around.
- **Never raise out of the loop.** Every operation returns
  ``(ok, detail)``; a failure is journaled by the caller and retried on
  the next tick. A sync problem must not take down the Core's API.
- **Rebase, bounded.** Receipts and journal entries are append-only new
  files, so a rebase onto the remote is conflict-free in the normal
  case. A conflict aborts the rebase cleanly and reports it — the tree
  is never left mid-rebase.
- **Push only named paths.** ``commit_push`` stages exactly what the
  caller says (receipts, journal); a stray local edit on the PC never
  rides along in an automated commit.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from aletheia.fleet import REPO_ROOT

GIT_TIMEOUT_S = 60
PUSH_ATTEMPTS = 3


def _git(args: list[str], cwd: Path) -> tuple[int, str]:
    # A daemon must never let git ask a human for credentials. On Windows,
    # an HTTPS push without stored credentials pops a credential-manager
    # GUI; our timeout then kills git but the prompt process keeps the
    # pipes open and subprocess.run blocks forever reaping them — the
    # sync loop died exactly this way live on the operator's PC
    # (2026-08-26). Non-interactive git fails fast and honestly instead.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0",
           "GCM_INTERACTIVE": "never", "GIT_ASKPASS": "echo"}
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True,
            timeout=GIT_TIMEOUT_S, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"git {args[0]}: {type(exc).__name__}: {exc}"
    out = (proc.stdout + proc.stderr).strip()
    return proc.returncode, out


class GitSync:
    """Sync one working copy with its remote. All methods return (ok, detail)."""

    def __init__(self, repo_root: Path | None = None, remote: str = "origin",
                 branch: str | None = None):
        self.root = Path(repo_root or REPO_ROOT)
        self.remote = remote
        self.branch = branch or self._current_branch()

    def _current_branch(self) -> str:
        code, out = _git(["rev-parse", "--abbrev-ref", "HEAD"], self.root)
        return out if code == 0 and out and out != "HEAD" else "main"

    def available(self) -> tuple[bool, str]:
        """Honest availability: a git repo with this remote configured."""
        code, _ = _git(["rev-parse", "--git-dir"], self.root)
        if code != 0:
            return False, f"{self.root} is not a git repository"
        code, out = _git(["remote", "get-url", self.remote], self.root)
        if code != 0:
            return False, f"remote {self.remote!r} is not configured"
        return True, f"{self.remote} -> {out}"

    def head(self) -> str | None:
        code, out = _git(["rev-parse", "HEAD"], self.root)
        return out if code == 0 else None

    def changed_paths(self, old: str, new: str,
                      limit_to: list[str] | None = None) -> list[str]:
        """Files changed between two commits, optionally under given dirs."""
        args = ["diff", "--name-only", f"{old}..{new}"]
        if limit_to:
            args += ["--", *limit_to]
        code, out = _git(args, self.root)
        return [l for l in out.splitlines() if l.strip()] if code == 0 else []

    def dirty(self) -> bool:
        code, out = _git(["status", "--porcelain"], self.root)
        return code == 0 and bool(out)

    def pull(self) -> tuple[bool, str]:
        """Fetch and rebase onto the remote branch; abort cleanly on conflict."""
        code, out = _git(["fetch", self.remote, self.branch], self.root)
        if code != 0:
            return False, f"fetch failed: {out[-200:]}"
        code, out = _git(
            ["rebase", "--autostash", f"{self.remote}/{self.branch}"], self.root)
        if code != 0:
            _git(["rebase", "--abort"], self.root)
            return False, f"rebase conflict, aborted cleanly: {out[-200:]}"
        if "resulted in conflicts" in out:
            # autostash pop conflicted: dirty file vs upstream — callers
            # avoid this by committing local state BEFORE pulling
            return False, f"autostash conflict: {out[-200:]}"
        return True, "up to date with remote"

    def commit(self, paths: list[Path | str], message: str) -> tuple[bool, str]:
        """Stage exactly `paths` and commit if anything changed — no push.
        The Core runs this BEFORE pulling so a rebase never has to touch a
        dirty working tree (its journal is nearly always mid-append)."""
        # Only paths that exist: `git add` fails the WHOLE invocation on one
        # unmatched pathspec, and exchange/commands legitimately does not
        # exist until the first command lands (git stores no empty dirs). A
        # fresh clone would fail every checkpoint, and because commit()
        # failing short-circuits commit_push(), the Core would never push at
        # all — receipts, journal and pulse all stranded on the PC.
        rels = [str(p) for p in paths if (self.root / p).exists()]
        if not rels:
            return True, "nothing to commit"
        code, out = _git(["add", "--", *rels], self.root)
        if code != 0:
            return False, f"add failed: {out[-200:]}"
        code, out = _git(["diff", "--cached", "--quiet"], self.root)
        if code == 0:
            return True, "nothing to commit"
        code, out = _git(["commit", "-m", message], self.root)
        if code != 0:
            return False, f"commit failed: {out[-200:]}"
        return True, "committed"

    def commit_push(self, paths: list[Path | str], message: str) -> tuple[bool, str]:
        """commit(), then push with rebase-and-retry when the remote moved
        first; commits survive the rebase, so nothing is lost by retrying."""
        ok, detail = self.commit(paths, message)
        if not ok or detail == "nothing to commit":
            # still try the push: earlier ticks may have local commits
            # (e.g. pre-pull checkpoints) waiting to publish
            code, out = _git(["rev-list", "--count",
                              f"{self.remote}/{self.branch}..HEAD"], self.root)
            if not ok or code != 0 or out.strip() == "0":
                return ok, detail
        for attempt in range(PUSH_ATTEMPTS):
            code, out = _git(["push", self.remote, f"HEAD:{self.branch}"], self.root)
            if code == 0:
                return True, "committed and pushed"
            if attempt < PUSH_ATTEMPTS - 1:
                ok, detail = self.pull()
                if not ok:
                    return False, f"push rejected and {detail}"
        return False, f"push failed after {PUSH_ATTEMPTS} attempts: {out[-200:]}"
