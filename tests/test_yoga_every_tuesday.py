"""What he does every week shows up on that day.

2026-10-28, talking to her with the models off:

    > I have yoga every tuesday at 6        Noted.
    > what's on tuesday                     Nothing on your calendar Tuesday.
    > we do pizza night on fridays          (to the planner)
    > read me the beach list                (the beach things were on the
                                             packing list; she offered to
                                             start a new one)
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import intercom, lists, localtime, quick, voice

OLD = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=40)).isoformat()


class EveryWeek(unittest.TestCase):
    def test_a_weekly_note_answers_its_day_however_old(self):
        notes = [{"text": "i have yoga every tuesday at 6", "ts": OLD},
                 {"text": "i used to swim every tuesday", "ts": OLD},
                 {"text": "we do pizza night on fridays", "ts": OLD}]
        with mock.patch.object(quick, "_notes", return_value=notes):
            self.assertEqual(quick._plans_told("tuesday"), "you have yoga every Tuesday at 6")
            self.assertEqual(quick._plans_told("friday"), "we do pizza night on Fridays")
            self.assertEqual(quick._plans_told("monday"), "")

    def test_today_and_tomorrow_are_their_weekdays_for_weekly_things_only(self):
        tz = localtime.operator_tz()
        tomorrow = (dt.datetime.now(tz).date() + dt.timedelta(days=1)).strftime("%A").lower()
        recent = dt.datetime.now(dt.timezone.utc).isoformat()
        notes = [{"text": f"i play basketball every {tomorrow} night", "ts": OLD},
                 {"text": f"we're having people over {tomorrow}", "ts": recent}]
        with mock.patch.object(quick, "_notes", return_value=notes):
            self.assertEqual(quick._plans_told("tomorrow"), f"you play basketball every {tomorrow.title()} night")

    def test_he_can_say_a_routine(self):
        for said in ("we do pizza night on fridays", "i play basketball every thursday night",
                     "i take piano on wednesdays at 4", "i go to the gym on mondays"):
            self.assertEqual(voice.interpret(said)["command"]["kind"], "note", said)
        self.assertNotEqual((voice.interpret("do i have yoga every tuesday").get("command") or {}).get("kind"), "note")


class TheListsHeHas(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = mock.patch.object(lists, "private_dir", lambda name: self.tmp / name)
        p.start()
        self.addCleanup(p.stop)
        (self.tmp / "lists").mkdir()

    def test_a_list_he_does_not_have_names_the_ones_he_does(self):
        self.assertNotIn("You do have", intercom.execute_command({"kind": "list_read", "list": "beach"}, {}))
        lists.add("packing", ["sunscreen"])
        said = intercom.execute_command({"kind": "list_read", "list": "beach"}, {})
        self.assertIn("Nothing's on a beach list yet. You do have a packing list.", said)
        lists.add("errands", ["post office"])
        said = intercom.execute_command({"kind": "list_read", "list": "beach"}, {})
        self.assertIn("You do have your errands and packing lists.", said)


if __name__ == "__main__":
    unittest.main()
