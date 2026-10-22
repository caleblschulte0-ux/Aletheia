""""What errands do I have" read his task list, and "add get gas to my
errands" went to the planner (2026-10-22). "Errand list" and "errands
list" were two lists.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import intercom, lists, stateio, voice


class ErrandsAreAList(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(lists, "private_dir",
                                    lambda name: Path(self.tmp.name, name).mkdir(parents=True, exist_ok=True)
                                    or Path(self.tmp.name, name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_adding_to_my_errands_is_the_errands_list(self):
        got = voice.interpret("add get gas to my errands")["command"]
        self.assertEqual((got["kind"], got["list"], got["item"]), ("list_add", "errands", "get gas"))

    def test_asking_about_errands_reads_the_errands_list(self):
        for said in ("what errands do I have", "do I have any errands", "what are my errands",
                     "what errands are left"):
            got = voice.interpret(said)["command"]
            self.assertEqual((got["kind"], got["list"]), ("list_read", "errands"), said)

    def test_errand_and_errands_are_one_list(self):
        lists.add("errands", ["get gas"])
        lists.add("errand", ["pick up dry cleaning"])
        self.assertEqual(lists.items("errands"), ["get gas", "pick up dry cleaning"])

    def test_an_errands_list_takes_an(self):
        said = intercom.execute_command({"kind": "list_read", "list": "errands"}, {})
        self.assertIn("an errands list", str(said))


if __name__ == "__main__":
    unittest.main()
