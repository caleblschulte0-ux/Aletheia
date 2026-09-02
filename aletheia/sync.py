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

- **Never rebase a tree someone else is holding.** Added 2026-08-27 after
  it happened: a session was editing this very clone on a `claude/*`
  branch while the Core was running. Every sixty seconds the Core ran
  ``git rebase --autostash origin/main`` on whatever branch was checked
  out — so it rewrote that branch onto main and swept the uncommitted
  edits into a stash nobody was watching. Work was recovered from the
  stash, but the loop had been quietly reverting a colleague's files for
  an hour. The Core owns its OWN branch and its OWN state paths; anything
  else in the tree belongs to whoever put it there, and a sync that would
  touch it refuses and says so instead.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from aletheia.fleet import REPO_ROOT
from aletheia.proc import run as proc_run

GIT_TIMEOUT_S = 60
PUSH_ATTEMPTS = 3

# What the Core writes itself, and may therefore safely stash across a
# rebase. Everything else in the tree belongs to a person.
OWNED_PATHS = ("state/", "exchange/commands/", "exchange/receipts/", "cache/")


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
        proc = proc_run(
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

    def foreign_changes(self, owned: list[str] | None = None) -> list[str]:
        """Uncommitted paths that are NOT the Core's own run-truth.

        The Core writes journal, receipts, pulse and private state; those
        it may stash and replay safely. A modified module, a new test, a
        half-finished edit — those belong to a person, and `--autostash`
        would make them vanish from the working tree mid-keystroke.
        """
        owned = owned if owned is not None else OWNED_PATHS
        # -uall: without it git collapses untracked trees to "exchange/",
        # and a directory the Core owns would read as a foreign path.
        code, out = _git(["status", "--porcelain", "-uall"], self.root)
        if code != 0:
            return []
        paths = []
        for line in out.splitlines():
            path = line[3:].strip().strip('"')
            if " -> " in path:            # a rename: the destination is what exists now
                path = path.split(" -> ", 1)[1]
            if path and not any(path.startswith(prefix) for prefix in owned):
                paths.append(path)
        return paths

    def merge_in_progress(self) -> bool:
        """Is a human (or an agent) part-way through a merge or rebase here?"""
        git_dir = self.root / ".git"
        return any((git_dir / marker).exists() for marker in (
            "MERGE_HEAD", "REBASE_HEAD", "rebase-merge", "rebase-apply",
            "CHERRY_PICK_HEAD", "REVERT_HEAD"))

    def recover_editor_only_upstream_merge(self) -> tuple[bool | None, str]:
        """Abort only the harmless merge state created by plain ``git pull``.

        Aletheia's PC checkout has local state-checkpoint commits. Running plain
        ``git pull`` on that branch can perform a clean upstream merge and then
        open Git's editor merely to approve the generated merge message. If the
        editor is closed, ``MERGE_HEAD`` remains and the Core correctly refuses
        to touch the tree forever.

        This recovery is intentionally much narrower than "abort any merge":
        it requires the sync branch, a MERGE_HEAD with no conflicted paths, no
        other Git operation, and Git's characteristic upstream-pull merge
        message. Real/conflicted/manual merges remain somebody's work and are
        left alone.

        Returns ``(None, '')`` when there is no MERGE_HEAD, ``(True, detail)``
        when the editor-only merge was safely aborted, and ``(False, detail)``
        when a merge exists but is not safe to recover automatically.
        """
        git_dir = self.root / ".git"
        if not (git_dir / "MERGE_HEAD").exists():
            return None, ""
        if any((git_dir / marker).exists() for marker in (
                "REBASE_HEAD", "rebase-merge", "rebase-apply",
                "CHERRY_PICK_HEAD", "REVERT_HEAD")):
            return False, "another Git operation is active — leaving it alone"

        code, current = _git(["rev-parse", "--abbrev-ref", "HEAD"], self.root)
        if code != 0 or current.strip() != self.branch:
            return False, "merge is not on the Core sync branch — leaving it alone"

        code, conflicts = _git(["diff", "--name-only", "--diff-filter=U"], self.root)
        if code != 0 or conflicts.strip():
            return False, "merge has conflicted paths — leaving it for the operator"

        try:
            message = (git_dir / "MERGE_MSG").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False, "merge message is unavailable — leaving it alone"
        expected = f"Merge branch '{self.branch}' of "
        if not message.startswith(expected):
            return False, "merge was not created by a plain upstream pull — leaving it alone"

        code, out = _git(["merge", "--abort"], self.root)
        if code != 0:
            return False, f"could not abort editor-only upstream merge: {out[-200:]}"
        return True, "aborted editor-only upstream merge left by plain git pull"

    def blocking_reason(self) -> str | None:
        """Why this tree must not be rebased right now, or None."""
        if self.merge_in_progress():
            return ("a merge or rebase is in progress in this working copy — "
                    "leaving it alone until whoever started it is finished")
        code, out = _git(["rev-parse", "--abbrev-ref", "HEAD"], self.root)
        if code == 0 and out and out != "HEAD" and out != self.branch:
            return (f"checked out on {out!r}, not the sync branch {self.branch!r} — "
                    "refusing to rebase someone else's branch")
        foreign = self.foreign_changes()
        if foreign:
            shown = ", ".join(sorted(foreign)[:4])
            more = f" (+{len(foreign) - 4} more)" if len(foreign) > 4 else ""
            return (f"uncommitted changes the Core does not own: {shown}{more} — "
                    "refusing to autostash a person's work")
        return None

    def pull(self) -> tuple[bool, str]:
        """Fetch and rebase onto the remote branch; abort cleanly on conflict.

        Refuses outright when the tree is not the Core's to rewrite. A very
        narrow editor-only merge left by a prior plain ``git pull`` is first
        aborted safely, so the normal bounded rebase can resume unattended.
        """
        recovered, recovery_detail = self.recover_editor_only_upstream_merge()
        if recovered is False:
            return False, recovery_detail
        blocked = self.blocking_reason()
        if blocked:
            return False, blocked
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
        if recovered:
            return True, f"{recovery_detail}; up to date with remote"
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
        # Observed live 2026-08-27: while a session resolved a merge here, the
        # Core kept trying to checkpoint every 60s and logged "you have
        # unmerged files" each time. Committing mid-merge would be worse than
        # the noise — `git add` on a conflicted path stages the conflict
        # markers as if they were resolved.
        if self.merge_in_progress():
            return True, "merge in progress — checkpoint skipped"
        rels = [str(p) for p in paths if (self.root / p).exists()]
        if not rels:
            return True, "nothing to commit"
        code, out = _git(["add", "--", *rels], self.root)
        if code != 0:
            return False, f"add failed: {out[-200:]}"
        code, out = _git(["diff", "--cached", "--quiet", "--", *rels], self.root)
        if code == 0:
            return True, "nothing to commit"
        # Commit BY PATHSPEC, not "whatever is in the index". Observed live
        # 2026-09-02: a session had staged a day's work in this clone and was
        # waiting on the test suite before committing; the Core's next
        # checkpoint swept all of it into "core: state checkpoint". Staging
        # only its own paths was never enough — `git commit -m` commits the
        # whole index, including what a person put there. With a pathspec,
        # git commits those paths and leaves everyone else's staging alone.
        code, out = _git(["commit", "-m", message, "--", *rels], self.root)
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
