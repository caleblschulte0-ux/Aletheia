"""A standing workstation grant changes session availability, never action safety."""
import unittest

from aletheia import work_direct


class WorkTrustBoundaryCase(unittest.TestCase):
    def test_standing_layer_does_not_make_destructive_click_public_safe(self):
        quote = "Delete my account"
        text = work_direct.encode(
            quote=quote,
            summary="Delete account",
            actions=[{
                "type": "browser",
                "url": "https://example.com/account",
                "steps": [{"action": "click", "selector": "button.delete-account"}],
            }],
        )
        with self.assertRaises(work_direct.DirectWorkRefused):
            work_direct.parse(text, quote=quote)

    def test_standing_layer_does_not_make_private_typing_public_safe(self):
        quote = "Type my private note"
        text = work_direct.encode(
            quote=quote,
            summary="Type note",
            actions=[{
                "type": "computer",
                "steps": [{
                    "action": "set_text",
                    "window": {"title": "Notes"},
                    "control": {"control_type": "Document"},
                    "text": "private",
                }],
            }],
        )
        with self.assertRaises(work_direct.DirectWorkRefused):
            work_direct.parse(text, quote=quote)


if __name__ == "__main__":
    unittest.main()
