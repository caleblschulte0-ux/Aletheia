"""How fast she talks, by his word (2026-10-07: "talk slower" went to the planner)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import intercom, quick, speaking_pace, voice


class HowFastSheTalks(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        patcher = mock.patch.object(speaking_pace, "_path", return_value=Path(self.dir) / "pace.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_his_words_reach_the_verb(self):
        for said, action in (("talk slower", "slower"), ("slower", "slower"), ("you're talking too fast", "slower"),
                             ("speak a little faster", "faster"), ("talk normally", "normal")):
            self.assertEqual(voice._interpret(said)["command"], {"kind": "speaking_pace", "action": action}, said)

    def test_slower_is_read_by_both_voices(self):
        self.assertEqual((speaking_pace.sapi_rate(), speaking_pace.piper_length_scale()), (1, 1.0))
        self.assertEqual(intercom.execute_command({"kind": "speaking_pace", "action": "slower"}, {}),
                         "Okay - a little slower than normal now.")
        self.assertEqual(speaking_pace.sapi_rate(), -1)
        self.assertGreater(speaking_pace.piper_length_scale(), 1.0)
        self.assertEqual(quick.answer("how fast are you talking"), "I'm talking at a little slower than normal.")

    def test_it_stops_at_the_ends_and_goes_back(self):
        for _ in range(3):
            speaking_pace.act("faster")
        self.assertEqual(speaking_pace.act("faster"), "That's already as fast as I go.")
        self.assertEqual(speaking_pace.act("normal"), "Back to my normal speed.")
        self.assertEqual(speaking_pace.step(), 0)

    def test_a_wrong_action_is_refused(self):
        with self.assertRaises(ValueError):
            speaking_pace.act("louder")

    def test_piper_is_told_the_pace(self):
        from aletheia import voice_quality
        seen = []

        def runner(args, **kw):
            seen.append(args)
            raise RuntimeError("stop here")

        speaking_pace.act("slower")
        with mock.patch.object(voice_quality, "piper_ready", return_value=(True, "")):
            voice_quality.piper_speak("hello", runner=runner, player=lambda p: None)
        self.assertIn("--length_scale", seen[0])


if __name__ == "__main__":
    unittest.main()
