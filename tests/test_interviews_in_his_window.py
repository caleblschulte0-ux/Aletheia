"""His words, 2026-09-23: "if I ever get an interview ... I want it to be to
the point where she'll just auto schedule an interview for me at sometime
between 1 p.m. and 2:30 p.m. Central Time. Preferably, or something close
to that." Built OFF; on, it picks the slot, drafts a HELD reply (his other
ruling that morning: drafts yes, sending not yet) and pencils the time in."""
import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from aletheia import interviews, journal, mail, policy

CHI = ZoneInfo("America/Chicago")
# A Tuesday, 10:00 Central.
NOW = dt.datetime(2026, 9, 22, 10, 0, tzinfo=CHI).astimezone(dt.timezone.utc)
WINDOW = dict(interviews.DEFAULT_WINDOW)


def at(day, hour, minute=0):
    start = dt.datetime(2026, 9, day, hour, minute, tzinfo=CHI)
    return {"start": start.isoformat(), "end": (start + dt.timedelta(minutes=30)).isoformat(), "quote": "x"}


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start(); self.addCleanup(env.stop)
        for module, attr, value in ((mail, "MAIL_DIR", root / "mail"), (policy, "APPROVALS_DIR", root / "approvals"),
                                    (journal, "JOURNAL_PATH", root / "journal.jsonl")):
            p = mock.patch.object(module, attr, value)
            p.start(); self.addCleanup(p.stop)


class ChoosingTheTime(unittest.TestCase):
    free = staticmethod(lambda s, e: False)

    def test_inside_the_window_on_a_weekday_wins(self):
        chosen = interviews.choose_slot([at(23, 9), at(23, 13, 30), at(24, 13)], now=NOW, window=WINDOW, busy=self.free)
        self.assertEqual(chosen["start"], at(23, 13, 30)["start"])
        self.assertEqual(chosen["fit"], "in the window")

    def test_the_closest_free_one_otherwise(self):
        chosen = interviews.choose_slot([at(23, 9), at(23, 15), at(24, 11, 30)], now=NOW, window=WINDOW, busy=self.free)
        self.assertEqual(chosen["start"], at(23, 15)["start"], "3 PM is 75 minutes from the window's middle; 11:30 is 135")
        self.assertEqual(chosen["fit"], "closest to the window")

    def test_a_weekend_and_a_busy_slot_lose(self):
        # 26th is Saturday; 23rd 1:00 PM is taken
        busy = lambda s, e: s == at(23, 13)["start"]
        chosen = interviews.choose_slot([at(26, 13), at(23, 13), at(24, 14)], now=NOW, window=WINDOW, busy=busy)
        self.assertEqual(chosen["start"], at(24, 14)["start"])
        self.assertIsNone(interviews.choose_slot([at(21, 13)], now=NOW, window=WINDOW, busy=self.free), "the past")
        self.assertIsNone(interviews.choose_slot([], now=NOW, window=WINDOW, busy=self.free))

    def test_the_window_edge(self):
        self.assertTrue(interviews.in_window(at(23, 13)["start"], WINDOW))
        self.assertTrue(interviews.in_window(at(23, 14)["start"], WINDOW), "2:00 to 2:30 still fits")
        self.assertFalse(interviews.in_window(at(23, 14, 15)["start"], WINDOW), "2:15 runs past 2:30")
        self.assertFalse(interviews.in_window(at(23, 12, 45)["start"], WINDOW))
        self.assertFalse(interviews.in_window(at(26, 13)["start"], WINDOW), "Saturday")

    def test_offers_are_the_next_free_weekday_window_starts(self):
        busy = lambda s, e: s == at(23, 13)["start"]
        offers = interviews.offer_slots(now=NOW, window=WINDOW, busy=busy)
        self.assertEqual([o["start"] for o in offers], [at(24, 13)["start"], at(25, 13)["start"], at(28, 13)["start"]],
                         "Wednesday (Tuesday's taken), Thursday, Friday... no: Wed, Thu, then Monday - Friday the 25th, then the 28th")

    def test_the_words(self):
        self.assertEqual(interviews.said_when(at(23, 13)["start"], WINDOW), "Wednesday 1 PM Central")
        self.assertEqual(interviews.said_when(at(23, 13, 30)["start"], WINDOW), "Wednesday 1:30 PM Central")
        self.assertEqual(interviews.window_words(WINDOW), "1 PM to 2:30 PM Central")
        text = interviews.reply_text(his_name="Caleb Schulte", company="Fin", chosen=at(23, 13, 30),
                                     offers=[], window=WINDOW)
        self.assertIn("Wednesday 1:30 PM Central works well for me", text)
        self.assertTrue(text.endswith("Caleb"))
        offered = interviews.reply_text(his_name="Caleb", company="Fin", chosen=None,
                                        offers=[at(24, 13), at(25, 13)], window=WINDOW)
        self.assertIn("Thursday 1 PM Central; Friday 1 PM Central", offered)
        self.assertIn("1 PM to 2:30 PM Central on a weekday", offered)


