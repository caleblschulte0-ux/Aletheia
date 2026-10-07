"""A reminder said with a date, a "next", or two units in one breath.

Found 2026-10-07 in the sandbox: "remind me on the 15th to pay rent" was
refused as SPENDING (the local planner's money door had no exemption for
writing something down), and "on october 20", "next tuesday" and "in 2
hours and 30 minutes" all fell to the planner.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import local_planner, voice


class ADateIsADay(unittest.TestCase):
    TODAY = dt.date(2026, 10, 7)

    def test_a_bare_ordinal_is_this_month_until_it_passes(self):
        self.assertEqual(voice._spoken_date("the 15th", self.TODAY), "2026-10-15")
        self.assertEqual(voice._spoken_date("the 3rd", self.TODAY), "2026-11-03")
        self.assertEqual(voice._spoken_date("on the 7th", self.TODAY), "2026-10-07")

    def test_a_month_and_day_is_this_year_until_it_passes(self):
        self.assertEqual(voice._spoken_date("october 20", self.TODAY), "2026-10-20")
        self.assertEqual(voice._spoken_date("oct 20th", self.TODAY), "2026-10-20")
        self.assertEqual(voice._spoken_date("the 20th of november", self.TODAY), "2026-11-20")
        self.assertEqual(voice._spoken_date("march 2", self.TODAY), "2027-03-02")

    def test_a_date_that_does_not_exist_is_not_moved(self):
        self.assertIsNone(voice._spoken_date("february 30", self.TODAY))
        self.assertIsNone(voice._spoken_date("the 40th", self.TODAY))
        self.assertIsNone(voice._spoken_date("soon", self.TODAY))


class ARemindersDay(unittest.TestCase):
    def _at(self, sentence):
        out = voice._interpret(sentence)
        self.assertIsNotNone(out["command"], out)
        self.assertEqual(out["command"]["kind"], "remind_at")
        return out["command"]

    def test_on_the_15th_is_a_reminder_not_a_payment(self):
        cmd = self._at("remind me on the 15th to pay rent")
        self.assertEqual(cmd["text"], "pay rent")
        self.assertEqual(dt.datetime.fromisoformat(cmd["at"]).day, 15)

    def test_a_month_either_end_of_the_sentence(self):
        a = self._at("remind me on october 20 to renew my tags")
        b = self._at("remind me to renew my tags on oct 20th at 9am")
        for cmd in (a, b):
            when = dt.datetime.fromisoformat(cmd["at"])
            self.assertEqual((when.month, when.day, when.hour), (10, 20, 9))
            self.assertEqual(cmd["text"], "renew my tags")

    def test_next_weekday_is_asked_with_the_answer_in_his_words(self):
        out = voice._interpret("remind me next tuesday to call mom")
        self.assertIsNone(out["command"])
        self.assertIn("Which Tuesday", out["say"])
        self.assertIn("to call mom", out["say"])


class TwoUnitsInOneBreath(unittest.TestCase):
    def _minutes(self, sentence):
        before = dt.datetime.now(dt.timezone.utc)
        out = voice._interpret(sentence)
        self.assertIsNotNone(out["command"], out)
        return round((dt.datetime.fromisoformat(out["command"]["at"]) - before).total_seconds() / 60)

    def test_hours_and_minutes(self):
        self.assertEqual(self._minutes("remind me in 2 hours and 30 minutes to stretch"), 150)
        self.assertEqual(self._minutes("remind me to stretch in two hours 15 minutes"), 135)

    def test_and_a_half(self):
        self.assertEqual(self._minutes("remind me in an hour and a half to check the laundry"), 90)
        self.assertEqual(self._minutes("remind me in 2 and a half hours to leave"), 150)


class RecordingIsNotSpending(unittest.TestCase):
    def test_the_local_door_lets_a_reminder_through(self):
        self.assertIsNone(local_planner._refusal_for_spending("remind me to pay rent tomorrow"))
        self.assertIsNone(local_planner._refusal_for_spending("add buy a new monitor to my tasks"))

    def test_the_local_door_still_stops_spending(self):
        self.assertTrue(local_planner._refusal_for_spending("buy me a monitor"))
        self.assertTrue(local_planner._refusal_for_spending("order me a pizza"))


if __name__ == "__main__":
    unittest.main()


class ATimeIsNotAService(unittest.TestCase):
    def test_cancel_my_3pm_cancels_no_subscription(self):
        for said in ("cancel my 3pm", "cancel my 3 pm meeting", "cancel my plans tonight",
                     "cancel my lunch with dana"):
            with self.subTest(said=said):
                cmd = voice._interpret(said)["command"] or {}
                self.assertNotEqual(cmd.get("kind"), "subscription_cancel")

    def test_a_service_is_still_one(self):
        self.assertEqual(voice._interpret("cancel my netflix")["command"]["kind"], "subscription_cancel")


class TheOtherWaysOfAsking(unittest.TestCase):
    def test_reminder_questions(self):
        for said in ("when's my next reminder", "what are my reminders", "show me my alarms",
                     "what reminders did i set"):
            with self.subTest(said=said):
                self.assertEqual(voice._interpret(said)["command"]["kind"], "reminders")

    def test_remind_me_again_is_a_snooze(self):
        self.assertEqual(voice._interpret("remind me again in 10 minutes")["command"],
                         {"kind": "notify_snooze", "minutes": 10})
        self.assertEqual(voice._interpret("remind me later")["command"]["kind"], "notify_snooze")

    def test_inbox_questions(self):
        for said in ("how many unread emails do i have", "check my inbox", "any unread emails"):
            with self.subTest(said=said):
                self.assertEqual(voice._interpret(said)["command"]["kind"], "email_check")


class SmallThingsWithNoModel(unittest.TestCase):
    def test_powers_and_roots(self):
        from aletheia import quick
        self.assertEqual(quick.answer("what's 2 to the power of 10"), "1,024.")
        self.assertEqual(quick.answer("what is 7 squared"), "49.")
        self.assertEqual(quick.answer("what's the square root of 144"), "12.")
        self.assertIsNone(quick.answer("what's 2 to the 1000"))

    def test_a_joke_is_one_of_hers(self):
        from aletheia import quick
        self.assertIn(quick.answer("tell me a joke"), quick.JOKES)

    def test_where_he_parked_is_his_newest_note(self):
        from aletheia import quick
        rows = [{"text": "I parked on level 3"}, {"text": "buy milk"}, {"text": "I parked on level 1"}]
        with mock.patch.object(quick, "_notes", return_value=rows):
            self.assertEqual(quick.answer("where did i park"), "You told me: I parked on level 3.")
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIn("haven't told me", quick.answer("where's my car"))
        self.assertEqual(voice._interpret("I parked on level 3")["command"],
                         {"kind": "note", "text": "I parked on level 3"})
