"""New words for a reminder, same time; a reminder changed to a day is a move.

2026-10-28, talking to her with the models off:

    > remind me friday at 10 to email sarah
    > change the email sarah one to call sarah        (to the planner)
    > change my dentist reminder to friday
      (kept as a fact: "my dentist reminder is friday")
"""
import unittest
from unittest import mock

from aletheia import intercom, scheduler, voice

SPEC = {"id": "r1", "kind": "once", "at": "2026-10-30T15:00:00Z", "enabled": True,
        "command": {"kind": "notify_operator", "text": "email sarah"}}


class Reword(unittest.TestCase):
    def test_he_can_say_it(self):
        for said, which, new in (("change the email sarah one to call sarah", "email sarah", "call sarah"),
                                 ("change my email sarah reminder to say call sarah", "email sarah", "call sarah"),
                                 ("make my vitamins reminder say take fish oil", "vitamins", "take fish oil")):
            self.assertEqual(voice.interpret(said)["command"],
                             {"kind": "reminder_reword", "which": which, "text": new}, said)

    def test_a_time_is_still_a_move(self):
        for said in ("change my dentist reminder to 4 pm", "change my dentist reminder to friday",
                     "change the first one to call bob"):
            cmd = voice.interpret(said)["command"] or {}
            self.assertNotIn(cmd.get("kind"), ("reminder_reword", "note"), said)

    def test_the_words_change_and_the_time_stays(self):
        with mock.patch.object(intercom, "_one_reminder", return_value=(SPEC, "")), \
                mock.patch.object(intercom, "_reminder_words", return_value="call sarah — Friday at 10 am"), \
                mock.patch.object(scheduler, "retext") as retext:
            said = intercom.execute_command({"kind": "reminder_reword", "which": "email sarah", "text": "call sarah"},
                                            {}, quote="test")
        retext.assert_called_once_with("r1", "call sarah")
        self.assertIn("Changed it to call sarah - Friday at 10 am. It used to say email sarah.", str(said))

    def test_retext_keeps_the_schedule(self):
        saved = {}
        with mock.patch.object(scheduler, "load", return_value=dict(SPEC)), \
                mock.patch.object(scheduler, "save", side_effect=lambda s: saved.update(s) or s):
            scheduler.retext("r1", "call sarah")
        self.assertEqual(saved["command"], {"kind": "notify_operator", "text": "call sarah"})
        self.assertEqual(saved["at"], SPEC["at"])


if __name__ == "__main__":
    unittest.main()
