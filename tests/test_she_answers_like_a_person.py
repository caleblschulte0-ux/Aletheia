"""What she says back, judged by whether a person would say it.

Found by actually talking to her through the Core, 2026-09-06. Every one
of these was correct data delivered in a way that fails him:

    "free on 2026-09-07 at 09:00, 09:15, 09:30, 09:45 and more"
    "I can't do room.scene yet; filed 1 build task(s)."
    "1 step ready — free_time. Say approve to run it (intent-0a06bbb663)."

The first one is worse than it looks: he asked about the AFTERNOON, and
the nine o'clock is the qualifier being silently dropped. Answering a
different question than the one asked is the failure he cannot detect.
"""
import datetime as dt
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from aletheia import calendar as cal, intents, intercom, planner, voice

CHICAGO = ZoneInfo("America/Chicago")


class HeSaidAfternoonCase(unittest.TestCase):
    """A part of the day is half of what he asked."""

    def slots(self, day="2026-09-07"):
        return cal.free_slots(dt.date.fromisoformat(day), duration_minutes=30,
                              timezone="America/Chicago", events=[])

    def test_the_qualifier_reaches_the_command(self):
        got = voice.interpret("thea am i free tomorrow afternoon")["command"]
        self.assertEqual(got["kind"], "free_time")
        self.assertEqual(got["part"], "afternoon")

    def test_afternoon_really_filters_the_hours(self):
        kept = cal.in_part(self.slots(), "afternoon")
        self.assertTrue(kept)
        for start, _end in kept:
            self.assertGreaterEqual(dt.datetime.fromisoformat(start).hour, 12)

    def test_no_part_named_means_the_whole_day(self):
        self.assertEqual(len(cal.in_part(self.slots(), "")), len(self.slots()))

    def test_an_unknown_word_does_not_silently_filter_everything(self):
        """Refusing to answer is fine; answering "you're never free" is not."""
        self.assertEqual(len(cal.in_part(self.slots(), "elevenses")),
                         len(self.slots()))

    def test_fifteen_minute_steps_become_stretches_of_time(self):
        merged = cal.merge_slots(self.slots())
        self.assertEqual(len(merged), 1, "an empty day is one free stretch")
        self.assertTrue(merged[0][0].endswith("09:00:00-05:00"))
        self.assertTrue(merged[0][1].endswith("17:00:00-05:00"))

    def test_a_meeting_splits_the_day_into_two_stretches(self):
        booked = [{"version": 1, "id": "e1", "title": "Standup",
                   "start": "2026-09-07T11:00:00-05:00",
                   "end": "2026-09-07T13:00:00-05:00", "status": "CONFIRMED",
                   "attendees": [], "created_at": "2026-09-01T00:00:00Z",
                   "updated_at": "2026-09-01T00:00:00Z"}]
        slots = cal.free_slots(dt.date(2026, 9, 7), duration_minutes=30,
                               timezone="America/Chicago", events=booked)
        self.assertEqual(len(cal.merge_slots(slots)), 2)


class TheSentenceCase(unittest.TestCase):
    """"free on 2026-09-07 at 09:00, 09:15, 09:30, 09:45 and more"."""

    def sentence(self, ranges, part="", day=dt.date(2026, 9, 7)):
        with mock.patch("aletheia.localtime.operator_tz", lambda: CHICAGO), \
             mock.patch("aletheia.speech.humanize_time",
                        lambda stamp, now=None: "tomorrow at 12 pm"):
            return intercom._free_sentence(ranges, day, part)

    def test_it_reads_as_a_stretch_of_time(self):
        said = self.sentence([("2026-09-07T12:00:00-05:00",
                               "2026-09-07T17:00:00-05:00")], "afternoon")
        self.assertEqual(said, "Free tomorrow afternoon 12 pm to 5 pm.")

    def test_no_machine_dates_and_no_machine_clocks(self):
        said = self.sentence([("2026-09-07T09:00:00-05:00",
                               "2026-09-07T17:00:00-05:00")])
        self.assertNotIn("2026-09-07", said)
        self.assertNotIn("09:00", said)

    def test_two_stretches_are_joined_the_way_a_person_joins_them(self):
        said = self.sentence([("2026-09-07T09:00:00-05:00",
                               "2026-09-07T11:00:00-05:00"),
                              ("2026-09-07T13:00:00-05:00",
                               "2026-09-07T17:00:00-05:00")])
        self.assertIn("9 am to 11 am and 1 pm to 5 pm", said)

    def test_an_empty_evening_says_why_it_is_empty(self):
        """"Nothing free this evening" alone is misleading — she only ever
        looks at working hours, so of course the evening is empty."""
        said = self.sentence([], "evening")
        self.assertIn("nine to five", said)

    def test_an_empty_afternoon_does_not_blame_the_work_window(self):
        said = self.sentence([], "afternoon")
        self.assertNotIn("nine to five", said)

    def test_today_takes_this_not_today(self):
        with mock.patch("aletheia.speech.humanize_time",
                        lambda stamp, now=None: "today at 12 pm"):
            said = intercom._free_sentence(
                [("2026-09-06T13:00:00-05:00", "2026-09-06T17:00:00-05:00")],
                dt.date(2026, 9, 6), "afternoon")
        self.assertIn("this afternoon", said)
        self.assertNotIn("today afternoon", said)


