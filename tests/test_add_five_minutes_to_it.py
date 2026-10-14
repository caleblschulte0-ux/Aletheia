""""How much time is left", then "add 5 minutes to it" (2026-10-14: to a
model); "what time is that reminder" after a weekly one (to a model); and
"remind me to get stamps when I get to the post office" (to a model, which
offered the shopping list).
"""
import unittest
from unittest import mock

from aletheia import policy, tasks, voice


def said(sentence):
    with mock.patch.object(policy, "all_approvals", return_value=[]):
        return voice.interpret(f"thea {sentence}")


class TheTimerSheJustNamed(unittest.TestCase):
    def test_her_answer_about_the_timer_makes_it_the_timer(self):
        with mock.patch.object(voice, "_running_once", return_value=[("2026-10-14T16:00:00+00:00", "timer is up")]), \
                mock.patch.object(voice, "_previous_ask", return_value="how much time is left"), \
                mock.patch.object(voice, "_her_last_answer", return_value="20 minutes left on your 20-minute timer."), \
                mock.patch.object(voice, "_more_on_the_timer", return_value={"command": {"kind": "timer_more"}, "say": None}) as more:
            said("add 5 minutes to it")
        more.assert_called_once_with(5, named="")


class WhenIsThatWeeklyReminder(unittest.TestCase):
    def test_her_confirmation_says_when(self):
        with mock.patch.object(voice, "_her_last_answer", return_value="Every Tuesday at 9 pm I'll remind you: take out the trash."):
            got = said("what time is that reminder")
        self.assertEqual(got["say"], "That's every Tuesday at 9 pm: take out the trash.")


class AndAlsoAtNine(unittest.TestCase):
    def test_the_same_repeat_again_at_the_second_time(self):
        with mock.patch.object(voice, "_her_last_answer", return_value="Every day at 9 am I'll remind you: take your pills."), \
                mock.patch.object(voice, "_recent_ask_of", side_effect=lambda kind, *_a: (
                    {"kind": "remind_daily", "time": "09:00", "text": "take my pills", "replaces": "x"}
                    if kind == "remind_daily" else {})):
            got = said("and also at 9 pm")["command"]
        self.assertEqual(got, {"kind": "remind_daily", "time": "21:00", "text": "take my pills"})


class WhenIsTheNextOne(unittest.TestCase):
    def test_after_a_skip_it_is_the_day_she_said(self):
        with mock.patch.object(voice, "_her_last_answer",
                               return_value="Skipped tomorrow at 9 am: water the plants. It's back Sunday at 9 am."):
            self.assertEqual(said("when is the next one")["say"], "Sunday at 9 am: water the plants.")


class NoWaitFriday(unittest.TestCase):
    def test_a_bare_day_after_a_reminder_moves_it(self):
        moved = {"command": {"kind": "remind_at", "at": "x", "text": "call the vet"}, "say": None}
        real = voice._interpret
        asked = []

        def interp(sentence, *a, **k):
            if sentence.startswith("make it "):
                asked.append(sentence)
                return moved
            return real(sentence, *a, **k)
        with mock.patch.object(voice, "_she_just_named_a_reminder", return_value=True), \
                mock.patch.object(voice, "_interpret", side_effect=interp):
            for sentence in ("friday instead", "actually thursday", "saturday"):
                self.assertEqual(real(sentence), moved)
        self.assertEqual(asked, ["make it friday", "make it thursday", "make it saturday"])

    def test_no_wait_is_a_correction_word(self):
        self.assertEqual(voice._without_preamble("no wait, friday"), "friday")
        self.assertEqual(voice._without_preamble("wait, 11 am"), "11 am")
        self.assertEqual(voice._without_preamble("wait for me"), "wait for me")


class AWeekBeforeTheAnniversary(unittest.TestCase):
    def test_said_or_asked_about_the_note_dates_it(self):
        import datetime as dt
        from aletheia import localtime, quick
        on = dt.datetime.now(localtime.operator_tz()).date() + dt.timedelta(days=40)
        note = f"our anniversary is {on.strftime('%B').lower()} {on.day}"
        with mock.patch.object(quick, "_noted_dates", return_value=[]), \
                mock.patch.object(quick, "_notes", return_value=[{"text": note}]):
            asked = voice._before_a_noted_date("remind me 3 days before", "how long until our anniversary")
            said_it = voice._before_a_noted_date("remind me a week before", note)
            other = voice._before_a_noted_date("remind me a week before", "how long until christmas")
        self.assertEqual(dt.datetime.fromisoformat(asked["command"]["at"]).date(), on - dt.timedelta(days=3))
        self.assertEqual(said_it["command"]["text"], f"your anniversary is {on.strftime('%B')} {on.day} - in a week")
        self.assertIsNone(other)


class AnErrandAtAPlace(unittest.TestCase):
    def test_it_goes_on_his_tasks_with_the_place(self):
        with mock.patch.object(tasks, "all_tasks", return_value=[]):
            got = said("remind me to get stamps when i get to the post office")
        self.assertEqual((got["command"]["kind"], got["command"]["description"]),
                         ("task_new", "get stamps at the post office"))
        self.assertIn("can't see where you are", got["say"])
        with mock.patch.object(tasks, "all_tasks", return_value=[]):
            got = said("remind me to pick up my prescription next time i'm at walgreens")
        self.assertEqual(got["command"]["description"], "pick up my prescription at walgreens")

    def test_groceries_and_home_keep_their_own_doors(self):
        self.assertEqual(said("remind me to buy milk when i get to the store")["command"]["kind"], "shopping_add")
        self.assertIn("I'm home", said("remind me to call mom when i get home")["say"])



class ForgetMyDoctor(unittest.TestCase):
    def test_the_older_versions_of_the_same_fact_go_too(self):
        from aletheia import intercom, journal, quick
        rows = [{"text": "my doctor is Dr. Patel"}, {"text": "my dentist is Dr. Lee"}, {"text": "my doctor is Dr. Kim"}]
        with mock.patch.object(quick, "_notes", return_value=rows), \
                mock.patch.object(journal, "append") as wrote:
            self.assertEqual(intercom._forget_older_versions("my doctor is Dr. Kim"), 2)
            self.assertEqual(intercom._forget_older_versions("the plumber comes friday"), 0)
        self.assertEqual([c.args[2] for c in wrote.call_args_list], ["my doctor is Dr. Patel", "my doctor is Dr. Kim"])


if __name__ == "__main__":
    unittest.main()
