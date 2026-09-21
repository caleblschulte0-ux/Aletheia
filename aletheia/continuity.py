"""What an update must not lose, checked before and after it.

The Windows bring-up updates the checkout in place, and the private state
lives INSIDE that checkout (`state/private/`, gitignored) - his profile,
the local-AI setting, the application records, the conversation thread.
Nothing verified that any of it was still there afterwards: the bring-up
ended with the Core answering and the tests green, and she had forgotten
him. INSTALLED is not WORKING, and a bring-up that says UP over an empty
memory is the same lie one layer down.

So the bring-up takes a `snapshot` of what exists before it stops
anything, and `verify` holds the checkout to it after the update: every
private store that was there is still there and no smaller, the local-AI
setting is what it was, the Python that ran her is the Python that runs
her. Anything lost is a failure of the bring-up, said in English, before
"Core: UP" - never after.

Read-only. Nothing here repairs anything: an update that lost his state
is a thing for him to know about, not a thing to paper over.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from aletheia import stateio

#: How a store's directory name is said out loud. Every top-level
#: directory under the private root is held, named or not: a list kept by
#: hand would miss the next store somebody adds, and a missing name would
#: mean a store nobody checks.
SAID = {
    "profile": "your profile",
    "local-ai": "the local AI setting",
    "jobs": "the job hunt records",
    "conversation": "the conversation thread",
    "memory": "what you asked me to remember",
    "contacts": "your contacts",
    "journal": "my own journal",
    "reasoning": "how I have been thinking",
}


def _count(root: Path) -> int:
    if not root.is_dir():
        return 0
    return sum(1 for p in root.rglob("*") if p.is_file())


def snapshot() -> dict[str, Any]:
    """Everything the update must hand back, as it stands now."""
    from aletheia import model_pool_config
    root = stateio.private_root()
    stores = {}
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if child.is_dir():
                stores[child.name] = {"said": SAID.get(child.name, child.name),
                                      "files": _count(child)}
    try:
        local_ai = model_pool_config.settings()["enabled"]
    except Exception:  # noqa: BLE001
        local_ai = None
    return {
        "private_root": str(root),
        "private_root_exists": root.is_dir(),
        "private_files": _count(root),
        "stores": stores,
        "local_ai_enabled": local_ai,
        "python": sys.executable,
    }


def verify(before: dict[str, Any], after: dict[str, Any] | None = None) -> list[str]:
    """Every way `after` is poorer than `before`, in English. Empty means kept."""
    after = after if after is not None else snapshot()
    lost: list[str] = []
    if before.get("private_root_exists") and not after.get("private_root_exists"):
        lost.append(f"my private state at {before.get('private_root')} is gone")
        return lost
    if str(before.get("private_root") or "") != str(after.get("private_root") or ""):
        lost.append(f"my private state moved from {before.get('private_root')} "
                    f"to {after.get('private_root')}, so I would be reading the wrong one")
    for name, entry in (before.get("stores") or {}).items():
        had = int((entry or {}).get("files") or 0)
        have = int(((after.get("stores") or {}).get(name) or {}).get("files") or 0)
        if had and have < had:
            said = (entry or {}).get("said") or name
            lost.append(f"{said}: {had} files before the update, {have} after")
    if before.get("local_ai_enabled") is True and after.get("local_ai_enabled") is not True:
        lost.append("local AI was on before the update and is off now")
    if before.get("python") and after.get("python") and \
            os.path.normcase(str(before["python"])) != os.path.normcase(str(after["python"])):
        lost.append(f"a different Python runs me now ({after['python']}, was {before['python']}); "
                    "installed packages may not have moved with it")
    return lost


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aletheia.continuity",
                                     description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    snap = sub.add_parser("snapshot", help="write what exists now to a file")
    snap.add_argument("path")
    check = sub.add_parser("verify", help="hold the checkout to an earlier snapshot")
    check.add_argument("path")
    args = parser.parse_args(argv)
    if args.cmd == "snapshot":
        value = snapshot()
        Path(args.path).write_text(json.dumps(value, indent=2), encoding="utf-8")
        print(f"private state: {value['private_files']} files at {value['private_root']}; "
              f"local AI {'on' if value['local_ai_enabled'] else 'off'}")
        return 0
    try:
        before = json.loads(Path(args.path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"could not read the snapshot at {args.path}: {exc}")
        return 2
    lost = verify(before)
    if not lost:
        print("the update kept everything: private state, local AI setting, Python")
        return 0
    print("THE UPDATE LOST SOMETHING:")
    for line in lost:
        print(f"  - {line}")
        try:
            from aletheia import friction
            friction.record("lost", line, source="bring-up")
        except Exception:  # noqa: BLE001
            pass
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
