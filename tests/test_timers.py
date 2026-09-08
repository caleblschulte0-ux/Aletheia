"""A timer needed no new machinery, only a sentence.

`timer.set` was registered NOT_BUILT this morning because "set a timer
for ten minutes" reached nothing. Then: what IS a timer? A one-shot
alert at a moment — which is exactly `remind_at`, a `once` schedule the
Core fires on its beat and speaks. "Remind me in 10 minutes to check the
oven" had worked for weeks.

The difference between a missing CAPABILITY and a missing PATTERN is
worth telling apart before building a subsystem for something that
already exists.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import cannot, capabilities, places, voice


class TimersCase(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(places, "resolve", side_effect=KeyError("none"))
        p.start()
        self.addCleanup(p.stop)

    def command(self, said):
        return (voice.interpret(said) or {}).get("command") or {}


class ATimerIsAOneShotAlertCase(TimersCase):
    def test_minutes_seconds_and_hours_all_land_in_the_future(self):
        now = dt.datetime.now(dt.timezone.utc)
        for said, seconds in (("set a timer for 30 seconds", 30),
                              ("set a timer for 10 minutes", 600),
                              ("start a timer for 1 hour", 3600)):
            with self.subTest(said=said):
                got = self.command(said)
                self.assertEqual(got["kind"], "remind_at")
                at = dt.datetime.fromisoformat(got["at"])
                gap = (at - now).total_seconds()
                self.assertAlmostEqual(gap, seconds, delta=5)

    def test_the_unit_is_singular_because_it_is_an_adjective(self):
        """"Your 10 minutes timer is up" is not English, and this is read
        out loud."""
        self.assertEqual(self.command("set a timer for 10 minutes")["text"],
                         "your 10 minute timer is up")
        self.assertEqual(self.command("set a timer for 1 minute")["text"],
                         "your 1 minute timer is up")
        self.assertEqual(self.command("set a timer for 30 seconds")["text"],
                         "your 30 second timer is up")

    def test_a_reason_he_gives_is_what_she_says(self):
        got = self.command("set a timer for 5 minutes to check the oven")
        self.assertEqual(got["text"], "check the oven")

    def test_a_timer_with_no_duration_goes_to_the_planner(self):
        """"Set a timer" is a question, not an instruction."""
        self.assertEqual(self.command("set a timer").get("kind"), "intent")


class AnAlarmIsTheSameThingAtAClockTimeCase(TimersCase):
    def test_an_alarm_reaches_the_same_durable_schedule(self):
        for said in ("set an alarm for 7", "wake me up at 6:30"):
            with self.subTest(said=said):
                got = self.command(said)
                self.assertEqual(got["kind"], "remind_at")
                self.assertTrue(got["at"])

    def test_a_bare_hour_is_never_three_in_the_morning(self):
        """The rule this file already learned the hard way: "at 7" means
        the next sensible 7, not 07:00 whatever the clock says."""
        got = self.command("set an alarm for 7")
        at = dt.datetime.fromisoformat(got["at"])
        self.assertGreater(at, dt.datetime.now(at.tzinfo))

    def test_an_unparseable_time_is_not_guessed(self):
        self.assertEqual(self.command("set an alarm for sometime").get("kind"),
                         "intent")


class TheRefusalRetiresItselfCase(TimersCase):
    def test_cannot_stops_refusing_the_day_it_is_built(self):
        """`cannot` reads the registry rather than a hard-coded list, so
        promoting the capability is all it takes. A refusal frozen in
        code would still be refusing."""
        self.assertEqual(capabilities.get("timer.set")["status"], "AVAILABLE")
        self.assertIsNone(cannot.answer("set a timer for 10 minutes"))

    def test_and_would_start_again_if_it_were_withdrawn(self):
        entry = dict(capabilities.get("timer.set"))
        entry["status"] = "NOT_BUILT"
        with mock.patch.object(capabilities, "get", return_value=entry):
            self.assertIn("timers", cannot.answer("set a timer for 10 minutes"))


if __name__ == "__main__":
    unittest.main()
