"""The funnel says where the general browser stopped on what it left.

Live 2026-10-07 "no way forward on the page" closed 71 applications in a
month and nothing said whether that was a posting with no Apply button, a
form she had filled, or a button she could not read. Counts only: no
address, no employer - the file is public.
"""
import datetime as dt
import json
import unittest

from aletheia import hunt_funnel

NOW = dt.datetime(2026, 10, 7, 15, 0, tzinfo=dt.timezone.utc)


def left(kind, page_state, *, step="", reached=(), days_ago=1, job=True):
    return {"id": ("bm-apply-for-this-job-x" if job else "bm-buy-milk-x"), "state": "LEFT",
            "left_at": (NOW - dt.timedelta(days=days_ago)).isoformat().replace("+00:00", "Z"),
            "start_url": "https://acme.example/jobs/1",
            "boundary": {"kind": kind, "page_state": page_state, "step": step,
                         "url": "https://acme.example/jobs/1/apply"},
            "checkpoints": [{"name": n} for n in reached]}


class WhereTheBrowserGotStuck(unittest.TestCase):
    def test_each_stop_is_named_by_cause_and_how_far_she_got(self):
        out = hunt_funnel.stuck_at([
            left("NO_WAY_FORWARD", "CONTENT", reached=["observed"]),
            left("NO_WAY_FORWARD", "CONTENT", reached=["observed"]),
            left("NO_WAY_FORWARD", "UNKNOWN"),
            left("NO_WAY_FORWARD", "FORM", step="tell me what to press on https://acme.example/x",
                 reached=["observed", "filled"]),
            left("NO_WAY_FORWARD", "EMAIL_VERIFICATION", step="find the box the site wants its code in"),
            left("CAPTCHA", "CAPTCHA", reached=["observed", "filled", "review_reached"]),
        ], now=NOW)
        self.assertEqual(out["no_way_forward"], {
            "nothing_to_press_on_content/observed": 2,
            "unreadable_page/nothing": 1,
            "unclear_button/filled": 1,
            "no_code_box/nothing": 1})
        self.assertEqual(out["captcha"], {"nothing_to_press_on_captcha/review_reached": 1})
        self.assertNotIn("acme", json.dumps(out))

    def test_only_job_missions_left_inside_the_window_count(self):
        out = hunt_funnel.stuck_at([
            left("NO_WAY_FORWARD", "CONTENT", days_ago=40),
            left("NO_WAY_FORWARD", "CONTENT", job=False),
            {**left("NO_WAY_FORWARD", "CONTENT"), "state": "NEEDS_YOU"},
            {**left("NO_WAY_FORWARD", "CONTENT"), "left_at": "not a date"},
        ], now=NOW)
        self.assertEqual(out, {})


    def test_a_dead_end_says_what_it_held(self):
        from aletheia import browser_loop
        here = "https://acme.example/jobs/1"
        page = lambda *targets: {"url": here, "targets": list(targets)}
        link = lambda label, href="": {"role": "link", "label": label, "href": href}
        self.assertEqual(browser_loop.dead_end(page()), "empty_page")
        self.assertEqual(browser_loop.dead_end(page({"role": "textbox", "label": "Search"})), "empty_page")
        self.assertEqual(browser_loop.dead_end(page(link("Benefits"), link("Careers"))), "no_apply")
        self.assertEqual(browser_loop.dead_end(page(link("Apply on LinkedIn", "https://linkedin.com/x"))),
                         "apply_elsewhere")
        self.assertEqual(browser_loop.dead_end(page(link("Apply", here + "/apply"))), "apply_not_taken")
        self.assertEqual(browser_loop.dead_end(page({"role": "button", "label": "Start application"})),
                         "apply_not_taken")
        for word in browser_loop.DEAD_ENDS:
            boundary = {"kind": "NO_WAY_FORWARD", "page_state": "CONTENT", "dead_end": word}
            self.assertEqual(hunt_funnel._stuck_cause(boundary), f"nothing_to_press_on_content+{word}")
        self.assertEqual(hunt_funnel._stuck_cause({"page_state": "CONTENT", "dead_end": "Acme said no"}),
                         "nothing_to_press_on_content")

    def test_the_stop_records_what_the_dead_end_held(self):
        from unittest import mock
        from aletheia import browser_loop
        record = {"id": "bm-x", "goal": "apply for this job", "start_url": "https://acme.example/jobs/1"}
        obs = {"url": "https://acme.example/jobs/1", "state": "CONTENT",
               "targets": [{"role": "link", "label": "Apply", "href": "https://elsewhere.example/a"}]}
        with mock.patch.object(browser_loop.bm, "stop_at", side_effect=lambda r, s, b: {**r, "boundary": b}), \
                mock.patch.object(browser_loop.site_skills, "learn"), \
                mock.patch("aletheia.demand.record_attempt"):
            out = browser_loop._stop(record, "NEEDS_YOU", "NO_WAY_FORWARD", obs)
        self.assertEqual(out["boundary"]["dead_end"], "apply_elsewhere")


if __name__ == "__main__":
    unittest.main()
