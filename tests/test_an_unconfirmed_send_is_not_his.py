"""Live 2026-09-23 four browser missions pressed and left unconfirmed by the
site sat under "needs you" saying "waiting for you" - with nothing for him
to do. An unconfirmed send waits on the site, not on him."""
import datetime as dt
import unittest

from aletheia import mission_browser

NOW = dt.datetime(2026, 9, 23, 10, 0, tzinfo=dt.timezone.utc)


def mission(state, hours_ago, kind="CAPTCHA"):
    at = (NOW - dt.timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
    return {"id": "m-1", "goal": "apply for this job", "start_url": "https://jobs.example.com/x", "state": state,
            "boundary": {"kind": kind, "url": "https://jobs.example.com/x", "at": at}, "beat": at}


class AnUnconfirmedSendIsNotHis(unittest.TestCase):
    def test_it_is_sent_not_needs_you_and_ages_out_like_a_done_one(self):
        card = mission_browser.card(mission("SUBMITTED_UNCONFIRMED", 1), NOW)
        self.assertEqual(card["status"], "WAITING", "on the site, not on him")
        self.assertEqual(card["needs"], [])
        self.assertNotIn("waiting for you", (card.get("step") or "") + (card.get("next") or ""))
        self.assertIsNone(mission_browser.card(mission("SUBMITTED_UNCONFIRMED", 30), NOW), "a day old, it is history")

    def test_a_human_check_still_needs_him(self):
        card = mission_browser.card(mission("NEEDS_YOU", 1, "CAPTCHA"), NOW)
        self.assertEqual(card["status"], "NEEDS YOU")
        self.assertTrue(card["needs"])


if __name__ == "__main__":
    unittest.main()
