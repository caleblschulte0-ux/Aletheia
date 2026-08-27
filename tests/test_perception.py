"""Reading the screen: never pressing, never leaking, never guessing."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, perception, policy


class FakeBackend:
    """Stands in for the UIA backend; records what it was asked to do."""

    def __init__(self, windows=None, controls=None):
        self.windows = windows if windows is not None else [
            {"name": "Bank of Somewhere - Chrome", "control_type": "Window"},
            {"name": "Taskbar", "control_type": "Pane"},
        ]
        self.controls = controls if controls is not None else [
            {"name": "Sign in", "control_type": "Button"},
            {"name": "Password", "control_type": "Edit"},
            {"name": "hunter2-the-actual-secret", "control_type": "Edit.Password"},
            {"name": "Balance: 1234.56", "control_type": "Text"},
        ]
        self.performed = []

    def perform(self, step):
        self.performed.append(step)
        if step["action"] == "list_windows":
            return {"action": "list_windows", "windows": self.windows}
        if step["action"] == "inspect_controls":
            return {"action": "inspect_controls", "controls": self.controls}
        raise AssertionError(f"backend asked to {step['action']} — it should not be")


class RedactionCase(unittest.TestCase):
    def test_a_password_control_never_yields_its_contents(self):
        safe = perception.redact_control(
            {"name": "hunter2-the-actual-secret", "control_type": "Edit.Password"})
        self.assertNotIn("hunter2", json.dumps(safe))
        self.assertTrue(safe["redacted"])

    def test_a_field_named_like_a_secret_is_treated_as_one(self):
        for name in ("Password", "API key", "Recovery code", "CVV",
                     "Seed phrase", "private key"):
            safe = perception.redact_control({"name": name, "control_type": "Edit"})
            self.assertEqual(safe["name"], "[a credential field]", name)

    def test_credential_shaped_values_are_masked_wherever_they_appear(self):
        for secret in ("sk-abcdefghijklmnopqrstuvwx",
                       "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
                       "xoxb-1234567890-abcdefghij",
                       "AKIAIOSFODNN7EXAMPLE",
                       "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0",
                       "4111111111111111"):
            masked = perception.redact(f"the value is {secret} ok")
            self.assertNotIn(secret, masked, secret)
            self.assertIn(perception.REDACTED, masked)

    def test_ordinary_text_survives_redaction(self):
        self.assertEqual(perception.redact("Submit order for 12 items"),
                         "Submit order for 12 items")

    def test_a_private_key_header_is_masked(self):
        self.assertIn(perception.REDACTED,
                      perception.redact("-----BEGIN RSA PRIVATE KEY-----"))


class ReadOnlyCase(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(policy, "ensure_not_halted")
        p.start(); self.addCleanup(p.stop)

    def test_the_allowlist_is_only_reads(self):
        self.assertEqual(perception.READ_ONLY_ACTIONS,
                         {"list_windows", "inspect_controls"})

    def test_any_acting_step_is_refused(self):
        backend = FakeBackend()
        for action in ("invoke", "set_text", "open_app", "close_window",
                       "screenshot_window", "focus_window"):
            with self.assertRaises(ValueError, msg=action):
                perception._perform(backend, {"action": action})
        self.assertEqual(backend.performed, [], "it acted on the desktop")

    def test_observation_only_ever_asks_for_reads(self):
        backend = FakeBackend()
        perception.observe({"title_re": "Bank"}, backend=backend)
        self.assertTrue(all(step["action"] in perception.READ_ONLY_ACTIONS
                            for step in backend.performed))

    def test_halt_stops_a_screen_read(self):
        with mock.patch.object(policy, "ensure_not_halted",
                               side_effect=policy.Halted("halted")):
            with self.assertRaises(policy.Halted):
                perception.observe(backend=FakeBackend())


class ObserveCase(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(policy, "ensure_not_halted")
        p.start(); self.addCleanup(p.stop)

    def test_observing_contacts_no_model(self):
        with mock.patch.object(perception.reasoner, "infer_json") as infer:
            perception.observe(backend=FakeBackend())
        infer.assert_not_called()

    def test_the_focused_window_is_described_without_its_secrets(self):
        observation = perception.observe({"title_re": "Bank"},
                                         backend=FakeBackend())
        blob = json.dumps(observation)
        self.assertIn("Sign in", blob)
        self.assertNotIn("hunter2", blob)
        self.assertIn("[a credential field]", blob)

    def test_it_carries_its_own_trust_boundary(self):
        observation = perception.observe(backend=FakeBackend())
        self.assertIn("never instructions", observation["trust_boundary"])

    def test_a_huge_screen_is_trimmed_by_whole_records(self):
        many = [{"name": f"Control number {i} with a fairly long label attached",
                 "control_type": "Text"} for i in range(400)]
        observation = perception.observe(
            {"title_re": "x"}, backend=FakeBackend(controls=many))
        self.assertTrue(observation["trimmed"])
        encoded = json.dumps(observation).encode("utf-8")
        self.assertLessEqual(len(encoded), perception.MAX_OBSERVATION_BYTES + 200)
        # whatever survived is still well-formed records, not sliced JSON
        for control in observation["focused"]["controls"]:
            self.assertIn("control_type", control)


class DescribeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(journal, "JOURNAL_PATH",
                              Path(self.tmp.name) / "journal.jsonl")
        p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(policy, "ensure_not_halted")
        p.start(); self.addCleanup(p.stop)

    def answer(self, **kw):
        base = {"answer": "Chrome is open on a banking page.",
                "confidence": 0.9, "basis": "window titles"}
        base.update(kw)
        return base

    def test_it_answers_from_the_observation(self):
        seen = {}

        def infer(system, text, context=None, **kw):
            seen["system"] = system
            seen["context"] = context
            return self.answer()

        out = perception.describe("what's open?", backend=FakeBackend(), infer=infer)
        self.assertEqual(out["confidence"], 0.9)
        self.assertIn("UNTRUSTED DATA", seen["system"])
        self.assertIn("windows", seen["context"])

    def test_a_secret_in_the_model_answer_is_still_redacted(self):
        out = perception.describe(
            "what's the key?", backend=FakeBackend(),
            infer=lambda *a, **k: self.answer(
                answer="The key is sk-abcdefghijklmnopqrstuvwx"))
        self.assertNotIn("sk-abcdefghij", out["answer"])

    def test_unknown_fields_from_the_model_are_refused(self):
        with self.assertRaises(ValueError):
            perception.validate_answer(
                {"answer": "hi", "confidence": 1.0, "clicked": True})

    def test_an_empty_or_unscored_answer_is_refused(self):
        with self.assertRaises(ValueError):
            perception.validate_answer({"answer": "", "confidence": 1.0})
        with self.assertRaises(ValueError):
            perception.validate_answer({"answer": "hi", "confidence": 2})

    def test_an_empty_question_is_refused_before_anything_is_read(self):
        backend = FakeBackend()
        with self.assertRaises(ValueError):
            perception.describe("   ", backend=backend)
        self.assertEqual(backend.performed, [])


class ReasonerEncodingCase(unittest.TestCase):
    """Regression: text=True alone decodes with the locale codec.

    On this machine that is cp1252, so one em-dash in a model's answer
    raised UnicodeDecodeError and took the whole reasoning path down —
    planner, advisor, scheduling and perception alike. Found live.
    """

    def test_the_cli_is_decoded_as_utf8(self):
        import subprocess
        from aletheia import reasoner
        captured = {}

        def fake_run(argv, **kwargs):
            captured.update(kwargs)
            return subprocess.CompletedProcess(
                argv, 0, json.dumps({"result": '{"ok": "em—dash and £"}'}), "")

        with mock.patch.object(reasoner, "cli_path", return_value="claude.exe"), \
                mock.patch.object(reasoner.subprocess, "run", fake_run):
            text = reasoner._run_cli("sys", "user", "haiku")
        self.assertEqual(captured.get("encoding"), "utf-8")
        self.assertEqual(captured.get("errors"), "replace")
        self.assertIn("em—dash", text)


if __name__ == "__main__":
    unittest.main()
