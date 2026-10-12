""""Remind me to take my medicine every day at 8am and 8pm" (2026-10-12).

"When's my medicine reminder" and "skip tonight's medicine reminder" both
asked "Which one?", and "what time are my medicine reminders" went to a model.
Asking when, both times are the answer; skipping tonight's, the one going off
tonight is the one.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import intercom, localtime, quick, scheduler


def daily(rid, hour):
    return {"id": rid, "kind": "daily", "time": f"{hour:02d}:00", "enabled": True, "created_at": rid,
            "command": {"kind": "notify", "text": "take my medicine"}}


ROWS = [daily("r1", 20), daily("r2", 8)]


def at_hour(spec, after):
    tz = localtime.operator_tz()
    hour = int(spec["time"][:2])
    day = after.astimezone(tz).date()
    for step in range(3):
        when = dt.datetime.combine(day + dt.timedelta(days=step), dt.time(hour), tzinfo=tz)
        if when > after:
            return when.astimezone(dt.timezone.utc)
    return None


class AskingWhen(unittest.TestCase):
    def test_both_times_in_clock_order(self):
        with mock.patch.object(intercom, "_reminder_schedules", return_value=ROWS), \
                mock.patch.object(intercom, "_reminder_words",
                                  side_effect=lambda r: f"take my medicine — every day at {int(r['time'][:2]) % 12} "
                                                        f"{'pm' if int(r['time'][:2]) >= 12 else 'am'}"), \
                mock.patch.object(intercom, "_reminder_clock", side_effect=lambda r: r["time"]):
            got = quick.answer("what time are my medicine reminders")
        self.assertEqual(got, "You have 2 reminders to take your medicine: every day at 8 am and every day at 8 pm.")

    def test_different_reminders_still_ask(self):
        rows = [dict(daily("r1", 17), command={"text": "call mom"}), dict(daily("r2", 18), command={"text": "call the bank"})]
        with mock.patch.object(intercom, "_reminder_schedules", return_value=rows):
            self.assertIsNone(quick._same_reminder_times("call"))


class SkippingTonights(unittest.TestCase):
    def test_tonight_names_the_evening_one(self):
        if dt.datetime.now(localtime.operator_tz()).hour >= 20:
            self.skipTest("tonight's has already gone off")
        with mock.patch.object(intercom, "_reminder_schedules", return_value=ROWS), \
                mock.patch.object(scheduler, "next_occurrence", side_effect=at_hour):
            found, why = intercom._one_reminder("medicine", once="tonight")
        self.assertEqual(found["id"], "r1", why)

    def test_without_a_day_it_still_asks(self):
        with mock.patch.object(intercom, "_reminder_schedules", return_value=ROWS), \
                mock.patch.object(scheduler, "next_occurrence", side_effect=at_hour):
            found, why = intercom._one_reminder("medicine")
        self.assertIsNone(found)
        self.assertTrue(why.startswith("Which one"), why)


if __name__ == "__main__":
    unittest.main()
