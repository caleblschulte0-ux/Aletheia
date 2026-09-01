"""Answers that arrive after the question: bounded, non-blocking, and
incapable of taking the Core down with them."""
import threading
import time
import unittest
import urllib.error
from unittest import mock

from aletheia import followups


class FollowupCase(unittest.TestCase):
    def setUp(self):
        followups.reset()
        self.addCleanup(followups.reset)

    def wait_for(self, followup_id, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            slot = followups.poll(followup_id)
            if slot["state"] != followups.PENDING:
                return slot
            time.sleep(0.01)
        self.fail("follow-up never left PENDING")

    def test_start_returns_immediately_with_the_acknowledgement(self):
        gate = threading.Event()
        started = time.monotonic()
        slot = followups.start(lambda: (gate.wait(5), "done")[1],
                               acknowledgement="One moment.")
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(slot["say"], "One moment.")
        self.assertEqual(slot["state"], followups.PENDING)
        gate.set()

    def test_the_real_answer_lands_in_the_slot(self):
        slot = followups.start(lambda: "two alerts and a pending approval")
        ready = self.wait_for(slot["id"])
        self.assertEqual(ready["state"], followups.READY)
        self.assertEqual(ready["say"], "two alerts and a pending approval")

    def test_a_thrown_exception_becomes_an_honest_sentence(self):
        def boom():
            raise RuntimeError("the provider fell over")

        failed = self.wait_for(followups.start(boom)["id"])
        self.assertEqual(failed["state"], followups.FAILED)
        self.assertIn("the provider fell over", failed["say"])

    def test_take_delivers_once_then_forgets(self):
        slot = followups.start(lambda: "said once")
        self.wait_for(slot["id"])
        self.assertEqual(followups.take(slot["id"])["say"], "said once")
        self.assertEqual(followups.take(slot["id"])["state"], "EXPIRED")

    def test_take_does_not_discard_an_answer_still_being_computed(self):
        gate = threading.Event()
        slot = followups.start(lambda: (gate.wait(5), "late")[1])
        self.assertEqual(followups.take(slot["id"])["state"], followups.PENDING)
        gate.set()
        self.assertEqual(self.wait_for(slot["id"])["say"], "late")

    def test_poll_is_non_destructive_until_explicit_ack(self):
        slot = followups.start(lambda: "survive a dropped response")
        self.wait_for(slot["id"])
        first = followups.poll(slot["id"])
        second = followups.poll(slot["id"])
        self.assertEqual(first["say"], "survive a dropped response")
        self.assertEqual(second["say"], first["say"])
        ack = followups.acknowledge(slot["id"])
        self.assertEqual(ack["state"], followups.ACKED)
        self.assertEqual(followups.poll(slot["id"])["state"], "EXPIRED")

    def test_ack_never_discards_pending_work(self):
        gate = threading.Event()
        slot = followups.start(lambda: (gate.wait(5), "late")[1])
        self.assertEqual(followups.acknowledge(slot["id"])["state"], followups.PENDING)
        gate.set()
        self.assertEqual(self.wait_for(slot["id"])["say"], "late")

    def test_an_unknown_id_reads_as_expired_not_as_an_error(self):
        self.assertEqual(followups.poll("fu-nonexistent")["state"], "EXPIRED")

    def test_slots_are_capped_so_a_chatty_room_cannot_grow_forever(self):
        for _ in range(followups.SLOTS * 3):
            followups.start(lambda: "x")
        time.sleep(0.2)
        self.assertLessEqual(len(followups._SLOTS), followups.SLOTS)

    def test_expired_slots_are_pruned_by_ttl(self):
        slot = followups.start(lambda: "x")
        self.wait_for(slot["id"])
        followups._SLOTS[slot["id"]]["created"] -= followups.TTL_S + 1
        self.assertEqual(followups.poll(slot["id"])["state"], "EXPIRED")

    def test_two_follow_ups_do_not_collide(self):
        a = followups.start(lambda: "first")
        b = followups.start(lambda: "second")
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(self.wait_for(a["id"])["say"], "first")
        self.assertEqual(self.wait_for(b["id"])["say"], "second")

    def test_pending_count_reflects_work_in_flight(self):
        gate = threading.Event()
        followups.start(lambda: (gate.wait(5), "x")[1])
        self.assertEqual(followups.pending_count(), 1)
        gate.set()

    def test_undelivered_count_includes_ready_answers_until_ack(self):
        slot = followups.start(lambda: "ready but not collected")
        self.wait_for(slot["id"])
        self.assertEqual(followups.pending_count(), 0)
        self.assertEqual(followups.undelivered_count(), 1)
        followups.acknowledge(slot["id"])
        self.assertEqual(followups.undelivered_count(), 0)

    def test_update_window_and_new_promises_are_atomic(self):
        self.assertTrue(followups.begin_update())
        self.assertTrue(followups.update_in_progress())
        with self.assertRaises(followups.UpdateInProgress):
            followups.start(lambda: "must not be born under a restart")
        followups.end_update()
        self.assertFalse(followups.update_in_progress())
        self.assertTrue(followups.start(lambda: "safe now"))

    def test_update_window_refuses_while_any_answer_is_undelivered(self):
        slot = followups.start(lambda: "ready")
        self.wait_for(slot["id"])
        self.assertFalse(followups.begin_update())
        followups.acknowledge(slot["id"])
        self.assertTrue(followups.begin_update())
        followups.end_update()


class RoomCollectionCase(unittest.TestCase):
    """The listener's half: speak the acknowledgement, then the answer."""

    def test_the_room_speaks_then_acknowledges_the_finished_answer(self):
        from aletheia import voice_room
        events = []

        def speaker(text):
            events.append(("speak", text))

        def ack(fid, core_url):
            events.append(("ack", fid))
            return True

        with mock.patch.object(
                voice_room, "ask_core",
                return_value={"say": "Working on that.", "followup_id": "fu-1"}), \
             mock.patch.object(voice_room, "collect_followup",
                               return_value="Here is the plan: two steps."), \
             mock.patch.object(voice_room, "acknowledge_followup", side_effect=ack):
            voice_room.listen_forever(recognizer=iter([(True, "thea sort my week")]),
                                      speaker=speaker)
        self.assertEqual(events, [
            ("speak", "Working on that."),
            ("speak", "Here is the plan: two steps."),
            ("ack", "fu-1"),
        ])

    def test_speaker_failure_does_not_false_ack_the_answer(self):
        from aletheia import voice_room
        calls = []

        def speaker(text):
            calls.append(text)
            if text == "finished":
                raise RuntimeError("speaker failed")

        with mock.patch.object(
                voice_room, "ask_core",
                return_value={"say": "Working on that.", "followup_id": "fu-1"}), \
             mock.patch.object(voice_room, "collect_followup", return_value="finished"), \
             mock.patch.object(voice_room, "acknowledge_followup") as ack:
            with self.assertRaises(RuntimeError):
                voice_room.listen_forever(
                    recognizer=iter([(True, "thea sort my week")]), speaker=speaker,
                )
        ack.assert_not_called()

    def test_a_follow_up_that_never_arrives_is_simply_not_spoken(self):
        from aletheia import voice_room
        spoken = []
        with mock.patch.object(
                voice_room, "ask_core",
                return_value={"say": "Working on that.", "followup_id": "fu-1"}), \
             mock.patch.object(voice_room, "collect_followup", return_value=None), \
             mock.patch.object(voice_room, "acknowledge_followup") as ack:
            voice_room.listen_forever(recognizer=iter([(True, "thea sort my week")]),
                                      speaker=spoken.append)
        self.assertEqual(spoken, ["Working on that."])
        ack.assert_not_called()

    def test_collect_followup_gives_up_rather_than_waiting_forever(self):
        from aletheia import voice_room
        now = [0.0]

        def advance(seconds):
            now[0] += seconds

        with mock.patch.object(voice_room.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = \
                b'{"state": "PENDING", "say": null}'
            said = voice_room.collect_followup("fu-1", wait_s=0.05, poll_s=0.01,
                                               sleep=advance,
                                               monotonic=lambda: now[0])
        self.assertIn("taking longer", said)

    def test_collect_followup_outwaits_the_standard_reasoning_budget(self):
        from aletheia import reasoning_gateway, voice_room
        self.assertGreater(
            voice_room.FOLLOWUP_WAIT_S,
            reasoning_gateway.STANDARD_TOTAL_TIMEOUT_S,
        )

    def test_collect_followup_retries_a_temporary_core_disconnect(self):
        from aletheia import voice_room
        now = [0.0]

        class Response:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return self.payload

        def advance(seconds):
            now[0] += seconds

        with mock.patch.object(
            voice_room.urllib.request,
            "urlopen",
            side_effect=[
                urllib.error.URLError("Core restarting"),
                Response(b'{"state": "PENDING", "say": null}'),
                Response(b'{"state": "READY", "say": "finished answer"}'),
            ],
        ):
            said = voice_room.collect_followup(
                "fu-1", wait_s=10, poll_s=1, sleep=advance,
                monotonic=lambda: now[0],
            )
        self.assertEqual(said, "finished answer")

    def test_ack_retries_and_treats_expired_as_already_delivered(self):
        from aletheia import voice_room

        class Response:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return self.payload

        with mock.patch.object(
            voice_room.urllib.request, "urlopen",
            side_effect=[
                urllib.error.URLError("lost ACK response"),
                Response(b'{"state": "EXPIRED", "say": null}'),
            ],
        ):
            self.assertTrue(voice_room.acknowledge_followup("fu-1", sleep=lambda _s: None))

    def test_expired_followup_is_spoken_as_a_failure_not_silence(self):
        from aletheia import voice_room

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"state": "EXPIRED", "say": null}'

        with mock.patch.object(voice_room.urllib.request, "urlopen",
                               return_value=Response()):
            said = voice_room.collect_followup("fu-gone", wait_s=1)
        self.assertIn("couldn't deliver", said)


if __name__ == "__main__":
    unittest.main()
