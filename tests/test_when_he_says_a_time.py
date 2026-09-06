"""Nobody means three in the morning.

Found by actually talking to her, 2026-09-06. "Thea, remind me at 3 to
call the dentist", said at 08:46, was scheduled for **03:00 tomorrow** —
eighteen hours late and in the middle of the night — and confirmed back
as "I'll remind you tomorrow at 8 am".

Two separate defects, and the second one hid the first:

1. A bare hour was read literally. "At 3" means 15:00 to every person who
   has ever said it before dinner, and 03:00 to nobody.
2. The spoken confirmation rendered the instant in the PROCESS's
   timezone rather than his, so 03:00 America/Chicago came back as "8
   am". The confirmation exists precisely so he can catch a mistake in
   one syllable; in the wrong zone it cannot do that job, and here it
   actively disguised an 18-hour error as a plausible-sounding time.

Both of these are the failure that costs trust fastest: not refusing, not
erroring — confidently agreeing to the wrong thing.
"""
import datetime as dt
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from aletheia import localtime, speech, voice

CHICAGO = ZoneInfo("America/Chicago")


def at_local(hour, minute=0, day=6):
    return dt.datetime(2026, 9, day, hour, minute, tzinfo=CHICAGO)


def when(said, now):
    """What she would schedule for `said`, spoken at `now`."""
    hhmm = voice._spoken_time(said)
    assert hhmm, f"{said!r} did not parse as a time at all"
    return dt.datetime.fromisoformat(voice._next_occurrence_iso(
        hhmm, bare_hour=voice._is_bare_hour(said), now=now))


class ABareHourCase(unittest.TestCase):
    """An hour with no am/pm is the commonest way a person says a time."""

    def setUp(self):
        p = mock.patch.object(localtime, "operator_tz", lambda: CHICAGO)
        p.start(); self.addCleanup(p.stop)

    def test_at_three_in_the_morning_means_this_afternoon(self):
        """The original bug, exactly as he said it."""
        got = when("3", at_local(8, 46))
        self.assertEqual((got.hour, got.day), (15, 6))

    def test_at_three_in_the_afternoon_means_tomorrow_afternoon(self):
        """Not tomorrow before dawn, which is the literal next 3 o'clock."""
        got = when("3", at_local(16, 0))
        self.assertEqual((got.hour, got.day), (15, 7))

    def test_an_hour_still_to_come_today_is_today(self):
        got = when("11", at_local(8, 46))
        self.assertEqual((got.hour, got.day), (11, 6))

    def test_eleven_said_at_lunchtime_is_tonight(self):
        got = when("11", at_local(12, 30))
        self.assertEqual((got.hour, got.day), (23, 6))

    def test_saying_am_still_means_am(self):
        """The rule may never override him. He said three in the morning."""
        got = when("3 am", at_local(8, 46))
        self.assertEqual((got.hour, got.day), (3, 7))

    def test_saying_pm_still_means_pm(self):
        got = when("3 pm", at_local(8, 46))
        self.assertEqual((got.hour, got.day), (15, 6))

    def test_a_bare_hour_never_lands_in_the_small_hours(self):
        """The property that matters, over every hour and every time of day."""
        for said_hour in range(1, 13):
            for now_hour in range(0, 24):
                got = when(str(said_hour), at_local(now_hour, 30))
                with self.subTest(said=said_hour, now=now_hour):
                    self.assertGreaterEqual(
                        got.hour, voice.EARLIEST_BARE_HOUR,
                        f'"at {said_hour}" said at {now_hour}:30 -> {got}')

    def test_it_is_always_in_the_future(self):
        for said_hour in range(1, 13):
            for now_hour in range(0, 24):
                now = at_local(now_hour, 30)
                with self.subTest(said=said_hour, now=now_hour):
                    self.assertGreater(when(str(said_hour), now), now)

    def test_twelve_and_twenty_four_hour_hours_are_not_doubled(self):
        """Only 1-11 are ambiguous. 12 and 13-23 said what they meant."""
        self.assertTrue(voice._is_bare_hour("15"))
        got = when("15", at_local(8, 0))
        self.assertEqual((got.hour, got.day), (15, 6))
        got = when("12", at_local(8, 0))
        self.assertEqual((got.hour, got.day), (12, 6))


class TheConfirmationIsInHisTimezoneCase(unittest.TestCase):
    """A confirmation he cannot trust is worse than none: it disguised an
    eighteen-hour error as a plausible time."""

    def test_the_hour_is_read_back_in_his_zone_not_the_machines(self):
        with mock.patch.object(localtime, "operator_tz", lambda: CHICAGO):
            said = speech.humanize_time(
                "2026-09-07T03:00:00-05:00",
                now=dt.datetime(2026, 9, 6, 20, 0, tzinfo=dt.timezone.utc))
        self.assertIn("3 am", said)
        self.assertIn("tomorrow", said)
        self.assertNotIn("8 am", said)

    def test_a_utc_stamp_is_spoken_as_his_local_time(self):
        with mock.patch.object(localtime, "operator_tz", lambda: CHICAGO):
            said = speech.humanize_time(
                "2026-09-06T20:00:00Z",
                now=dt.datetime(2026, 9, 6, 14, 0, tzinfo=dt.timezone.utc))
        self.assertIn("3 pm", said)

    def test_today_and_tomorrow_are_counted_in_his_days_too(self):
        """22:30 in Chicago is 03:30 UTC the NEXT DAY. Comparing a local
        instant against a UTC 'now' makes tonight sound like tomorrow."""
        with mock.patch.object(localtime, "operator_tz", lambda: CHICAGO):
            said = speech.humanize_time(
                "2026-09-06T22:30:00-05:00",
                now=dt.datetime(2026, 9, 7, 0, 30, tzinfo=dt.timezone.utc))
        self.assertIn("today", said)

    def test_a_broken_timezone_database_does_not_break_the_sentence(self):
        """This is the last step before something is spoken out loud."""
        def boom():
            raise RuntimeError("no tzdata")
        with mock.patch.object(localtime, "operator_tz", boom):
            said = speech.humanize_time("2026-09-07T03:00:00-05:00")
        self.assertTrue(said.strip())
        self.assertNotIn("Error", said)


class EndToEndCase(unittest.TestCase):
    """What he actually says, through the actual voice interpreter."""

    def setUp(self):
        p = mock.patch.object(localtime, "operator_tz", lambda: CHICAGO)
        p.start(); self.addCleanup(p.stop)

    def test_the_sentence_he_said_produces_an_afternoon_reminder(self):
        intent = voice.interpret("thea remind me at 3 to call the dentist")
        self.assertEqual(intent["command"]["kind"], "remind_at")
        got = dt.datetime.fromisoformat(intent["command"]["at"])
        self.assertEqual(got.astimezone(CHICAGO).hour, 15)
        self.assertEqual(intent["command"]["text"], "call the dentist")

    def test_an_unparseable_time_is_refused_rather_than_guessed(self):
        intent = voice.interpret("thea remind me at half past sevenish to go")
        self.assertIsNone(intent["command"])
        self.assertIn("couldn't parse", intent["say"])


if __name__ == "__main__":
    unittest.main()
