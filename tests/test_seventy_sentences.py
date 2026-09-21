"""What seventy everyday sentences turned up, said with every model off.

2026-09-21, the seamless brief: "I just want to be able to talk at it and
no matter what I say it will get stuff done." Seventy ordinary sentences
through the voice door with the frontier and her own model switched off.
Each case below was wrong or fell through; each now has a home, and none
needs a model. (The rung tests hold the rules; this file holds the rest.)
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import presence, quick, rule_planner, tasks, voice


class WakeUpsAndTimersAreReminders(unittest.TestCase):
    def test_wake_me_up_is_a_morning_reminder(self):
        cmd = voice._interpret("wake me up at 6 tomorrow")["command"]
        self.assertEqual(cmd["kind"], "remind_at")
        self.assertEqual(cmd["text"], "wake up")
        when = dt.datetime.fromisoformat(cmd["at"])
        self.assertEqual((when.hour, when.minute), (6, 0))
        from aletheia import localtime
        self.assertEqual(when.date(), (dt.datetime.now(localtime.operator_tz()) + dt.timedelta(days=1)).date())

    def test_a_timer_is_a_reminder_from_now(self):
        cmd = voice._interpret("set a timer for ten minutes")["command"]
        self.assertEqual(cmd["kind"], "remind_at")
        self.assertEqual(cmd["text"], "your ten-minute timer is up")
        when = dt.datetime.fromisoformat(cmd["at"])
        self.assertLess(abs((when - dt.datetime.now(dt.timezone.utc)).total_seconds() - 600), 5)
        self.assertEqual(voice._interpret("remind me in 5 minutes")["command"]["text"], "your 5-minute timer is up")


class APersonIsNotAFile(unittest.TestCase):
    def test_find_me_a_plumber_near_me_is_not_a_file_search(self):
        self.assertNotEqual(voice._interpret("find me a plumber near me")["command"].get("kind"), "file_find")
        kind, args, said = rule_planner.match("find me a plumber near me")
        self.assertEqual(kind, "web_task")
        self.assertIn("plumber", args["goal"])

    def test_a_folder_with_something_in_it_is_a_file_search_not_a_website(self):
        kind, args, _ = rule_planner.match("open the folder with my resume")
        self.assertEqual((kind, args), ("file_find", {"query": "resume"}))


class HisListIsHis(unittest.TestCase):
    def test_a_build_ticket_is_not_on_his_task_list(self):
        self.assertTrue(tasks.is_his({"id": "call-the-plumber", "description": "call the plumber"}))
        self.assertFalse(tasks.is_his({"id": "verify-message-send", "description": "verify",
                                       "required_capabilities": ["message.send"], "assigned_worker": "claude"}))
        rows = [{"id": "call-the-plumber", "description": "call the plumber", "status": "QUEUED"},
                {"id": "verify-message-send", "description": "Teach program_compose.fill_args", "status": "QUEUED",
                 "required_capabilities": ["message.send"], "assigned_worker": "claude"}]
        with mock.patch("aletheia.tasks.all_tasks", return_value=rows), \
             mock.patch("aletheia.tasks.is_ready", return_value=True):
            said = quick.answer("what are my tasks")
        self.assertIn("1 task open", said)
        self.assertIn("call the plumber", said)
        self.assertNotIn("program_compose", said)


class WhatIsGoingOn(unittest.TestCase):
    def test_a_plan_waiting_on_him_is_not_something_she_is_working_on(self):
        records = [{"state": "PROPOSED", "summary": "Add eggs to the list"},
                   {"state": "PROPOSED", "summary": "Open spotify"},
                   {"state": "PROPOSED", "summary": "Book a haircut"}]
        with mock.patch("aletheia.intents.all_intents", return_value=records), \
             mock.patch("aletheia.followups.pending_count", return_value=0), \
             mock.patch("aletheia.errands.all_errands", return_value=[]):
            working = presence._working()
        self.assertTrue(all(w["pending"] for w in working))
        snap = {"halted": False, "working": working, "waiting_on_you": []}
        with mock.patch("aletheia.presence.snapshot", lambda: snap), \
             mock.patch("aletheia.current_state.sections", return_value={"agent": {"state": "IDLE"}}):
            said = quick.answer("what are you doing")
        self.assertTrue(said.startswith("Nothing running. I'm waiting on you to say yes to Add eggs to the list, and 2 others."), said)
        self.assertNotIn("plan waiting on you, plan waiting on you", said)

    def test_the_repository_alerts_line_agrees_in_number(self):
        with mock.patch("aletheia.core.status_payload", return_value={
                "halted": False, "approvals_pending": [], "tasks": {"live": 0}, "pulse": {"alerts": 2}}), \
             mock.patch("aletheia.quick.doing_words", return_value="Nothing right now."):
            self.assertIn("2 things in your repositories need looking at", voice._status_say())
        with mock.patch("aletheia.core.status_payload", return_value={
                "halted": False, "approvals_pending": [], "tasks": {"live": 0}, "pulse": {"alerts": 1}}), \
             mock.patch("aletheia.quick.doing_words", return_value="Nothing right now."):
            self.assertIn("1 thing in your repositories needs looking at", voice._status_say())


class TheFastLaneGrewSevenAnswers(unittest.TestCase):
    def test_replies_from_employers(self):
        hunt = {"readable": True, "replies": [{"company": "Stripe", "job": "Ops", "outcome": "interview"}]}
        with mock.patch("aletheia.current_state.job_hunt", return_value=hunt):
            self.assertEqual(quick.answer("did i get any replies"), "1 reply today: Stripe (interview).")
        with mock.patch("aletheia.current_state.job_hunt", return_value={"readable": True, "replies": []}):
            self.assertEqual(quick.answer("any replies yet"), "No replies from employers today.")

    def test_why_are_you_slow_says_who_is_thinking(self):
        with mock.patch("aletheia.current_state.brains_words", return_value="Thinking with my own model."):
            self.assertEqual(quick.answer("why are you so slow"), "Thinking with my own model.")

    def test_coming_and_going(self):
        with mock.patch("aletheia.needs_you.items", return_value=[{"what": "x"}, {"what": "y"}]):
            self.assertEqual(quick.answer("i'm home"), "Welcome back. 2 things waiting on you.")
        self.assertEqual(quick.answer("goodnight"), "Goodnight. I'll keep going quietly.")
        self.assertEqual(quick.answer("i'm leaving"), "See you. I'll keep at it while you're out.")

    def test_sums_and_units(self):
        for said, want in (("what's 15 percent of 80", "12."), ("what's 12 times 7", "84."),
                           ("what is 100 divided by 8", "12.5."), ("convert 5 miles to km", "8.05 km."),
                           ("what's 100 f in c", "37.8 degrees Celsius."), ("10 kg in pounds", "22.05 lb.")):
            self.assertEqual(quick.answer(said), want, said)
        self.assertIsNone(quick.answer("convert 5 miles to kg"))      # not the same kind of thing

    def test_a_week_of_calendar(self):
        from aletheia import calendar, localtime
        tz = localtime.operator_tz()
        soon = dt.datetime.now(tz).replace(hour=10, minute=0, second=0, microsecond=0) + dt.timedelta(days=2)
        rows = [{"id": "a", "title": "Dentist", "start": soon.isoformat(),
                 "end": (soon + dt.timedelta(hours=1)).isoformat(), "status": "CONFIRMED"}]
        with mock.patch.object(calendar, "all_events", return_value=rows):
            said = quick.answer("what's on my calendar this week")
        self.assertTrue(said.startswith("This week: Dentist "), said)
        self.assertIn(soon.strftime("%A"), said)


class TheJournalLineIsSayable(unittest.TestCase):
    def test_a_kept_ask_is_said_like_a_person_says_it(self):
        import inspect
        from aletheia import work_engine
        source = inspect.getsource(work_engine.add)
        self.assertIn("kept for later", source)
        self.assertNotIn('f"work filed ({state})', source)


if __name__ == "__main__":
    unittest.main()
