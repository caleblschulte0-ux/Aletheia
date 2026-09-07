"""She set a reminder, then said "Nothing yet today."

`recollection.HERS` decides which journal actors count as HER doing
something. It is matched as a prefix list, and it contained "core" — but
the Core journals every command it runs as **"operator-local-core"**,
which does not START with "core". So the single most-used path in the
system, everything he asks for out loud, was invisible to "what did you
do today?" and to "did you...?".

Found 2026-09-06 by talking to her: two reminders set, and she said she
had done nothing.

The list is prefixes over free-form strings, so it will drift again the
moment someone adds a module with a new ACTOR. The second class here
holds it against the constants that actually exist.
"""
import re
import unittest
from pathlib import Path

from aletheia import recollection

AXIOM = Path(__file__).resolve().parent.parent / "aletheia"
ACTOR_LINE = re.compile(r'^ACTOR\s*=\s*["\']([^"\']+)["\']', re.M)

# Actors that are deliberately NOT her, each with the reason. Anything
# else must be recognised, or "did you...?" silently loses a whole
# subsystem the way it lost the Core.
NOT_HERS = {
    # CI and the repo's own telemetry writers: things that happened TO
    # her, not things she did for him.
    "aletheia-ci",
}


def actors() -> dict[str, str]:
    """Every module-level ACTOR constant under aletheia/, by module."""
    found = {}
    for path in sorted(AXIOM.glob("*.py")):
        match = ACTOR_LINE.search(path.read_text(encoding="utf-8"))
        if match:
            found[path.name] = match.group(1)
    return found


def recognised(actor: str) -> bool:
    return any(actor.startswith(prefix) for prefix in recollection.HERS)


class TheCoreCountsCase(unittest.TestCase):
    def test_the_core_is_recognised_as_her(self):
        """The bug, named. Every voice command journals as this actor."""
        from aletheia import core
        self.assertEqual(core.ACTOR, "operator-local-core")
        self.assertTrue(recognised(core.ACTOR),
                        "everything he asks for out loud was invisible to her")

    def test_prefix_matching_is_what_broke_it(self):
        """"core" is in the list and "operator-local-core" is not covered
        by it — a substring is not a prefix, and the list is prefixes."""
        self.assertIn("core", recollection.HERS)
        self.assertFalse("operator-local-core".startswith("core"))

    def test_a_reminder_she_set_is_something_she_did(self):
        rows = recollection.day(hours=24)  # empty store; must not raise
        self.assertIsInstance(rows, list)


class EveryActorIsAccountedForCase(unittest.TestCase):
    """The anti-drift half: a new module with a new ACTOR must not quietly
    vanish from her memory."""

    def test_every_actor_constant_is_hers_or_deliberately_not(self):
        unaccounted = {module: actor for module, actor in actors().items()
                       if not recognised(actor) and actor not in NOT_HERS}
        self.assertEqual(unaccounted, {},
                         "these actors journal work she does, and 'what did "
                         "you do today?' cannot see them")

    def test_there_are_actors_to_check(self):
        """A regex that stops matching would make the check above vacuous."""
        self.assertGreater(len(actors()), 20)


class TheReceiptIsSpokenNotShownCase(unittest.TestCase):
    """"core:remind_at: done — reminder remind-386c2036 set for
    2026-09-06T15:00:00-05:00 — 'call the dentist'" is not an answer to
    "what did you do today?"."""

    def row(self, subject, text, kind="action"):
        return recollection._row(
            {"ts": "2026-09-06T20:00:00Z", "kind": kind,
             "actor": "operator-local-core", "subject": subject, "text": text})

    def test_a_command_receipt_becomes_a_sentence(self):
        said = self.row(
            "core:remind_at",
            "done — reminder remind-386c2036 set for "
            "2026-09-06T15:00:00-05:00 — 'call the dentist'")["what"]
        self.assertIn("call the dentist", said)
        self.assertNotIn("remind-386c2036", said)
        self.assertNotIn("core:remind_at", said)
        self.assertNotIn("2026-09-06T15:00", said)

    def test_a_successful_outcome_word_is_dropped(self):
        said = self.row("core:note", "done — noted")["what"]
        self.assertFalse(said.lower().startswith("done"))

    def test_a_failure_keeps_its_outcome_because_that_is_the_point(self):
        said = self.row("core:email_draft", "refused — no address for 'mum'")["what"]
        self.assertIn("refused", said)

    def test_an_ordinary_journal_line_keeps_its_subject(self):
        said = self.row("repo:aletheia", "health red -> green")["what"]
        self.assertIn("repo:aletheia", said)
        self.assertIn("health red", said)

    def test_ids_are_stripped_from_ordinary_lines_too(self):
        said = self.row("webtask", "finished run-a1b2c3d4e5f6")["what"]
        self.assertNotIn("a1b2c3d4e5f6", said)


if __name__ == "__main__":
    unittest.main()
