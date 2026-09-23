"""Night sweep 2026-09-23, every frontier off: "remember that my landlord is
Mr Okafor" was compiled into a plan waiting for his approve; "what's my
landlord's name", "what did I tell you about the car", "when is my lease
up" and "what notes do you have" each waited on a model for a store she
holds. And the pursuit drafted an email to his own inbox and asked his yes
to send it."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import pursuit, quick, voice

NOTES = [
    {"ts": "2026-09-23T03:18:00Z", "kind": "note", "subject": "operator", "text": "my landlord is Mr Okafor"},
    {"ts": "2026-09-23T03:19:00Z", "kind": "note", "subject": "operator", "text": "the car needs an oil change"},
    {"ts": "2026-09-23T03:20:00Z", "kind": "action", "subject": "apply", "text": "the lease car was applied to"},
]


class RememberThatIsANote(unittest.TestCase):
    def test_a_fact_is_a_note_and_a_reminder_is_not(self):
        out = voice.interpret("thea remember that my landlord is Mr Okafor")
        self.assertEqual(out["command"]["kind"], "note")
        self.assertEqual(out["command"]["text"], "my landlord is Mr Okafor")
        out = voice.interpret("remember my lease is up in March")
        self.assertEqual(out["command"], {"kind": "note", "text": "my lease is up in March"})
        self.assertNotEqual(voice.interpret("remember to call mom at 3")["command"].get("kind"), "note")
        self.assertNotEqual(voice.interpret("remember me")["command"].get("kind"), "note")


class RecallReadsHerStores(unittest.TestCase):
    def test_what_he_told_her_comes_back_in_his_words(self):
        with mock.patch("aletheia.journal.entries", return_value=NOTES), \
             mock.patch("aletheia.memory.everything", return_value={}):
            self.assertEqual(quick.answer("what did I tell you about the car"),
                             "You told me: the car needs an oil change.")
            self.assertEqual(quick.answer("what's my landlord's name"), "You told me: my landlord is Mr Okafor.")
            self.assertIn("nothing about lease", quick.answer("when is my lease up"))
            said = quick.answer("what notes do you have")
            self.assertTrue(said.startswith("2 notes: the car needs an oil change; my landlord is Mr Okafor"), said)

    def test_memory_answers_too_and_nothing_is_said_as_nothing(self):
        with mock.patch("aletheia.journal.entries", return_value=[]), \
             mock.patch("aletheia.memory.everything",
                        return_value={"people": {"sister": {"value": "Dana"}},
                                      "home": {"wifi_password": {"value": "hunter2", "kind": "explicit"}}}):
            self.assertEqual(quick.answer("what's my sister's name"), "Sister: Dana.")
            self.assertEqual(quick.answer("do you remember my wifi password"), "Wifi password: hunter2.")
            self.assertEqual(quick.answer("what notes do you have"),
                             'No notes yet. Say "note that" or "remember that" and I\'ll keep it.')


class ANoteToHimIsNotMail(unittest.TestCase):
    def test_a_note_the_model_addressed_to_him_is_a_suggestion_not_a_draft(self):
        record = {"id": "opp-1", "evidence": [], "subject": {"name": "GitLab"}}
        move = {"id": "m1", "kind": "note_to_person", "why": "he should check the accessibility question",
                "detail": {"to": "Caleb", "text": "Verify the accessibility question status.", "grounded_on": ["e1"]}}
        published = []
        with mock.patch.object(pursuit, "_address_of", return_value=("openrangeinteractive@gmail.com", "Caleb")), \
             mock.patch("aletheia.profile.known", return_value={"email": "openrangeinteractive@gmail.com"}), \
             mock.patch("aletheia.mail.available", return_value=(True, "")), \
             mock.patch("aletheia.mail.draft", side_effect=AssertionError("drafted mail to himself")), \
             mock.patch("aletheia.notifications.publish", side_effect=lambda *a, **k: published.append((a, k)) or {}):
            out = pursuit._do_note(record, move, dt.datetime(2026, 9, 23, 8, 0, tzinfo=dt.timezone.utc))
        self.assertEqual(out["state"], "handed to him")
        self.assertEqual(len(published), 1)
        self.assertIn("GitLab", published[0][0][0])


if __name__ == "__main__":
    unittest.main()
