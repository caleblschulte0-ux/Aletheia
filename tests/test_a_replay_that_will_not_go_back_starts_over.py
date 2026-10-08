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
    def resume(self, mid):
        # A box that is not there is waited for until the page's timeout; a
        # loopback page is either there at once or never. Only the replay
        # waits for boxes that are gone, so only the replay is shortened: the
        # first pass at two seconds stopped at "started" on a busy Windows
        # runner twice on 2026-10-08, before the test's crash ever came.
        with mock.patch.object(browse, "DEFAULT_TIMEOUT_MS", 5_000):
            return browser_loop.resume(mid, force=True)

    def crashed(self):
        def crash(step, record):
            if step == 4:
                raise RuntimeError("the process died")
        try:
            ended = browser_loop.pursue(GOAL, self.url("/clinic"), inputs=CLINIC_INPUTS, on_step=crash)
        except RuntimeError:
            pass
        else:
            # Failed once on a Windows runner, 2026-10-08, with nothing to say
            # where the mission stopped instead. Say it.
            self.fail(f"the mission ended before the crash: {ended.get('state')} "
                      f"{(ended.get('boundary') or {}).get('kind')} {ended.get('history', [])[-3:]}")
        record = bm.load(bm.mission_id(GOAL, self.url("/clinic")))
        self.assertTrue(record["route"])
        # The site redrew its form: nothing the route names is there any more.
        record["route"] = [{**step, "selector": "#drawn-again-with-a-new-id"} for step in record["route"]]
        return bm.save(record)

    def test_it_fills_the_form_again_and_reaches_his_approval(self):
        mid = self.crashed()["id"]
        record = self.resume(mid)
        self.assertBoundary(record, bm.AWAITING_APPROVAL, "SUBMIT_APPROVAL")
        self.assertTrue(any("starting again" in h["did"] for h in record["history"]))
        self.assertNotIn("/clinic/submit", self.state["posts"], "nothing was sent before his yes")

    def test_once_something_was_pressed_to_send_it_still_stops(self):
        record = self.crashed()
        record = bm.checkpoint(record, bm.SUBMIT_CLICKED, url=self.url("/clinic/review"))
        stopped = self.resume(record["id"])
        self.assertBoundary(stopped, bm.NEEDS_YOU, "ERROR")
