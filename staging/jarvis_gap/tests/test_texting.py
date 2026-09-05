from __future__ import annotations

import datetime as dt
import unittest

from staging.jarvis_gap.phonelink_messages_probe import probe
from staging.jarvis_gap.texting import TextDraft, prepare

UTC = dt.timezone.utc


class FakePhoneLinkProbeBackend:
    def __init__(self, windows, controls):
        self.windows = windows
        self.controls = controls
        self.actions = []

    def perform(self, step):
        self.actions.append(dict(step))
        if step["action"] == "list_windows":
            return {"windows": list(self.windows)}
        if step["action"] == "inspect_controls":
            return {"controls": list(self.controls)}
        raise AssertionError(f"unexpected action {step['action']}")


class TextingTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 8, 30, 20, 0, tzinfo=UTC)
        self.contact = {
            "id": "alex",
            "display_name": "Alex",
            "phones": ["+1 (605) 555-0100"],
        }

    def test_draft_is_exact_recipient_and_hash_bound_but_cannot_execute(self):
        draft = prepare(self.contact, "Running five minutes late.", now=self.now)
        meta = draft.metadata()
        self.assertEqual(meta["phone"], "•••0100")
        self.assertFalse(meta["execution_authority"])
        self.assertNotIn("Running five", repr(draft))
        self.assertNotIn("+16055550100", repr(draft))
        binding = draft.approval_binding()
        self.assertEqual(binding["body"], "Running five minutes late.")
        self.assertEqual(binding["phone"], "+16055550100")

    def test_multiple_saved_numbers_require_explicit_choice(self):
        contact = {**self.contact, "phones": ["+16055550100", "+16055550101"]}
        with self.assertRaisesRegex(LookupError, "multiple"):
            prepare(contact, "Hi", now=self.now)
        draft = prepare(contact, "Hi", phone="+16055550101", now=self.now)
        self.assertEqual(draft.approval_binding()["phone"], "+16055550101")

    def test_explicit_number_must_belong_to_contact(self):
        with self.assertRaisesRegex(LookupError, "not one"):
            prepare(self.contact, "Hi", phone="+16055550999", now=self.now)

    def test_digest_changes_when_message_changes(self):
        first = prepare(self.contact, "one", now=self.now)
        second = prepare(self.contact, "two", now=self.now)
        self.assertNotEqual(first.digest, second.digest)

    def test_empty_and_oversized_bodies_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "required"):
            prepare(self.contact, "   ", now=self.now)
        with self.assertRaisesRegex(ValueError, "exceeds"):
            prepare(self.contact, "x" * 4001, now=self.now)

    def test_direct_draft_construction_requires_canonical_private_payload(self):
        with self.assertRaisesRegex(ValueError, "phone must already be normalized"):
            TextDraft("alex", "Alex", "+1 (605) 555-0100", "Hi", self.now)
        with self.assertRaisesRegex(ValueError, "body must already be trimmed"):
            TextDraft("alex", "Alex", "+16055550100", " Hi ", self.now)


class PhoneLinkMessagesProbeTests(unittest.TestCase):
    def test_probe_only_reads_and_omits_arbitrary_message_content(self):
        backend = FakePhoneLinkProbeBackend(
            [{"name": "Phone Link", "process_id": 42}],
            [
                {"name": "Messages", "control_type": "TabItem"},
                {"name": "Private conversation preview", "control_type": "Text"},
                {"name": "Send", "control_type": "Button"},
            ],
        )
        result = probe(backend)
        self.assertTrue(result["window_found"])
        self.assertTrue(result["messages_surface"])
        self.assertTrue(result["send_control_visible"])
        self.assertNotIn("Private conversation", repr(result))
        self.assertEqual(
            [step["action"] for step in backend.actions],
            ["list_windows", "inspect_controls"],
        )

    def test_probe_refuses_ambiguity_instead_of_inspecting_random_window(self):
        backend = FakePhoneLinkProbeBackend(
            [
                {"name": "Phone Link", "process_id": 1},
                {"name": "Phone Link", "process_id": 2},
            ],
            [],
        )
        result = probe(backend)
        self.assertEqual(result["ambiguous_windows"], 2)
        self.assertEqual([step["action"] for step in backend.actions], ["list_windows"])


if __name__ == "__main__":
    unittest.main()
