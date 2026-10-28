"""What she remembers about a thing, asked the ways he asks it.

2026-10-28, talking to her with the models off:

    > remember that the spare key is under the blue pot
    > what do you remember about the key
      The big models can't answer right now, so I looked that up myself. ...
"""
import unittest
from unittest import mock

from aletheia import quick

NOTES = [{"text": "the spare key is under the blue pot", "ts": "2026-10-28T14:00:00+00:00"}]


class Remember(unittest.TestCase):
    def test_every_way_he_asks(self):
        with mock.patch.object(quick, "_notes", return_value=NOTES):
            for q in ("what do you remember about the key", "what have i told you about the key",
                      "tell me what you know about the key", "what did you remember about the spare key"):
                self.assertEqual(quick.answer(q), "You told me: the spare key is under the blue pot.", q)

    def test_his_schedule_is_not_a_note(self):
        for q in ("what do i have on my calendar", "what do i have on friday", "what do we have on this weekend"):
            self.assertNotEqual((quick.match(q) or ("",))[0], "recall", q)


if __name__ == "__main__":
    unittest.main()
