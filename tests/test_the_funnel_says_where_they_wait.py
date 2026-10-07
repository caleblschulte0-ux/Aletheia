"""The funnel says where filled-but-unsent applications are sitting.

Live 2026-10-06: 15 filled, 4 sent, and nothing said where the other
eleven were. Each place is a different fix, so each is its own count, and
the brief names them in words. Counts only: the file is public.
"""
import datetime as dt
import json
import unittest
from unittest import mock

from aletheia import hunt_funnel

NOW = dt.datetime(2026, 10, 7, 15, 0, tzinfo=dt.timezone.utc)


def row(state, **extra):
    base = {"id": f"r-{state}-{len(extra)}", "state": state, "staged_at": "2026-10-05T15:00:00Z"}
    base.update(extra)
    return base


class WhereTheyWait(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(hunt_funnel, "_waits_for_him",
                                    side_effect=lambda r: r.get("employment", ""))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_each_place_is_its_own_count(self):
        rows = [row("NEEDS_YOU"), row("NEEDS_YOU"), row("NEEDS_ACCOUNT"),
                row("AWAITING_YOU"), row("AWAITING_YOU", employment="part-time"),
                row("APPROVED", employment="contract"), row("FAILED"), row("SUBMITTED"),
                row("CLOSED", closed_because="not realistic: wants 5 years", closed_at="2026-10-06T10:00:00Z"),
                row("CLOSED", closed_because="an application already went to this form",
                    closed_at="2026-10-06T10:00:00Z"),
                row("CLOSED", closed_because="Acme said no", closed_at="2026-10-06T10:00:00Z")]
        held = hunt_funnel.counts(rows, now=NOW)["waiting"]
        self.assertEqual(held["needs_answer"], 2)
        self.assertEqual(held["needs_account"], 1)
        self.assertEqual(held["to_send"], 1)
        self.assertEqual(held["his_ok"], {"contract": 1, "part-time": 1})
        self.assertEqual(held["failed"], 1)
        # A closure with no kind and no known reason is what apply_run itself
        # calls it: a judgement that the job was not realistic.
        self.assertEqual(held["closed"], {"duplicate": 1, "not_realistic": 2})
        self.assertEqual(held["oldest_days"], 2)

    def test_a_closure_kind_on_the_record_names_its_bucket(self):
        at = "2026-10-06T10:00:00Z"
        rows = [row("CLOSED", closed_kind="not-a-form", closed_because="a job alert signup", closed_at=at),
                row("CLOSED", closed_kind="not-a-form", closed_because="a bot check", closed_at=at),
                row("CLOSED", closed_kind="gone", closed_because="Sorry, we can't find that page", closed_at=at),
                row("CLOSED", closed_kind="left", closed_because="the browser could not finish it", closed_at=at),
                row("CLOSED", closed_because="this posting is no longer available", closed_at=at)]
        self.assertEqual(hunt_funnel.counts(rows, now=NOW)["waiting"]["closed"],
                         {"gone": 1, "left": 1, "not_a_form": 2, "stale": 1})

    def test_an_application_the_browser_left_is_counted_by_the_wall(self):
        at = "2026-10-06T10:00:00Z"
        rows = [row("CLOSED", closed_kind="left", closed_at=at,
                    closed_because="a human check on a job application, which is not yours to do"),
                row("CLOSED", closed_kind="left", closed_at=at,
                    closed_because="nothing more she could do here: no way forward on the page"),
                row("CLOSED", closed_kind="left", closed_at=at,
                    closed_because="waited two days for questions only you can answer and you did not come"),
                row("CLOSED", closed_kind="left", closed_at=at,
                    closed_because="nothing more she could do here: she ran out of steps")]
        self.assertEqual(hunt_funnel.counts(rows, now=NOW)["waiting"]["closed"],
                         {"left_captcha": 1, "left_no_way_forward": 1, "left_out_of_steps": 1,
                          "left_questions": 1})

    def test_a_failure_the_general_browser_left_unworded_is_counted_by_its_wall(self):
        rows = [row("FAILED", engine="loop", boundary="MANUAL_ONLY"),
                row("FAILED", engine="loop", boundary=""),
                row("FAILED", failure="ApplyError: the Submit button would not take a click - x")]
        self.assertEqual(hunt_funnel.counts(rows, now=NOW)["waiting"]["failed_because"],
                         {"browser_manual_only": 1, "browser_unknown": 1, "submit_would_not_click": 1})

    def test_a_stopped_form_is_counted_by_what_its_questions_ask(self):
        rows = [row("NEEDS_YOU", questions=[{"label": "Will you now or in the future require visa sponsorship?"},
                                            {"label": "Why do you want to work at Acme?"}]),
                row("NEEDS_YOU", questions=[{"label": "Do you require sponsorship to work here?"},
                                            {"label": "What is your favourite colour at Acme?"}]),
                row("NEEDS_YOU", questions=["What are your salary expectations?"])]
        held = hunt_funnel.counts(rows, now=NOW)["waiting"]
        self.assertEqual(held["needs_answer"], 3)
        self.assertEqual(held["asked_about"],
                         {"other": 1, "pay": 1, "sponsorship": 2, "why_this_job": 1})
        self.assertNotIn("acme", json.dumps(held).casefold())

    def test_a_word_inside_another_word_does_not_mislabel_a_question(self):
        self.assertEqual(hunt_funnel._question_topic("What is your ethnicity?"), "demographic")
        self.assertEqual(hunt_funnel._question_topic("Preferred first name"), "other")
        self.assertEqual(hunt_funnel._question_topic("Were you referred by an employee?"), "referral")

    def test_the_browser_librarys_bare_error_is_named_by_its_network_code(self):
        rows = [row("FAILED", failure="Error: page.goto: net::ERR_NAME_NOT_RESOLVED at https://acme.example/jobs"),
                row("FAILED", failure="Error: Target crashed"),
                row("FAILED", failure="Something Acme said")]
        held = hunt_funnel.counts(rows, now=NOW)["waiting"]["failed_because"]
        self.assertEqual(held, {"browser_err_name_not_resolved": 1, "browser_error": 1, "other": 1})
        self.assertNotIn("acme", json.dumps(held).casefold())

    def test_a_failure_is_counted_by_its_shape_never_its_words(self):
        rows = [row("FAILED", failure="TimeoutError: page.goto https://acme.example/jobs/1 timed out"),
                row("FAILED", failure="BrowserBusy: in use (tried 3 times, nothing was ever pressed)"),
                row("FAILED", failure="the site refused it: Acme needs a cover letter"),
                row("FAILED", failure="ApplyError: Acme's form wants a phone extension"),
                row("FAILED", failure="Acme Robotics broke something")]
        held = hunt_funnel.counts(rows, now=NOW)["waiting"]
        self.assertEqual(held["failed"], 5)
        self.assertEqual(held["failed_because"], {"ApplyError": 1, "TimeoutError": 1, "never_pressed": 1,
                                                  "other": 1, "site_refused": 1})
        self.assertNotIn("acme", json.dumps(held).casefold())

    def test_nothing_that_names_an_employer_is_published(self):
        rows = [row("CLOSED", closed_because="Acme Robotics said no", company="Acme Robotics",
                    closed_at="2026-10-06T10:00:00Z"),
                row("NEEDS_YOU", company="Acme Robotics", questions=["Why Acme?"])]
        text = json.dumps(hunt_funnel.counts(rows, now=NOW))
        self.assertNotIn("Acme", text)

    def test_closures_before_the_window_are_not_counted(self):
        rows = [row("CLOSED", closed_because="not realistic", closed_at="2026-08-01T10:00:00Z",
                    staged_at="2026-08-01T10:00:00Z")]
        self.assertEqual(hunt_funnel.counts(rows, now=NOW)["waiting"]["closed"], {})

    def test_the_brief_says_where_they_wait_and_what_clears_it(self):
        rows = [row("SUBMITTED"), row("NEEDS_YOU"), row("NEEDS_ACCOUNT"),
                row("AWAITING_YOU", employment="part-time")]
        lines = hunt_funnel.words(hunt_funnel.counts(rows, now=NOW), now=NOW)
        waiting = [line for line in lines if line.startswith("- **Waiting:**")]
        self.assertEqual(len(waiting), 1)
        self.assertIn("1 stopped on a question only you can answer", waiting[0])
        self.assertIn("1 need an account", waiting[0])
        self.assertIn("1 wait for your own OK", waiting[0])

    def test_nothing_waiting_is_no_line(self):
        lines = hunt_funnel.words(hunt_funnel.counts([row("SUBMITTED")], now=NOW), now=NOW)
        self.assertFalse([line for line in lines if "Waiting" in line])

    def test_an_old_funnel_without_the_block_still_reads(self):
        funnel = hunt_funnel.counts([row("SUBMITTED")], now=NOW)
        funnel.pop("waiting")
        self.assertTrue(hunt_funnel.words(funnel, now=NOW))


if __name__ == "__main__":
    unittest.main()
