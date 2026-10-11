"""Talked to her, 2026-10-11: "what did you sign me up for" went to a model, which has never seen
the ledger of sign-ups she keeps. A store with a writer and no reader makes her a liar."""
import os
import tempfile
import unittest
from unittest import mock

from aletheia import event_signup, quick


class WhatSheSignedHimUpFor(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": tmp.name})
        env.start()
        self.addCleanup(env.stop)

    def test_the_ledger_is_read_back_newest_first(self):
        event_signup._remember("https://example.org/mixer", {
            "state": "registered", "title": "Young Professionals Mixer", "at": "2026-10-10T18:00:00-05:00",
            "slot": {"start": "2026-10-16T18:00:00-05:00"}})
        event_signup._remember("https://example.org/lunch", {
            "state": "registered", "title": "Chamber Lunch", "at": "2026-10-09T12:00:00-05:00", "slot": {}})
        event_signup._remember("https://example.org/list", {
            "state": "joined", "title": "Downtown Events", "at": "2026-10-09T09:00:00-05:00"})
        event_signup._remember("https://example.org/fair", {
            "state": "unconfirmed", "title": "Job Fair", "at": "2026-10-08T09:00:00-05:00"})
        event_signup._remember("https://example.org/paid", {
            "state": "costs_money", "title": "Gala", "at": "2026-10-08T09:00:00-05:00"})
        said = quick.answer("what did you sign me up for")
        self.assertTrue(said.startswith("I signed you up for Young Professionals Mixer, Friday, October 16"), said)
        self.assertIn("Chamber Lunch", said)
        self.assertIn("Downtown Events", said)
        self.assertIn("not sure", said)
        self.assertNotIn("Gala", said)

    def test_an_empty_ledger_says_nothing_yet_and_whether_the_switch_is_off(self):
        with mock.patch.object(event_signup, "status", return_value={"on": False, "ruled_by": "", "set_by": ""}):
            said = quick.answer("did you sign me up for anything")
        self.assertEqual(said, "I haven't signed you up for anything yet. Signing you up is switched off.")

    def test_an_instruction_to_sign_up_is_not_read_as_a_question(self):
        self.assertIsNone(quick.match("sign me up for the mixer"))


class AnyEventsThisWeekendIsHisCalendar(unittest.TestCase):
    """Talked to her, 2026-10-11: "any events this weekend" went to the planner, which could not
    plan it with the models out. It is his calendar for the days he named."""

    def test_the_day_he_names_is_the_day_read(self):
        self.assertEqual(quick.match("any events this weekend"), ("agenda", "this weekend"))
        self.assertEqual(quick.match("are there any events on saturday"), ("agenda", "saturday"))
        self.assertEqual(quick.match("do i have any plans tomorrow"), ("agenda", "tomorrow"))

    def test_an_instruction_is_not_a_question(self):
        self.assertNotEqual((quick.match("find any events this weekend") or ("",))[0], "agenda")
