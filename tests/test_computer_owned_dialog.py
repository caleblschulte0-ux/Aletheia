"""A dialog an app owns is a window the hands can find.

2026-09-02, live on the operator's PC: a plan waited for "Save As" and
timed out while Notepad's Save dialog sat on screen. Two causes, both
held here — Windows 11 titles it "Save as", and under UI Automation the
dialog is a CHILD of Notepad's window, not a top-level window, so
`Desktop.window()` never saw it.
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from aletheia import computer


class FakeUIATimeout(RuntimeError):
    pass


class FakeSpec:
    """A WindowSpecification: found only when anchored by handle or when
    the top-level table has the title."""

    def __init__(self, state, selector):
        self.state = state
        self.selector = selector

    handle = 4242   # every real top-level window has an HWND

    def wait(self, condition, timeout):
        self.state["waits"].append(dict(self.selector))
        if "handle" in self.selector:
            return self
        import re
        for title in self.state["top_titles"]:
            if "title_re" in self.selector and re.match(self.selector["title_re"], title):
                return self
            if self.selector.get("title") == title:
                return self
        raise FakeUIATimeout("not at the top level")


class FakeElement:
    def __init__(self, title, handle, class_name="#32770", control_type="Window"):
        self._title, self.handle = title, handle
        self._class, self.element_info = class_name, types.SimpleNamespace(
            control_type=control_type, automation_id="")

    def window_text(self):
        return self._title

    def class_name(self):
        return self._class


class FakeTop(FakeElement):
    def __init__(self, title, handle, owned=()):
        super().__init__(title, handle, class_name="Notepad")
        self.owned = list(owned)

    def children(self, control_type=None):
        return [c for c in self.owned
                if control_type is None or c.element_info.control_type == control_type]


class FakeDesktop:
    def __init__(self, state, backend):
        self.state = state

    def window(self, **selector):
        return FakeSpec(self.state, selector)

    def windows(self):
        return self.state["tops"]


class OwnedDialogCase(unittest.TestCase):
    def backend(self, tops, top_titles=()):
        state = {"tops": tops, "top_titles": list(top_titles), "waits": []}
        module = types.SimpleNamespace(
            Application=lambda backend: None,
            Desktop=lambda backend: FakeDesktop(state, backend))
        timings = types.SimpleNamespace(TimeoutError=FakeUIATimeout)
        for patch in (mock.patch.object(computer, "available", return_value=(True, "ready")),
                      mock.patch.dict(sys.modules, {"pywinauto": module,
                                                    "pywinauto.timings": timings}),
                      mock.patch.object(computer, "WAIT_POLL_S", 0.01)):
            patch.start(); self.addCleanup(patch.stop)
        return computer.WindowsUIABackend(), state

    def test_a_dialog_under_its_owner_is_found_and_anchored_by_handle(self):
        dialog = FakeElement("Save as", handle=777)
        tops = [FakeTop("Chrome", 1), FakeTop("Untitled - Notepad", 2, owned=[dialog])]
        backend, state = self.backend(tops, top_titles=["Chrome", "Untitled - Notepad"])
        result = backend.perform({"action": "wait_window",
                                  "window": {"title_re": "Save As"}, "timeout_s": 1})
        self.assertEqual(result["verified"], "window exists, visible, enabled, and ready")
        self.assertIn({"handle": 777}, state["waits"])

    def test_the_title_pattern_ignores_case_at_the_top_level_too(self):
        backend, state = self.backend([], top_titles=["Save as"])
        backend.perform({"action": "wait_window", "window": {"title_re": "Save As"},
                         "timeout_s": 1})
        self.assertEqual(state["waits"][0], {"title_re": "(?i).*Save As"})

    def test_a_title_pattern_matches_anywhere_in_the_title(self):
        # pywinauto anchors title_re at the start; "Notepad" must still find
        # "Untitled - Notepad" (the planner's own example, live 2026-09-02)
        sel = computer._window_selector({"title_re": "Notepad"})
        self.assertEqual(sel, {"title_re": "(?i).*Notepad"})
        import re
        self.assertTrue(re.match(sel["title_re"], "Untitled - Notepad"))
        self.assertTrue(re.match(sel["title_re"], "*hands.txt - notepad"))
        self.assertEqual(computer._window_selector({"title_re": ".*Notepad"}),
                         {"title_re": "(?i).*Notepad"})
        self.assertEqual(computer._window_selector({"title_re": "(?s)^Save$"}),
                         {"title_re": "(?si).*^Save$"})
        self.assertTrue(re.match("(?si).*^Save$", "Save"))
        self.assertFalse(re.match("(?si).*^Save$", "Save as"))

    def test_a_found_window_is_re_addressed_by_handle_for_the_action(self):
        backend, state = self.backend([], top_titles=["Untitled - Notepad"])
        window = backend._window({"window": {"title_re": ".*Notepad"}, "timeout_s": 1})
        self.assertEqual(window.selector, {"handle": 4242})

    def test_an_exact_title_is_left_alone(self):
        self.assertEqual(computer._window_selector({"title": "Save As"}),
                         {"title": "Save As"})

    def test_nothing_matching_anywhere_still_times_out(self):
        tops = [FakeTop("Untitled - Notepad", 2, owned=[FakeElement("Open", 5)])]
        backend, state = self.backend(tops, top_titles=["Untitled - Notepad"])
        with self.assertRaises(FakeUIATimeout):
            backend.perform({"action": "wait_window",
                             "window": {"title_re": "Save As"}, "timeout_s": 0.05})
        self.assertFalse(any("handle" in w for w in state["waits"]))

    def test_only_direct_window_children_are_considered(self):
        # a Button child is not a dialog, and an owner that errors is skipped
        class Broken(FakeTop):
            def children(self, control_type=None):
                raise RuntimeError("COM error")
        button = FakeElement("Save as", handle=9, control_type="Button")
        tops = [Broken("x", 1), FakeTop("Untitled - Notepad", 2, owned=[button])]
        backend, state = self.backend(tops, top_titles=[])
        with self.assertRaises(FakeUIATimeout):
            backend.perform({"action": "wait_window",
                             "window": {"title_re": "Save as"}, "timeout_s": 0.05})

    def test_halt_is_re_read_while_waiting(self):
        backend, state = self.backend([], top_titles=[])
        with mock.patch.object(computer.policy, "ensure_not_halted",
                               side_effect=computer.policy.Halted("stop")):
            with self.assertRaises(computer.policy.Halted):
                backend.perform({"action": "wait_window",
                                 "window": {"title_re": "Save as"}, "timeout_s": 1})
        self.assertEqual(state["waits"], [])


class FakeCtrlSpec:
    def __init__(self, state, selector):
        self.state, self.selector = state, selector

    def wait(self, condition, timeout):
        self.state["control_waits"].append(dict(self.selector))
        if self.selector.get("control_type") in self.state["controls_present"]:
            return self
        raise FakeUIATimeout("no such control")

    def wrapper_object(self):
        return self.state["wrapper"]


class TextAreaCase(unittest.TestCase):
    """A planner that cannot see the screen says Edit; Notepad says Document."""

    def test_candidates(self):
        self.assertEqual(computer._control_candidates({"control_type": "Edit"}),
                         [{"control_type": "Edit"}, {"control_type": "Document"}])
        self.assertEqual(computer._control_candidates({"control_type": "Document"}),
                         [{"control_type": "Document"}, {"control_type": "Edit"}])
        self.assertEqual(computer._control_candidates({"control_type": "Button"}),
                         [{"control_type": "Button"}])
        self.assertEqual(computer._control_candidates({"control_type": "Edit", "auto_id": "x"}),
                         [{"control_type": "Edit", "auto_id": "x"}])

    def test_set_text_finds_the_document_when_the_plan_said_edit(self):
        class Wrapper:
            text = None
            def set_edit_text(self, text): self.text = text
            def window_text(self): return self.text
        state = {"control_waits": [], "controls_present": {"Document"}, "wrapper": Wrapper(),
                 "waits": [], "top_titles": ["Untitled - Notepad"], "tops": []}

        class Spec(FakeSpec):
            def child_window(self, **selector):
                return FakeCtrlSpec(self.state, selector)

        module = types.SimpleNamespace(
            Application=lambda backend: None,
            Desktop=lambda backend: types.SimpleNamespace(
                window=lambda **s: Spec(state, s), windows=lambda: []))
        timings = types.SimpleNamespace(TimeoutError=FakeUIATimeout)
        with mock.patch.object(computer, "available", return_value=(True, "ready")),                 mock.patch.dict(sys.modules, {"pywinauto": module, "pywinauto.timings": timings}),                 mock.patch.object(computer, "WAIT_POLL_S", 0.01):
            backend = computer.WindowsUIABackend()
            result = backend.perform({"action": "set_text", "window": {"title_re": "Notepad"},
                                      "control": {"control_type": "Edit"},
                                      "text": "Crimson leaves", "timeout_s": 1})
        self.assertTrue(result["verified"])
        self.assertEqual(state["wrapper"].text, "Crimson leaves")
        self.assertEqual(state["control_waits"][:2],
                         [{"control_type": "Edit"}, {"control_type": "Document"}])

    def test_a_named_control_is_never_widened(self):
        state = {"control_waits": [], "controls_present": {"Document"}, "wrapper": None,
                 "waits": [], "top_titles": ["Untitled - Notepad"], "tops": []}

        class Spec(FakeSpec):
            def child_window(self, **selector):
                return FakeCtrlSpec(self.state, selector)

        module = types.SimpleNamespace(
            Application=lambda backend: None,
            Desktop=lambda backend: types.SimpleNamespace(
                window=lambda **s: Spec(state, s), windows=lambda: []))
        timings = types.SimpleNamespace(TimeoutError=FakeUIATimeout)
        with mock.patch.object(computer, "available", return_value=(True, "ready")),                 mock.patch.dict(sys.modules, {"pywinauto": module, "pywinauto.timings": timings}),                 mock.patch.object(computer, "WAIT_POLL_S", 0.01):
            backend = computer.WindowsUIABackend()
            with self.assertRaises(FakeUIATimeout):
                backend.perform({"action": "set_text", "window": {"title_re": "Notepad"},
                                 "control": {"control_type": "Edit", "auto_id": "body"},
                                 "text": "x", "timeout_s": 0.05})
        self.assertTrue(all(w == {"control_type": "Edit", "auto_id": "body"}
                            for w in state["control_waits"]))


class LineEndingsCase(unittest.TestCase):
    def test_a_control_reporting_cr_for_lf_still_verifies(self):
        sent = "Crimson leaves\nCool wind\nAutumn"
        self.assertEqual(computer._line_endings("Crimson leaves\rCool wind\rAutumn\r"),
                         computer._line_endings(sent))
        self.assertEqual(computer._line_endings("a\r\nb"), "a\nb")

    def test_different_words_still_fail(self):
        self.assertNotEqual(computer._line_endings("Crimson leaves\rCool wind"),
                            computer._line_endings("Crimson leaves\nCool winds"))

    def test_set_text_verifies_through_notepads_line_breaks(self):
        class Wrapper:
            text = None
            def set_edit_text(self, text): self.text = text.replace("\n", "\r")
            def window_text(self): return self.text + "\r"
        state = {"control_waits": [], "controls_present": {"Edit"}, "wrapper": Wrapper(),
                 "waits": [], "top_titles": ["Untitled - Notepad"], "tops": []}

        class Spec(FakeSpec):
            def child_window(self, **selector):
                return FakeCtrlSpec(self.state, selector)

        module = types.SimpleNamespace(
            Application=lambda backend: None,
            Desktop=lambda backend: types.SimpleNamespace(
                window=lambda **s: Spec(state, s), windows=lambda: []))
        timings = types.SimpleNamespace(TimeoutError=FakeUIATimeout)
        with mock.patch.object(computer, "available", return_value=(True, "ready")), \
                mock.patch.dict(sys.modules, {"pywinauto": module, "pywinauto.timings": timings}), \
                mock.patch.object(computer, "WAIT_POLL_S", 0.01):
            backend = computer.WindowsUIABackend()
            result = backend.perform({"action": "set_text", "window": {"title_re": "Notepad"},
                                      "control": {"control_type": "Edit"},
                                      "text": "Crimson leaves\nCool wind\nAutumn", "timeout_s": 1})
        self.assertTrue(result["verified"])


class FakeAmbiguous(Exception):
    pass


class FakeMatch:
    def __init__(self, title, handle, pid, active):
        self._t, self.handle, self._pid, self._active = title, handle, pid, active

    def window_text(self):
        return self._t

    def is_active(self):
        return self._active

    def process_id(self):
        return self._pid


class TwoWindowsCase(unittest.TestCase):
    """Two Notepads: the one that just opened is the one he means."""

    def backend(self, matches):
        state = {"waits": [], "matches": matches}

        class Spec:
            def __init__(self, selector):
                self.selector = selector
                self.handle = selector.get("handle")

            def wait(self, condition, timeout):
                state["waits"].append(dict(self.selector))
                if "handle" in self.selector:
                    return self
                raise FakeAmbiguous("two match")

        desktop = types.SimpleNamespace(window=lambda **s: Spec(s),
                                        windows=lambda **s: list(state["matches"]))
        module = types.SimpleNamespace(Application=lambda backend: None,
                                       Desktop=lambda backend: desktop)
        finder = types.SimpleNamespace(ElementAmbiguousError=FakeAmbiguous)
        timings = types.SimpleNamespace(TimeoutError=FakeUIATimeout)
        for patch in (mock.patch.object(computer, "available", return_value=(True, "ready")),
                      mock.patch.dict(sys.modules, {"pywinauto": module,
                                                    "pywinauto.timings": timings,
                                                    "pywinauto.findwindows": finder}),
                      mock.patch.object(computer, "WAIT_POLL_S", 0.01)):
            patch.start(); self.addCleanup(patch.stop)
        return computer.WindowsUIABackend(), state

    def test_the_active_window_wins(self):
        backend, state = self.backend([FakeMatch("*haiku - Notepad", 11, 3020, False),
                                       FakeMatch("Untitled - Notepad", 22, 3020, True)])
        backend.perform({"action": "wait_window", "window": {"title_re": "Notepad"},
                         "timeout_s": 1})
        self.assertEqual(state["waits"][-1], {"handle": 22})

    def test_then_a_window_of_a_process_this_run_started(self):
        backend, state = self.backend([FakeMatch("A - Notepad", 11, 100, False),
                                       FakeMatch("B - Notepad", 22, 200, False)])
        backend._opened.add(200)
        backend.perform({"action": "wait_window", "window": {"title_re": "Notepad"},
                         "timeout_s": 1})
        self.assertEqual(state["waits"][-1], {"handle": 22})

    def test_otherwise_the_ambiguity_is_refused_not_guessed(self):
        backend, state = self.backend([FakeMatch("A - Notepad", 11, 100, False),
                                       FakeMatch("B - Notepad", 22, 100, False)])
        with self.assertRaises(FakeAmbiguous):
            backend.perform({"action": "wait_window", "window": {"title_re": "Notepad"},
                             "timeout_s": 1})
        self.assertFalse(any("handle" in w for w in state["waits"]))

    def test_two_active_windows_is_still_ambiguous(self):
        backend, state = self.backend([FakeMatch("A - Notepad", 11, 100, True),
                                       FakeMatch("B - Notepad", 22, 100, True)])
        with self.assertRaises(FakeAmbiguous):
            backend.perform({"action": "wait_window", "window": {"title_re": "Notepad"},
                             "timeout_s": 1})


class SelectorMatchCase(unittest.TestCase):
    def test_each_field_is_checked(self):
        el = FakeElement("Save as", 1)
        self.assertTrue(computer._selector_matches(el, {"title": "Save as"}))
        self.assertFalse(computer._selector_matches(el, {"title": "Save As"}))
        self.assertTrue(computer._selector_matches(el, {"title_re": "(?i)save"}))
        self.assertFalse(computer._selector_matches(el, {"title_re": "Open"}))
        self.assertTrue(computer._selector_matches(el, {"class_name": "#32770"}))
        self.assertFalse(computer._selector_matches(el, {"class_name": "Notepad"}))
        self.assertTrue(computer._selector_matches(el, {"control_type": "Window"}))
        self.assertFalse(computer._selector_matches(el, {"auto_id": "x"}))


class FakeListItem:
    def __init__(self, text):
        self._t = text

    def window_text(self):
        return self._t


class FakeCombo:
    def __init__(self, items, readable=True):
        self.items, self.readable = items, readable
        self.selected, self.expanded, self.collapsed = None, 0, 0

    def expand(self):
        self.expanded += 1

    def collapse(self):
        self.collapsed += 1

    def descendants(self, control_type=None):
        if not self.readable:
            raise RuntimeError("no pattern")
        return [FakeListItem(i) for i in self.items]

    def select(self, item):
        if item not in self.items:
            raise IndexError(f"item {item!r} not found")
        self.selected = item

    def selected_text(self):
        return self.selected or ""


class ChoiceOnControlCase(unittest.TestCase):
    """`select` asks for what a person would say; the control is read for
    what it really holds."""

    def choose(self, items, wanted, readable=True):
        combo = FakeCombo(items, readable)
        return computer.WindowsUIABackend._choice_on(combo, wanted), combo

    def test_trailing_space_and_case_do_not_matter(self):
        choice, combo = self.choose(["Text documents (*.txt)", "All files "], "all FILES")
        self.assertEqual(choice, "All files ")
        self.assertEqual((combo.expanded, combo.collapsed), (1, 1))

    def test_a_unique_prefix_resolves(self):
        choice, _ = self.choose(["Text documents (*.txt)", "All files (*.*)"], "All files")
        self.assertEqual(choice, "All files (*.*)")

    def test_an_ambiguous_prefix_is_refused_not_guessed(self):
        with self.assertRaises(computer.VerificationFailed) as caught:
            self.choose(["All files (*.*)", "All filesystems"], "All files")
        self.assertIn("ambiguous", str(caught.exception))

    def test_a_prefix_that_reaches_a_committing_word_is_refused(self):
        with self.assertRaises(computer.VerificationFailed) as caught:
            self.choose(["Order later", "Send now"], "Sen")
        self.assertIn("send", str(caught.exception).lower())
        self.assertIn("refused", str(caught.exception))

    def test_an_unreadable_control_gets_the_plan_value_verbatim(self):
        choice, _ = self.choose([], "All files", readable=False)
        self.assertEqual(choice, "All files")

    def test_no_match_at_all_lets_the_control_answer(self):
        choice, _ = self.choose(["Text documents (*.txt)"], "PDF")
        self.assertEqual(choice, "PDF")


class ScreenshotNeedsPillowCase(unittest.TestCase):
    def test_a_missing_pillow_is_named_not_a_none_attribute_error(self):
        class Spec:
            def wait(self, *a, **k): return self
            def capture_as_image(self): return None
        state = {}
        module = types.SimpleNamespace(
            Application=lambda backend: None,
            Desktop=lambda backend: types.SimpleNamespace(window=lambda **s: Spec()))
        timings = types.SimpleNamespace(TimeoutError=FakeUIATimeout)
        with mock.patch.object(computer, "available", return_value=(True, "ready")), \
                mock.patch.dict(sys.modules, {"pywinauto": module,
                                              "pywinauto.timings": timings}), \
                mock.patch.object(computer, "CAPTURE_DIR", computer.CAPTURE_DIR / "_t"):
            backend = computer.WindowsUIABackend()
            with self.assertRaises(RuntimeError) as caught:
                backend.perform({"action": "screenshot_window",
                                 "window": {"title": "x"}, "filename": "never.png"})
        self.assertIn("Pillow", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
