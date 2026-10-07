"""A resumed mission whose route no longer fits the page starts that leg over.

Live 2026-10-07: eight filled applications ended at "the page could not be
put back" - the site drew its form with new element ids between visits and
the saved route had nothing to type into. His answers live in his profile and
the mission's inputs, not in the route, so a fresh pass fills the form again.
Once anything was pressed to send, it still stops: never twice.
"""
from __future__ import annotations

from unittest import mock

from aletheia import browse, browser_loop, browser_mission as bm
from tests.test_browser_loop_torture import CLINIC_INPUTS, LoopCase, needs_browser

GOAL = "request a dental cleaning appointment"


@needs_browser
class AReplayThatWillNotGoBackStartsOver(LoopCase):
    def setUp(self):
        super().setUp()
        # A box that is not there is waited for until the page's timeout; a
        # loopback page is either there at once or never.
        patch = mock.patch.object(browse, "DEFAULT_TIMEOUT_MS", 2_000)
        patch.start()
        self.addCleanup(patch.stop)

    def crashed(self):
        def crash(step, record):
            if step == 4:
                raise RuntimeError("the process died")
        with self.assertRaises(RuntimeError):
            browser_loop.pursue(GOAL, self.url("/clinic"), inputs=CLINIC_INPUTS, on_step=crash)
        record = bm.load(bm.mission_id(GOAL, self.url("/clinic")))
        self.assertTrue(record["route"])
        # The site redrew its form: nothing the route names is there any more.
        record["route"] = [{**step, "selector": "#drawn-again-with-a-new-id"} for step in record["route"]]
        return bm.save(record)

    def test_it_fills_the_form_again_and_reaches_his_approval(self):
        mid = self.crashed()["id"]
        record = browser_loop.resume(mid, force=True)
        self.assertBoundary(record, bm.AWAITING_APPROVAL, "SUBMIT_APPROVAL")
        self.assertTrue(any("starting again" in h["did"] for h in record["history"]))
        self.assertNotIn("/clinic/submit", self.state["posts"], "nothing was sent before his yes")

    def test_once_something_was_pressed_to_send_it_still_stops(self):
        record = self.crashed()
        record = bm.checkpoint(record, bm.SUBMIT_CLICKED, url=self.url("/clinic/review"))
        stopped = browser_loop.resume(record["id"], force=True)
        self.assertBoundary(stopped, bm.NEEDS_YOU, "ERROR")
