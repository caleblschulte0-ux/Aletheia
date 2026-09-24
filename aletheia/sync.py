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

- **A conflict in the Core's OWN files is the Core's to settle.** Added
  2026-09-21 after three days of it: an autostash replay left conflict
  markers inside `state/journal/journal.jsonl` on the operator's PC, no
  process writes that file any more, so nothing ever rewrote it clean;
  `heal_owned_conflicts` refused a file still holding markers, every
  rebase after that refused "you have unmerged files", and the Core ran
  code 85 commits old — every merge of that week — with nothing on the
  page saying so. An append-only log keeps BOTH sides (the union the
  Windows recovery script already used); anything else keeps the Core's
  own copy, which is its newest write. The same rule finishes a rebase
  that stopped on one of its own files instead of aborting it.

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
import re
import subprocess
from pathlib import Path

from aletheia.fleet import REPO_ROOT
from aletheia.proc import run as proc_run

GIT_TIMEOUT_S = 60
PUSH_ATTEMPTS = 3
#: How many of its own conflicted commits a rebase may settle before the
#: Core gives up and aborts it. A checkpoint a minute for a day is far
#: fewer than this; an endless loop is what the bound is for.
REBASE_STEPS = 20

# What the Core writes itself, and may therefore safely stash across a
# rebase. Everything else in the tree belongs to a person.
OWNED_PATHS = ("state/", "exchange/commands/", "exchange/receipts/", "cache/")

_MARKER = re.compile(r"^(<{7}|>{7}) ", re.MULTILINE)


def resolve_conflict_markers(text: str, keep_both: bool) -> str | None:
    """`text` with every conflict block settled, or None if it is not
    shaped like git left it.

    Git writes the side already in the tree FIRST (upstream: `HEAD` in a
    rebase, `Updated upstream` when an autostash is replayed) and the side
    being applied second (the Core's own commit or its own dirty copy). So
    `keep_both` keeps first then second — what `git merge-file --union`
    does, right for an append-only log — and otherwise the second block,
    the Core's newest write, wins.
    """
    out, first, second = [], [], []
    where = "outside"
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        if where == "outside":
            if bare.startswith("<<<<<<< "):
                where, first, second = "first", [], []
            else:
                out.append(line)
        elif where == "first":
            if bare == "=======":
                where = "second"
            elif bare.startswith("<<<<<<< ") or bare.startswith(">>>>>>> "):
                return None
            else:
                first.append(line)
        else:  # second
            if bare.startswith(">>>>>>> "):
                out.extend(first if keep_both else [])
                out.extend(second)
                where = "outside"
            elif bare.startswith("<<<<<<< ") or bare == "=======":
                return None
            else:
                second.append(line)
    if where != "outside":
        return None
    return "".join(out)


def _keeps_both_sides(rel: str) -> bool:
    """An append-only log keeps both halves; a snapshot keeps the Core's."""
    return rel.endswith(".jsonl")


_IN_THE_WAY = re.compile(
    r"untracked working tree files would be overwritten by [a-z ]+:\n((?:[ \t]+\S.*\n?)+)")


def untracked_in_the_way(out: str) -> list[str]:
    """The paths git names in 'untracked working tree files would be
    overwritten by checkout/merge', or [] when that is not the complaint."""
    m = _IN_THE_WAY.search(out.replace("\r\n", "\n"))
    if not m:
        return []
    return [line.strip() for line in m.group(1).splitlines() if line.strip()]


#: `XY path`, where XY is one or two status characters. Matched by SHAPE
#: rather than sliced at a fixed offset, because `_git` strips its output
#: and that removes the leading space of the first line - which turned
#: " M state/pulse/latest.json" into "tate/pulse/latest.json", stopped it
#: matching the owned `state/` prefix, and blocked the Core's own pull.
_PORCELAIN = re.compile(r"^\s*(?P<status>[MADRCU?!]{1,2})\s+(?P<path>.+)$")


