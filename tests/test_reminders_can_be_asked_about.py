"""She could set a reminder and had no verb for reading or stopping one.

Out loud, "cancel that reminder" produced a sentence that contradicted
itself in the space of two clauses:

    1 step ready — Cancel a reminder. Say approve to run it.
    I can't reminder.cancel yet. I've put it on the build list.

...while `scheduler.all_schedules` and `scheduler.set_enabled` had been
there the whole time. Same shape as the weekly reminder: the machinery
existed, the grammar could not say it, and the planner filled the hole
with an invented capability id it then read aloud.
"""
import unittest
from unittest import mock

from aletheia import act, intercom, scheduler, speech, voice

# NOTHING HERE TOUCHES THE REAL SCHEDULE STORE. An earlier draft of this
# file set ALETHEIA_PRIVATE_STATE and reloaded `scheduler` to point it
# somewhere safe — which rebinds the module for every test that runs
# after it, the exact contamination `-t .` exists to prevent, in a file
# about not breaking things. Every store here is a mock.


class HeCanAskWhatIsSet(unittest.TestCase):
    def test_the_question_never_reaches_a_model(self):
        for said in ("what reminders do I have", "list my reminders",
                     "my reminders", "what am I being reminded about"):
            got = voice.interpret(said)
            self.assertEqual(got["command"], {"kind": "reminders"}, said)

    def test_stopping_one_is_heard_two_ways(self):
        self.assertEqual(voice.interpret("stop reminding me about the trash")["command"],
                         {"kind": "reminder_off", "which": "the trash"})
        self.assertEqual(voice.interpret("cancel the reminder about the gym")["command"],
                         {"kind": "reminder_off", "which": "the gym"})

    def test_a_question_is_never_read_as_a_new_reminder(self):
        # "reminders" and "remind me" are one letter apart in a noisy room.
        self.assertEqual(voice.interpret("reminders")["command"]["kind"], "reminders")

    def test_reading_is_read_only_and_stopping_is_routine(self):
        self.assertIn("reminders", intercom.READ_ONLY_KINDS)
        self.assertIn("reminder_off", intercom.ROUTINE_KINDS)
        # Disabling is reversible by saying the opposite, which is the
        # whole test for the routine tier.
        self.assertEqual(intercom.tier("reminder_off"), intercom.TIER_ROUTINE)


class TheWholeConversationWorks(unittest.TestCase):
    scheduler = scheduler

    def run_it(self, cmd):
        return intercom.execute_command(cmd, {})

    def test_nothing_set_says_so(self):
        with mock.patch.object(intercom, "_reminder_schedules", return_value=[]):
            self.assertEqual(self.run_it({"kind": "reminders"}),
                             "You have no reminders set.")

    def test_set_then_list_then_stop(self):
        made = []

        def all_schedules():
            return made

        def create(sid, command, **kw):
            made.append({"id": sid, "command": command, "enabled": True, **kw})
            return made[-1]

        def set_enabled(sid, enabled):
            for spec in made:
                if spec["id"] == sid:
                    spec["enabled"] = enabled
            return {}

        with mock.patch.object(self.scheduler, "create", create), \
             mock.patch.object(self.scheduler, "all_schedules", all_schedules), \
             mock.patch.object(self.scheduler, "set_enabled", set_enabled):
            self.run_it({"kind": "remind_weekly", "days": ["monday"],
                         "time": "09:00", "text": "take out the trash"})
            self.run_it({"kind": "remind_daily", "time": "08:00", "text": "stretch"})
            listed = self.run_it({"kind": "reminders"})
            self.assertIn("2 reminders", listed)
            self.assertIn("take out the trash — every Monday at 9 am", listed)
            self.assertIn("stretch — every day at 8 am", listed)

            said = self.run_it({"kind": "reminder_off", "which": "the trash"})
            self.assertEqual(speech.spoken_receipt("reminder_off", said),
                             "Stopped reminding you: take out the trash — "
                             "every Monday at 9 am.")
            self.assertIn("1 reminder", self.run_it({"kind": "reminders"}))

    def test_it_disables_and_never_deletes(self):
        spec = {"id": "remind-daily-1", "kind": "daily", "time": "08:00",
                "enabled": True, "command": {"kind": "notify_operator",
                                             "text": "stretch"}}
        with mock.patch.object(self.scheduler, "all_schedules", return_value=[spec]), \
             mock.patch.object(self.scheduler, "set_enabled") as off:
            self.run_it({"kind": "reminder_off", "which": "stretch"})
        off.assert_called_once_with("remind-daily-1", False)

    def test_two_that_match_is_a_question_not_a_guess(self):
        rows = [{"id": "a", "kind": "daily", "time": "08:00", "enabled": True,
                 "command": {"kind": "notify_operator", "text": "call mom"}},
                {"id": "b", "kind": "daily", "time": "09:00", "enabled": True,
                 "command": {"kind": "notify_operator", "text": "call the bank"}}]
        with mock.patch.object(intercom, "_reminder_schedules", return_value=rows):
            with self.assertRaises(act.Refused) as caught:
                self.run_it({"kind": "reminder_off", "which": "call"})
        self.assertIn(" or ", str(caught.exception))

    def test_a_reminder_he_does_not_have_is_refused_in_words(self):
        with mock.patch.object(intercom, "_reminder_schedules", return_value=[]):
            with self.assertRaises(act.Refused):
                self.run_it({"kind": "reminder_off", "which": "the dog"})

    def test_only_reminders_are_listed_not_every_schedule(self):
        rows = [{"id": "sync", "kind": "interval", "enabled": True,
                 "command": {"kind": "pulse"}},
                {"id": "off", "kind": "daily", "time": "07:00", "enabled": False,
                 "command": {"kind": "notify_operator", "text": "old one"}},
                {"id": "live", "kind": "daily", "time": "08:00", "enabled": True,
                 "command": {"kind": "notify_operator", "text": "stretch"}}]
        with mock.patch.object(self.scheduler, "all_schedules", return_value=rows):
            said = self.run_it({"kind": "reminders"})
        self.assertIn("1 reminder", said)
        self.assertIn("stretch", said)
        self.assertNotIn("old one", said)


