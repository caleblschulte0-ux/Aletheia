"""Mocked contract tests for the Windows UI Automation backend."""
import subprocess
import types
import unittest
from unittest import mock

from aletheia import computer


class FakeWrapper:
    def __init__(self, state):
        self.state = state

    def invoke(self):
        self.state["invoked"] = True

    def click_input(self):
        raise AssertionError("coordinate/input clicking must not be used")

    def set_edit_text(self, text):
        self.state["typed"] = text

    def window_text(self):
        return self.state.get("observed", self.state.get("typed", ""))


class FakeControl:
    def __init__(self, state):
        self.state = state

    def wait(self, condition, timeout):
        self.state["control_wait"] = (condition, timeout)

    def wrapper_object(self):
        return FakeWrapper(self.state)


class FakeWindow:
    def __init__(self, state):
        self.state = state

    def wait(self, condition, timeout):
        self.state["window_wait"] = (condition, timeout)

    def wait_not(self, condition, timeout):
        self.state["window_wait_not"] = (condition, timeout)

    def set_focus(self):
        self.state["focused"] = True

    def close(self):
        self.state["closed"] = True

    def child_window(self, **selector):
        self.state["control_selector"] = selector
        return FakeControl(self.state)


class FakeDesktop:
    def __init__(self, state, backend):
        self.state = state
        self.state["desktop_backend"] = backend

    def window(self, **selector):
        self.state["window_selector"] = selector
        return FakeWindow(self.state)


class FakeStartedApp:
    process = 4242


class FakeApplication:
    def __init__(self, state, backend):
        self.state = state
        self.state["application_backend"] = backend

    def start(self, command):
        self.state["start_command"] = command
        return FakeStartedApp()


class UIABackendCase(unittest.TestCase):
    def backend(self, observed=None):
        state = {}
        if observed is not None:
            state["observed"] = observed
        module = types.SimpleNamespace(
            Application=lambda backend: FakeApplication(state, backend),
            Desktop=lambda backend: FakeDesktop(state, backend))
        available = mock.patch.object(computer, "available", return_value=(True, "ready"))
        modules = mock.patch.dict("sys.modules", {"pywinauto": module})
        available.start(); modules.start()
        self.addCleanup(available.stop); self.addCleanup(modules.stop)
        return computer.WindowsUIABackend(), state

    def test_open_app_uses_argument_quoting_without_a_shell(self):
        backend, state = self.backend()
        result = backend.perform({
            "action": "open_app", "app": r"C:\Program Files\Example\app.exe",
            "arguments": ["hello world", "--safe"]})
        expected = subprocess.list2cmdline([
            r"C:\Program Files\Example\app.exe", "hello world", "--safe"])
        self.assertEqual(state["start_command"], expected)
        self.assertEqual(state["application_backend"], "uia")
        self.assertEqual(result["process_id"], 4242)

    def test_invoke_uses_named_uia_selectors_not_click_input(self):
        backend, state = self.backend()
        result = backend.perform({
            "action": "invoke",
            "window": {"title": "Calculator"},
            "control": {"title": "One", "control_type": "Button"},
            "timeout_s": 4})
        self.assertEqual(state["window_selector"], {"title": "Calculator"})
        self.assertEqual(
            state["control_selector"], {"title": "One", "control_type": "Button"})
        self.assertTrue(state["invoked"])
        self.assertIn("Invoke", result["verified"])

    def test_set_text_requires_exact_readback(self):
        backend, state = self.backend()
        result = backend.perform({
            "action": "set_text",
            "window": {"title": "Notepad"},
            "control": {"control_type": "Document"},
            "text": "hello"})
        self.assertEqual(state["typed"], "hello")
        self.assertTrue(result["verified"])

    def test_set_text_mismatch_fails_without_disclosing_content(self):
        backend, _ = self.backend(observed="different")
        with self.assertRaisesRegex(computer.VerificationFailed, "verification failed"):
            backend.perform({
                "action": "set_text",
                "window": {"title": "Notepad"},
                "control": {"control_type": "Document"},
                "text": "sensitive requested text"})

    def test_close_waits_until_window_no_longer_exists(self):
        backend, state = self.backend()
        result = backend.perform({
            "action": "close_window",
            "window": {"title": "Harmless test window"},
            "timeout_s": 7})
        self.assertTrue(state["closed"])
        self.assertEqual(state["window_wait_not"], ("exists", 7.0))
        self.assertIn("no longer exists", result["verified"])


if __name__ == "__main__":
    unittest.main()
