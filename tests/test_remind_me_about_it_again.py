""""Remind me about it again in an hour" (2026-10-28) set a reminder whose
words were "it again". It is the snooze "remind me again in an hour" is, and
a reminder that would say only "it again" is never kept."""
import unittest

from aletheia import voice


class RemindMeAboutItAgain(unittest.TestCase):
    def test_it_is_a_snooze(self):
        self.assertEqual(voice.interpret("remind me about it again in an hour")["command"],
                         {"kind": "notify_snooze", "minutes": 60})
        self.assertEqual(voice.interpret("remind me about that again")["command"]["kind"], "notify_snooze")

    def test_it_again_is_never_the_words(self):
        got = voice.interpret("remind me about it again tomorrow")
        self.assertNotEqual((got.get("command") or {}).get("text"), "it again")


if __name__ == "__main__":
    unittest.main()
