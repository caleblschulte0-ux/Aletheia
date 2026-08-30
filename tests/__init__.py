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

The durable repo journal is a separate store, so it is explicitly routed
into that same temporary root too. This prevents a real-PC test run from
syncing fake test approvals/actions into fleet history.

The kill switch is intentionally repo-backed so a remote operator halt can reach
the PC. That means a real live halt is present in a checkout and would otherwise
poison tests that are specifically exercising acting paths. Route only the
*test process's* imported policy module to the same temporary root; production
`policy.HALT_PATH` remains unchanged and the real halt file is never removed,
renamed, or ignored by a running Aletheia process.
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

# journal.py binds JOURNAL_PATH at import time, just like private-state modules.
# Set this before any aletheia import so unpatched journal calls remain isolated.
if not os.environ.get("ALETHEIA_JOURNAL_PATH"):
    os.environ["ALETHEIA_JOURNAL_PATH"] = str(Path(_suite_state) / "journal.jsonl")

# policy.py's HALT_PATH is deliberately repo-backed in production, rather than a
# private_dir() store. Import it only after the test state/journal environment is
# established, then redirect this process's module constant. This keeps a real
# operator emergency halt active on the machine while the suite tests unhalted
# behavior against an empty temporary halt path.
from aletheia import policy as _test_policy  # noqa: E402
_test_policy.HALT_PATH = Path(_suite_state) / "policy" / "halt.json"

if _created_suite_state:
    @atexit.register
    def _cleanup() -> None:
        shutil.rmtree(_suite_state, ignore_errors=True)
