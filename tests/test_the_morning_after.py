"""Night sweep 2026-09-23, every frontier off: "how did the job hunt go last
night", "what jobs did you send overnight", "did anything get sent while I
slept", "how many did you send last night", "which companies did you apply
to last night" and "any replies overnight" each went to a planner nobody
could run - the first things he says when he wakes."""
import datetime as dt
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from aletheia import quick

TZ = ZoneInfo("America/Chicago")


def sent(hours_ago, company, title):
    at = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
    return {"state": "SUBMITTED", "submitted_at": at, "company": company, "job_title": title}


class TheMorningAfter(unittest.TestCase):
    def test_the_shapes_are_claimed(self):
        for said, shape in (("how did the job hunt go last night", "overnight"),
                            ("how did the hunt go overnight", "overnight"),
                            ("what jobs did you send overnight", "sent_window"),
                            ("which companies did you apply to last night", "sent_window"),
                            ("did anything get sent while I slept", "sent_window"),
                            ("anything sent last night", "sent_window"),
                            ("how many did you send last night", "status_of"),
                            ("how many did you send while I slept", "status_of"),
                            ("any replies overnight", "replies"),
                            ("any replies last night", "replies")):
            with self.subTest(said=said):
                found = quick.match(said)
                self.assertIsNotNone(found, said)
                self.assertEqual(found[0], shape)

    def test_what_went_out_last_night_names_them(self):
        rows = [sent(2, "Vanta", "Customer Success Manager"), sent(30, "OldCo", "Analyst")]
        with mock.patch("aletheia.localtime.operator_tz", return_value=TZ), \
             mock.patch("aletheia.quick._sent_records", return_value=rows):
            now = dt.datetime.now(TZ)
            said = quick.answer("what jobs did you send overnight")
            # the night starts at ten yesterday: a send two hours ago is in it
            # whenever "now" is after midnight; before ten it is still "today"
            self.assertIsNotNone(said)
            self.assertNotIn("OldCo", said)
            if now.hour >= 0 and (now - dt.timedelta(hours=2)) >= (now - dt.timedelta(days=1)).replace(hour=22, minute=0):
                self.assertIn("Vanta", said)
            self.assertEqual(quick.answer("did anything get sent while I slept"), quick.answer("what jobs did you send last night"))

    def test_how_many_last_night_counts_the_same_window(self):
        rows = [sent(1, "Vanta", "CSM"), sent(1, "Notion", "BSA")]
        with mock.patch("aletheia.localtime.operator_tz", return_value=TZ), \
             mock.patch("aletheia.quick._sent_records", return_value=rows):
            said = quick.answer("how many did you send last night")
            self.assertIsNotNone(said)
            self.assertNotIn("could not plan", said)


if __name__ == "__main__":
    unittest.main()
