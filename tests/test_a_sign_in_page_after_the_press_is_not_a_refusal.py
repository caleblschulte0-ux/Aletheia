"""A site that answers the press with its sign-in door has not refused anything.

Live 2026-09-24 Workday met "Apply" with "Sign In / Create Account / Email
Address / Password", and the press was recorded as REJECTED - "the site
handed it back (its page read: Skip to main content Careers English Sign
In ...)" - ten times on three hosts in one night, each with "change what
the site objected to, then tell me to try again" and nothing to change.
Nothing was refused and nothing was accepted: the site wants an account
first, which is the SIGN_IN boundary every other path already names.
"""
from __future__ import annotations

import unittest

from aletheia import apply_run, browser_loop, browser_mission as bm, page_state as ps
from tests.test_browser_loop_anywhere import OwnRoom

WORKDAY_DOOR = ("Skip to main content Careers English Sign In Search for Jobs Sign In Email Address "
                "Password Email Address is required Forgot Password? Create Account")
REAL_REFUSAL = "There was a problem with your submission. Phone must be 10 digits. Please correct the errors below."


class TheWordsOfASignInDoor(unittest.TestCase):
    def test_workdays_door_reads_as_sign_in(self):
        self.assertTrue(ps.reads_as_sign_in(WORKDAY_DOOR, "Sign In - Workday"))
        self.assertTrue(ps.reads_as_sign_in("Please sign in to continue to your application."))
        self.assertTrue(ps.reads_as_sign_in("Welcome back! Log in Password"))

    def test_a_form_or_a_real_refusal_does_not(self):
        self.assertFalse(ps.reads_as_sign_in(REAL_REFUSAL))
        self.assertFalse(ps.reads_as_sign_in("First name Last name Email Resume Submit application"))
        # a header link that says "Sign in" on an ordinary page is a link, not a door
        self.assertFalse(ps.reads_as_sign_in("Careers Sign in Account Executive Apply now Job description"))


class ASignInPageAfterThePressIsNotARefusal(OwnRoom):
    def mission(self) -> dict:
        record = bm.open_mission("Apply: Account Executive - https://acme.wd1.myworkdayjobs.com/x/job/1",
                                 "https://acme.wd1.myworkdayjobs.com/x/job/1")
        record["gate"] = {"button": "Apply", "kind": ps.COMMIT, "url": record["start_url"]}
        bm.begin_submit(record, button="Apply", url=record["start_url"])
        return record

    def test_the_mission_stops_at_the_sign_in_boundary_not_rejected(self):
        record = self.mission()
        out = browser_loop.after_press(
            {"mission": record["id"], "button": "Apply"},
            {"verdict": "rejected", "evidence": WORKDAY_DOOR, "title": "Sign In",
             "url": "https://acme.wd1.myworkdayjobs.com/login", "site_errors": ["Email Address is required"]})
        self.assertEqual(out["verdict"], browser_loop.SIGN_IN_AFTER_PRESS)
        self.assertIn("sign-in page", out["note"])
        after = bm.load(record["id"])
        self.assertEqual(after["state"], bm.NEEDS_YOU)
        self.assertEqual(after["boundary"]["kind"], "SIGN_IN")
        self.assertNotIn("rejected", after)
        self.assertNotEqual(after["submits"][-1]["verdict"], "rejected")

    def test_the_application_record_says_the_site_wants_an_account(self):
        record = self.mission()
        browser_loop.after_press({"mission": record["id"], "button": "Apply"},
                                 {"verdict": "rejected", "evidence": WORKDAY_DOOR, "title": "Sign In",
                                  "url": "https://acme.wd1.myworkdayjobs.com/login"})
        state = apply_run._MISSION_TO_APPLICATION.get(bm.load(record["id"])["state"], "NEEDS_YOU")
        boundary = bm.load(record["id"])["boundary"]
        if state == "NEEDS_YOU" and boundary.get("kind") in ("SIGN_IN", "NO_VAULT", "ACCOUNT_CREATION_APPROVAL"):
            state = "NEEDS_ACCOUNT"
        self.assertEqual(state, "NEEDS_ACCOUNT")
        self.assertEqual(apply_run._loop_line(record["start_url"], state, boundary, bm.load(record["id"])),
                         "acme.wd1.myworkdayjobs.com: the site wants an account first")

    def test_once_she_is_in_the_same_button_may_be_pressed_because_nothing_was_sent(self):
        record = self.mission()
        browser_loop.after_press({"mission": record["id"], "button": "Apply"},
                                 {"verdict": "rejected", "evidence": WORKDAY_DOOR, "title": "Sign In",
                                  "url": "https://acme.wd1.myworkdayjobs.com/login"})
        ok, why = bm.may_submit(bm.load(record["id"]), button="Apply", url=record["start_url"])
        self.assertTrue(ok, why)

    def test_a_real_refusal_is_still_a_refusal(self):
        record = self.mission()
        out = browser_loop.after_press({"mission": record["id"], "button": "Apply"},
                                       {"verdict": "rejected", "evidence": REAL_REFUSAL, "title": "Apply",
                                        "url": record["start_url"], "site_errors": ["Phone must be 10 digits"]})
        self.assertEqual(out.get("verdict"), "rejected")
        self.assertEqual(bm.load(record["id"])["state"], bm.REJECTED)


if __name__ == "__main__":
    unittest.main()
