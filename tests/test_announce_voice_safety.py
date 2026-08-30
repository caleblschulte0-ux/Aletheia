"""Spoken room interruptions are opt-in even though notifications stay live."""
import unittest
from unittest import mock

from aletheia import announce


class AnnounceSafetyCase(unittest.TestCase):
    def test_default_config_never_speaks_first(self):
        self.assertFalse(announce.DEFAULT_CONFIG["enabled"])

    def test_default_disabled_config_does_not_even_read_notifications(self):
        with mock.patch.object(announce.policy, "halted", return_value=False), \
             mock.patch.object(announce.notifications, "all_notifications") as notices:
            self.assertEqual(announce.pending(config=dict(announce.DEFAULT_CONFIG)), [])
        notices.assert_not_called()


if __name__ == "__main__":
    unittest.main()
