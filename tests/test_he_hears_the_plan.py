"""A long request is three things, in order, and the middle one was missing.

His shape for it: *"A longer request, it might not get handled fast, but
I know that she's working on it fast, and then I'll hear the plan fast,
and then the results, they'll come when they come."*

    ~1s     she is on it              ack_line, already there
    soon    what she is going to do   THIS
    later   the results               the followup answer, already there

Between the acknowledgement and the results there was silence — minutes
of it — with a plan she had already compiled and was sitting on. Being
told she started and then nothing until she finished is the shape that
makes a person go and check.
"""
import time
import unittest
from unittest import mock

from aletheia import followups, voice_room


class ReportingCase(unittest.TestCase):
    def test_outside_a_followup_it_is_a_no_op_not_an_error(self):
        """`intents.propose` called directly must behave identically."""
        self.assertFalse(followups.report("anything"))

    def test_a_line_reported_during_work_is_visible_while_it_runs(self):
        started = mock.Mock()

        def work():
            followups.report("Here's the plan: water the plants — 2 steps.")
            started.wait = True
            time.sleep(0.25)
            return "Done."

        slot = followups.start(work, acknowledgement="Working on it.")
        self.assertEqual(slot["say"], "Working on it.")
        time.sleep(0.1)
        mid = followups.poll(slot["id"])
        self.assertEqual(mid["state"], followups.PENDING)
        self.assertEqual(mid["progress"],
                         ["Here's the plan: water the plants — 2 steps."])
        time.sleep(0.4)
        self.assertEqual(followups.poll(slot["id"])["state"], followups.READY)

    def test_two_followups_do_not_narrate_into_each_other(self):
        """A thread marker, not a global: two long requests can overlap."""
        def one():
            followups.report("plan one")
            time.sleep(0.2)
            return "done one"

        def two():
            followups.report("plan two")
            time.sleep(0.2)
            return "done two"

        a = followups.start(one)
        b = followups.start(two)
        time.sleep(0.1)
        self.assertEqual(followups.poll(a["id"])["progress"], ["plan one"])
        self.assertEqual(followups.poll(b["id"])["progress"], ["plan two"])
        time.sleep(0.4)

    def test_an_empty_line_is_not_reported(self):
        def work():
            self.assertFalse(followups.report("   "))
            return "done"
        slot = followups.start(work)
        time.sleep(0.2)
        self.assertEqual(followups.poll(slot["id"]).get("progress"), [])


class TheRoomSaysItCase(unittest.TestCase):
    def run_room(self, progress, answer="Done: 3 steps."):
        said = []

        def collector(fid, url, on_progress=None):
            for line in progress:
                on_progress(line)
            return answer

        thread = voice_room.launch_followup(
            "fu-1", "http://core", said.append,
            collector=collector, acknowledge=lambda f, u: None)
        thread.join(2)
        return said

    def test_the_plan_is_spoken_before_the_results(self):
        said = self.run_room(["Here's the plan: check the repos — 3 steps."])
        self.assertEqual(said, ["Here's the plan: check the repos — 3 steps.",
                                "Done: 3 steps."])

    def test_each_line_is_said_once_however_often_it_is_polled(self):
        """The slot carries the whole list on every poll; she says the NEW
        ones, not everything she has already said."""
        def collector(fid, url, on_progress=None):
            # the same list, seen three times, the way polling sees it
            for _ in range(3):
                for line in ["one"]:
                    pass
            on_progress("one")
            on_progress("two")
            return "done"

        said = []
        thread = voice_room.launch_followup(
            "fu-2", "http://core", said.append,
            collector=collector, acknowledge=lambda f, u: None)
        thread.join(2)
        self.assertEqual(said, ["one", "two", "done"])

    def test_a_collector_that_cannot_narrate_still_delivers(self):
        """An older injected collector takes no `on_progress`."""
        said = []
        thread = voice_room.launch_followup(
            "fu-3", "http://core", said.append,
            collector=lambda fid, url: "just the answer",
            acknowledge=lambda f, u: None)
        thread.join(2)
        self.assertEqual(said, ["just the answer"])

    def test_narration_that_throws_never_loses_the_answer(self):
        """The guard is in the REAL collector, so test the real one.

        A first version of this injected a fake collector that called
        `on_progress` unguarded, and proved only that an unguarded call
        is unguarded. `collect_followup` is what runs in the room.
        """
        import json as _json
        from contextlib import contextmanager

        payloads = iter([
            {"state": "PENDING", "progress": ["a line"], "say": None},
            {"state": "READY", "progress": ["a line"], "say": "the answer"},
        ])

        @contextmanager
        def fake_urlopen(*a, **k):
            class R:
                def read(self):
                    return _json.dumps(next(payloads)).encode("utf-8")
            yield R()

        def say(line):
            raise RuntimeError("the speaker fell over")

        with mock.patch.object(voice_room.urllib.request, "urlopen",
                               fake_urlopen):
            answer = voice_room.collect_followup(
                "fu-4", "http://core", wait_s=5, poll_s=0.01,
                sleep=lambda s: None, on_progress=say)
        self.assertEqual(answer, "the answer")


if __name__ == "__main__":
    unittest.main()
