"""His machine, asked about the way he asks.

    > what's using all my memory    -> "I can't think just now"
    > is my internet working        -> a paragraph about offline models
    > how long have you been running -> "I can't think just now"

The OS lists its programs for free, "my internet" is the internet, and a
model asked about her own clock knows less than she does.
"""
import unittest
from unittest import mock

from aletheia import machine, quick

TASKLIST = '''"chrome.exe","1","Console","1","812,000 K"
"chrome.exe","2","Console","1","400,000 K"
"Code.exe","3","Console","1","600,000 K"
"System","4","Services","0","2,000 K"
"python.exe","5","Console","1","90,000 K"
'''


class WhatHoldsTheMemory(unittest.TestCase):
    def test_programs_are_summed_by_name_and_the_os_is_left_out(self):
        with mock.patch.object(machine.sys, "platform", "win32"):
            users = machine.memory_users(3, run=lambda cmd: TASKLIST)
        self.assertEqual([name for name, _ in users], ["chrome", "Code", "python"])
        self.assertEqual(users[0][1], 1_212_000 * 1024)

    def test_the_sentence_names_them_and_says_whether_memory_is_the_problem(self):
        users = [("chrome", 3 * 1024 ** 3), ("Code", 1024 ** 3)]
        with mock.patch.object(machine, "memory_users", return_value=users), \
             mock.patch.object(machine, "memory", return_value={"total": 16 * 1024 ** 3,
                                                                 "available": 1024 ** 3}):
            said = quick.answer("what's using all my memory")
        self.assertIn("chrome", said)
        self.assertIn("tight", said)
        self.assertIn("I don't close programs", said)
        with mock.patch.object(machine, "memory_users", return_value=users), \
             mock.patch.object(machine, "memory", return_value={"total": 16 * 1024 ** 3,
                                                                 "available": 10 * 1024 ** 3}):
            self.assertIn("isn't what's slowing it down", quick.answer("what's eating my ram"))

    def test_nothing_readable_says_so(self):
        with mock.patch.object(machine, "memory_users", return_value=[]):
            self.assertIn("can't see", quick.answer("what programs are using the most memory"))


class TheOtherReadings(unittest.TestCase):
    def test_my_internet_is_the_internet(self):
        for said in ("is my internet working", "is my wifi down"):
            self.assertEqual(quick.match(said)[0], "internet", said)

    def test_her_own_clock_is_hers_to_answer(self):
        with mock.patch("aletheia.liveness.uptime_seconds", return_value=None):
            self.assertIn("can't say", quick.answer("how long have you been running"))


if __name__ == "__main__":
    unittest.main()
