"""Routine reversible work happens quietly, and nothing else changes.

His rule, 2026-09-18: tell him when something important FINISHES, FAILS,
CHANGES or genuinely NEEDS HIM, and let routine reversible work happen
quietly.

That rule had nowhere to live. `IMPORTANT` is not a description of a
notice, it is a request to interrupt — it is what the desktop toasts,
what `announce` speaks into the room and what the wall headlines — and
forty-two call sites were each deciding, on their own, how loud his house
is. The job hunt alone published one IMPORTANT per application SENT:
overnight that is twenty-five toasts for twenty-five things that went
exactly as he approved them.

The policy lives in `publish`, because a rule forty-two callers have to
remember is a rule that holds in forty-one places.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import desktop_notify, notifications


class TheCapOnRoutineWork(unittest.TestCase):
    def test_routine_work_may_not_interrupt_him(self):
        for priority in notifications.INTERRUPTS:
            self.assertNotIn(
                notifications.loudness(priority, notifications.ROUTINE),
                notifications.INTERRUPTS)

    def test_quiet_is_not_the_same_as_dropped(self):
        """A notification she silently declined to write is a store with a
        writer and no reader — and the receipt is what the activity view
        and "how did the job hunt go" are counted from."""
        self.assertIn(notifications.QUIET, notifications.PRIORITIES)
        with mock.patch.object(notifications, "NOTICES_DIR", self.tmp):
            notice = notifications.publish("Application sent", "Acme",
                                           priority="IMPORTANT",
                                           about=notifications.ROUTINE)
        self.assertEqual(notice["priority"], notifications.QUIET)
        self.assertEqual(notice["about"], notifications.ROUTINE)
        self.assertNotIn(notice["priority"], desktop_notify.LOUD)

    def test_the_policy_can_only_ever_make_her_quieter(self):
        """A policy that PROMOTES is a policy that can invent an
        interruption, which is the opposite of what this is for."""
        order = ("INFO", "NORMAL", "IMPORTANT", "URGENT")
        for about in sorted(notifications.ABOUT):
            for index, priority in enumerate(order):
                got = notifications.loudness(priority, about)
                self.assertLessEqual(order.index(got), index,
                                     f"{about} made {priority} louder")

    def test_the_four_things_worth_interrupting_for_are_left_alone(self):
        for about in (notifications.FINISHED, notifications.FAILED,
                      notifications.CHANGED, notifications.NEEDS_YOU):
            self.assertEqual(
                notifications.loudness("IMPORTANT", about), "IMPORTANT")

    def test_a_caller_that_says_nothing_keeps_what_it_asked_for(self):
        """So this can be adopted one noisy caller at a time rather than
        in a flag day — and so a caller nobody has looked at yet is never
        silently silenced."""
        self.assertEqual(notifications.loudness("IMPORTANT", ""), "IMPORTANT")

    def test_an_unknown_kind_is_refused_rather_than_ignored(self):
        with self.assertRaises(ValueError):
            notifications.loudness("IMPORTANT", "PROBABLY_FINE")

    def setUp(self):
        import tempfile
        from pathlib import Path
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._dir.name)

    def tearDown(self):
        self._dir.cleanup()


class TheNoisyCallersOfRecord(unittest.TestCase):
    """The ones that were actually loud on his machine, by name.

    A hand-kept list on purpose, the same reason
    `test_every_writer_has_a_reader` keeps one: a mechanical check would
    have to guess which notices matter to him, and a wrong guess is a test
    that passes for the wrong reason.
    """

    def test_an_application_going_out_as_approved_is_routine(self):
        from aletheia import runtime
        source = _source_of(runtime, "apply-sent")
        self.assertIn("about=notifications.ROUTINE", source)

    def test_an_application_that_could_not_be_sent_still_interrupts(self):
        from aletheia import runtime
        for key in ("apply-failed", "apply-grant-failed"):
            self.assertIn("about=notifications.FAILED", _source_of(runtime, key))

    def test_a_subsystem_failing_every_beat_still_interrupts(self):
        from aletheia import core
        self.assertIn("about=notifications.FAILED",
                      _source_of(core, "runtime-failure"))

    def test_a_reminder_he_set_still_interrupts(self):
        from aletheia import intercom
        self.assertIn("about=notifications.NEEDS_YOU",
                      _source_of(intercom, '"Reminder", cmd["text"]'))


class NothingTechnicalInANotificationBody(unittest.TestCase):
    """A notification is READ OUT — by `announce`, by the wall, by the phone.

    Every body in `runtime` used to be written for a log: a URL and a class
    name, which is a perfectly good line in a file and nothing at all out
    loud. The diagnosis is still in the journal with the traceback attached.
    """

    def test_a_crash_becomes_a_reason_and_a_url_becomes_a_place(self):
        from aletheia import runtime
        said = runtime._why_not(
            {"url": "https://boards.greenhouse.io/acme/jobs/41"},
            TimeoutError("Page.goto: net::ERR_CONNECTION_RESET"))
        self.assertNotIn("TimeoutError", said)
        self.assertNotIn("https://", said)
        self.assertNotIn("net::", said)

    def test_the_company_beats_the_link_when_she_knows_it(self):
        from aletheia import runtime
        self.assertEqual(runtime._where({"company": "Acme", "url": "https://x.io/1"}),
                         "Acme")
        self.assertEqual(runtime._where({"url": "https://boards.greenhouse.io/x"}),
                         "boards.greenhouse.io")
        self.assertEqual(runtime._where({}), "the site")

    def test_no_rule_id_is_ever_a_title(self):
        """"Proactive: r1" was a real notification title. He has no idea
        what r1 is, and it is the first thing read out."""
        from aletheia import runtime
        self.assertNotIn('"Proactive: " + rule["id"]', _text(runtime))


def _text(module) -> str:
    import inspect
    return inspect.getsource(module)


def _source_of(module, needle: str) -> str:
    """The `publish(...)` call whose text contains `needle`."""
    text = _text(module)
    at = text.index(needle)
    start = text.rindex("notifications.publish", 0, at)
    end = text.index("\n\n", at)
    return text[start:end]


if __name__ == "__main__":
    unittest.main()
