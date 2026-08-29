"""The wall mic must never compete with the native hands-free room listener."""
import unittest

from aletheia.fleet import REPO_ROOT


class BrowserVoiceSafetyCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (REPO_ROOT / "interface" / "voice.js").read_text(encoding="utf-8")

    def test_browser_recognizer_is_one_shot(self):
        self.assertIn("rec.continuous = false", self.source)
        self.assertNotIn("rec.continuous = true", self.source)
        self.assertNotIn("if (armed)", self.source)

    def test_browser_push_to_talk_adds_the_server_wake_word(self):
        self.assertIn("const transcript = `thea ${command}`", self.source)

    def test_spoken_wake_word_is_refused_by_browser_to_avoid_duplicate_send(self):
        self.assertIn("if (WAKE.test(t))", self.source)
        wake_block = self.source.split("if (WAKE.test(t))", 1)[1].split("sendCommand(t)", 1)[0]
        self.assertIn("return;", wake_block)


if __name__ == "__main__":
    unittest.main()
