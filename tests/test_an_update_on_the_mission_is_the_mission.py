"""Talked to her, 2026-10-12: "anything new from the move plan", "any update on the move plan",
"where are we on the move plan" and "how's the move plan coming along" all went to a model with
the mission right there - and "what's the latest on the reboot" would have searched the web for
news about it. Every one of them is the mission's own status."""

from tests import test_his_mission_rehearsed as rehearsed

NOW, pg = rehearsed.NOW, rehearsed.pg


class AnUpdateOnTheMissionIsTheMission(rehearsed.HisMissionRunsWithoutHim):

    def test_the_ways_he_asks_for_an_update_are_answered_from_the_mission(self):
        from aletheia import quick
        pg.add_words(self.pid, "also start planning a move somewhere warm", via="operator-voice", now=NOW)
        for asked in ("anything new from the move plan", "anything new on the move plan",
                      "any update on the move plan", "any updates on the reboot", "any progress on the move plan",
                      "where are we on the move plan", "where are we with the move plan",
                      "how's the move plan coming along", "what's the latest on the reboot",
                      "status of the move plan", "update me on the move plan",
                      "give me an update on the move plan"):
            said = quick.answer(asked)
            self.assertIsNotNone(said, asked)
            self.assertIn("Project Reboot", said, asked)

    def test_a_subject_naming_nothing_of_his_is_still_not_answered(self):
        from aletheia import quick
        for asked in ("any update on the election", "anything new on the moon landing"):
            self.assertIsNone(quick.answer(asked), asked)
