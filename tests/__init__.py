"""Test-suite setup that runs before any test imports aletheia.

Three times in one day a test wrote into the operator's REAL private state
— a notification titled "Proactive: r1", a communications thread called
"thread:test", an intent record about a sandwich. Each time it was found
by eye, in his notification centre, and once it made an unrelated test
fail by giving it four notices it did not create.

The cause is structural, not careless. Modules bind their store paths at
import time (`RULES_DIR = private_dir("proactive")`), so a test that
forgets one `mock.patch.object` writes to the real one, silently, and a
guard like `if hasattr(...)` turns the mistake into a no-op instead of an
error. Reviewing harder does not fix that.

So the whole suite gets its own private root, set here — before the first
`from aletheia import ...` anywhere — and thrown away at exit. A test that
forgets to patch now pollutes a temp directory nobody will ever read.

The durable repo journal, approvals, and kill-switch are separate stores,
so they are explicitly routed into that same temporary root too. This is
especially important for the kill switch: an intentional production HALT
must protect the real system without turning a hermetic unit test into a
false failure. Tests that exercise HALT still do so against the isolated
path and therefore keep the production safety contract intact.
"""
from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

_created_suite_state = False
_suite_state = os.environ.get("ALETHEIA_PRIVATE_STATE")
if not _suite_state:
    _suite_state = tempfile.mkdtemp(prefix="aletheia-tests-private-")
    os.environ["ALETHEIA_PRIVATE_STATE"] = _suite_state
    _created_suite_state = True

_suite_root = Path(_suite_state)

# journal.py binds JOURNAL_PATH at import time, just like private-state modules.
# Set this before any aletheia import so unpatched journal calls remain isolated.
if not os.environ.get("ALETHEIA_JOURNAL_PATH"):
    os.environ["ALETHEIA_JOURNAL_PATH"] = str(_suite_root / "journal.jsonl")

# policy.py intentionally stores approvals + HALT in tracked repo state so the
# cloud and PC see the same operator decision. That is correct in production,
# but a test run must never consume the live operator policy. Import only after
# the private/journal roots above are established, then redirect the two policy
# stores for this process. Tests that patch these paths continue to work.
from aletheia import policy  # noqa: E402  (ordering is the safety mechanism)
policy.APPROVALS_DIR = _suite_root / "approvals"
policy.HALT_PATH = _suite_root / "halt.json"

if _created_suite_state:
    @atexit.register
    def _cleanup() -> None:
        shutil.rmtree(_suite_state, ignore_errors=True)
