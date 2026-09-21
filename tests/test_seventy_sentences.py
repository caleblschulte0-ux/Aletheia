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
                           ("what is 100 divided by 8", "12.5."), ("convert 5 miles to km", "About 8.05 kilometers."),
                           ("what's 100 f in c", "37.8 degrees Celsius."), ("10 kg in pounds", "About 22.05 pounds."),
                           ("how many miles is 10 km", "About 6.21 miles."),
                           ("how many inches is 1 foot", "12 inches."),
                           ("how many feet in a meter", "About 3.28 feet.")):
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
        """The line is what a person says: the ask in his words, kept for
        later, and why - not "work filed (BLOCKED_MODEL): Plan and do:"."""
        import tempfile
        from pathlib import Path
        from aletheia import journal, work_engine, work_states
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "journal.jsonl"
            with mock.patch.object(journal, "JOURNAL_PATH", log):
                work_engine.add("Plan and do: read me my resume", state=work_states.BLOCKED_MODEL,
                                requires=("frontier_reasoning",), reason="no model",
                                next="when a model is back", key="test:kept-line:read me my resume",
                                payload={"request": "read me my resume"})
                lines = [e["text"] for e in journal.since(1, log) if e.get("actor") == work_engine.ACTOR]
        self.assertEqual(lines, ["kept \u201cread me my resume\u201d for later, until a model is back"])



