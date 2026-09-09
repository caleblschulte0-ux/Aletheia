"""A category is not a notice, and the phone was showing the category.

On the mobile surface the unread list read:

    Reminder
    Reporting live computer state pulled from your machine just now

"Reminder" is the KIND. The thing he wants was underneath it in small
grey text. The wall already solved this - `presence` renders a line, and
`speech.notice_line` prefers the body when the title names a category -
but the page read `/api/notifications` raw and showed `title`.

`voice.approval_label` set the precedent when all three surfaces
disagreed about one approval: the API carries the label, because smarts
belong in the collector and never in the page.

And there were already TWO lists of generic titles, which had drifted:
`presence.GENERIC_TITLES` had "update" and "aletheia";
`speech._CATEGORY_TITLES` had "aletheia finished thinking" and neither of
those. So the wall and the room disagreed about which titles were worth
reading out.
"""
from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from unittest import mock

from aletheia import core, presence, speech


class OneListOfCategoryTitlesCase(unittest.TestCase):
    def test_presence_and_speech_share_it(self):
        """Two copies had already drifted apart."""
        self.assertIs(presence.GENERIC_TITLES, speech.CATEGORY_TITLES)

    def test_it_holds_what_both_copies_used_to_have(self):
        for title in ("reminder", "notification", "notice", "alert",
                      "update", "aletheia", "aletheia finished thinking"):
            with self.subTest(title=title):
                self.assertIn(title, speech.CATEGORY_TITLES)


class TheLineToShowCase(unittest.TestCase):
    def test_a_category_title_yields_to_the_body(self):
        self.assertEqual(
            speech.notice_line({"title": "Reminder",
                                "body": "Pick up the kids at four"}),
            "Pick up the kids at four")

    def test_a_real_title_is_kept(self):
        self.assertEqual(
            speech.notice_line({"title": "Shorts-pipeline failed",
                                "body": "daily.yml exited 1"}),
            "Shorts-pipeline failed")

    def test_the_titles_that_had_drifted_are_now_handled(self):
        for title in ("Update", "Aletheia"):
            with self.subTest(title=title):
                self.assertEqual(
                    speech.notice_line({"title": title, "body": "the real thing"}),
                    "the real thing")


class TheEndpointRendersItCase(unittest.TestCase):
    ROWS = [
        {"id": "n1", "title": "Reminder", "state": "UNREAD",
         "body": "Pick up the kids at four"},
        {"id": "n2", "title": "Shorts-pipeline failed", "state": "UNREAD",
         "body": "daily.yml exited 1"},
    ]

    def _fetch(self):
        with mock.patch("aletheia.notifications.all_notifications",
                        return_value=[dict(r) for r in self.ROWS]):
            server = core.make_server(port=0)
            port = server.server_address[1]
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/notifications") as r:
                    return json.loads(r.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()

    def test_every_row_carries_the_line_to_show(self):
        rows = self._fetch()
        self.assertEqual(rows[0]["says"], "Pick up the kids at four")
        self.assertEqual(rows[1]["says"], "Shorts-pipeline failed")

    def test_the_page_never_has_to_know_about_categories(self):
        """The point: no surface reimplements this."""
        with open(core.__file__.replace("core.py", "../interface/mobile.js"),
                  encoding="utf-8") as handle:
            page = handle.read()
        self.assertIn("n.says", page)
        # Not a grep for the word "Reminder": it appears in the comment
        # that explains this, and a test that cannot tell a comment from
        # logic is one that gets silenced. What matters is that the page
        # holds no LIST of category titles of its own.
        code = " ".join(line for line in page.splitlines()
                        if not line.strip().startswith("//"))
        for shape in ("CATEGORY", "categoryTitles", "GENERIC_TITLES",
                      "'reminder'", '"reminder"'):
            self.assertNotIn(shape, code,
                             "the page is deciding what a category title is")

    def test_a_broken_renderer_still_returns_the_notices(self):
        """A label is worth less than the list it labels."""
        with mock.patch.object(speech, "notice_line",
                               side_effect=RuntimeError("boom")):
            rows = self._fetch()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["says"], "Reminder")


if __name__ == "__main__":
    unittest.main()
