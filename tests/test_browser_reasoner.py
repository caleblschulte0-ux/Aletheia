import unittest
from unittest import mock

from aletheia import browser_reasoner


class FakeKeyboard:
    def __init__(self, page):
        self.page = page

    def press(self, key):
        if key != "Enter":
            raise AssertionError(key)
        self.page.submitted = True


class FakeLocator:
    def __init__(self, page, kind):
        self.page = page
        self.kind = kind

    @property
    def first(self):
        return self

    @property
    def last(self):
        return self

    def count(self):
        if self.kind == "editor":
            return 1
        if self.kind == "assistant":
            return 1 if self.page.submitted else 0
        return 0

    def is_visible(self):
        return True

    def fill(self, text):
        self.page.prompt = text

    def press(self, key):
        if self.kind != "editor" or key != "Enter":
            raise AssertionError(key)
        self.page.submitted = True

    def inner_text(self):
        return '{"intent":"clarify","summary":"done","required_capabilities":[],"confidence":0.9}'


class FakePage:
    def __init__(self, url="https://chatgpt.com/"):
        self.url = url
        self.submitted = False
        self.prompt = ""
        self.keyboard = FakeKeyboard(self)
        self.goto_timeout = None

    def goto(self, url, *, wait_until, timeout):
        self.url = url
        self.goto_timeout = timeout

    def close(self):
        pass

    def locator(self, selector):
        if selector == browser_reasoner.EDITOR_SELECTORS[0]:
            return FakeLocator(self, "editor")
        if selector == browser_reasoner.ASSISTANT_SELECTORS[0]:
            return FakeLocator(self, "assistant")
        return FakeLocator(self, "none")

    def wait_for_timeout(self, ms):
        pass


class BrowserReasonerCase(unittest.TestCase):
    def test_extracts_fenced_or_embedded_json(self):
        self.assertEqual(
            browser_reasoner._first_json_object('```json\n{"intent":"plan"}\n```')["intent"],
            "plan",
        )
        self.assertEqual(
            browser_reasoner._first_json_object('answer: {"intent":"clarify"} done')["intent"],
            "clarify",
        )

    def test_cross_host_is_refused_before_prompt_submission(self):
        page = FakePage("https://auth.openai.com/login")
        with self.assertRaises(browser_reasoner.BrowserReasonerUnavailable):
            browser_reasoner._infer_page(page, "PRIVATE PROMPT", timeout_s=0.01)
        self.assertFalse(page.submitted)
        self.assertEqual(page.prompt, "")

    def test_submits_once_and_reads_only_a_new_assistant_message(self):
        page = FakePage()
        result = browser_reasoner._infer_page(page, "bounded prompt", timeout_s=0.1)
        self.assertTrue(page.submitted)
        self.assertEqual(page.prompt, "bounded prompt")
        self.assertEqual(result["summary"], "done")

    def test_prompt_is_bounded_and_context_must_serialize(self):
        with self.assertRaises(browser_reasoner.BrowserReasonerUnavailable):
            browser_reasoner._compose("x" * 31_000, "hello", {})
        with self.assertRaises(browser_reasoner.BrowserReasonerUnavailable):
            browser_reasoner._compose("contract", "hello", {"bad": object()})

    def test_local_browser_failure_never_echoes_prompt(self):
        secret = "private-operator-context-that-must-not-leak"
        with mock.patch.object(browser_reasoner.browse, "available", return_value=(True, "ready")), \
             mock.patch.object(browser_reasoner.browse, "_Session", side_effect=OSError(secret)):
            with self.assertRaises(browser_reasoner.BrowserReasonerUnavailable) as ctx:
                browser_reasoner.infer_json("contract", secret)
        self.assertNotIn(secret, str(ctx.exception))
        self.assertEqual(str(ctx.exception), "ChatGPT browser reasoning failed locally")

    def test_navigation_and_response_share_the_caller_timeout(self):
        page = FakePage()

        class Session:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def new_page(self):
                return page

        with mock.patch.object(browser_reasoner.browse, "available", return_value=(True, "ready")), \
             mock.patch.object(browser_reasoner, "_subscription_session", return_value=Session()), \
             mock.patch.object(browser_reasoner, "_infer_page", return_value={"ok": True}) as infer:
            result = browser_reasoner.infer_json("contract", "request", timeout_s=2.0)
        self.assertEqual(result, {"ok": True})
        self.assertLessEqual(page.goto_timeout, 2000)
        self.assertGreater(page.goto_timeout, 0)
        self.assertLessEqual(infer.call_args.kwargs["timeout_s"], 2.0)


if __name__ == "__main__":
    unittest.main()