class TheSwitch(Isolated):
    def test_off_by_default_and_on_with_his_words(self):
        self.assertFalse(interviews.status()["on"])
        self.assertEqual(interviews.consider({}, {"id": "apply-1", "company": "Fin"}, subject="x"), {"state": "off"})
        state = interviews.enable(quote="auto schedule an interview for me")
        self.assertTrue(state["on"])
        self.assertEqual(state["window"], WINDOW)
        self.assertIn("auto schedule", journal.JOURNAL_PATH.read_text(encoding="utf-8"))
        self.assertFalse(interviews.disable()["on"])

    def test_the_window_is_his_to_move(self):
        state = interviews.set_window("14:00", "15:00")
        self.assertEqual(state["window"]["start"], "14:00")
        self.assertEqual(state["window"]["timezone"], "America/Chicago")
        with self.assertRaises(ValueError):
            interviews.set_window("15:00", "14:00")
        with self.assertRaises(ValueError):
            interviews.set_window("1pm", "2pm")


class TheAct(Isolated):
    EVENT = {"id": "ev-1", "attributes": {"sender": "recruiter@fin.ai"}}
    ENTRY = {"id": "apply-1", "company": "Fin", "job_title": "Customer Success Manager"}

    def test_on_it_picks_drafts_holds_marks_and_says_so(self):
        interviews.enable(quote="auto schedule")
        holds, marks, notices = [], [], []
        text = "Thanks for applying! Could you do Wednesday September 23 at 9am, 1:30pm or 3pm Central?"
        out = interviews.consider(
            self.EVENT, self.ENTRY, subject="Interview - Fin", text=text, now=NOW, busy=lambda s, e: False,
            holder=lambda eid, title, s, e: holds.append((eid, title, s, e)) or {"id": eid},
            marker=lambda rid, outcome, note="": marks.append((rid, outcome, note)),
            notify=lambda title, body, **kw: notices.append((title, body, kw)),
            known={"full_name": "Caleb Schulte"})
        self.assertEqual(out["state"], "drafted")
        self.assertEqual(out["chosen"]["start"], at(23, 13, 30)["start"])
        drafts = mail.held_drafts()
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0]["to"], "recruiter@fin.ai")
        self.assertEqual(drafts[0]["subject"], "Re: Interview - Fin")
        self.assertIn("Wednesday 1:30 PM Central works well", drafts[0]["body"])
        with self.assertRaises(Exception):
            policy.load(drafts[0]["id"])        # held: no approval exists to tap
        self.assertEqual(holds[0][1], "Interview: Fin")
        self.assertEqual(marks, [("apply-1", "interview", "asked for time; Wednesday 1:30 PM Central chosen")])
        self.assertEqual(notices[0][0], "Fin wants to talk")
        self.assertIn("I picked Wednesday 1:30 PM Central and pencilled it in", notices[0][1])
        self.assertIn("drafted and held", notices[0][1])
        self.assertEqual(notices[0][2]["related"]["draft"], drafts[0]["id"])

    def test_nothing_proposed_means_offers_and_no_hold(self):
        interviews.enable()
        holds, notices = [], []
        out = interviews.consider(
            self.EVENT, self.ENTRY, subject="Next steps", text="We'd love to set up a call. When works for you?",
            now=NOW, busy=lambda s, e: False, holder=lambda *a: holds.append(a),
            marker=lambda *a, **k: None, notify=lambda title, body, **kw: notices.append(body), known={"full_name": "Caleb"})
        self.assertEqual(out["state"], "drafted")
        self.assertIsNone(out["chosen"])
        self.assertEqual(len(out["offers"]), 3)
        self.assertEqual(holds, [])
        self.assertIn("offered 3 in your window", notices[0])
        self.assertIn("Wednesday 1 PM Central", mail.held_drafts()[0]["body"])

    def test_the_beat_hook_does_nothing_when_off(self):
        from aletheia import runtime
        with mock.patch.object(interviews, "consider", side_effect=AssertionError("must not run")):
            runtime._consider_interview(self.EVENT, self.ENTRY, "Interview - Fin")

    def test_the_words_when_off_name_the_switch(self):
        self.assertIn("python -m aletheia.interviews on", interviews.spoken())
        interviews.enable()
        self.assertIn("1 PM to 2:30 PM Central", interviews.spoken())


if __name__ == "__main__":
    unittest.main()
