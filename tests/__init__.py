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

This is the package's only job. Anything a test needs it still sets up
itself; this only decides WHERE "private state" means.
"""
from __future__ import annotations

import atexit
import os
import shutil
import tempfile

# Only if the caller has not chosen one. Someone deliberately pointing the
# suite at a specific directory (to reproduce a bug against a copy of real
# state, say) should keep it.
if not os.environ.get("ALETHEIA_PRIVATE_STATE"):
    _SUITE_STATE = tempfile.mkdtemp(prefix="aletheia-tests-private-")
    os.environ["ALETHEIA_PRIVATE_STATE"] = _SUITE_STATE

    @atexit.register
    def _cleanup() -> None:
        shutil.rmtree(_SUITE_STATE, ignore_errors=True)
