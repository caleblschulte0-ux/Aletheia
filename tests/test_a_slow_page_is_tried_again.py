"""A page that timed out before Submit was pressed is tried again.

Live 2026-10-07 TimeoutError was 14 of the month's 74 failed sends: each a
slow page on one attempt, FAILED for good though the button had never been
pressed. Back in line it goes, a few times, like a busy browser; a timeout
AFTER the press is still counted as maybe sent, never retried.
"""
from aletheia import apply_run, campaign, stateio

import tests.test_apply_run as apply_base


class TimeoutError(Exception):       # Playwright's is matched by its name
    pass


class ASlowPageIsTriedAgain(apply_base.ApplyCase):
    def ready_and_confirmed(self):
        out = self.staged(extra={"#felony": "No", "#cert": True})
        apply_run.confirm(out["id"])
        return out

    def test_a_timeout_before_the_press_goes_back_in_line(self):
        out = self.ready_and_confirmed()

        def slow(record):
            raise TimeoutError("Timeout 30000ms exceeded waiting for the form")
        with self.assertRaises(TimeoutError):
            apply_run.submit(out["id"], submitter=slow)
        record = apply_run.load_run(out["id"])
        self.assertEqual(record["state"], "AWAITING_YOU")
        self.assertEqual(record["submit_tries"], 1)
        self.assertIsNone(apply_run.was_sent(record["url"]))

    def test_a_page_slow_every_time_fails_after_a_few_turns(self):
        out = self.ready_and_confirmed()
        for _ in range(apply_run.MAX_SUBMIT_TRIES):
            apply_run.accept(out["id"])
            with self.assertRaises(TimeoutError):
                apply_run.submit(out["id"], submitter=lambda r: (_ for _ in ()).throw(
                    TimeoutError("slow")))
        record = apply_run.load_run(out["id"])
        self.assertEqual(record["state"], "FAILED")
        self.assertIn("nothing was ever pressed", record["failure"])

    def test_a_timeout_after_the_press_is_maybe_sent_never_retried(self):
        out = self.ready_and_confirmed()

        def pressed_then_slow(record):
            record["pressed_at"] = stateio.utcnow()
            raise TimeoutError("waiting for the confirmation page")
        record = apply_run.submit(out["id"], submitter=pressed_then_slow)
        self.assertEqual(record["state"], "SUBMITTED")
        self.assertIsNotNone(apply_run.was_sent(record["url"]))


class AnOldSlowFailureIsReadAgain(apply_base.ApplyCase):
    def test_a_failed_timeout_with_fillings_left_is_read_again(self):
        self.assertTrue(campaign.refused_submit(
            {"state": "FAILED", "failure": "TimeoutError: Timeout 30000ms exceeded", "stagings": 1}))

    def test_one_with_no_fillings_left_or_pressed_is_not(self):
        self.assertFalse(campaign.refused_submit(
            {"state": "FAILED", "failure": "TimeoutError: slow",
             "stagings": apply_run.MAX_STAGINGS_AFTER_FAILURE}))
        self.assertFalse(campaign.refused_submit(
            {"state": "FAILED", "failure": "TimeoutError: slow", "stagings": 1,
             "pressed_at": "2026-10-07T10:00:00Z"}))
        self.assertFalse(campaign.refused_submit(
            {"state": "FAILED", "failure": "KeyError: 'x'", "stagings": 1}))