class TheSecondProbe(unittest.TestCase):
    """Thirty-seven more sentences through the sandbox door with no model
    reachable, and what each one needed. A shape that only takes a digit,
    a fact she cannot store, a refusal swallowed into "I can't think",
    and a brains line that called an absent model present."""

    def test_a_reminder_in_a_spoken_number_of_minutes(self):
        from aletheia import voice
        for said in ("remind me in twenty minutes to check the oven",
                     "remind me in 20 minutes to check the oven",
                     "remind me in an hour to check the oven"):
            command = voice.interpret(f"thea {said}")["command"]
            self.assertEqual(command["kind"], "remind_at", said)
            self.assertEqual(command["text"], "check the oven", said)

    def test_remember_is_compiled_with_no_model(self):
        from aletheia import rule_planner
        for said, domain, key, value in (
                ("remember my landlord is Dana Whitfield", "people", "landlord", "Dana Whitfield"),
                ("remember that my sister's name is Mia", "people", "sister", "Mia"),
                ("keep in mind my dentist is Dr Okafor", "people", "dentist", "Dr Okafor"),
                ("remember the wifi password is hunter2", "preferences", "wifi password", "hunter2"),
                ("remember my company is Barkly", "organizations", "company", "Barkly")):
            kind, args, _summary = rule_planner.match(said)
            self.assertEqual(kind, "remember", said)
            self.assertEqual(args, {"domain": domain, "key": key, "value": value}, said)
        # A question is never an instruction, and a "remember" with no fact is not one either.
        self.assertIsNone(rule_planner.match("remember to call the dentist"))

    def test_what_he_remembered_is_recalled_by_what_he_calls_it(self):
        import tempfile
        from pathlib import Path
        from aletheia import intercom, memory
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(memory, "MEMORY_DIR", Path(tmp)):
                intercom.execute_command({"kind": "remember", "domain": "people", "key": "landlord",
                                          "value": "Dana Whitfield"}, {"repos": {}}, quote="test")
                said = intercom.execute_command({"kind": "recall", "about": "landlord's name"},
                                                {"repos": {}}, quote="test")
        self.assertIn("Dana Whitfield", said)

    def test_a_refusal_from_a_read_rule_is_the_answer(self):
        """"How far is the airport" with no address on file: the refusal
        says what she needs, and that IS the answer - not "I can't think"."""
        from aletheia import act, intents
        with mock.patch("aletheia.intercom.execute_command",
                        side_effect=act.Refused("I don't know where the airport is. Tell me the address once.")):
            said = intents._answer_by_rules("how far is the airport", {"repos": {}})
        self.assertIn("I don't know where the airport is", said)

    def test_the_weather_says_what_it_needs_instead_of_thinking(self):
        from aletheia import quick, weather
        for said in ("what's the weather like", "what's it like outside", "how's it looking out",
                     "what's the weather like today"):
            self.assertEqual(quick.match(said)[0], "weather", said)
        with mock.patch.object(weather, "spoken", side_effect=weather.WeatherUnavailable(
                "I don't know where you are. Tell me your postcode and I'll remember it.")):
            self.assertIn("postcode", quick._weather(""))
        with mock.patch.object(weather, "spoken", side_effect=KeyError("bug")):
            self.assertIsNone(quick._weather(""))

    def test_the_week_in_more_words(self):
        from aletheia import quick
        for said in ("what's on this week", "anything on this week", "what's my week looking like",
                     "what have i got on next week", "what's on today"):
            self.assertEqual(quick.match(said)[0], "agenda", said)
        self.assertIn("this week", quick.answer("what's my week looking like").lower())

    def test_the_brains_line_does_not_claim_a_model_that_is_not_there(self):
        from aletheia import current_state
        minds = {"claude": {"resting_until": None, "installed": False},
                 "codex": {"resting_until": None, "installed": False},
                 "local": {"allowed": False, "why": "local reasoning is switched off"}}
        said = current_state.brains_words(minds)
        self.assertNotIn("Thinking with the big models", said)
        self.assertIn("aren't signed in", said)
        minds["local"] = {"allowed": True, "why": "", "recent": {}, "busy": None}
        self.assertIn("my own model", current_state.brains_words(minds))
        # An older snapshot without the flag reads as before.
        minds["claude"] = {"resting_until": None}
        self.assertIn("Thinking with the big models", current_state.brains_words(minds))

    def test_a_fact_on_disk_settles_the_ask_with_no_model(self):
        """No resume on the PC, no number for his sister: the rule already
        has the sentence, so nothing is kept for a model to plan and her
        own model is not asked about a resume it has never seen."""
        from aletheia import applications, intents, messages, rule_planner
        with mock.patch.object(applications, "find_resume", side_effect=applications.ApplicationError("none")):
            kind, args, _ = rule_planner.match("read me my resume")
            self.assertEqual(kind, rule_planner.ANSWER)
            self.assertIn("can't find a resume", args["say"])
            self.assertEqual(rule_planner.compile("read me my resume")["intent"], "answer")
            self.assertIn("can't find a resume", intents._answer_by_rules("read me my resume", {"repos": {}}))
        with mock.patch.object(applications, "find_resume", return_value="/docs/resume.pdf"):
            kind, args, _ = rule_planner.match("read me my resume")
            self.assertEqual((kind, args["path"]), ("file_read", "/docs/resume.pdf"))
        with mock.patch.object(messages, "resolve_number", return_value=(None, "your sister")):
            kind, args, _ = rule_planner.match("text my sister i'm running late")
            self.assertEqual(kind, rule_planner.ANSWER)
            self.assertIn("phone number for your sister", args["say"])
        with mock.patch.object(messages, "resolve_number", return_value=("+15551234567", "Dana")):
            kind, args, summary = rule_planner.match("text Dana that I'm on my way")
            self.assertEqual((kind, args), ("message_send", {"to": "Dana", "body": "I'm on my way"}))
            self.assertEqual(summary, "Text Dana: I'm on my way")

    def test_the_mail_variables_are_for_the_screen_and_not_the_room(self):
        from aletheia import speech
        line = ("mail isn't set up yet. It needs your email address and an app password once, "
                "on the PC (ALETHEIA_MAIL_ADDRESS and ALETHEIA_MAIL_PASSWORD), and it works from the next ask.")
        said = speech.for_the_room(line)
        self.assertNotIn("ALETHEIA", said)
        self.assertIn("on the PC, and it works", said)


if __name__ == "__main__":
    unittest.main()
