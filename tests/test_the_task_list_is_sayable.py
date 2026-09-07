"""She could add a task by voice and had no verb for reading the list.

    "add a task to renew my passport"   ->  0.0s, instant
    "what are my tasks"                 ->  8.5s, through the planner,
                                            "Two open: - Call the dentist
                                             - Renew your passport No due
                                             dates attached to either."

Markdown bullets read out loud, sentences run together, and eight and a
half seconds to read a directory. And "mark the passport one done" asked
for an approval to change a local status, while "add a task to renew my
passport" — the same store, the same risk — ran instantly, because one
phrasing had a regex and the other did not.
"""
import unittest
from unittest import mock

from aletheia import intercom, speech, voice


def task(tid, description, status="QUEUED"):
    return {"id": tid, "description": description, "status": status}


class AskingForTheListCase(unittest.TestCase):
    def test_the_ways_he_would_ask(self):
        for said in ("what are my tasks", "whats on my list",
                     "what's on my plate", "my tasks", "list tasks",
                     "list my tasks", "what do i have to do",
                     "what's left to do", "todo list"):
            with self.subTest(said=said):
                self.assertEqual(voice.interpret(f"thea {said}")["command"],
                                 {"kind": "tasks"}, said)

    def test_it_reads_as_a_sentence(self):
        rows = [task("t1", "call the dentist"), task("t2", "renew my passport")]
        with mock.patch("aletheia.tasks.all_tasks", lambda: rows):
            said = intercom._tasks_answer()
        self.assertEqual(said,
                         "2 things on your list: call the dentist and "
                         "renew my passport.")
        self.assertNotIn("- ", said)

    def test_finished_tasks_are_not_on_the_list(self):
        rows = [task("t1", "call the dentist"),
                task("t2", "renew my passport", status="COMPLETED"),
                task("t3", "old thing", status="CANCELLED")]
        with mock.patch("aletheia.tasks.all_tasks", lambda: rows):
            said = intercom._tasks_answer()
        self.assertIn("call the dentist", said)
        self.assertNotIn("passport", said)
        self.assertNotIn("old thing", said)

    def test_an_empty_list_says_so(self):
        with mock.patch("aletheia.tasks.all_tasks", lambda: []):
            self.assertEqual(intercom._tasks_answer(), "Nothing on your list.")

    def test_a_long_list_is_summarised_rather_than_recited(self):
        rows = [task(f"t{n}", f"thing {n}") for n in range(9)]
        with mock.patch("aletheia.tasks.all_tasks", lambda: rows):
            said = intercom._tasks_answer()
        self.assertIn("and 4 more", said)

    def test_looking_at_the_list_needs_no_approval(self):
        self.assertIn("tasks", intercom.READ_ONLY_KINDS)


