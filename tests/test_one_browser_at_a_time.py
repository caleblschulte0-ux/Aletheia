"""Two sessions in one Chrome profile is how six sends died.

2026-09-12. His standing grant made sending automatic, so the Core's beat
pressed submit while a campaign was still hunting — and every session
opens the SAME persistent profile directory (`cache/browser-profile`).
Chrome will not have two processes in one profile, so six of seven
unattended sends died with::

    TargetClosedError: BrowserType.launch_persistent_context:
    Target page, context or browser has been closed

Nothing serialised access; the two halves of his job hunt simply fought.

The lock is a plain file taken with O_EXCL. Two things it has to get
right, and the first version got the second one wrong badly enough to
let both sessions in while reporting that it could not happen:

- a second session WAITS rather than opening the profile;
- a lock left behind by a crashed run is eventually stolen, or one bad
  night would leave her unable to open a browser ever again.

The bug: the staleness threshold was read from the caller's own `wait_s`,
so a caller willing to wait two seconds treated a two-second-old lock —
one another session was actively holding — as abandoned, deleted it, and
walked in. Staleness is now its own number and is not something a
impatient caller can shrink.
"""
from __future__ import annotations

import os
import pathlib
import tempfile
import time
import unittest

from aletheia import browse


class OneBrowserAtATimeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.profile = pathlib.Path(self.tmp.name) / "browser-profile"
        self.profile.mkdir()

    def lock(self, wait_s=2.0, stale_after_s=None):
        made = browse._profile_lock(self.profile)
        made.wait_s = wait_s
        if stale_after_s is not None:
            made.stale_after_s = stale_after_s
        return made

    def test_a_second_session_does_not_get_in(self):
        first, second = self.lock(), self.lock()
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire(), "two sessions in one profile is the bug")

    def test_an_impatient_waiter_cannot_shrink_staleness(self):
        """The exact defect: wait_s WAS the staleness threshold, so a caller
        willing to wait two seconds stole a two-second-old live lock."""
        first = self.lock()
        self.assertTrue(first.acquire())
        time.sleep(2.2)
        second = self.lock(wait_s=2.0)
        self.assertGreater(second.stale_after_s, 60,
                           "staleness is its own number, not the caller's patience")
        self.assertFalse(second.acquire())

    def test_it_is_released_and_the_next_session_proceeds(self):
        first, second = self.lock(), self.lock()
        first.acquire()
        first.release()
        self.assertTrue(second.acquire())
        second.release()
        self.assertFalse((self.profile.parent
                          / (self.profile.name + ".lock")).exists())

    def test_a_lock_from_a_crashed_run_is_eventually_stolen(self):
        """Otherwise one bad night ends browsing for good."""
        dead = self.lock()
        dead.acquire()
        path = self.profile.parent / (self.profile.name + ".lock")
        old = time.time() - 10_000
        os.utime(path, (old, old))
        alive = self.lock(wait_s=2.0, stale_after_s=60.0)
        self.assertTrue(alive.acquire())
        alive.release()

    def test_releasing_a_lock_it_never_held_is_harmless(self):
        never = self.lock()
        never.release()          # must not raise, must not delete another's lock
        holder = self.lock()
        self.assertTrue(holder.acquire())


if __name__ == "__main__":
    unittest.main()
