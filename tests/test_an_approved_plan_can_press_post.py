"""A plan she compiles can press Post: once, and only with his approval of it.

2026-09-11, the TikTok app-review take. The brief ends on the demo's sandbox
"Post to TikTok" button, and her first plan for it would have produced a video
of nothing. Three gaps:

- the committing guard refused the sixteen clicks, correctly for unattended
  hands, and the approval still offered the other five steps under the
  summary of the whole take;
- she had no way to wait the seconds the brief asks for;
- the recorder could not read the window name she wrote (that one is held in
  test_the_screen_is_recorded).

These hold the repairs, and the line under them: nothing presses a committing
control without his approval of the exact plan, and the label on screen is
read again before the press.
"""
import json
import threading
import unittest
from unittest import mock

from aletheia import brain, computer, intents, journal, planner, policy
from tests.test_hands_and_do_task import FakeDesktop, Isolated

FLEET = {"repos": {"Aletheia": {}}}
REGISTRY = {
    "providers": {"aletheia.local": {}},
    "capabilities": [
        {"id": "task.persist", "status": "AVAILABLE", "provider": "aletheia.local"},
    ],
}
EDGE = {"title_re": "localhost|Shorts|Edge"}


def take(press="Post to TikTok"):
    return [{"action": "focus_window", "window": EDGE},
            {"action": "invoke", "window": EDGE, "control": {"title": "Connect TikTok"}},
            {"action": "pause", "seconds": 3},
            {"action": "invoke", "window": EDGE, "control": {"title": press}},
            {"action": "invoke", "window": EDGE, "control": {"title": "Done"}}]


class NoSleep(Isolated):
    def setUp(self):
        super().setUp()
        self.slept = []
        p = mock.patch.object(computer, "_sleep", self.slept.append)
        p.start()
        self.addCleanup(p.stop)


class SheCanWait(NoSleep):
    def test_a_pause_touches_nothing_and_waits_what_it_says(self):
        desk = FakeDesktop()
        result = computer.act([{"action": "focus_window", "window": EDGE},
                               {"action": "pause", "seconds": 3}], backend=desk)
        self.assertEqual(result["steps_done"], 2)
        self.assertEqual(desk.performed, ["focus_window"])
        self.assertAlmostEqual(sum(self.slept), 3.0)

    def test_a_pause_is_capped_and_counts_toward_the_wait_budget(self):
        for bad in (0, -1, 11, True, "3", None):
            with self.subTest(seconds=bad):
                self.assertTrue(computer.validate_steps([{"action": "pause", "seconds": bad}]))
        self.assertEqual(computer.validate_steps([{"action": "pause", "seconds": 2.5}]), [])
        self.assertTrue(computer.validate_steps([{"action": "pause", "seconds": 10}] * 31),
                        "310 seconds of waiting is over the plan's budget")

    def test_halt_is_read_during_a_pause(self):
        with mock.patch.object(computer, "_sleep",
                               lambda seconds: policy.halt("stop", via="test")):
            with self.assertRaises(policy.Halted):
                computer.act([{"action": "pause", "seconds": 5}], backend=FakeDesktop())


