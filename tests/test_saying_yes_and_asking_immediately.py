"""'Approve' / 'what's on my shopping list' -> 'Nothing on your shopping list.'

One breath after approving three things onto it. The work an approval
unblocks is kicked off-thread — right, because a slow errand may not
stall the room — and the next question was answered deterministically in
0.0s, beating it. An answer that is wrong for a quarter of a second is
indistinguishable from an answer that is wrong.

So the room WAITS a bounded moment. Not a promise that the work
finished: a chance for the local steps, which take milliseconds, to be
done before he can ask about them.
"""
import threading
import time
import unittest
from unittest import mock

from aletheia import core


class TheRoomWaitsABeat(unittest.TestCase):
    def setUp(self):
        core._KICKING = False

    def _kick(self, work, **kw):
        with mock.patch.object(core.runtime, "_run_approved_intents", work), \
             mock.patch.object(core.runtime, "_run_authorized_errands", lambda: None), \
             mock.patch.object(core.runtime, "_reconcile_scheduling", lambda now: None):
            core.kick_approved_work({"repos": {}}, **kw)
            # let the thread finish so it cannot leak into the next test
            for _ in range(200):
                if not core._KICKING:
                    break
                time.sleep(0.01)

    def test_a_local_step_is_done_before_the_call_returns(self):
        done = threading.Event()

        def work(_fleet):
            time.sleep(0.05)
            done.set()

        self._kick(work, wait_s=core.KICK_WAIT_S)
        self.assertTrue(done.is_set())

    def test_it_is_still_off_thread_without_a_wait(self):
        started = threading.Event()
        release = threading.Event()

        def work(_fleet):
            started.set()
            release.wait(2.0)

        with mock.patch.object(core.runtime, "_run_approved_intents", work), \
             mock.patch.object(core.runtime, "_run_authorized_errands", lambda: None), \
             mock.patch.object(core.runtime, "_reconcile_scheduling", lambda now: None):
            began = time.monotonic()
            core.kick_approved_work({"repos": {}})
            elapsed = time.monotonic() - began
            self.assertTrue(started.wait(1.0))
            self.assertLess(elapsed, 0.5, "the default must not block")
            release.set()
        for _ in range(200):
            if not core._KICKING:
                break
            time.sleep(0.01)

    def test_a_slow_step_cannot_stall_the_room_for_longer_than_the_wait(self):
        release = threading.Event()

        def work(_fleet):
            release.wait(5.0)

        with mock.patch.object(core.runtime, "_run_approved_intents", work), \
             mock.patch.object(core.runtime, "_run_authorized_errands", lambda: None), \
             mock.patch.object(core.runtime, "_reconcile_scheduling", lambda now: None):
            began = time.monotonic()
            core.kick_approved_work({"repos": {}}, wait_s=0.2)
            elapsed = time.monotonic() - began
        release.set()
        self.assertLess(elapsed, 1.0)
        # The claim is "it waited a beat rather than returning instantly",
        # not "it waited 0.2s to the millisecond". Windows' default timer
        # granularity is ~15.6ms and `Event.wait` can come back marginally
        # early against `monotonic`: this asserted >= 0.19 for a 0.2s wait
        # -- a 5% margin -- and failed the whole suite on 0.188s. The floor
        # is still nowhere near an immediate return, which is what would
        # actually be a regression.
        self.assertGreaterEqual(elapsed, 0.15)
        for _ in range(200):
            if not core._KICKING:
                break
            time.sleep(0.01)

    def test_the_wait_is_bounded_and_short(self):
        # Long enough for local work, short enough that a stuck errand is
        # not a stuck room.
        self.assertLessEqual(core.KICK_WAIT_S, 3.0)
        self.assertGreater(core.KICK_WAIT_S, 0.0)


if __name__ == "__main__":
    unittest.main()
