"""She looks up what she can do instead of guessing it.

The most likely first question anyone asks a new assistant is "what can
you do?", and the second is "can you do X?". The conversational half had
no path to config/capabilities.json at all, so both were answered by a
language model reasoning from its general idea of what an assistant
probably does — §104 and §106, the two rules the playbook states twice.

It is worse here than in most systems because most of those answers would
have been RIGHT. She really can send email, write files, drive the
desktop. That is precisely what makes the wrong ones impossible to spot.
"""
import unittest
from unittest import mock

from aletheia import capabilities, self_knowledge


REG = {"revision": 9, "capabilities": [
    {"id": "email.send", "status": "AVAILABLE",
     "description": "Draft and send email with approval gate",
     "module": "aletheia.mail"},
    {"id": "calendar.read", "status": "NEEDS_CONFIGURATION",
     "description": "Read availability, reason about work hours",
     "module": "aletheia.calendar_live"},
    {"id": "message.send", "status": "NOT_BUILT",
     "description": "Send a text message to a person",
     "module": "aletheia.communications"},
    {"id": "purchase.execute", "status": "EXPERIMENTAL",
     "description": "Execute an actual purchase with money",
     "module": "aletheia.purchases"},
    {"id": "pulse.collect", "status": "AVAILABLE",
     "description": "Gather fleet health into one reading",
     "module": "aletheia.pulse"},
]}


class ItFindsWhatHeIsAskingAbout(unittest.TestCase):
    def found(self, question):
        return [m["capability"] for m in
                self_knowledge.relevant(question, registry=REG)]

    def test_his_words_reach_the_registry_words(self):
        self.assertIn("email.send", self.found("can you send an email?"))

    def test_a_synonym_he_would_really_say_still_lands(self):
        """He says "text my brother"; the registry says message.send."""
        self.assertIn("message.send", self.found("can you text my brother?"))

    def test_a_question_about_nothing_of_hers_returns_nothing(self):
        """Noise in this block teaches the brain the block is noise."""
        self.assertEqual(self.found("why are there tides?"), [])
        self.assertEqual(self_knowledge.for_question("why are there tides?"), {})

    def test_the_word_he_used_outranks_a_synonym(self):
        found = self.found("read my calendar")
        self.assertEqual(found[0], "calendar.read")

    def test_it_is_bounded(self):
        found = self_knowledge.relevant("email calendar message purchase pulse",
                                        limit=2, registry=REG)
        self.assertEqual(len(found), 2)


class ItNeverLaundersAStatus(unittest.TestCase):
    def one(self, question, cid):
        for match in self_knowledge.relevant(question, registry=REG):
            if match["capability"] == cid:
                return match
        self.fail(f"{cid} not found for {question!r}")

    def test_not_built_says_not_built(self):
        self.assertEqual(self.one("text my brother", "message.send")["status"],
                         "NOT_BUILT")

    def test_experimental_is_not_described_as_working(self):
        self.assertEqual(
            self.one("buy me a keyboard", "purchase.execute")["status"],
            "EXPERIMENTAL")

    def test_the_prompt_forbids_improving_on_the_block(self):
        from aletheia import converse
        flat = " ".join(converse.SYSTEM.split())
        self.assertIn("not something you know", flat.lower())
        self.assertIn("NOT_BUILT means it does not exist", flat)
        self.assertIn("would have to check", flat)


class ANoCarriesItsNextStep(unittest.TestCase):
    """A capability at NEEDS_CONFIGURATION is not "I can't" — it is "not
    yet, and here is the command"."""

    def test_a_configurable_gap_carries_the_real_instructions(self):
        match = next(m for m in self_knowledge.relevant("read my calendar",
                                                        registry=REG)
                     if m["capability"] == "calendar.read")
        self.assertTrue(match.get("to_turn_it_on"))
        self.assertTrue(any("apply calendar" in line
                            for line in match["to_turn_it_on"]))

    def test_the_instructions_come_from_setup_not_a_second_copy(self):
        """A second copy of a setup instruction disagrees by Friday."""
        from aletheia.fleet import REPO_ROOT
        body = (REPO_ROOT / "aletheia" / "self_knowledge.py").read_text(
            encoding="utf-8")
        self.assertIn("setup.steps()", body)

    def test_something_that_works_needs_no_instructions(self):
        match = next(m for m in self_knowledge.relevant("send an email",
                                                        registry=REG)
                     if m["capability"] == "email.send")
        self.assertNotIn("to_turn_it_on", match)

    def test_a_broken_checklist_does_not_break_the_answer(self):
        from aletheia import setup
        with mock.patch.object(setup, "steps", side_effect=OSError("gone")):
            self.assertTrue(self_knowledge.relevant("read my calendar",
                                                    registry=REG))


class TheWholePictureIsASHAPENotAList(unittest.TestCase):
    """"What can you do?" is not answered by 114 lines. It is answered by
    the shape plus the honest exceptions — what needs him and what is not
    built — because those are the parts he can act on."""

    def test_a_broad_question_gets_the_overview(self):
        out = self_knowledge.for_question("what can you do?", registry=REG)
        self.assertEqual(out["asked_about"], "everything")
        self.assertEqual(out["how_many"], 5)

    def test_the_exceptions_are_named_not_just_counted(self):
        out = self_knowledge.overview(REG)
        self.assertEqual([c["capability"] for c in out["waiting_on_you"]],
                         ["calendar.read"])
        self.assertEqual([c["capability"] for c in out["not_built_yet"]],
                         ["message.send"])

    def test_the_real_registry_answers_it_too(self):
        out = self_knowledge.for_question("what are you able to do?")
        self.assertEqual(out["asked_about"], "everything")
        self.assertGreater(out["how_many"], 50)
        self.assertEqual(out["by_status"]["AVAILABLE"],
                         len(capabilities.by_status("AVAILABLE")))


class ItRunsInsideEveryQuestion(unittest.TestCase):
    def test_it_needs_no_model_and_no_network(self):
        """This is in the prompt-building path of every question."""
        import re
        from aletheia.fleet import REPO_ROOT
        body = (REPO_ROOT / "aletheia" / "self_knowledge.py").read_text(
            encoding="utf-8")
        imported = set(re.findall(r"^\s*(?:from|import)\s+([\w.]+)", body,
                                  re.MULTILINE))
        for forbidden in ("reasoner", "urllib", "requests", "subprocess",
                          "socket", "http"):
            self.assertFalse({m for m in imported if forbidden in m}, forbidden)

    def test_conversation_actually_attaches_it(self):
        from aletheia.fleet import REPO_ROOT
        body = (REPO_ROOT / "aletheia" / "converse.py").read_text(
            encoding="utf-8")
        self.assertIn("self_knowledge.for_question", body)

    def test_a_broken_registry_thins_the_answer_rather_than_killing_it(self):
        with mock.patch.object(capabilities, "load_registry",
                               side_effect=OSError("gone")):
            self.assertEqual(self_knowledge.relevant("send an email"), [])


if __name__ == "__main__":
    unittest.main()
