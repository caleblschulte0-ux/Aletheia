"""A store he can write to and cannot ask about produces a contradiction.

Three of these turned up in one afternoon, all found by talking to her
and all identical underneath:

    "Added to the shopping list: milk."  /  "I don't have a shopping list."
    "Every Monday at 9 am I'll remind you."  /  "I can't reminder.cancel yet."
    "I don't have a record of jobs you've applied to"  (there is one)

The writer shipped, the reader did not, and the model — asked about a
store nothing in its context mentions — denies the store exists. That is
worse than an error: he goes and keeps the list somewhere else.

So every ROUTINE (write) kind has to name the READ kind he uses to ask
about what it did, or say in one line why nothing needs to. Adding a new
writer fails this test until somebody answers that question. It is a
list, deliberately — a mechanical check would have to guess which store
a handler touches, and a wrong guess here is a test that passes for the
wrong reason.
"""
import unittest

from aletheia import intercom

# writer -> the read-only kind he asks with, or "" and a reason.
READER_FOR = {
    # Stopping a worker changes what is running, and "what are your
    # workers doing" is how he finds out it worked. A runtime he can
    # start things in and not see is the exact shape this file exists
    # to prevent.
    # Closing the microphone changes what is listening, and "is the mic
    # on" is how he confirms it. A switch he can flip and not see is the
    # shape this file exists to prevent — doubly so for a microphone.
    "mic_off": "mic",
    # He turned it off; "are you using my ChatGPT" is how he sees it.
    "chatgpt_off": "chatgpt",
    # Pressing pause is its own confirmation: the room goes quiet.
    # There is no store to read back, so this is the reader.
    "music": "running",
    "agent_stop": "agents",
    "agents_pause": "agents",
    "task_new": "tasks",
    "task_status": "tasks",
    "task_done": "tasks",
    "shopping_add": "shopping_list",
    "shopping_off": "shopping_list",
    "remind_at": "reminders",
    "remind_daily": "reminders",
    "remind_weekly": "reminders",
    "reminder_off": "reminders",
    "contact_add": "contacts",
    "watch_email_from": "watches",
    "remember": "recall",
    "plan_new": "projects",
    "plan_add_step": "projects",
    "plan_step": "projects",
    "plan_set": "projects",
    "apply_prepare": "applications",
    "apply_campaign": "applications",
    # She wrote it into the workspace; `file_list` is how he sees it is
    # there, and `file_read` cannot read a .docx back as text.
    "doc_make": "file_list",
    "file_write": "file_list",
    "file_edit": "file_read",
    "file_move": "file_list",
    "file_delete": "file_list",
    "compose": "file_read",
    "media_trim": "media_probe",
    "media_join": "media_probe",
    "media_audio": "media_probe",
    "media_captions": "media_probe",
    "media_convert": "media_probe",
    "notify_operator": "notify_check",
    "notify_clear": "notify_check",
    "notify_snooze": "notify_check",
    # He is the one being told. "What are you announcing" is answered
    # from the announce setting itself, which `setup_status` carries.
    "announce_set": "setup_status",
    # `handle` files an intent and answers with its own state; the thing
    # it produces is a task or a plan, both readable above.
    "handle": "tasks",
}


class EveryWriterCanBeAskedAbout(unittest.TestCase):
    def test_every_routine_kind_names_its_reader(self):
        missing = sorted(set(intercom.ROUTINE_KINDS) - set(READER_FOR))
        self.assertEqual(
            missing, [],
            "these write something and nothing here says how he asks about "
            "it. Name the read-only kind, or add one: " + ", ".join(missing))

    def test_the_readers_are_real_and_read_only(self):
        for writer, reader in sorted(READER_FOR.items()):
            if not reader:
                continue
            self.assertIn(reader, intercom.KIND_ARGS, f"{writer} -> {reader}")
            self.assertIn(reader, intercom.READ_ONLY_KINDS, f"{writer} -> {reader}")

    def test_it_does_not_list_kinds_that_no_longer_exist(self):
        stale = sorted(set(READER_FOR) - set(intercom.KIND_ARGS))
        self.assertEqual(stale, [], f"gone from the grammar: {stale}")

    def test_every_reader_really_answers(self):
        # A reader that raises for an empty store is not a reader — the
        # empty case is the one he hits first.
        self.assertTrue(intercom.shopping_answer())
        self.assertTrue(intercom._reminders_answer())
        self.assertTrue(intercom._contacts_answer())
        self.assertTrue(intercom._watches_answer())
        self.assertTrue(intercom._applications_answer())
        self.assertTrue(intercom._tasks_answer())


if __name__ == "__main__":
    unittest.main()
