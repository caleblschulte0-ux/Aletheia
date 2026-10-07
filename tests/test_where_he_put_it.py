"""Sweep 24 (2026-10-07): where he put things, alarms said every way, a
weekend reminder, a need said as a task, and a reminder before an event."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import intercom, quick, voice


class WhereHePutIt(unittest.TestCase):
    def test_putting_it_somewhere_is_a_note(self):
        self.assertEqual(voice._interpret("i put my keys in the drawer")["command"],
                         {"kind": "note", "text": "i put my keys in the drawer"})
        self.assertEqual(voice._interpret("my passport is in the safe")["command"]["kind"], "note")

    def test_the_note_answers_where(self):
        notes = [{"text": "I put my keys in the drawer", "ts": "2026-10-07T01:00:00Z"}]
        with mock.patch.object(quick, "_notes", return_value=notes):
            self.assertEqual(voice._interpret("where are my keys")["say"],
                             "You put your keys in the drawer.")

    def test_no_note_is_still_the_honest_no_eyes(self):
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIn("no eyes in the room", voice._interpret("where are my keys")["say"])


class AlarmsEveryWay(unittest.TestCase):
    def test_every_weekday_first(self):
        self.assertEqual(voice._interpret("set an alarm for every weekday at 6")["command"],
                         {"kind": "remind_weekly", "days": ["weekdays"], "time": "06:00", "text": "wake up"})

    def test_a_nap(self):
        got = voice._interpret("wake me up in 20 minutes")["command"]
        at = dt.datetime.fromisoformat(got["at"])
        self.assertEqual((got["text"], round((at - dt.datetime.now(dt.timezone.utc)).total_seconds() / 60)),
                         ("wake up", 20))

    def test_how_long_until_it(self):
        self.assertEqual(quick.match("how long until my alarm")[0], "alarm_left")
        self.assertEqual(quick.match("how long until christmas")[0], "until")
        soon = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=7, minutes=30)
        with mock.patch.object(quick, "_coming", return_value=[(soon, "wake up", "reminder")]):
            self.assertIn("7 hours and 30 minutes from now", quick.answer("how long until my alarm"))


class AWeekendAndANeed(unittest.TestCase):
    def test_this_weekend_is_saturday_morning(self):
        got = voice._interpret("remind me this weekend to clean the garage")["command"]
        self.assertEqual(got["text"], "clean the garage")
        self.assertIn(dt.datetime.fromisoformat(got["at"]).weekday(), (5, 6))

    def test_a_need_is_a_task(self):
        got = voice._interpret("i need to call the bank tomorrow")["command"]
        self.assertEqual((got["kind"], got["description"]), ("task_new", "call the bank"))
        self.assertIn("deadline", got)
        self.assertEqual(voice._interpret("don't let me forget to pay rent")["command"]["description"], "pay rent")

    def test_a_need_with_a_clock_time_is_a_reminder(self):
        self.assertEqual(voice._interpret("i have to pick up the kids at 3")["command"]["kind"], "remind_at")

    def test_not_every_need_is_a_task(self):
        self.assertEqual(voice._interpret("i need to know the time")["command"]["kind"], "intent")


class BeforeTheEvent(unittest.TestCase):
    def test_the_other_order(self):
        from aletheia import calendar as cal
        start = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)
        events = [{"title": "Dentist", "start": start.isoformat(), "end": start.isoformat(), "status": "CONFIRMED"}]
        with mock.patch.object(cal, "all_events", return_value=events):
            got = voice._interpret("remind me about the meeting 10 minutes before")["command"]
        self.assertEqual(got["text"], "Dentist in 10 minutes")
        self.assertEqual(dt.datetime.fromisoformat(got["at"]), start - dt.timedelta(minutes=10))


class SmallerReads(unittest.TestCase):
    def test_do_i_need_milk_only_answers_yes(self):
        with mock.patch.object(intercom, "_shopping_items", return_value=[{"need": "milk"}]):
            self.assertEqual(quick.answer("do i need milk"), "Yes - milk is on your shopping list.")
            self.assertIsNone(quick.answer("do i need a visa"))

    def test_his_last_note(self):
        with mock.patch.object(quick, "_notes", return_value=[{"text": "my gate code is 4321"}]):
            self.assertEqual(quick.answer("what's my last note"), "Your last note: your gate code is 4321.")
        self.assertEqual(voice._interpret("read me my latest note")["command"]["kind"], "intent")


class HisAlarmAskedEveryWay(unittest.TestCase):
    def test_the_phrasings_reach_the_alarm_reader(self):
        for said in ("when does my alarm go off", "is my alarm set", "what's my alarm set for"):
            self.assertEqual(quick.match(said)[0], "alarm_q", said)


class SaidToHerAndAboutHer(unittest.TestCase):
    def test_shut_up_quiets_her_notices(self):
        for said in ("shut up", "be quiet", "stop talking"):
            self.assertEqual(voice._interpret(said)["command"], {"kind": "notify_snooze", "minutes": 60}, said)
        self.assertEqual(voice._interpret("stop talking unless i ask")["command"]["kind"], "announce_set")

    def test_not_what_i_meant(self):
        self.assertIn("what I got wrong", voice._interpret("no that's not what i meant")["say"])

    def test_she_is_not_chatgpt_and_says_who_she_asks(self):
        said = quick.answer("are you chatgpt")
        self.assertTrue(said.startswith("No - I'm Thea"))
        self.assertIn("Claude or ChatGPT", said)
        self.assertIsNotNone(quick.answer("how smart are you"))


class ClockArithmetic(unittest.TestCase):
    def test_until_a_clock_time(self):
        self.assertEqual(quick.match("how long until 5pm")[0], "clock_until")
        self.assertEqual(quick.match("how many hours until midnight")[0], "clock_until")
        self.assertEqual(quick.match("how long until christmas")[0], "until")
        self.assertRegex(quick.answer("how long until midnight"), r"until midnight\.$")

    def test_his_zone_and_the_clock_change(self):
        said = quick.answer("what time zone am i in")
        self.assertRegex(said, r"^You're on \w+ time")
        self.assertEqual(quick.match("is it daylight saving time")[0], "time_zone")

    def test_clearing_his_calendar_is_said_plainly(self):
        self.assertIn("can't cancel things on your calendar", voice._interpret("clear my calendar tomorrow")["say"])


class WhatIsAhead(unittest.TestCase):
    def setUp(self):
        from aletheia import localtime
        tz = localtime.operator_tz()
        now = dt.datetime.now(tz)
        tomorrow = (now + dt.timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        self.rows = [(tomorrow, "Standup", "calendar"), (tomorrow.replace(hour=8), "take my pills", "reminder")]
        self.rows.sort(key=lambda r: r[0])

    def test_coming_up_lists_both_stores(self):
        with mock.patch.object(quick, "_coming", return_value=self.rows):
            said = quick.answer("what's coming up")
        self.assertIn("reminder: take my pills", said)
        self.assertIn("Standup", said)

    def test_meetings_tomorrow_counts_only_meetings(self):
        with mock.patch.object(quick, "_coming", return_value=self.rows):
            self.assertEqual(quick.answer("how many meetings do i have tomorrow"), "1 meeting tomorrow: 10 am, Standup.")

    def test_is_a_day_free(self):
        self.assertEqual(voice._interpret("is friday free")["command"]["kind"], "free_time")

    def test_a_title_keeps_no_next(self):
        self.assertEqual(voice._interpret("schedule lunch with sam next tuesday at noon")["command"]["title"],
                         "lunch with sam")

    def test_due_and_overdue_asked_about_tasks(self):
        self.assertEqual(quick.match("what tasks are due this week"), ("due", "this week"))
        self.assertEqual(quick.match("show me my overdue tasks"), ("due", "overdue"))

    def test_his_whole_list_is_not_one_sentence(self):
        for said in ("delete all my tasks", "mark everything done", "clear my to do list"):
            self.assertIn("one at a time", voice._interpret(said)["say"], said)


class PeopleHeKnows(unittest.TestCase):
    CARD = {"version": 1, "id": "dana", "display_name": "Dana", "phones": ["6055551234"], "emails": [],
            "aliases": [], "organizations": [], "tags": [], "provenance": "x",
            "created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-10-01T00:00:00Z"}

    def test_who_someone_is_is_a_note(self):
        self.assertEqual(voice._interpret("dana is my sister")["command"]["kind"], "note")
        self.assertEqual(voice._interpret("this is my house")["command"]["kind"], "intent")

    def test_who_is_dana_reads_the_card_and_the_note(self):
        from aletheia import contacts
        with mock.patch.object(contacts, "all_contacts", return_value=[self.CARD]), \
                mock.patch.object(quick, "_notes", return_value=[{"text": "Dana is my sister"}]):
            self.assertEqual(quick.answer("who is dana"),
                             "In your contacts: Dana — 605 555 1234. You told me: Dana is your sister.")
            self.assertEqual(quick.answer("who is my sister"), "Your sister is Dana.")

    def test_someone_she_does_not_know_goes_on(self):
        from aletheia import contacts
        with mock.patch.object(contacts, "all_contacts", return_value=[]), \
                mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIsNone(quick.answer("who is taylor swift"))

    def test_a_changed_number_updates_the_card(self):
        self.assertEqual(voice._interpret("change dana's number to 605 555 9999")["command"],
                         {"kind": "contact_add", "name": "Dana", "phone": "605 555 9999"})

    def test_email_with_nothing_to_say_asks(self):
        self.assertIn("What should it say?", voice._interpret("email dana")["say"])

    def test_mail_from_someone(self):
        self.assertEqual(voice._interpret("any new emails from stripe")["command"], {"kind": "email_read", "which": "stripe"})
        self.assertEqual(voice._interpret("did anyone email me")["command"], {"kind": "email_check"})

    def test_weather_at_his_house_is_his_weather(self):
        self.assertEqual(quick.match("what's the weather at my house")[0], "weather")


class ATimerWithAName(unittest.TestCase):
    def test_a_name_and_no_length_asks_how_long(self):
        got = voice._interpret("set a timer for the pasta")
        self.assertIsNone(got["command"])
        self.assertIn("How long for the pasta?", got["say"])

    def test_a_name_and_a_length_is_its_name_at_the_end(self):
        text = voice._interpret("set a timer for 10 minutes for the eggs")["command"]["text"]
        self.assertEqual(text, "your 10 minute eggs timer is up")

    def test_a_named_timer_is_still_read_back_as_a_timer(self):
        soon = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=9, seconds=30)).isoformat()
        spec = {"kind": "once", "at": soon, "command": {"text": "your 10 minute eggs timer is up"}}
        with mock.patch.object(intercom, "_reminder_schedules", return_value=[spec]):
            self.assertEqual(voice._timer_left(), "9 minutes left on the eggs timer.")

    def test_a_length_alone_is_still_a_timer(self):
        self.assertEqual(voice._interpret("set a timer for ten minutes")["command"]["kind"], "remind_at")


class TheWeekendAndBirthdays(unittest.TestCase):
    def test_the_weekend_is_saturday_and_sunday(self):
        from aletheia import calendar, localtime
        tz = localtime.operator_tz()
        today = dt.datetime.now(tz).date()
        sat = today + dt.timedelta(days=(5 - today.weekday()) % 7)
        event = {"title": "Brunch", "start": dt.datetime.combine(sat, dt.time(11), tzinfo=tz).isoformat()}
        self.assertEqual(quick.match("what's on my calendar this weekend")[0], "agenda")
        self.assertEqual(quick.match("anything happening this weekend")[0], "agenda")
        if today.weekday() != 6:
            with mock.patch.object(calendar, "all_events", return_value=[event]):
                self.assertIn("Brunch", quick.answer("what's on my calendar this weekend"))

    def test_somebody_elses_birthday_asked_with_what(self):
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertEqual(quick.answer("what's dana's birthday"),
                             "You haven't told me Dana's birthday. Tell me once and I'll remember it.")
            self.assertIn("your mom's birthday", quick.answer("when is my mom's birthday"))

    def test_a_birthday_he_told_her_is_read_back(self):
        with mock.patch.object(quick, "_notes", return_value=[{"text": "Dana's birthday is March 3"}]):
            self.assertEqual(quick.answer("what's dana's birthday"), "You told me: Dana's birthday is March 3.")

    def test_his_anniversary_asked_with_when(self):
        self.assertEqual(quick.match("when's my anniversary")[0], "fact_q")