class MarkingOneDoneCase(unittest.TestCase):
    ROWS = [task("t1", "call the dentist"), task("t2", "renew my passport")]

    def test_he_names_it_the_way_he_says_it(self):
        for said, which in (("mark the passport one done", "passport"),
                            ("mark the passport done", "passport"),
                            ("tick off the laundry", "laundry"),
                            ("i finished the dentist task", "dentist"),
                            ("finished the passport one", "passport"),
                            ("completed the report", "report"),
                            ("check off groceries", "groceries")):
            with self.subTest(said=said):
                got = voice.interpret(f"thea {said}")["command"]
                self.assertEqual(got, {"kind": "task_done", "which": which}, said)

    def test_a_question_about_her_is_not_an_instruction(self):
        """"Did you do the dishes" starts with the same verb and is a
        question about HER. Bare "did" may not start this — only "I did"."""
        for said in ("did you do the dishes", "did you send the email",
                     "did you finish the report"):
            with self.subTest(said=said):
                got = voice.interpret(f"thea {said}")["command"]
                self.assertEqual(got["kind"], "intent", said)

    def test_a_pronoun_with_no_referent_is_not_guessed_at(self):
        got = voice.interpret("thea mark it done")["command"]
        self.assertEqual(got["kind"], "intent")

    def test_one_word_of_his_finds_it(self):
        with mock.patch("aletheia.tasks.all_tasks", lambda: self.ROWS):
            found, why = intercom._one_task("the passport one")
        self.assertIsNotNone(found, why)
        self.assertEqual(found["id"], "t2")

    def test_two_matches_ask_rather_than_guess(self):
        rows = [task("t1", "call the dentist"), task("t2", "call the plumber")]
        with mock.patch("aletheia.tasks.all_tasks", lambda: rows):
            found, why = intercom._one_task("call")
        self.assertIsNone(found)
        self.assertIn("Which one", why)
        # a CHOICE takes "or"; "and" reads as one thing made of two
        self.assertIn(" or ", why)
        self.assertNotIn(" and ", why)

    def test_nothing_matching_says_so(self):
        with mock.patch("aletheia.tasks.all_tasks", lambda: self.ROWS):
            found, why = intercom._one_task("badger")
        self.assertIsNone(found)
        self.assertIn("badger", why)

    def test_a_finished_task_is_not_a_candidate(self):
        rows = [task("t1", "call the dentist", status="COMPLETED")]
        with mock.patch("aletheia.tasks.all_tasks", lambda: rows):
            found, _why = intercom._one_task("dentist")
        self.assertIsNone(found)

    def test_the_receipt_is_a_sentence(self):
        self.assertEqual(
            speech.spoken_receipt("task_done", "marked done — renew my passport"),
            "Done: renew my passport.")


class OrListCase(unittest.TestCase):
    def test_a_choice_takes_or(self):
        self.assertEqual(speech.or_list(["a", "b", "c"]), "a, b or c")
        self.assertEqual(speech.or_list(["a"]), "a")
        self.assertEqual(speech.or_list([]), "")

    def test_a_list_still_takes_and(self):
        self.assertEqual(speech.and_list(["a", "b"]), "a and b")

class ADeadlineHeSaidIsARealDeadlineCase(unittest.TestCase):
    """"Add a task to renew my passport by friday" put "by friday" in the
    DESCRIPTION. `task_new` has always taken a deadline and `tasks.due`
    surfaces it on the beat — so the date he said was prose, which is the
    exact difference between a task list and a graveyard."""

    def test_the_deadline_is_split_out_and_resolved(self):
        got = voice.interpret(
            "thea add a task to renew my passport by friday")["command"]
        self.assertEqual(got["description"], "renew my passport")
        self.assertRegex(got["deadline"], r"^\d{4}-\d{2}-\d{2}$")
        import datetime as dt
        self.assertEqual(
            dt.date.fromisoformat(got["deadline"]).strftime("%A"), "Friday")

    def test_a_time_of_day_survives_too(self):
        got = voice.interpret(
            "thea add a task to submit the form by tomorrow at 5 pm")["command"]
        self.assertEqual(got["description"], "submit the form")
        self.assertTrue(got["deadline"].endswith("T17:00:00"), got["deadline"])

    def test_the_other_words_he_uses(self):
        for said in ("file taxes by tomorrow", "email dana before monday",
                     "pay rent due on tuesday"):
            with self.subTest(said=said):
                got = voice.interpret(f"thea add a task to {said}")["command"]
                self.assertTrue(got.get("deadline"), said)

    def test_by_that_is_not_a_deadline_is_left_alone(self):
        """"Sort the photos by date" must not acquire a due date."""
        for said in ("sort the photos by date", "order the list by size",
                     "pay by card"):
            with self.subTest(said=said):
                got = voice.interpret(f"thea add a task to {said}")["command"]
                self.assertEqual(got["description"], said, said)
                self.assertNotIn("deadline", got)

    def test_a_deadline_with_nothing_before_it_is_not_a_task_about_nothing(self):
        got = voice.interpret("thea add a task to by friday")["command"]
        self.assertEqual(got["description"], "by friday")

    def test_the_confirmation_says_the_deadline_back(self):
        """A confirmation exists so he can catch it being wrong in one
        syllable, and a date he cannot hear is one he cannot check."""
        said = speech.spoken_receipt(
            "task_new", "task renew-my-passport queued — renew my passport "
                        "due Friday")
        self.assertEqual(said, "Added a task: renew my passport due Friday.")

    def test_the_list_says_it_without_a_comma_collision(self):
        """`and_list` already uses commas: "renew my passport, due Friday
        and submit the form, due tomorrow" is unparseable by ear."""
        rows = [task("t1", "call the dentist"),
                {"id": "t2", "description": "renew my passport",
                 "status": "QUEUED", "deadline": "2026-09-11"}]
        with mock.patch("aletheia.tasks.all_tasks", lambda: rows):
            said = intercom._tasks_answer()
        self.assertIn("renew my passport due", said)
        self.assertNotIn("passport, due", said)

    def test_an_end_of_day_deadline_does_not_recite_11_59_pm(self):
        rows = [{"id": "t1", "description": "renew my passport",
                 "status": "QUEUED", "deadline": "2026-09-11"}]
        with mock.patch("aletheia.tasks.all_tasks", lambda: rows):
            said = intercom._tasks_answer()
        self.assertNotIn("11:59", said)