class APlaceSheDoesNotKnow(unittest.TestCase):
    def test_it_is_a_sentence_not_a_keyerror(self):
        # `That failed: KeyError: "no place matches 'the airport'"` — he
        # cannot act on that; he can act on being asked for the address.
        from aletheia import places
        with mock.patch.object(places, "resolve",
                               side_effect=KeyError("no place matches 'the airport'")):
            with self.assertRaises(act.Refused) as caught:
                intercom.execute_command(
                    {"kind": "travel_time", "place": "the airport"}, {})
        said = str(caught.exception)
        self.assertNotIn("KeyError", said)
        self.assertIn("I don't know where the airport is", said)

    def test_an_ambiguous_place_asks_which(self):
        from aletheia import places
        with mock.patch.object(places, "resolve",
                               side_effect=LookupError("ambiguous")):
            with self.assertRaises(act.Refused) as caught:
                intercom.execute_command(
                    {"kind": "travel_time", "place": "the office"}, {})
        self.assertIn("which one", str(caught.exception).lower())


if __name__ == "__main__":
    unittest.main()


class ContactsAndWatchesCanBeAskedAbout(unittest.TestCase):
    """`contact_add` and `watch_email_from` were writers with no reader.

    Found by the same sweep, before either produced a contradiction out
    loud — which is the point of doing the sweep rather than waiting.
    """

    def test_the_questions_are_deterministic(self):
        self.assertEqual(voice.interpret("list my contacts")["command"],
                         {"kind": "contacts"})
        self.assertEqual(voice.interpret("what are you watching for")["command"],
                         {"kind": "watches"})

    def test_his_possessive_is_not_part_of_her_name(self):
        # "what's MY MUM's number" — a substring match on "my mum" finds a
        # contact called "Mum" never.
        got = voice.interpret("what's my mom's number")
        self.assertEqual(got["command"]["kind"], "contacts")
        rows = [{"id": "mom", "display_name": "Mom", "phones": ["555-1234"]}]
        from aletheia import contacts
        with mock.patch.object(contacts, "all_contacts", return_value=rows):
            said = intercom.execute_command(got["command"], {})
        self.assertIn("555-1234", said)

    def test_an_empty_store_does_not_deny_the_store(self):
        from aletheia import contacts
        with mock.patch.object(contacts, "all_contacts", return_value=[]):
            self.assertEqual(intercom.execute_command({"kind": "contacts"}, {}),
                             "You have no contacts saved with me.")

    def test_a_watch_is_said_as_the_sentence_it_was_created_with(self):
        from aletheia import events as bus
        watcher = {"id": "watch-1", "once": True,
                   "note": "operator asked: tell me when email arrives from Dana"}
        with mock.patch.object(bus, "list_watchers", return_value=[watcher]), \
             mock.patch.object(bus, "watcher_state", return_value="ACTIVE"):
            said = intercom.execute_command({"kind": "watches"}, {})
        self.assertIn("tell me when email arrives from Dana", said)
        self.assertNotIn("operator asked", said)

    def test_a_finished_watch_is_not_still_being_watched(self):
        from aletheia import events as bus
        watcher = {"id": "watch-1", "once": True, "note": "x: done one"}
        with mock.patch.object(bus, "list_watchers", return_value=[watcher]), \
             mock.patch.object(bus, "watcher_state", return_value="TRIGGERED"):
            said = intercom.execute_command({"kind": "watches"}, {})
        self.assertIn("not watching for anything", said)
