# Public Git history privacy cleanup — plan only

**Status: PLAN ONLY. No history rewrite, force-push, credential rotation, or destructive repository action is authorized by this document.**

## Why this exists

A personal contact detail was briefly committed to this public repository and was later removed from the current tree. Removing it from `main` does **not** remove it from old Git objects, forks, clones, caches, screenshots, search indexes, or third-party archives.

The current application design has already been corrected: personal contacts live under gitignored private runtime state, and mail resolves private contacts before the legacy public memory store. This document addresses only historical exposure.

## Risk classification

- Treat the exposed value as **publicly disclosed PII**, not as a secret that can be made private again by rewriting Git.
- If any credential/token/password is ever found during the audit, **revoke/rotate it first**. History rewriting is not credential rotation.
- Do not paste the exposed value into issues, PRs, logs, shell history, CI output, or this document while investigating it.

## Preconditions before any rewrite

1. Operator gives explicit approval for a destructive history rewrite.
2. Claude (or another designated reviewer) identifies the exact commits/paths and confirms whether the exposed material is only contact information or includes any credential.
3. Pause all Aletheia writers that push to this repository: local Core sync, scheduled workflows that commit state, and active coding sessions.
4. Confirm every important branch/tag is known and backed up to an offline/local clone that will **not** be pushed accidentally.
5. Notify any collaborators that old clones must be discarded or carefully rebased after the rewrite.

## Recommended rewrite procedure

Use `git filter-repo` from a clean local clone. Prefer path-based deletion when the offending file/entry can be removed without damaging legitimate history; otherwise use a replace-text rule that matches the exact exposed value without printing it into terminal output.

High-level sequence:

1. Mirror-clone the repository locally.
2. Record the old refs in an offline note.
3. Run `git filter-repo` across **all branches and tags** with the narrowly scoped removal rule.
4. Verify the rewritten object graph locally before pushing.
5. Search every reachable commit for the affected path/value without echoing the value into logs.
6. Run the complete Aletheia test suite against the rewritten history tip.
7. With explicit operator confirmation, force-push rewritten branches/tags using the narrowest possible commands.
8. Recreate/repair any open PR branches that referenced old object IDs.
9. Restart the Core from a fresh clone or hard-reset it to rewritten `main`; do not let an old clone push the removed history back.
10. Verify GitHub's default branch, tags, Actions, Pages, and open PRs still point at intended rewritten commits.

## Verification checklist

A rewrite is not complete merely because the value disappears from `main`.

- `git rev-list --all` plus a local content scan finds no reachable occurrence.
- The specific old commit hashes no longer exist in the rewritten refs.
- `git fsck --no-reflogs --unreachable` is reviewed locally for accidental retained objects before cleanup.
- All Aletheia tests pass.
- Core bootstrap/sync can pull the rewritten history from a fresh clone.
- No automation is still pushing from a pre-rewrite clone.
- GitHub code search no longer shows the value in reachable repository history (allow for indexing delay).

## GitHub and third-party reality

A force-push cannot guarantee erasure from:

- forks and other people's clones;
- GitHub caches or support-side retained objects;
- search engine caches;
- archival services;
- screenshots or copied text.

If the operator needs GitHub-side cached sensitive data purged beyond normal rewritten refs, use GitHub's documented sensitive-data-removal/support process after the rewrite. Do not claim the information is private again; the correct claim is only that the repository's reachable history no longer contains it.

## Prevention added to the engineering backlog

The repository should keep automated privacy regression tests that refuse likely emails, tokens, credentials, and other private fields in committed personal-state paths. Those tests are additive defense; they are not a substitute for code review or gitignored private stores.