class TheBriefDoesNotCrashOnAnUnpulsedMachineCase(unittest.TestCase):
    """"give me the brief" -> "I couldn't: 'generated_at'." A bare KeyError,
    read out loud, from a pulse that had never been collected."""

    def test_no_pulse_says_so_and_names_the_command(self):
        with mock.patch("aletheia.pulse.PULSE_DIR", __import__("pathlib").Path("/nowhere")):
            said = intercom.execute_command({"kind": "brief"}, {"repos": {}},
                                            quote="q")
        self.assertIn("haven't collected a pulse", said)
        self.assertIn("aletheia.pulse", said)

    def test_previous_pulse_tolerates_a_pulse_with_no_timestamp(self):
        from aletheia import brief
        self.assertIsNone(brief.previous_pulse({}))
        self.assertIsNone(brief.previous_pulse({"repos": {}}))

    def test_a_message_that_cannot_stand_alone_keeps_its_class(self):
        """"I couldn't: 'generated_at'" tells him nothing; "KeyError:
        'generated_at'" is at least a thing he can report."""
        from aletheia import intents
        self.assertEqual(intents._plainly({"detail": "KeyError: 'generated_at'"}),
                         "KeyError: 'generated_at'")
        self.assertEqual(
            intents._plainly({"detail": "WorkspaceError: resume is not a file"}),
            "resume is not a file")



if __name__ == "__main__":
    unittest.main()


class MarkThatDone(unittest.TestCase):
    """"That" is ambiguous with two things open and obvious with one.

    The exclusion of "it"/"that"/"them" was right in general and wrong in
    the commonest case: he had exactly one task, said "mark that done",
    and paid a round trip and an approval for a sentence with only one
    possible meaning.
    """

    def _said(self, rows):
        with mock.patch.object(intercom, "_open_tasks", return_value=rows):
            return voice.interpret("mark that done")["command"]

    def test_one_open_task_is_not_ambiguous(self):
        rows = [{"id": "t1", "description": "email the landlord", "status": "QUEUED"}]
        self.assertEqual(self._said(rows),
                         {"kind": "task_done", "which": "email the landlord"})

    def test_two_open_tasks_still_go_to_the_planner_to_ask(self):
        rows = [{"id": "t1", "description": "email the landlord", "status": "QUEUED"},
                {"id": "t2", "description": "call the plumber", "status": "QUEUED"}]
        self.assertEqual(self._said(rows)["kind"], "intent")

    def test_nothing_open_is_not_a_task_called_that(self):
        self.assertEqual(self._said([])["kind"], "intent")

    def test_ticking_one_off_is_as_routine_as_setting_its_status(self):
        # `task_status` sets ANY status including COMPLETED and has always
        # been routine; the narrower verb was left in the world tier when
        # it was added, so it asked for approval and its sibling did not.
        self.assertEqual(intercom.tier("task_done"), intercom.tier("task_status"))
        self.assertEqual(intercom.tier("task_done"), intercom.TIER_ROUTINE)
