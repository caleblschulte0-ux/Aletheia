"""Private browser observation never follows a redirect into another host's data."""
import unittest
from unittest import mock

from aletheia import sealed_observe


class RedirectPage:
    def __init__(self, reached):
        self.url = reached
        self.private_reads = 0

    def goto(self, url, wait_until=None):
        return None

    def title(self):
        self.private_reads += 1
        return "Private destination"

    def inner_text(self, selector):
        self.private_reads += 1
        return "should never be read"

    def eval_on_selector_all(self, selector, script):
        self.private_reads += 1
        return []

    def close(self):
        pass


class Context:
    def __init__(self, page):
        self.page = page

    def new_page(self):
        return self.page


class Session:
    def __init__(self, page):
        self.page = page

    def __enter__(self):
        return Context(self.page)

    def __exit__(self, *exc):
        return False


class RedirectBoundaryCase(unittest.TestCase):
    def test_cross_host_redirect_is_refused_before_page_content_is_read(self):
        page = RedirectPage("https://other.example/private?token=secret")
        with mock.patch.object(
            sealed_observe.browse, "available", return_value=(True, "ready")
        ), mock.patch.object(
            sealed_observe.browse, "_Session", return_value=Session(page)
        ), mock.patch.object(sealed_observe.journal, "append"):
            with self.assertRaises(PermissionError):
                sealed_observe.observe_browser("https://start.example/project")
        self.assertEqual(page.private_reads, 0)

    def test_same_host_https_upgrade_can_be_observed(self):
        page = RedirectPage("https://start.example/project")
        with mock.patch.object(
            sealed_observe.browse, "available", return_value=(True, "ready")
        ), mock.patch.object(
            sealed_observe.browse, "_Session", return_value=Session(page)
        ), mock.patch.object(sealed_observe.journal, "append"):
            result = sealed_observe.observe_browser("http://start.example/project")
        self.assertEqual(result["url"], "https://start.example/project")
        self.assertGreater(page.private_reads, 0)


if __name__ == "__main__":
    unittest.main()
