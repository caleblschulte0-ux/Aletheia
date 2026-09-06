"""`talk --sandbox` moved every store somewhere throwaway. Moving a store
does not stop an email leaving.

On his own machine, with mail configured, auditing her would have SENT
things — a real email, a real GitHub issue, a real browser pressing
Submit on a real site. The word "sandbox" says otherwise, and a promise
that is true of the filesystem and false of the world is the kind of
half-truth this whole session has been about.

Everything LOCAL still runs, so a rehearsal exercises the real planner,
the real gates, the real stores and the real sentences. Only the last
inch into the world is withheld.
"""
import os
import unittest
from unittest import mock

from aletheia import intercom


class RehearsalCase(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(os.environ, {intercom.REHEARSAL: "1"})
        p.start(); self.addCleanup(p.stop)

    def test_it_is_off_unless_asked_for(self):
        with mock.patch.dict(os.environ, {intercom.REHEARSAL: ""}):
            self.assertFalse(intercom.rehearsing())
        self.assertTrue(intercom.rehearsing())

    def test_a_world_touching_kind_is_refused(self):
        from aletheia import act
        for kind, cmd in (("email_draft", {"to": "d@x.com", "body": "hi"}),
                          ("issue", {"repo": "Aletheia", "title": "t"}),
                          ("dispatch", {"repo": "Aletheia", "workflow": "w.yml"})):
            with self.subTest(kind=kind):
                with self.assertRaises(act.Refused) as caught:
                    intercom.execute_command({"kind": kind, **cmd}, {"repos": {}},
                                             quote="q")
                self.assertIn("rehearsal", str(caught.exception))

    def test_local_work_still_really_happens(self):
        """A rehearsal that refuses everything tests nothing."""
        said = intercom.execute_command({"kind": "note", "text": "a thought"},
                                        {"repos": {}}, quote="q")
        self.assertEqual(said, "journaled")

    def test_the_planner_still_runs(self):
        """`intent` is world-tier because its STEPS can be, and each step
        comes back through here to be checked on its own. Refusing the
        container would leave a rehearsal able to exercise only the
        handful of sentences that have a deterministic verb."""
        self.assertIn("intent", intercom.CONTAINERS)
        for kind in intercom.CONTAINERS:
            with self.subTest(kind=kind):
                self.assertIn(kind, intercom.KIND_ARGS)

    def test_every_container_really_re_enters_this_function(self):
        """A container that executed its own steps some other way would
        slip past the check entirely."""
        from pathlib import Path
        source = Path(intercom.__file__).read_text(encoding="utf-8")
        for kind in intercom.CONTAINERS:
            with self.subTest(kind=kind):
                self.assertIn(f'kind == "{kind}"', source)

    def test_the_refusal_says_what_did_happen(self):
        from aletheia import act
        with self.assertRaises(act.Refused) as caught:
            intercom.execute_command({"kind": "issue", "repo": "Aletheia",
                                      "title": "t"}, {"repos": {}}, quote="q")
        self.assertIn("Everything local happened for real", str(caught.exception))

    def test_the_sandbox_turns_it_on(self):
        from pathlib import Path
        from aletheia import talk
        body = Path(talk.__file__).read_text(encoding="utf-8")
        self.assertIn("ALETHEIA_REHEARSAL", body)


class ApprovalLabelsNameTheConsequentialOneCase(unittest.TestCase):
    """"2 things waiting: the plan and Remember that landlord is Mr Okafor."

    `intent.execute` returned the literal "the plan" BEFORE the check that
    reads the plan's own summary — so every world-touching plan was the
    nameless one, and the routine ones got a description. Exactly
    backwards.
    """

    def test_a_world_touching_plan_is_named(self):
        from aletheia import voice
        said = voice.approval_label({
            "capability": "intent.execute",
            "requested_action": "run 1 step: issue", "reason": "",
            "consequence": "File a GitHub issue about the wall"})
        self.assertEqual(said, "File a GitHub issue about the wall")

    def test_the_generic_label_is_still_there_when_there_is_nothing_better(self):
        from aletheia import voice
        for capability, expected in (("intent.execute", "the plan"),
                                     ("calendar.write", "the calendar booking")):
            with self.subTest(capability=capability):
                self.assertEqual(voice.approval_label({
                    "capability": capability, "requested_action": "x",
                    "reason": "", "consequence": "see the plan"}), expected)

    def test_an_email_still_names_its_recipient(self):
        from aletheia import voice
        self.assertEqual(voice.approval_label({
            "capability": "email.send", "requested_action": "email.send",
            "reason": "send to Dana.", "consequence": "an email leaves"}),
            "the email to Dana")


if __name__ == "__main__":
    unittest.main()
