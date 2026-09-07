"""'I don't have a record of jobs you've applied to — no application tracker.'

`apply_run` has written a record for every staged and submitted
application since it was written. The sentence was accidentally true in
an empty sandbox and false the moment he has applied to anything — and
unfalsifiable to him either way, which is the whole problem: he would go
and keep the list somewhere else.

Third of the same kind in one afternoon (reminders, the shopping list,
this): a store with a writer and no reader, and a model asked to answer
from a context that never mentions it.
"""
import unittest
from unittest import mock

from aletheia import apply_run, intercom, voice


def run(state="SUBMITTED", title="Stripe — Backend Engineer", url="https://x.co/1"):
    return {"id": "apply-1", "state": state, "url": url, "page_title": title}


class HeCanAsk(unittest.TestCase):
    def test_the_question_is_deterministic(self):
        for said in ("what jobs have I applied to", "what have I applied to",
                     "list my applications"):
            self.assertEqual(voice.interpret(said)["command"],
                             {"kind": "applications"}, said)

    def test_searching_boards_is_still_the_other_direction(self):
        # `jobs` searches for NEW ones. Confusing the two answers a
        # different question than the one he asked.
        self.assertNotEqual(voice.interpret("find me a job")["command"],
                            {"kind": "applications"})

    def test_it_is_read_only(self):
        self.assertIn("applications", intercom.READ_ONLY_KINDS)


class TheAnswerComesFromTheStore(unittest.TestCase):
    def answer(self, rows):
        with mock.patch.object(apply_run, "all_runs", return_value=rows):
            return intercom.execute_command({"kind": "applications"}, {})

    def test_none_yet_says_so_without_denying_the_record(self):
        self.assertEqual(self.answer([]),
                         "You haven't applied to anything through me yet.")

    def test_it_names_what_was_sent(self):
        said = self.answer([run()])
        self.assertIn("1 application sent", said)
        self.assertIn("Stripe — Backend Engineer", said)

    def test_staged_and_sent_are_different_facts(self):
        said = self.answer([run(), run(state="AWAITING_YOU", title="Acme — SRE")])
        self.assertIn("1 application sent", said)
        self.assertIn("staged and waiting on you", said)
        self.assertIn("Acme — SRE", said)

    def test_a_record_with_no_title_falls_back_to_where_it_was(self):
        said = self.answer([run(title="", url="https://jobs.example/1234")])
        self.assertIn("jobs.example", said)

    def test_it_says_applications_not_mores(self):
        said = self.answer([run(), run(state="AWAITING_YOU"),
                            run(state="AWAITING_YOU")])
        self.assertNotIn("mores", said)
        self.assertIn("2 applications staged", said)


if __name__ == "__main__":
    unittest.main()
