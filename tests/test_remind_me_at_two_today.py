""""Remind me at 2 today", said at 3, was quietly tomorrow, and "pick up the
kids at 3 today" said at 3:15 was set for a time already gone (2026-10-14).
He said today: she says it has passed."""
import datetime as dt
import unittest

from aletheia import localtime, voice


def _clock(at):
    return at.strftime("%I:%M %p").lstrip("0").lower()


class AlreadyGone(unittest.TestCase):
    def setUp(self):
        now = dt.datetime.now(localtime.operator_tz())
        if now.hour < 2:
            self.skipTest("needs an hour already gone today")
        self.gone = now.replace(minute=0, second=0, microsecond=0) - dt.timedelta(hours=1)

    def test_said_today_is_said_back(self):
        clock = _clock(self.gone)
        for said in (f"remind me at {clock} today to call bob", f"remind me to call bob at {clock} today",
                     f"i need to pick up the kids at {clock} today"):
            out = voice._interpret(said)
            self.assertIsNone(out["command"], said)
            self.assertTrue(out["say"].startswith("It's already past "), said)

    def test_no_day_said_is_still_the_next_one(self):
        out = voice._interpret(f"remind me at {_clock(self.gone)} to call bob")
        self.assertEqual(out["command"]["kind"], "remind_at")
        self.assertGreater(dt.datetime.fromisoformat(out["command"]["at"]), dt.datetime.now(localtime.operator_tz()))


if __name__ == "__main__":
    unittest.main()