def _porcelain_path(line: str) -> str:
    """The path out of one `git status --porcelain` line, or ""."""
    m = _PORCELAIN.match(line)
    if not m:
        return ""
    path = m.group("path").strip().strip('"')
    if " -> " in path:      # a rename: what exists now is the destination
        path = path.split(" -> ", 1)[1].strip().strip('"')
    return path


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
            path = _porcelain_path(line)
            if not path or any(path.startswith(prefix) for prefix in owned):
                continue
            if self._is_stray_clone(line, path):
                continue
            paths.append(path)
        return paths

    def _is_stray_clone(self, line: str, path: str) -> bool:
        """An untracked directory that is itself a git repository.

        A recovery on 2026-09-19 left a whole second clone inside the
        checkout, and for two days it read as "a person's uncommitted
        work" and blocked every pull. It is nobody's work in progress:
        git treats a nested repository as opaque, never descends into it,
        and a rebase cannot touch it — so it is not a reason to refuse.
        """
        if not line.lstrip().startswith("??"):
            return False
        return (self.root / path.rstrip("/") / ".git").exists()

    def merge_in_progress(self) -> bool:
        """Is a human (or an agent) part-way through a merge or rebase here?

        A rebase is in progress while its `rebase-merge` or `rebase-apply`
        directory exists — that is what `git status` reads. `REBASE_HEAD`
        is NOT on the list: git 2.55 leaves that ref behind after a rebase
        finishes (`git rebase --continue` then "fatal: no rebase in
        progress", with the file still there), and reading it as "in
        progress" made a clean tree refuse every pull that followed.
        """
        git_dir = self.root / ".git"
        return any((git_dir / marker).exists() for marker in (
            "MERGE_HEAD", "rebase-merge", "rebase-apply",
            "CHERRY_PICK_HEAD", "REVERT_HEAD"))

    def heal_owned_conflicts(self) -> list[str]:
        """Mark the Core's own conflicted files resolved, as they are on disk.

        `rebase --autostash` replays the Core's dirty pulse over upstream's
        and can conflict. Git then leaves the path unmerged with no MERGE_HEAD,
        so nothing above calls it a merge, and every later rebase and commit
        refuses with "you have unmerged files". Observed live 2026-09-10 15:56:
        the Core stopped pulling and pushing over its own heartbeat file.

        Once the Core has rewritten the file (no conflict markers left), the
        copy on disk is its newest write and is the resolution. A file still
        holding markers is settled by `resolve_conflict_markers` — both
        halves of a log, the Core's own copy of anything else — because a
        file nothing writes any more (the legacy journal) would otherwise
        hold its markers forever, and did: 2026-09-18 to 09-21, with every
        pull refused behind it. A conflicted file anyone else owns is theirs.
        """
        if self.merge_in_progress():
            return []
        conflicted = self._owned_conflicts()
        if not conflicted or not self._settle_on_disk(conflicted):
            return []
        code, _ = _git(["add", "--", *conflicted], self.root)
        if code != 0:
            return []
        _git(["reset", "-q", "--", *conflicted], self.root)
        return conflicted

    def _owned_conflicts(self) -> list[str]:
        """Conflicted paths, if EVERY one is the Core's own; else []."""
        code, out = _git(["diff", "--name-only", "--diff-filter=U"], self.root)
        if code != 0:
            return []
        conflicted = [p.strip() for p in out.splitlines() if p.strip()]
        if not conflicted or not all(p.startswith(OWNED_PATHS) for p in conflicted):
            return []
        return conflicted

    def _settle_on_disk(self, conflicted: list[str]) -> bool:
        """Rewrite each file without markers. False leaves everything as it was."""
        settled = []
        for rel in conflicted:
            path = self.root / rel
            try:
                raw = path.read_bytes()
            except OSError:
                return False
            text = raw.decode("utf-8", errors="surrogateescape")
            if _MARKER.search(text):
                text = resolve_conflict_markers(text, _keeps_both_sides(rel))
                if text is None:
                    return False
                settled.append((path, text.encode("utf-8", errors="surrogateescape")))
        for path, data in settled:
            try:
                path.write_bytes(data)
            except OSError:
                return False
        return True

    def _set_aside_and_rebase(self, in_the_way: list[str]) -> tuple[int, str]:
        """Move the Core's own untracked files out of a rebase's way, run
        it, and put them back by the owned-file rule. Returns the rebase's
        (code, output); on any failure the files are exactly as they were."""
        kept: list[tuple[Path, bytes]] = []
        for rel in in_the_way:
            path = self.root / rel
            try:
                kept.append((path, path.read_bytes()))
            except OSError:
                return 1, f"could not read {rel} to set it aside"
        for path, _ in kept:
            try:
                path.unlink()
            except OSError:
                for back, data in kept:   # put back what was already moved
                    back.write_bytes(data)
                return 1, f"could not set aside {path.name}"
        code, out = _git(
            ["rebase", "--autostash", f"{self.remote}/{self.branch}"], self.root)
        for path, data in kept:
            rel = path.relative_to(self.root).as_posix()
            try:
                if code == 0 and path.exists() and _keeps_both_sides(rel):
                    upstream = path.read_bytes()
                    data = upstream + (b"" if upstream.endswith(b"\n") or not upstream
                                       else b"\n") + data
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            except OSError:
                pass   # the copy is in the log below; never raise out of sync
        return code, out

    def finish_owned_rebase(self) -> tuple[bool, str]:
        """Carry a rebase that stopped on the Core's own files through to the
        end. (True, what was kept) when it finished; (False, why) when a
        person's file is in the conflict or the bound ran out — the caller
        aborts then, exactly as before this existed."""
        if not self.merge_in_progress():
            # Refused before it began (an untracked file in the way, a
            # detached HEAD it could not make): nothing here to finish.
            return False, "the rebase never started"
        kept = []
        for _ in range(REBASE_STEPS):
            if not self.merge_in_progress():
                return True, ("kept the Core's own copy of " + ", ".join(sorted(set(kept)))
                              if kept else "")
            conflicted = self._owned_conflicts()
            if not conflicted or not self._settle_on_disk(conflicted):
                return False, "a file that is not the Core's is in the conflict"
            code, _ = _git(["add", "--", *conflicted], self.root)
            if code != 0:
                return False, "could not stage the settled files"
            kept.extend(conflicted)
            code, _ = _git(["diff", "--cached", "--quiet"], self.root)
            if code == 0:   # the commit became empty once settled: nothing to keep
                code, out = _git(["rebase", "--skip"], self.root)
            else:
                code, out = _git(["-c", "core.editor=true", "rebase", "--continue"],
                                 self.root)
            if code != 0 and not self.merge_in_progress():
                return False, f"rebase could not continue: {out[-200:]}"
        return False, f"rebase still unfinished after {REBASE_STEPS} of its own conflicts"

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
                "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD")):
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
        # FETCH FIRST, whatever the tree is doing. A fetch touches no working
        # file, and it is the only way the Core learns it is behind: live
        # 2026-09-23 a tree refused as "a rebase in progress" was never
        # fetched, `version()` counted against a remote ref six hours old,
        # and the health line said everything was running while nine merges
        # sat on the remote. Refused is refused; behind is still said.
        code, out = _git(["fetch", self.remote, self.branch], self.root)
        if code != 0:
            return False, f"fetch failed: {out[-200:]}"
        healed = self.heal_owned_conflicts()
        blocked = self.blocking_reason()
        if blocked:
            return False, blocked
        code, out = _git(
            ["rebase", "--autostash", f"{self.remote}/{self.branch}"], self.root)
        notes = [recovery_detail] if recovered else []
        if code != 0:
            # An untracked file of its OWN that upstream has since added
            # (the Core filed a task; a session committed the same task)
            # stops a rebase before it starts, and the autostash never
            # carries untracked files. Set them aside, rebase, then apply
            # the same rule as a conflict: both halves of a log, its own
            # copy of anything else. Found live 2026-09-21, one file.
            in_the_way = untracked_in_the_way(out)
            if in_the_way and all(p.startswith(OWNED_PATHS) for p in in_the_way):
                code, out = self._set_aside_and_rebase(in_the_way)
                healed = healed + in_the_way
        if code != 0:
            # Its own checkpoint clashing with upstream's copy of its own
            # file is the Core's to settle; anything else is aborted clean.
            finished, note = self.finish_owned_rebase()
            if not finished:
                _git(["rebase", "--abort"], self.root)
                return False, f"rebase conflict, aborted cleanly: {out[-200:]}"
            if note:
                notes.append(note)
        if "resulted in conflicts" in out:
            # The rebase itself is done; replaying the Core's dirty copy
            # over upstream's clashed. Settle it the same way, now, rather
            # than leave markers in a file nothing may rewrite.
            healed = healed + self.heal_owned_conflicts()
            _code, left = _git(["diff", "--name-only", "--diff-filter=U"], self.root)
            if left.strip():
                return False, f"autostash conflict: {out[-200:]}"
        if healed:
            notes.append("kept the Core's own copy of " + ", ".join(sorted(set(healed))))
        return True, "; ".join(notes + ["up to date with remote"])

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
        self.heal_owned_conflicts()
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
