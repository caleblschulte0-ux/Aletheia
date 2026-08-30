"""How she sounds, and when she speaks first.

Three behaviours were the problem: she read hex ids and ISO timestamps
aloud, she dead-ended on "approve" the moment two things were pending,
and she never said anything unless spoken to.
"""
import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import announce, journal, notifications, policy, speech, voice

NOW = dt.datetime(2026, 9, 3, 10, 0)


class SpeechCase(unittest.TestCase):
    def test_ids_never_reach_the_room(self):
        for detail in ("reminder remind-3f9ab2c1 set for 2026-09-04T09:00:00Z — 'x'",
                       "approval mail-a1e1957d0f is pending",
                       "intent intent-0a06bbb663 queued"):
            said = speech.spoken_receipt("anything", detail, now=NOW)
            self.assertNotIn("3f9ab2c1", said)
            self.assertNotIn("a1e1957d0f", said)
            self.assertNotIn("0a06bbb663", said)

    def test_a_reminder_is_a_sentence(self):
        said = speech.spoken_receipt(
            "remind_at",
            "reminder remind-3f9ab2c1 set for 2026-09-04T15:00:00+00:00 — 'Call the dentist'",
            now=NOW)
        self.assertIn("Call the dentist", said)
        self.assertNotIn("2026-09-04", said)
        self.assertNotIn("remind-", said)

    def test_a_name_keeps_its_capital(self):
        said = speech.spoken_receipt(
            "remind_at",
            "reminder remind-abc123 set for 2026-09-04T15:00:00+00:00 — 'Dana needs an answer'",
            now=NOW)
        self.assertIn("Dana needs an answer", said)

    def test_slugs_become_words(self):
        self.assertEqual(speech.spoken_receipt("task_new", "task water-the-plants queued"),
                         "Added a task: water the plants.")

    def test_times_are_relative_where_a_person_would_be(self):
        base = dt.datetime(2026, 9, 3, 10, 0).astimezone()
        self.assertIn("today", speech.humanize_time(
            base.replace(hour=18).isoformat(), base))
        self.assertIn("tomorrow", speech.humanize_time(
            (base + dt.timedelta(days=1)).isoformat(), base))
        # 3 Sep 2026 is a Thursday, so +5 days is the following Tuesday
        self.assertIn("Tuesday", speech.humanize_time(
            (base + dt.timedelta(days=5)).isoformat(), base))

    def test_an_unparseable_time_is_returned_untouched(self):
        self.assertEqual(speech.humanize_time("sometime soon"), "sometime soon")

    def test_an_unknown_receipt_is_tidied_never_invented(self):
        said = speech.spoken_receipt("mystery_kind", "something happened with id-abc123def")
        self.assertIn("something happened", said)
        self.assertNotIn("abc123def", said)

    def test_a_separator_is_not_squeezed_into_a_typo(self):
        self.assertIn(" :: ", speech.tidy("Example Domain :: an excerpt"))

    def test_and_list_speaks_like_a_person(self):
        self.assertEqual(speech.and_list(["a"]), "a")
        self.assertEqual(speech.and_list(["a", "b"]), "a and b")
        self.assertEqual(speech.and_list(["a", "b", "c"]), "a, b and c")
        self.assertEqual(speech.and_list([]), "")

    def test_counts_agree_with_their_nouns(self):
        self.assertEqual(speech.count_phrase(1, "thing"), "1 thing")
        self.assertEqual(speech.count_phrase(2, "thing"), "2 things")


APPROVALS = [
    {"id": "intent-0a06bbb663", "state": "PENDING", "capability": "intent.execute",
     "requested_action": "run 3 steps"},
    {"id": "mail-a1e1957d0f", "state": "PENDING", "capability": "email.send",
     "requested_action": "email.send:abc", "reason": "send email to Dana Okafor"},
    {"id": "book-meet-dana", "state": "PENDING", "capability": "calendar.write",
     "requested_action": "calendar.write:abc"},
]


class ApprovalByVoiceCase(unittest.TestCase):
    def approve(self, phrase, pending=APPROVALS):
        with mock.patch.object(policy, "all_approvals", return_value=pending):
            return voice.interpret(f"thea {phrase}")

    def test_one_pending_still_needs_no_name(self):
        out = self.approve("approve", APPROVALS[:1])
        self.assertEqual(out["command"], {"kind": "approve", "id": "intent-0a06bbb663"})

    def test_nothing_pending_says_so(self):
        self.assertIn("Nothing is waiting", self.approve("approve", [])["say"])

    def test_several_pending_are_read_out_rather_than_refused(self):
        said = self.approve("approve")["say"]
        self.assertIn("3 things waiting", said)
        self.assertIn("the email to Dana Okafor", said)
        self.assertIn("the calendar booking", said)
        # the old dead end sent him to a browser
        self.assertNotIn("Command Center", said)

    def test_he_can_pick_by_position(self):
        self.assertEqual(self.approve("approve the first")["command"]["id"],
                         "intent-0a06bbb663")
        self.assertEqual(self.approve("approve the last")["command"]["id"],
                         "book-meet-dana")

    def test_he_can_pick_by_name(self):
        self.assertEqual(self.approve("approve the email")["command"]["id"],
                         "mail-a1e1957d0f")
        self.assertEqual(self.approve("approve the calendar booking")["command"]["id"],
                         "book-meet-dana")

    def test_an_ambiguous_name_asks_again_rather_than_guessing(self):
        out = self.approve("approve the thing")
        self.assertIsNone(out["command"])
        self.assertIn("Which one", out["say"])

    def test_an_out_of_range_position_does_not_approve_anything(self):
        self.assertIsNone(self.approve("approve the third", APPROVALS[:2])["command"])

    def test_labels_never_contain_an_id(self):
        for approval in APPROVALS:
            self.assertNotIn("a1e1957d0f", voice.approval_label(approval))
            self.assertNotIn("0a06bbb663", voice.approval_label(approval))


class AnnounceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ,
                              {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start(); self.addCleanup(env.stop)
        # No hasattr guard: mock.patch.object raises on a wrong name, and it
        # should. Guarding it made this suite run against the operator's REAL
        # notification store, which is how a "said twice" test saw four
        # unrelated notices.
        for module, attr, value in (
                (notifications, "NOTICES_DIR", root / "notifications"),
                (journal, "JOURNAL_PATH", root / "journal.jsonl")):
            p = mock.patch.object(module, attr, value)
            p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(policy, "halted", return_value=None)
        p.start(); self.addCleanup(p.stop)
        # Production defaults are deliberately silent. These tests exercise the
        # opt-in announcement behavior, so turn it on explicitly here rather
        # than making a test fixture silently redefine the product default.
        self.config = {**announce.DEFAULT_CONFIG, "enabled": True}

    def notify(self, title, priority="IMPORTANT", body="details"):
        return notifications.publish(title, body, priority=priority,
                                     source="test", dedupe_key=title)

    def test_quiet_hours_span_midnight(self):
        for hour, quiet in ((9, False), (21, False), (22, True), (2, True),
                            (7, True), (8, False)):
            self.assertEqual(
                announce.in_quiet_hours(self.config, dt.datetime(2026, 8, 27, hour, 0)),
                quiet, f"{hour:02d}:00")

    def test_nothing_is_spoken_in_quiet_hours(self):
        self.notify("The boiler is on fire", priority="URGENT")
        spoken = announce.speak_pending(
            speaker=lambda t: None, config=self.config,
            now=dt.datetime(2026, 8, 27, 3, 0))
        self.assertEqual(spoken, [])

    def test_only_important_things_are_spoken(self):
        self.notify("Routine thing", priority="INFO")
        self.notify("Worth saying", priority="IMPORTANT")
        said = announce.speak_pending(speaker=lambda t: None, config=self.config,
                                      now=NOW)
        self.assertEqual(len(said), 1)
        self.assertIn("Worth saying", said[0])

    def test_the_same_thing_is_never_said_twice(self):
        self.notify("Dana replied")
        first = announce.speak_pending(speaker=lambda t: None, config=self.config, now=NOW)
        second = announce.speak_pending(speaker=lambda t: None, config=self.config, now=NOW)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])

    def test_an_hourly_cap_keeps_the_house_quiet(self):
        for i in range(8):
            self.notify(f"Thing {i}")
        said = announce.speak_pending(speaker=lambda t: None, config=self.config, now=NOW)
        self.assertLessEqual(len(said), self.config["max_per_hour"])

    def test_halted_means_silent(self):
        self.notify("Something urgent", priority="URGENT")
        with mock.patch.object(policy, "halted", return_value={"reason": "stop"}):
            self.assertEqual(announce.pending(self.config, NOW), [])

    def test_disabled_means_silent(self):
        self.notify("Something urgent", priority="URGENT")
        self.assertEqual(
            announce.pending({**self.config, "enabled": False}, NOW), [])

    def test_a_failing_mouth_does_not_break_the_loop(self):
        self.notify("Dana replied")

        def broken(text):
            raise RuntimeError("no speakers")

        announce.speak_pending(speaker=broken, config=self.config, now=NOW)

    def test_the_line_carries_no_identifiers(self):
        notice = {"title": "Plan intent-0a06bbb663 needs you",
                  "body": "approve mail-a1e1957d0f to send"}
        line = announce.sentence(notice)
        self.assertNotIn("0a06bbb663", line)
        self.assertNotIn("a1e1957d0f", line)

    def test_a_broken_config_is_quieter_not_louder(self):
        path = Path(self.tmp.name) / "announce.json"
        path.write_text("{ not json", encoding="utf-8")
        self.assertEqual(announce.load_config(path), announce.DEFAULT_CONFIG)

    def test_bad_config_values_are_refused(self):
        for bad in ({"quiet_from": "25:00"}, {"priorities": []},
                    {"max_per_hour": -1}, {"enabled": "yes"}, {"nope": 1}):
            with self.assertRaises(ValueError, msg=str(bad)):
                announce.validate_config(bad)


if __name__ == "__main__":
    unittest.main()
