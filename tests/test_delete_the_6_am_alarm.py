"""An alarm is not a thing on the list he was just talking about.

2026-10-28, talking to her with the models off:

    > add batteries to my target list
    > set an alarm for 5 pm
    > delete the 6 am alarm
      There's nothing called the 6 am alarm on your target list.
"""
import unittest
from unittest import mock

from aletheia import intercom, voice

TARGET = [{"he_asked": "add batteries to my target list",
           "she_answered": "Added to your target list: batteries."}]


class NotTheList(unittest.TestCase):
    def interpret(self, said):
        with mock.patch("aletheia.converse.recent", return_value=TARGET):
            return voice.interpret(said)["command"]

    def test_an_alarm_goes_to_the_alarms(self):
        for said in ("delete the 6 am alarm", "remove my 7:30 am reminder", "delete the meeting"):
            cmd = self.interpret(said) or {}
            self.assertNotEqual(cmd.get("kind"), "list_off", said)

    def test_a_thing_still_comes_off_the_list(self):
        self.assertEqual(self.interpret("remove batteries"),
                         {"kind": "list_off", "list": "target", "item": "batteries"})
        self.assertEqual(self.interpret("remove the alarm clock from it"),
                         {"kind": "list_off", "list": "target", "item": "alarm clock"})

    def test_the_one_he_has_is_an_alarm(self):
        row = {"id": "r1", "command": {"kind": "notify", "text": "wake up"}}
        with mock.patch.object(intercom, "_reminder_words", return_value="wake up — today at 5 pm"):
            self.assertEqual(intercom._reminder_list_words([row]),
                             "The one you have is an alarm today at 5 pm.")


if __name__ == "__main__":
    unittest.main()
