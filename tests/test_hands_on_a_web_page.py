"""Hands on a web page: what the TikTok demo's post sheet taught (2026-09-11).

A probe of the real page under Windows UI Automation found what a
button-shaped hand could not do there: a checkbox or switch has Toggle and no
Invoke, a drop-down has ExpandCollapse and no Invoke, the sheet's heading and
its button are both named "Post to TikTok", and the video's button is named
"play" where a plan writes "Play". These fakes hold the repairs. None of them
clicks with the mouse.
"""
import re
import sys
import types
import unittest
from unittest import mock

from aletheia import computer


class NoPatternInterfaceError(Exception):
    pass


class FakeUIATimeout(RuntimeError):
    pass


class FakeAmbiguous(Exception):
    pass


class Toggle:
    def __init__(self, state=0, sticks=True):
        self.CurrentToggleState = state
        self.sticks = sticks

    def Toggle(self):
        if self.sticks:
            self.CurrentToggleState = 1 - self.CurrentToggleState


class Expand:
    expanded = False

    def Expand(self):
        self.expanded = True


class Element:
    def __init__(self, name, control_type, *, invoke=False, toggle=None, expand=None):
        self.name = name
        self.element_info = types.SimpleNamespace(control_type=control_type, automation_id="")
        self.invoked = False
        if invoke:
            self.iface_invoke = object()
        if toggle is not None:
            self.iface_toggle = toggle
        if expand is not None:
            self.iface_expand_collapse = expand

    def window_text(self):
        return self.name

    def class_name(self):
        return ""

    def invoke(self):
        if not hasattr(self, "iface_invoke"):
            raise NoPatternInterfaceError()
        self.invoked = True

    def click_input(self, *args, **kwargs):
        raise AssertionError("hands never click with the mouse")


class Spec:
    def __init__(self, window, selector):
        self.window, self.selector, self.found = window, selector, None

    def wait(self, condition, timeout):
        self.window.asked.append(dict(self.selector))
        hits = [e for e in self.window.elements if computer._selector_matches(e, self.selector)]
        if not hits:
            raise FakeUIATimeout("not there")
        if len(hits) > 1:
            raise FakeAmbiguous("several")
        self.found = hits[0]
        return self

    def wrapper_object(self):
        return self.found


class Window:
    handle = 7

    def __init__(self, elements):
        self.elements, self.asked = elements, []

    def wait(self, condition, timeout):
        return self

    def wrapper_object(self):
        return self

    def child_window(self, **selector):
        return Spec(self, selector)

    def descendants(self):
        return list(self.elements)


