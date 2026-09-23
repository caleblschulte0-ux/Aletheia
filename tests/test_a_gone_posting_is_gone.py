"""Live 2026-09-23 two 404 pages ("Sorry, we couldn't find anything here",
"Sorry, but we can't find that page") were closed as "asks nothing about who
he is - a bot check or a contact page looks like this". A page with no boxes
at all is a posting that is gone, and the record says that."""
import unittest

from aletheia import apply_run
from tests.test_apply_run import ApplyCase


class AGonePostingCase(ApplyCase):
    def test_no_boxes_at_all_is_gone_not_a_bot_check(self):
        with self.assertRaises(apply_run.ApplyError) as held:
            self.staged(form=[])
        self.assertIn("taken down", str(held.exception))
        self.assertNotIn("bot check", str(held.exception))
        record = apply_run.load_run("apply-" + apply_run._tag("https://jobs.example.com/1"))
        self.assertEqual(record["state"], apply_run.CLOSED)
        self.assertEqual(record["closed_kind"], apply_run.GONE)

    def test_a_page_with_boxes_that_ask_nothing_about_him_is_still_not_a_form(self):
        form = [{"selector": "#reason", "label": "Reason for contacting us", "name": "", "id": "reason",
                 "tag": "input", "type": "text", "required": True, "value": ""}]
        with self.assertRaises(apply_run.ApplyError) as held:
            self.staged(form=form)
        self.assertIn("bot check", str(held.exception))
        record = apply_run.load_run("apply-" + apply_run._tag("https://jobs.example.com/1"))
        self.assertEqual(record["closed_kind"], apply_run.NOT_A_FORM)


if __name__ == "__main__":
    unittest.main()
