""""Actually make it 5 minutes later" shifts the reminder he just moved.

2026-10-28, talking to her with the models off:

    > remind me in 20 minutes to check the oven
    > push it back 10 minutes
      I'll remind you today at 2:11 pm: check the oven.
    > actually make it 5 minutes later
      I could not plan that: nothing could think just now ...

"Push it back" was a shift from where the reminder is; "make it ...
later", with or without "actually" in front, is the same ask.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import converse, intercom, voice


class MakeItLater(unittest.TestCase):
    def _shift(self, said):
        at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=30)
        spec = {"id": "r1", "kind": "once", "at": at.isoformat(), "enabled": True,
                "command": {"kind": "notify_operator", "text": "check the oven"}}
        turns = [{"he_asked": "remind me in 20 minutes to check the oven", "she_answered": "I'll remind you today at 2:01 pm: check the oven."},
                 {"he_asked": "push it back 10 minutes", "she_answered": "I'll remind you today at 2:11 pm: check the oven."}]
        with mock.patch.object(converse, "recent", return_value=turns), \
                mock.patch.object(intercom, "_one_reminder", return_value=(spec, "")):
            cmd = voice._interpret(said)["command"] or {}
        return at, cmd

    def test_every_way_he_says_it(self):
        for said, minutes in (("actually make it 5 minutes later", 5), ("make it 5 minutes later", 5),
                              ("make it an hour later", 60), ("no, make it 10 minutes earlier", -10),
                              ("actually push it back 5 minutes", 5)):
            at, cmd = self._shift(said)
            self.assertEqual(cmd.get("kind"), "remind_at", said)
            self.assertEqual(cmd["text"], "check the oven", said)
            self.assertEqual(dt.datetime.fromisoformat(cmd["at"]), at + dt.timedelta(minutes=minutes), said)


if __name__ == "__main__":
    unittest.main()
