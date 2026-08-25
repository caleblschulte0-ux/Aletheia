"""Mocked contract tests for the Windows UI Automation backend."""
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
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
        if self.state.get("window_timeouts", 0):
            self.state["window_timeouts"] -= 1
            raise FakeUIATimeout("not ready")
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

    def descendants(self):
        return [FakeInspectable(f"Control {index}") for index in range(5)]

    def capture_as_image(self):
        return FakeImage()

    def window_text(self):
        return self.state.get("window_name", "Test Window")

    def class_name(self):
        return "TestClass"

    def control_type(self):
        return "Window"

    def process_id(self):
        return 123


class FakeInspectable:
    def __init__(self, name):
        self.name = name

    def window_text(self):
        return self.name

    def class_name(self):
        return "ChildClass"

    def control_type(self):
        return "Button"

    def process_id(self):
        return 123


class FakeImage:
    def save(self, path, format):
        self.format = format
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\nmock")


class FakeDesktop:
    def __init__(self, state, backend):
        self.state = state
        self.state["desktop_backend"] = backend

    def window(self, **selector):
        self.state["window_selector"] = selector
        return FakeWindow(self.state)

    def windows(self):
        return [FakeWindow({"window_name": f"Window {index}"})
                for index in range(4)]


class FakeStartedApp:
    process = 4242


class FakeApplication:
    def __init__(self, state, backend):
        self.state = state
        self.state["application_backend"] = backend

    def start(self, command):
        self.state["start_command"] = command
        return FakeStartedApp()


class FakeUIATimeout(RuntimeError):
    pass


class UIABackendCase(unittest.TestCase):
    def backend(self, observed=None):
        state = {}
        if observed is not None:
            state["observed"] = observed
        module = types.SimpleNamespace(
            Application=lambda backend: FakeApplication(state, backend),
            Desktop=lambda backend: FakeDesktop(state, backend))
        timings = types.SimpleNamespace(TimeoutError=FakeUIATimeout)
        available = mock.patch.object(computer, "available", return_value=(True, "ready"))
        modules = mock.patch.dict(
            "sys.modules", {"pywinauto": module, "pywinauto.timings": timings})
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
        self.assertEqual(state["window_wait_not"][0], "exists")
        self.assertLessEqual(state["window_wait_not"][1], computer.WAIT_POLL_S)
        self.assertIn("no longer exists", result["verified"])

    def test_lists_windows_and_bounds_results(self):
        backend, _ = self.backend()
        result = backend.perform({"action": "list_windows", "max_results": 2})
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["windows"][0]["name"], "Window 0")
        self.assertEqual(result["windows"][0]["process_id"], 123)

    def test_inspects_named_window_controls_with_a_limit(self):
        backend, _ = self.backend()
        result = backend.perform({
            "action": "inspect_controls",
            "window": {"title": "Test Window"},
            "max_results": 3})
        self.assertEqual(result["count"], 3)
        self.assertEqual(
            [row["name"] for row in result["controls"]],
            ["Control 0", "Control 1", "Control 2"])

    def test_screenshot_is_confined_to_capture_dir_and_verified(self):
        backend, _ = self.backend()
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(computer, "CAPTURE_DIR", Path(directory)):
                result = backend.perform({
                    "action": "screenshot_window",
                    "window": {"title": "Test Window"},
                    "filename": "evidence.png"})
                out = Path(result["path"])
                self.assertEqual(out.parent, Path(directory))
                self.assertEqual(out.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_screenshot_never_overwrites_existing_evidence(self):
        backend, _ = self.backend()
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "evidence.png"
            out.write_bytes(b"original")
            with mock.patch.object(computer, "CAPTURE_DIR", Path(directory)):
                with self.assertRaisesRegex(FileExistsError, "never overwritten"):
                    backend.perform({
                        "action": "screenshot_window",
                        "window": {"title": "Test Window"},
                        "filename": "evidence.png"})
            self.assertEqual(out.read_bytes(), b"original")

    def test_uia_wait_retries_in_short_interruptible_polls(self):
        backend, state = self.backend()
        state["window_timeouts"] = 1
        with mock.patch.object(computer.policy, "ensure_not_halted") as guard:
            backend.perform({
                "action": "wait_window",
                "window": {"title": "Slow Window"},
                "timeout_s": 2})
        self.assertGreaterEqual(guard.call_count, 2)
        self.assertLessEqual(state["window_wait"][1], computer.WAIT_POLL_S)

    def test_halt_interrupts_while_uia_wait_is_retrying(self):
        backend, state = self.backend()
        state["window_timeouts"] = 5
        with mock.patch.object(
                computer.policy, "ensure_not_halted",
                side_effect=[None, computer.policy.Halted("stop")]):
            with self.assertRaises(computer.policy.Halted):
                backend.perform({
                    "action": "wait_window",
                    "window": {"title": "Slow Window"},
                    "timeout_s": 10})
        self.assertEqual(state["window_timeouts"], 4)


if __name__ == "__main__":
    unittest.main()