class WebPageCase(unittest.TestCase):
    def backend(self, *elements):
        window = Window(list(elements))
        desktop = types.SimpleNamespace(window=lambda **selector: window, windows=lambda: [window])
        module = types.SimpleNamespace(Application=lambda backend: None,
                                       Desktop=lambda backend: desktop)
        for patch in (mock.patch.object(computer, "available", return_value=(True, "ready")),
                      mock.patch.dict(sys.modules, {
                          "pywinauto": module,
                          "pywinauto.timings": types.SimpleNamespace(TimeoutError=FakeUIATimeout),
                          "pywinauto.findwindows": types.SimpleNamespace(
                              ElementAmbiguousError=FakeAmbiguous)}),
                      mock.patch.object(computer, "WAIT_POLL_S", 0.01),
                      mock.patch.object(computer, "_sleep", lambda seconds: None)):
            patch.start()
            self.addCleanup(patch.stop)
        return computer.WindowsUIABackend(), window

    @staticmethod
    def step(title):
        return {"action": "invoke", "window": {"title": "Shorts Media"},
                "control": {"title": title}, "timeout_s": 1}

    def test_a_checkbox_is_toggled_not_invoked(self):
        box = Element("Comment", "CheckBox", toggle=Toggle(0))
        backend, _ = self.backend(box)
        result = backend.perform(self.step("Comment"))
        self.assertEqual(box.iface_toggle.CurrentToggleState, 1)
        self.assertIn("Toggle", result["verified"])

    def test_a_toggle_that_does_not_change_is_not_reported_as_done(self):
        backend, _ = self.backend(Element("Comment", "CheckBox", toggle=Toggle(0, sticks=False)))
        with self.assertRaises(computer.VerificationFailed):
            backend.perform(self.step("Comment"))

    def test_a_drop_down_is_opened(self):
        combo = Element("Who can view this video", "ComboBox", expand=Expand())
        backend, _ = self.backend(combo)
        backend.perform(self.step("Who can view this video"))
        self.assertTrue(combo.iface_expand_collapse.expanded)

    def test_something_with_nothing_to_press_is_refused(self):
        backend, _ = self.backend(Element("Comment", "Text"))
        with self.assertRaises(computer.VerificationFailed):
            backend.perform(self.step("Comment"))

    def test_a_failure_that_is_not_a_missing_pattern_is_not_papered_over(self):
        broken = Element("Save", "Button", invoke=True, toggle=Toggle(0))
        broken.invoke = mock.Mock(side_effect=RuntimeError("element went away"))
        backend, _ = self.backend(broken)
        with self.assertRaises(RuntimeError):
            backend.perform(self.step("Save"))
        self.assertEqual(broken.iface_toggle.CurrentToggleState, 0)

    def test_the_heading_and_the_button_share_a_name(self):
        heading = Element("Post to TikTok", "Text")
        button = Element("Post to TikTok", "Button", invoke=True)
        backend, _ = self.backend(heading, button)
        # the guard reads the one that will be pressed...
        self.assertEqual(backend.describe_control(self.step("Post to TikTok"))["control_type"],
                         "Button")
        # ...and that is the one pressed
        backend.perform(self.step("Post to TikTok"))
        self.assertTrue(button.invoked)

    def test_two_pressable_matches_are_still_refused(self):
        backend, _ = self.backend(Element("OK", "Button", invoke=True),
                                  Element("OK", "Button", invoke=True))
        with self.assertRaises(FakeAmbiguous):
            backend.perform(self.step("OK"))

    def test_a_name_in_a_different_case_is_found(self):
        play = Element("play", "Button", invoke=True)
        backend, window = self.backend(play)
        backend.perform(self.step("Play"))
        self.assertTrue(play.invoked)
        self.assertEqual(window.asked[0], {"title": "Play"}, "the exact title is tried first")

    def test_a_text_box_that_takes_its_value_a_moment_later_is_read_again(self):
        class SlowBox(Element):
            def __init__(self):
                super().__init__("Caption 0/2200", "Edit")
                self.iface_value = object()
                self.value, self.pending, self.reads = "old caption", None, 0

            def set_edit_text(self, text):
                self.pending = text

            def get_value(self):
                self.reads += 1
                if self.pending is not None and self.reads > 2:
                    self.value, self.pending = self.pending, None
                return self.value

        box = SlowBox()
        backend, _ = self.backend(box)
        result = backend.perform({"action": "set_text", "window": {"title": "Shorts Media"},
                                  "control": {"title_re": "Caption", "control_type": "Edit"},
                                  "text": "new #shorts", "timeout_s": 1})
        self.assertTrue(result["verified"])
        self.assertEqual(box.value, "new #shorts")

    def test_a_browser_list_is_chosen_through_its_option(self):
        class Option(Element):
            def __init__(self, name, box):
                super().__init__(name, "ListItem")
                self.iface_selection_item = types.SimpleNamespace(Select=lambda: setattr(box, "value", name))

        class WebList(Element):
            def __init__(self):
                super().__init__("Who can view this video", "ComboBox", expand=Expand())
                self.value = "Select who can view this video…"
                self.options = [Option(n, self) for n in ("Only me (private)", "Followers", "Everyone")]

            def children(self):
                return self.options if self.iface_expand_collapse.expanded else []

            def descendants(self, control_type=None):
                return list(self.children())

            def select(self, item):
                raise IndexError("the options could not be read")

            def get_value(self):
                return self.value

        box = WebList()
        backend, _ = self.backend(box)
        result = backend.perform({"action": "select", "window": {"title": "Shorts Media"},
                                  "control": {"control_type": "ComboBox"}, "value": "Everyone",
                                  "timeout_s": 1})
        self.assertEqual(box.value, "Everyone")
        self.assertEqual(result["selected"], "Everyone")

    def test_a_label_that_starts_a_longer_name_is_found_last(self):
        lead = computer._control_candidates({"title": "Caption"})[2]["title_re"]
        self.assertTrue(re.match(lead, "Caption 178/2200"))
        self.assertTrue(re.match(lead, "caption"))
        self.assertFalse(re.match(lead, "Captions off"), "a whole word, not part of one")
        self.assertFalse(re.match(lead, "Add caption"), "the start of the name, not anywhere")
        card = Element("Urban Growth Just Hit A 50-Year Low Of 1.36%", "Button", invoke=True)
        backend, window = self.backend(card)
        backend.perform(self.step("Urban Growth Just Hit A 50-Year Low"))
        self.assertTrue(card.invoked)
        self.assertEqual([sorted(asked) for asked in window.asked[:3]],
                         [["title"], ["title_re"], ["title_re"]], "exact first, then loose, then lead")

    def test_an_exact_name_still_wins_over_a_longer_one(self):
        save = Element("Save", "Button", invoke=True)
        save_as = Element("Save as", "Button", invoke=True)
        backend, _ = self.backend(save_as, save)
        backend.perform(self.step("Save"))
        self.assertTrue(save.invoked)
        self.assertFalse(save_as.invoked)

    def test_the_loose_title_is_still_the_whole_name(self):
        loose = computer._control_candidates({"title": "Play"})[1]["title_re"]
        self.assertTrue(re.match(loose, " play "))
        self.assertFalse(re.match(loose, "Play all"))
        self.assertFalse(re.match(loose, "Autoplay"))
        self.assertEqual(computer._control_candidates({"title_re": "Play"}), [{"title_re": "Play"}])


EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


class AnInstalledProgramIsFound(unittest.TestCase):
    """His approved take failed on its first action: "msedge.exe" is not on
    PATH, and CreateProcess does not read App Paths (2026-09-11)."""

    @staticmethod
    def registered(name):
        return EDGE if name == "msedge.exe" else ""

    def test_a_registered_program_is_found_by_its_name(self):
        for asked in ("msedge.exe", "msedge", ' "msedge.exe" '):
            with self.subTest(asked=asked):
                self.assertEqual(computer.resolve_app(asked, app_paths=self.registered,
                                                      which=lambda name: None), EDGE)

    def test_a_path_is_used_as_written_and_path_is_asked_first(self):
        refuse = mock.Mock(side_effect=AssertionError("a path is not looked up"))
        self.assertEqual(computer.resolve_app(r"C:\Tools\app.exe", app_paths=refuse, which=refuse),
                         r"C:\Tools\app.exe")
        # what started before still starts the same way: PATH wins over App Paths
        self.assertEqual(computer.resolve_app(
            "notepad.exe", app_paths=lambda n: r"C:\Program Files\WindowsApps\Notepad\Notepad.exe",
            which=lambda n: r"C:\Windows\System32\notepad.exe"),
            r"C:\Windows\System32\notepad.exe")
        self.assertEqual(computer.resolve_app("nowhere.exe", app_paths=lambda n: "",
                                              which=lambda n: None), "nowhere.exe")

    def backend(self):
        started = []
        app = types.SimpleNamespace(start=lambda command: started.append(command)
                                    or types.SimpleNamespace(process=4242))
        module = types.SimpleNamespace(Application=lambda backend: app, Desktop=lambda backend: None)
        for patch in (mock.patch.object(computer, "available", return_value=(True, "ready")),
                      mock.patch.dict(sys.modules, {
                          "pywinauto": module,
                          "pywinauto.timings": types.SimpleNamespace(TimeoutError=FakeUIATimeout)})):
            patch.start()
            self.addCleanup(patch.stop)
        return computer.WindowsUIABackend(), started

    def test_the_program_found_is_the_one_started(self):
        backend, started = self.backend()
        with mock.patch.object(computer, "resolve_app", return_value=EDGE):
            backend.perform({"action": "open_app", "app": "msedge.exe",
                             "arguments": ["http://localhost:8770/"]})
        self.assertEqual(started, [f'"{EDGE}" http://localhost:8770/'])

    def test_a_name_that_resolves_to_a_shell_is_never_started(self):
        backend, started = self.backend()
        with mock.patch.object(computer, "resolve_app",
                               return_value=r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"):
            with self.assertRaises(computer.ApprovalRequired):
                backend.perform({"action": "open_app", "app": "harmless.exe"})
        self.assertEqual(started, [])


if __name__ == "__main__":
    unittest.main()
