import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import contacts


class ContactCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(contacts, "CONTACTS_DIR", Path(self.tmp.name) / "contacts")
        patcher.start(); self.addCleanup(patcher.stop)


class TestContacts(ContactCase):
    def test_create_and_resolve_alias(self):
        contacts.create("bob-smith", "Bob Smith", emails=["bob@example.com"], aliases=["Bob"])
        self.assertEqual(contacts.resolve("bob")["id"], "bob-smith")
        self.assertEqual(contacts.primary_email(contacts.resolve("bob@example.com")), "bob@example.com")

    def test_unknown_is_never_guessed(self):
        contacts.create("bob", "Bob Smith")
        with self.assertRaises(KeyError):
            contacts.resolve("Robert")

    def test_ambiguous_alias_refused(self):
        contacts.create("bob-a", "Bob A", aliases=["Bob"])
        contacts.create("bob-b", "Bob B", aliases=["Bob"])
        with self.assertRaises(LookupError):
            contacts.resolve("Bob")

    def test_multiple_emails_require_explicit_choice(self):
        value = contacts.create("bob", "Bob", emails=["a@example.com", "b@example.com"])
        with self.assertRaises(LookupError):
            contacts.primary_email(value)

    def test_case_duplicate_email_refused(self):
        with self.assertRaises(ValueError):
            contacts.create("bob", "Bob", emails=["Bob@Example.com", "bob@example.com"])

    def test_update_revalidates(self):
        contacts.create("bob", "Bob")
        updated = contacts.update("bob", aliases=["Robert"])
        self.assertEqual(updated["aliases"], ["Robert"])
        with self.assertRaises(ValueError):
            contacts.update("bob", emails=["not-an-email"])


if __name__ == "__main__":
    unittest.main()
