"""Answers that arrive after the question: bounded, non-blocking, and
incapable of taking the Core down with them."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from aletheia import followups, journal, notifications, stateio


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
        # a background thread that dies silently is worse than one that
        # says what went wrong: the operator is standing there waiting
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


class DurableFollowupCase(unittest.TestCase):
    def setUp(self):
        followups.reset()
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [
            mock.patch.object(followups, "records_dir", return_value=root / "followups"),
            mock.patch.object(notifications, "NOTICES_DIR", root / "notifications"),
            mock.patch.object(journal, "JOURNAL_PATH", root / "journal.jsonl"),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        followups.reset()
        for patcher in reversed(self.patches):
            patcher.stop()
        self.tmp.cleanup()

    def wait_for(self, followup_id, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = followups.poll(followup_id)
            if result["state"] != followups.PENDING:
                return result
            time.sleep(0.01)
        self.fail("durable follow-up never left PENDING")

    def test_answer_is_durable_and_notified_until_delivered(self):
        slot = followups.start(lambda: "The answer survived.", durable=True)
        self.assertEqual(self.wait_for(slot["id"])["say"], "The answer survived.")

        record = followups._load_record(slot["id"])
        self.assertEqual(record["state"], followups.READY)
        notice = notifications.load(record["notification_id"])
        self.assertEqual(notice["state"], "UNREAD")
        self.assertEqual(notice["body"], "The answer survived.")

        self.assertEqual(followups.take(slot["id"])["say"], "The answer survived.")
        self.assertEqual(followups._load_record(slot["id"])["state"],
                         followups.DELIVERED)
        self.assertEqual(notifications.load(notice["id"])["state"], "ACKNOWLEDGED")

    def test_restart_turns_an_orphaned_promise_into_visible_failure(self):
        followup_id = "fu-orphaned"
        stateio.write_json_atomic(followups._record_path(followup_id), {
            "version": 1, "id": followup_id, "state": followups.PENDING,
            "say": None, "owner": "previous-core", "created_at": stateio.utcnow(),
            "updated_at": stateio.utcnow(),
        })

        recovered = followups.recover_pending()

        self.assertEqual(recovered, [{"id": followup_id, "state": followups.FAILED}])
        record = followups._load_record(followup_id)
        self.assertTrue(record["recovered_after_restart"])
        self.assertIn("interrupted", record["say"])
        notice = notifications.load(record["notification_id"])
        self.assertEqual(notice["priority"], "IMPORTANT")
        self.assertEqual(notice["state"], "UNREAD")


class RoomCollectionCase(unittest.TestCase):
    """The listener's half: speak the acknowledgement, then the answer."""

    def test_the_room_speaks_the_answer_when_it_lands(self):
        from aletheia import voice_room
        spoken = []
        with mock.patch.object(
                voice_room, "ask_core",
                return_value={"say": "Working on that.", "followup_id": "fu-1"}), \
             mock.patch.object(voice_room, "collect_followup",
                               return_value="Here is the plan: two steps."):
            voice_room.listen_forever(recognizer=iter([(True, "thea sort my week")]),
                                      speaker=spoken.append, max_utterances=1)
        self.assertEqual(spoken, ["Working on that.", "Here is the plan: two steps."])

    def test_a_follow_up_that_never_arrives_gets_an_honest_failure(self):
        from aletheia import voice_room
        spoken = []
        with mock.patch.object(
                voice_room, "ask_core",
                return_value={"say": "Working on that.", "followup_id": "fu-1"}), \
             mock.patch.object(voice_room, "collect_followup", return_value=None):
            voice_room.listen_forever(recognizer=iter([(True, "thea sort my week")]),
                                      speaker=spoken.append, max_utterances=1)
        self.assertEqual(spoken, ["Working on that.", voice_room.FOLLOWUP_FAILURE])

    def test_collect_followup_gives_up_rather_than_waiting_forever(self):
        from aletheia import voice_room
        slept = []
        with mock.patch.object(voice_room.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = \
                b'{"state": "PENDING", "say": null}'
            said = voice_room.collect_followup("fu-1", wait_s=0.05, poll_s=0.01,
                                               sleep=slept.append)
        self.assertIsNone(said)

    def test_collect_followup_retries_a_core_restart(self):
        from aletheia import voice_room
        ready = mock.MagicMock()
        ready.__enter__.return_value.read.return_value = \
            b'{"state": "READY", "say": "I am back."}'
        with mock.patch.object(
                voice_room.urllib.request, "urlopen",
                side_effect=[OSError("Core restarting"), ready]) as urlopen:
            said = voice_room.collect_followup(
                "fu-1", wait_s=1, poll_s=0, sleep=lambda _seconds: None)
        self.assertEqual(said, "I am back.")
        self.assertEqual(urlopen.call_count, 2)

    def test_followup_collection_does_not_block_the_room(self):
        from aletheia import voice_room
        gate = threading.Event()
        spoken = []

        def collect(_followup_id, _core_url):
            gate.wait(2)
            return "Finished later."

        started = time.monotonic()
        thread = voice_room.launch_followup("fu-1", "http://core", spoken.append,
                                            collector=collect)
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertTrue(thread.is_alive())
        gate.set()
        thread.join(2)
        self.assertEqual(spoken, ["Finished later."])

    def test_collector_failure_is_spoken_instead_of_dying_silently(self):
        from aletheia import voice_room
        spoken = []

        def broken(_followup_id, _core_url):
            raise RuntimeError("collector crashed")

        thread = voice_room.launch_followup("fu-1", "http://core", spoken.append,
                                            collector=broken)
        thread.join(2)
        self.assertEqual(spoken, [voice_room.FOLLOWUP_FAILURE])


if __name__ == "__main__":
    unittest.main()
