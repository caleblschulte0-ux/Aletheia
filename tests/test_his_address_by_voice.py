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
