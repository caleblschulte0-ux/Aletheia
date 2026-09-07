"""Three answers that denied something she has, or read like a log.

  "what do I have to do this week"
    -> "I don't have a calendar or task list connected right now"
    She has a task store. She had just read it. It was EMPTY, the key was
    simply absent from her context, and a model asked to answer without it
    concluded the capability did not exist. Same shape as the journal
    defect in CLAUDE.md: absence of rows is not absence of the store.

  "what's the weather going to be tomorrow"
    -> "I couldn't: ... Page.goto: net::ERR_CONNECTION_RESET at
       https://example.com/ Call log: - navigating to ..."
    A stack trace, out loud.

  "make me a spreadsheet of my monthly bills"
    -> "... until you run `python -m aletheia.standing on` once."
    A backtick is either silence or the word "backtick".
"""
import unittest
from unittest import mock

from aletheia import browse, converse, speech


class AnEmptyListStillProvesTheList(unittest.TestCase):
    def test_the_key_is_there_even_when_nothing_is_open(self):
        with mock.patch("aletheia.tasks.all_tasks", return_value=[]):
            facts = converse.situation()
        self.assertEqual(facts.get("open_tasks"), [])
        self.assertIn("never say you have no task list",
                      facts.get("open_tasks_note", ""))

    def test_an_unreadable_store_says_that_instead(self):
        with mock.patch("aletheia.tasks.all_tasks", side_effect=OSError("gone")):
            facts = converse.situation()
        self.assertIn("could not be read", facts.get("open_tasks_note", ""))
        self.assertNotIn("open_tasks", facts)

    def test_real_tasks_still_travel(self):
        rows = [{"status": "PROPOSED", "description": "call the plumber",
                 "deadline": "2026-09-09"}]
        with mock.patch("aletheia.tasks.all_tasks", return_value=rows):
            facts = converse.situation()
        self.assertEqual(facts["open_tasks"], ["call the plumber (due 2026-09-09)"])
        self.assertNotIn("open_tasks_note", facts)


class ANetworkErrorIsASentence(unittest.TestCase):
    def test_playwrights_call_log_never_reaches_a_room(self):
        said = browse._network_reason(RuntimeError(
            'Page.goto: net::ERR_CONNECTION_RESET at https://example.com/\n'
            'Call log:\n  - navigating to "https://example.com/", waiting until'))
        self.assertNotIn("Call log", said)
        self.assertIn("the connection was reset", said)

    def test_the_code_is_kept_for_the_screen(self):
        said = browse._network_reason(RuntimeError("net::ERR_NAME_NOT_RESOLVED"))
        self.assertIn("net::ERR_NAME_NOT_RESOLVED", said)
        self.assertIn("did not resolve", said)

    def test_an_unknown_code_is_still_english_first(self):
        said = browse._network_reason(RuntimeError("net::ERR_SOMETHING_NEW"))
        self.assertTrue(said.startswith("the browser refused"), said)
        self.assertIn("net::ERR_SOMETHING_NEW", said)

    def test_say_reason_drops_the_code_and_keeps_the_sentence(self):
        why = ("the browser launched but could not load https://example.com — "
               "the connection was reset (net::ERR_CONNECTION_RESET)")
        said = browse.say_reason(why)
        self.assertNotIn("net::", said)
        self.assertIn("the connection was reset", said)

    def test_a_timeout_has_no_code_and_still_says_something(self):
        self.assertIn("timed out", browse._network_reason(RuntimeError("Timeout 20000ms")))


class NoMarkupInAFailure(unittest.TestCase):
    def test_the_shared_stripper_removes_markup_too(self):
        # Any module's message can end up spoken through `plainly`; two of
        # them carried backticks around a command.
        self.assertEqual(speech.plainly("run `hass observe` first"),
                         "run hass observe first")
        # A one-word remainder keeps its class name on purpose — "gone"
        # alone is not an answer — so this uses a real message.
        self.assertEqual(speech.plainly("OSError: **the file is gone**"),
                         "the file is gone")


if __name__ == "__main__":
    unittest.main()
