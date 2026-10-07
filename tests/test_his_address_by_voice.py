""""Where do I live" says tell me; telling her has to work."""
import unittest

from aletheia import voice


class HisAddress(unittest.TestCase):
    def test_my_address_is_remembered(self):
        c = voice._interpret("my address is 123 Main St, Hartford, SD 57033")["command"]
        self.assertEqual((c["kind"], c["domain"], c["key"], c["value"]),
                         ("remember", "identity", "address", "123 Main St, Hartford, SD 57033"))

    def test_the_nearest_thing_is_not_a_file(self):
        c = voice._interpret("where is the nearest gas station").get("command") or {}
        self.assertNotEqual(c.get("kind"), "file_find")


if __name__ == "__main__":
    unittest.main()


class HisEmailAndPhone(unittest.TestCase):
    def test_saying_them_remembers_them(self):
        c = voice._interpret("my email is caleb@example.com")["command"]
        self.assertEqual((c["key"], c["value"]), ("email", "caleb@example.com"))
        c = voice._interpret("my phone number is 605 555 1234")["command"]
        self.assertEqual((c["key"], c["value"]), ("phone", "605 555 1234"))

    def test_asking_reads_her_memory(self):
        from unittest import mock
        from aletheia import quick
        held = {"identity": {"email": {"value": "caleb@example.com"}}}
        with mock.patch("aletheia.profile.answer", return_value=None), \
                mock.patch("aletheia.memory.everything", return_value=held):
            self.assertIn("caleb@example.com", quick.answer("what's my email"))
