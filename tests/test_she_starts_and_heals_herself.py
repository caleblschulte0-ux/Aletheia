"""Normal operation asks nothing of him, and a crash loop is not silent.

Two halves of the same promise. The first is that nothing about her being
there requires him to remember a command: the registration that brings
her back is repaired by her, not by him running `install` on the day he
happens to think of it. The second is that when she cannot heal herself
she SAYS SO — the supervisor is very good at hiding a crash loop, because
from the outside the process really is there and every answer is just "I
couldn't reach my Core".

And the health view answers the question he actually asks, which is never
"which parts are up": it is "are you all right", and it is answered with
a because.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import running, supervisor


def _state(**over) -> dict:
    state = {"parts": [{"part": "supervisor", "what": "x", "up": True,
                        "pids": [1], "mb": 0},
                       {"part": "core", "what": "y", "up": True,
                        "pids": [2], "mb": 0},
                       {"part": "voice", "what": "z", "up": True,
                        "pids": [3], "mb": 0}],
             "closed": False, "closed_reason": "", "halted": False,
             "halt_reason": "", "listening": True, "running_old_code": False}
    state.update(over)
    return state


def _down(state: dict, part: str) -> dict:
    for row in state["parts"]:
        if row["part"] == part:
            row["up"] = False
    return state


class TheHealthViewIsTwoSentences(unittest.TestCase):
    def test_everything_running_is_the_whole_answer(self):
        self.assertEqual(running.headline(_state()), "Everything's running.")

    def test_a_missing_part_comes_with_its_because(self):
        """"PARTLY ON — running, but voice is not" names something that
        stopped and says nothing about why or what to do, which is the
        half of a health view worth having."""
        said = running.headline(_down(_state(), "voice"))
        self.assertIn("Everything's running except", said)
        self.assertIn("can't hear the room", said)
        self.assertIn("turn the microphone on", said.lower())
        # ...and the what-next starts a sentence properly. `.capitalize()`
        # lowercases everything after the first letter, which gave
        # "Turn the microphone on and i'll start listening."
        self.assertIn("I'll start listening", said)

    def test_a_missing_part_is_never_named_by_its_module(self):
        for part in ("supervisor", "core", "voice"):
            said = running.headline(_down(_state(), part))
            self.assertNotIn(part, said.lower().replace("voice", ""), said)

    def test_the_microphone_being_off_is_not_a_fault(self):
        """He turned it off; that is the default and his ruling. Reporting
        it as a missing part every time teaches him to ignore the line."""
        said = running.headline(_down(_state(listening=False), "voice"))
        self.assertTrue(said.startswith("Everything's running."), said)
        self.assertIn("how you set it", said)

    def test_halted_says_what_it_means_for_him(self):
        said = running.headline(_state(halted=True, halt_reason="you said stop"))
        self.assertIn("you said stop", said)
        self.assertIn("resume", said)

    def test_no_state_word_is_ever_the_first_thing_he_hears(self):
        """"ON.", "OFF.", "PARTLY ON —" are a status board read out loud."""
        for state in (_state(), _state(listening=False),
                      _down(_state(), "core"), _state(halted=True),
                      _state(closed=True), _state(running_old_code=True)):
            said = running.headline(state)
            first = said.split()[0].rstrip(".,")
            self.assertNotIn(first.upper(), ("ON", "OFF", "PARTLY", "CLOSED"),
                             said)

    def test_nothing_running_says_what_happens_next(self):
        state = _state()
        for row in state["parts"]:
            row["up"] = False
        said = running.headline(state)
        self.assertIn("five minutes", said)


class AskedOutLoud(unittest.TestCase):
    def test_the_health_questions_reach_the_health_view(self):
        """Each of these took a model round trip to be answered WORSE:
        "why is your voice off" came back with an address and a port read
        out loud, and a hundred words of hedging."""
        from aletheia import quick
        for question in ("is everything running", "is everything working",
                         "why is your voice off", "why can't you hear me",
                         "are you broken", "why aren't you listening"):
            matched = quick.match(question)
            self.assertIsNotNone(matched, question)
            self.assertEqual(matched[0], "running", question)

    def test_the_answer_is_the_headline_and_nothing_technical(self):
        from aletheia import quick, speech
        with mock.patch.object(running, "snapshot",
                               lambda **k: _down(_state(), "voice")):
            said = quick.answer("why is your voice off")
        self.assertEqual(speech.for_the_room(said), said)
        self.assertNotIn("http", said)


class ACrashLoopIsNotSilent(unittest.TestCase):
    def _run(self, codes, alive_s=1.0):
        """Run the supervisor over a scripted list of child exit codes."""
        codes = list(codes)
        said = []

        def launch():
            return codes.pop(0)

        with mock.patch.object(supervisor, "_say_crash_loop",
                               lambda code, n: said.append((code, n))), \
             mock.patch.object(supervisor, "_journal", lambda *a: None), \
             mock.patch("aletheia.closed.is_closed", lambda: False), \
             mock.patch("time.monotonic", side_effect=_clock(alive_s)):
            supervisor.run_forever(launch=launch, sleep=lambda s: None,
                                   max_runs=len(codes))
        return said

    def test_he_is_told_once_after_enough_crashes_in_a_row(self):
        said = self._run([1] * (supervisor.CRASH_LOOP_AT + 3))
        self.assertEqual(len(said), 1, "one notice, not one per crash")
        self.assertEqual(said[0], (1, supervisor.CRASH_LOOP_AT))

    def test_a_few_crashes_are_not_a_loop(self):
        self.assertEqual(self._run([1] * (supervisor.CRASH_LOOP_AT - 1)), [])

    def test_a_self_update_is_health_and_never_counts(self):
        from aletheia.core import RESTART_EXIT_CODE
        self.assertEqual(self._run([RESTART_EXIT_CODE] * 8), [])

    def test_the_notice_is_a_failure_and_allowed_to_interrupt(self):
        """This is the thing that answers him being gone and staying gone,
        so it is exactly what the notification policy is FOR."""
        import inspect
        from aletheia import notifications
        source = inspect.getsource(supervisor._say_crash_loop)
        self.assertIn("about=notifications.FAILED", source)
        self.assertEqual(
            notifications.loudness("IMPORTANT", notifications.FAILED),
            "IMPORTANT")


class TheRegistrationRepairsItself(unittest.TestCase):
    def test_a_broken_task_is_put_back_without_him(self):
        """`install` was the only thing that ever checked, and `install` is
        something HE runs — so a task that lost a trigger to a Windows
        update stayed broken until he happened to think of it."""
        fixed = []
        with mock.patch("os.name", "nt"), \
             mock.patch("aletheia.autostart.doctor",
                        lambda: {"AletheiaVoice": ["the task is Disabled"]}), \
             mock.patch("aletheia.autostart.install",
                        lambda spec, *a, **k: (fixed.append(spec.name), (True, "ok"))[1]), \
             mock.patch.object(supervisor, "_journal", lambda *a: None):
            self.assertEqual(supervisor.repair_registration(), ["AletheiaVoice"])
        self.assertEqual(fixed, ["AletheiaVoice"])

    def test_a_healthy_registration_is_left_alone(self):
        with mock.patch("os.name", "nt"), \
             mock.patch("aletheia.autostart.doctor", lambda: {}), \
             mock.patch("aletheia.autostart.install",
                        lambda *a, **k: self.fail("re-registered a healthy task")):
            self.assertEqual(supervisor.repair_registration(), [])

    def test_a_repair_that_fails_never_takes_the_supervisor_down(self):
        """An immortal loop cannot have a mortal statement in it. Losing
        the repair is a bad day; losing the supervisor is the outage."""
        def boom(*a, **k):
            raise OSError("Task Scheduler is not answering")

        with mock.patch("os.name", "nt"), \
             mock.patch("aletheia.autostart.doctor",
                        lambda: {"Aletheia": ["not registered at all"]}), \
             mock.patch("aletheia.autostart.install", boom), \
             mock.patch.object(supervisor, "_journal", lambda *a: None):
            self.assertEqual(supervisor.repair_registration(), [])

    def test_a_test_supervisor_never_shells_out_to_task_scheduler(self):
        """`launch` is only ever passed by a test, and a test that talks to
        the real Task Scheduler is a test that changes his machine."""
        with mock.patch.object(supervisor, "repair_registration",
                               lambda: self.fail("a test touched schtasks")), \
             mock.patch.object(supervisor, "_journal", lambda *a: None), \
             mock.patch("aletheia.closed.is_closed", lambda: False):
            supervisor.run_forever(launch=lambda: 0, sleep=lambda s: None,
                                   max_runs=1)


def _clock(alive_s: float):
    """A monotonic clock where every child lives exactly `alive_s`."""
    now = [0.0]

    def tick():
        now[0] += alive_s / 2.0
        return now[0]

    return tick


if __name__ == "__main__":
    unittest.main()
