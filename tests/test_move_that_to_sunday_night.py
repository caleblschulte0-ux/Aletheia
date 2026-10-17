""""Move that to Sunday night" after a reminder went to the planner, and with
nothing thinking the room heard "neither Claude nor the ChatGPT browser could
answer just now; local reasoning is unavailable too: local reasoning is
disabled" (2026-10-17, every model off)."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import intents, intercom, localtime, voice


class ADayAndAPartOfIt(unittest.TestCase):
    def _moved(self, said):
        tz = localtime.operator_tz()
        was = (dt.datetime.now(tz) + dt.timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        with mock.patch.object(voice, "_recent_reminder_ask",
                               return_value={"kind": "remind_at", "text": "take out the trash", "at": was.isoformat()}), \
                mock.patch.object(intercom, "_one_reminder", return_value=(None, "")):
            command = voice.interpret(said)["command"]
        self.assertEqual(command["kind"], "remind_at")
        self.assertEqual(command["replaces"], "take out the trash")
        return dt.datetime.fromisoformat(command["at"]).astimezone(tz)

    def test_sunday_night(self):
        at = self._moved("move that to sunday night")
        self.assertEqual((at.weekday(), at.hour), (6, 21))

    def test_monday_morning(self):
        at = self._moved("make it monday morning")
        self.assertEqual((at.weekday(), at.hour), (0, 9))

    def test_friday_afternoon(self):
        at = self._moved("change it to friday afternoon")
        self.assertEqual((at.weekday(), at.hour), (4, 14))


class NothingThinkingIsOneSentence(unittest.TestCase):
    def test_the_gateway_line_without_the_word_subscription(self):
        said = intents._degraded_line("neither Claude nor the ChatGPT browser could answer just now; "
                                      "local reasoning is unavailable too: local reasoning is disabled")
        self.assertNotIn("ChatGPT browser", said)
        self.assertNotIn("disabled", said)


if __name__ == "__main__":
    unittest.main()
