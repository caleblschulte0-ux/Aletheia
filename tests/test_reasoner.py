"""The reasoning provider adapter: bounded, tool-less, and honest when absent.

No test here runs a model. What is under test is the boundary — how a
model's text is parsed, what invocation it is given, and what happens when
the provider is missing, slow, or wrong.
"""
import subprocess
import unittest
from unittest import mock

from aletheia import brain, reasoner


class ParseCase(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(reasoner._first_json_object('{"a": 1}'), {"a": 1})

    def test_fenced_json(self):
        # models fence output even when told not to
        self.assertEqual(
            reasoner._first_json_object('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(reasoner._first_json_object('```\n{"a": 1}\n```'), {"a": 1})

    def test_json_with_prose_around_it(self):
        self.assertEqual(
            reasoner._first_json_object('Sure! {"a": 1} Hope that helps.'), {"a": 1})

    def test_braces_inside_strings_do_not_end_the_object(self):
        value = reasoner._first_json_object('Here: {"text": "a } b", "n": 2} done')
        self.assertEqual(value, {"text": "a } b", "n": 2})

    def test_escaped_quote_inside_a_string(self):
        value = reasoner._first_json_object(r'{"text": "she said \"hi\"", "n": 1}')
        self.assertEqual(value["n"], 1)

    def test_no_object_is_an_error_not_a_guess(self):
        with self.assertRaises(ValueError):
            reasoner._first_json_object("I would rather not.")

    def test_truncated_object_is_an_error(self):
        with self.assertRaises(ValueError):
            reasoner._first_json_object('{"a": 1, "b": ')

    def test_a_json_array_is_not_a_valid_answer(self):
        with self.assertRaises(ValueError):
            reasoner._first_json_object("[1, 2, 3]")


class InvocationCase(unittest.TestCase):
    def run_with(self, completed):
        with mock.patch.object(reasoner, "cli_path", return_value="claude.exe"), \
                mock.patch.object(reasoner.subprocess, "run",
                                  return_value=completed) as run:
            text = reasoner._run_cli("sys", "user", "haiku")
        return text, run.call_args

    def completed(self, stdout, code=0, stderr=""):
        return subprocess.CompletedProcess([], code, stdout, stderr)

    def test_the_model_is_given_no_tools_and_no_session(self):
        _, call = self.run_with(self.completed('{"result": "{\\"a\\": 1}"}'))
        argv = call.args[0]
        self.assertIn("--tools", argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertIn("--no-session-persistence", argv)
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--disable-slash-commands", argv)

    def test_no_api_key_is_ever_passed(self):
        _, call = self.run_with(self.completed('{"result": "{}"}'))
        joined = " ".join(call.args[0])
        self.assertNotIn("api-key", joined.lower())
        self.assertNotIn("--bare", joined)  # --bare would REQUIRE a key (§6)

    def test_it_runs_outside_the_repo(self):
        # inside the repo the CLI loads this project's context into every call
        _, call = self.run_with(self.completed('{"result": "{}"}'))
        self.assertIn("aletheia-brain", call.kwargs["cwd"])

    def test_it_is_bounded_by_a_timeout(self):
        _, call = self.run_with(self.completed('{"result": "{}"}'))
        self.assertEqual(call.kwargs["timeout"], reasoner.TIMEOUT_S)

    def test_the_result_field_is_what_comes_back(self):
        text, _ = self.run_with(self.completed('{"result": "hello"}'))
        self.assertEqual(text, "hello")

    def test_a_timeout_is_unavailable_not_a_crash(self):
        with mock.patch.object(reasoner, "cli_path", return_value="claude.exe"), \
                mock.patch.object(reasoner.subprocess, "run",
                                  side_effect=subprocess.TimeoutExpired("claude", 90)):
            with self.assertRaises(reasoner.ReasonerUnavailable):
                reasoner._run_cli("s", "u", "haiku")

    def test_a_nonzero_exit_is_unavailable(self):
        with mock.patch.object(reasoner, "cli_path", return_value="claude.exe"), \
                mock.patch.object(reasoner.subprocess, "run",
                                  return_value=self.completed("", 1, "bad login")):
            with self.assertRaises(reasoner.ReasonerUnavailable) as caught:
                reasoner._run_cli("s", "u", "haiku")
        self.assertIn("bad login", str(caught.exception))

    def test_an_error_envelope_is_unavailable(self):
        with mock.patch.object(reasoner, "cli_path", return_value="claude.exe"), \
                mock.patch.object(reasoner.subprocess, "run",
                                  return_value=self.completed('{"is_error": true}')):
            with self.assertRaises(reasoner.ReasonerUnavailable):
                reasoner._run_cli("s", "u", "haiku")

    def test_a_missing_binary_says_so_and_does_not_pretend(self):
        with mock.patch.object(reasoner, "cli_path", return_value=None):
            ok, why = reasoner.available()
            self.assertFalse(ok)
            self.assertIn("not on PATH", why)
            self.assertIn("no API key", why)
            with self.assertRaises(reasoner.ReasonerUnavailable):
                reasoner._run_cli("s", "u", "haiku")


class FallbackCase(unittest.TestCase):
    def test_a_working_provider_returns_its_answer_and_no_reason(self):
        provider = brain.Provider("ok", lambda t, c: {"intent": "answer",
                                                      "summary": "hi"})
        output, degraded = reasoner.infer_or_fallback(provider, "x")
        self.assertEqual(output["summary"], "hi")
        self.assertIsNone(degraded)

    def test_an_unavailable_provider_yields_the_honest_fallback(self):
        provider = brain.Provider("no", mock.Mock(
            side_effect=reasoner.ReasonerUnavailable("not installed")))
        output, degraded = reasoner.infer_or_fallback(provider, "x")
        self.assertEqual(output["intent"], "clarify")
        self.assertIn("not installed", degraded)

    def test_a_contract_violation_is_caught_not_propagated(self):
        provider = brain.Provider("bad", lambda t, c: {"intent": "nonsense"})
        output, degraded = reasoner.infer_or_fallback(provider, "x")
        self.assertEqual(output["intent"], "clarify")
        self.assertIn("BrainOutputError", degraded)

    def test_infer_or_fallback_never_raises(self):
        provider = brain.Provider("boom", mock.Mock(side_effect=ValueError("x")))
        reasoner.infer_or_fallback(provider, "x")  # must not raise


class BrainStepContractCase(unittest.TestCase):
    def valid(self, **kw):
        return brain.validate_output({"intent": "plan", "summary": "s", **kw})

    def test_steps_are_accepted(self):
        self.valid(steps=[{"kind": "note", "text": "x"}, {"gap": "a.b"},
                          {"manual": "do it"}])

    def test_a_step_needs_exactly_one_discriminator(self):
        for bad in ([{}], [{"kind": "note", "gap": "a.b"}], [{"text": "x"}]):
            with self.assertRaises(brain.BrainOutputError):
                self.valid(steps=bad)

    def test_steps_are_bounded(self):
        with self.assertRaises(brain.BrainOutputError):
            self.valid(steps=[{"kind": "note"}] * (brain.MAX_STEPS + 1))

    def test_steps_must_be_a_list_of_objects(self):
        with self.assertRaises(brain.BrainOutputError):
            self.valid(steps="note everything")
        with self.assertRaises(brain.BrainOutputError):
            self.valid(steps=["note everything"])

    def test_unbounded_text_in_a_step_is_refused(self):
        with self.assertRaises(brain.BrainOutputError):
            self.valid(steps=[{"manual": "x" * (brain.MAX_TEXT + 1)}])


if __name__ == "__main__":
    unittest.main()