class NamingDaysCase(unittest.TestCase):
    def test_a_weekday_is_a_day(self):
        """Every weekday name used to come back "I couldn't parse the day"."""
        got = voice._spoken_day("friday")
        self.assertIsNotNone(got)
        self.assertEqual(dt.date.fromisoformat(got).strftime("%A"), "Friday")
        self.assertGreaterEqual(dt.date.fromisoformat(got), dt.date.today())

    def test_this_friday_is_the_same_friday(self):
        self.assertEqual(voice._spoken_day("this friday"),
                         voice._spoken_day("friday"))

    def test_next_friday_is_asked_about_rather_than_guessed(self):
        """It means the coming Friday to half the people who say it and the
        one after to the other half. Picking silently is how she confirms
        the wrong thing confidently."""
        said = voice.interpret("thea am i free next friday")
        self.assertIsNone(said["command"])
        self.assertIn("Which Friday", said["say"])
        self.assertRegex(said["say"], r"\d+(st|nd|rd|th)")

    def test_ordinals_are_sayable(self):
        self.assertEqual(
            [voice._ordinal(d) for d in (1, 2, 3, 11, 12, 13, 21, 22, 23)],
            ["1st", "2nd", "3rd", "11th", "12th", "13th", "21st", "22nd", "23rd"])

    def test_asking_is_instant_and_never_reaches_the_planner(self):
        """It fell through to the planner before — six and a half seconds
        for a question she can answer from a date and a calendar file."""
        self.assertIsNotNone(voice.interpret("thea am i free tomorrow")["command"])
        self.assertIsNotNone(
            voice.interpret("thea do i have time this afternoon")["command"])


class NotYetCase(unittest.TestCase):
    """"I can't do room.scene yet; filed 1 build task(s)." """

    def test_a_capability_id_is_never_spoken(self):
        said = intents._cannot_yet([{"capability": "room.scene"}],
                                   {"gap_tasks": ["t1"]})
        self.assertNotIn("room.scene", said)
        self.assertNotIn("(s)", said)

    def test_something_waiting_on_him_gives_him_the_command(self):
        said = intents._cannot_yet([{"capability": "room.scene"}], {})
        self.assertIn("python -m aletheia.apply room", said)
        self.assertIn("needs setting up", said)

    def test_something_that_does_not_exist_says_so_instead(self):
        """A hub he has not connected and a capability nobody has written
        are different answers. They used to be the same sentence."""
        said = intents._cannot_yet([{"capability": "message.send"}],
                                   {"gap_tasks": ["t1"]})
        self.assertIn("text message", said)
        self.assertIn("build list", said)
        self.assertNotIn("needs setting up", said)

    def test_the_registry_supplies_the_english(self):
        self.assertIn("text message", intents._in_english("message.send"))
        self.assertNotIn("message.send", intents._in_english("message.send"))

    def test_an_unknown_capability_still_produces_a_sentence(self):
        said = intents._in_english("nothing.at-all")
        self.assertTrue(said.strip())

    def test_a_broken_registry_does_not_break_her_mouth(self):
        with mock.patch("aletheia.capabilities.get",
                        side_effect=RuntimeError("registry gone")):
            said = intents._cannot_yet([{"capability": "message.send"}], {})
        self.assertTrue(said.strip())


class TheApprovalIdCase(unittest.TestCase):
    def test_the_hex_id_is_not_read_out_loud(self):
        """§145: he approves by saying "approve". A hash is a handle he
        cannot hold in his head, and the sentence told him to say it back."""
        record = {
            "steps": [{"n": 1, "status": planner.EXECUTABLE,
                       "capability": "email.send",
                       "command": {"kind": "email_draft"}, "detail": ""}],
            "approval": "intent-0a06bbb663", "intent": "plan",
        }
        said = intents.spoken(record)
        self.assertNotIn("0a06bbb663", said)
        self.assertIn("Say approve", said)


if __name__ == "__main__":
    unittest.main()