class PressesNeedHisApprovalOfThisPlan(NoSleep):
    def test_without_an_approval_post_is_still_refused(self):
        desk = FakeDesktop()
        with self.assertRaises(computer.CommittingControl):
            computer.act(take(), backend=desk)
        self.assertEqual(desk.performed, [])

    def test_the_presses_a_plan_makes_are_named(self):
        presses = computer.committing_presses(take())
        self.assertEqual([(p["index"], p["label"]) for p in presses], [(3, "Post to TikTok")])
        for refused in ([{"action": "open_app", "app": "cmd.exe"}],
                        [{"action": "close_window", "window": EDGE}],
                        [{"action": "invoke", "window": EDGE, "control": {"class_name": "Button"}}]):
            with self.subTest(step=refused[0]["action"]):
                with self.assertRaises(computer.ApprovalRequired):
                    computer.committing_presses(refused)

    def test_his_approval_of_this_exact_plan_presses_it_once(self):
        desk = FakeDesktop()
        with computer.approved_presses("intent-take", [take()]):
            self.assertEqual(computer.act(take(), backend=desk)["steps_done"], 5)
            with self.assertRaises(computer.CommittingControl):
                computer.act(take(), backend=FakeDesktop())
        self.assertEqual(desk.performed, ["focus_window", "invoke", "invoke", "invoke"])
        with self.assertRaises(computer.CommittingControl):
            computer.act(take(), backend=FakeDesktop())
        started = [e["text"] for e in journal.entries()
                   if e["subject"] == "computer:act" and e["text"].startswith("STARTED")]
        self.assertEqual(len(started), 1)
        self.assertIn("approval=intent-take", started[0])
        self.assertIn("Post to TikTok", started[0])

    def test_an_approval_of_a_different_plan_presses_nothing(self):
        desk = FakeDesktop()
        with computer.approved_presses("intent-take", [take()]):
            with self.assertRaises(computer.CommittingControl):
                computer.act(take(press="Delete video"), backend=desk)
        self.assertEqual(desk.performed, [])

    def test_the_label_on_screen_must_be_the_press_he_approved(self):
        key = json.dumps({"title": "Post to TikTok"}, sort_keys=True)
        desk = FakeDesktop(live_names={key: "Delete account"})
        with computer.approved_presses("intent-take", [take()]):
            with self.assertRaises(computer.CommittingControl):
                computer.act(take(), backend=desk)
        self.assertEqual(desk.performed, ["focus_window", "invoke"], "stopped before the press")

    def test_an_approved_press_does_not_unlock_another_step(self):
        key = json.dumps({"title": "Done"}, sort_keys=True)
        desk = FakeDesktop(live_names={key: "Send"})
        with computer.approved_presses("intent-take", [take()]):
            with self.assertRaises(computer.CommittingControl):
                computer.act(take(), backend=desk)
        self.assertEqual(desk.performed, ["focus_window", "invoke", "invoke"])

    def test_another_thread_does_not_borrow_it(self):
        caught = []

        def elsewhere():
            try:
                computer.act(take(), backend=FakeDesktop())
            except computer.CommittingControl as exc:
                caught.append(exc)

        with computer.approved_presses("intent-take", [take()]):
            worker = threading.Thread(target=elsewhere)
            worker.start()
            worker.join()
        self.assertEqual(len(caught), 1)


class TheTakeAsAPlan(NoSleep):
    def propose(self, *steps):
        output = {"intent": "plan", "summary": "Record the TikTok review take",
                  "steps": list(steps)}
        return intents.propose("do the thing", quote="do the thing", fleet=FLEET,
                               materialize=False, registry=REGISTRY,
                               provider=brain.Provider("stub", lambda text, ctx: output))

    def test_a_take_that_presses_post_is_one_approval_that_names_the_press(self):
        record = self.propose({"kind": "computer_do", "steps": take()},
                              {"kind": "screen_record_stop"})
        self.assertEqual(record["state"], intents.PROPOSED)
        self.assertEqual([s["status"] for s in record["steps"]], [planner.EXECUTABLE] * 2)
        self.assertEqual(record["presses"], [{"n": record["steps"][0]["n"],
                                              "presses": ["Post to TikTok"]}])
        approval = policy.load(record["approval"])
        self.assertEqual(approval["state"], "PENDING", "no standing grant covers a press")
        self.assertEqual(approval["capability"], "intent.execute")
        self.assertIn("Post to TikTok", approval["requested_action"])
        self.assertIn("Post to TikTok", approval["consequence"])
        said = intents.spoken(record)
        self.assertIn("Post to TikTok", said)
        self.assertNotIn("Say approve", said, "a desktop plan is approved on the phone")

    def test_he_approves_and_the_press_is_made_inside_that_run_only(self):
        record = self.propose({"kind": "computer_do", "steps": take()})
        desk = FakeDesktop()

        def run(cmd, fleet, quote=""):
            return computer.act(cmd["steps"], backend=desk, requested_by="test")["steps_done"]

        self.assertEqual(intents.run_approved(FLEET, executor=run), [])
        self.assertEqual(desk.performed, [])
        policy.decide(record["approval"], "APPROVED", via="test")
        results = intents.run_approved(FLEET, executor=run)
        self.assertEqual(results[0]["outcome"], intents.EXECUTED)
        self.assertEqual(desk.performed, ["focus_window", "invoke", "invoke", "invoke"])
        with self.assertRaises(computer.CommittingControl):
            computer.act(take(), backend=FakeDesktop())

    def test_a_take_whose_hands_are_refused_is_not_offered(self):
        for hands in ({"kind": "computer_do", "steps": [
                          {"action": "hotkey", "window": EDGE, "keys": "enter"}]},
                      {"kind": "computer_do", "steps": [
                          {"action": "invoke", "window": EDGE, "control": {"class_name": "Button"}}]},
                      {"kind": "screen_record", "name": "take"}):
            with self.subTest(hands=hands):
                record = self.propose(hands, {"kind": "screen_record_stop"})
                self.assertEqual(record["state"], intents.RETIRED)
                with self.assertRaises(Exception):
                    policy.load(record["approval"])
                said = intents.spoken(record)
                self.assertIn("Nothing is queued", said)
                self.assertNotIn("ready", said)
                self.assertNotIn("python -m", said)


if __name__ == "__main__":
    unittest.main()
