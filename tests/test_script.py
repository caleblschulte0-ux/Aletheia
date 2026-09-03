"""She writes the verb when there isn't one — inside a box that holds.

Forty-five named verbs will never be "any request". The move that makes
an agent general is writing a program for the job and running it, and it
is also the most dangerous thing in the repository. So almost everything
here tests what the box REFUSES, and the money line is enforced by the
one property that makes it structural: generated code cannot open a
socket, so it cannot reach a checkout page.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, policy, script, workspace


class ScriptCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "ws"
        self.root.mkdir()
        env = mock.patch.dict(os.environ, {"ALETHEIA_WORKSPACE": str(self.root)})
        env.start(); self.addCleanup(env.stop)
        for target, attr, value in (
                (journal, "JOURNAL_PATH", Path(self.tmp.name) / "j.jsonl"),
                (policy, "HALT_PATH", Path(self.tmp.name) / "halt.json")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)

    def thinks(self, program):
        def fake(system, text, **kwargs):
            value = {"program": program}
            validator = kwargs.get("validator")
            return validator(value) if validator else value
        return fake


class NothingReachesTheNetwork(ScriptCase):
    """The property that makes 'never spends money' hold for code nobody
    wrote by hand: a program that cannot open a socket cannot reach a
    checkout page."""

    def test_every_networking_module_is_refused(self):
        for module in ("socket", "urllib.request", "http.client", "requests",
                       "ftplib", "smtplib", "telnetlib", "asyncio", "ssl",
                       "webbrowser", "xmlrpc.client"):
            with self.subTest(module=module):
                with self.assertRaises(script.ScriptRefused):
                    script.check(f"import {module}\n")

    def test_from_imports_are_checked_too(self):
        with self.assertRaises(script.ScriptRefused):
            script.check("from urllib.request import urlopen\n")
        with self.assertRaises(script.ScriptRefused):
            script.check("from socket import socket\n")

    def test_urllib_parse_is_allowed_but_urllib_request_is_not(self):
        script.check("import urllib.parse\n")            # parsing is not reaching
        with self.assertRaises(script.ScriptRefused):
            script.check("import urllib.request\n")

    def test_a_module_nobody_thought_of_is_refused_not_permitted(self):
        """A whitelist, so the unknown case fails closed."""
        with self.assertRaises(script.ScriptRefused):
            script.check("import some_module_invented_next_year\n")


class NothingStartsAProcess(ScriptCase):
    def test_subprocess_and_friends_are_refused(self):
        for module in ("subprocess", "ctypes", "importlib", "multiprocessing",
                       "pty", "signal"):
            with self.subTest(module=module):
                with self.assertRaises(script.ScriptRefused):
                    script.check(f"import {module}\n")

    def test_os_is_allowed_for_paths_but_not_for_spawning(self):
        script.check("import os\nprint(os.path.join('a', 'b'))\n")
        for call in ("os.system('rm -rf /')", "os.popen('ls')",
                     "os.execv('/bin/sh', [])", "os.fork()"):
            with self.subTest(call=call):
                with self.assertRaises(script.ScriptRefused):
                    script.check(f"import os\n{call}\n")


class TheCheckCannotBeWalkedAround(ScriptCase):
    def test_the_dynamic_escapes_are_refused(self):
        for source in ("eval('1+1')", "exec('x=1')", "__import__('socket')",
                       "compile('1', '<s>', 'eval')", "globals()['x']"):
            with self.subTest(source=source):
                with self.assertRaises(script.ScriptRefused):
                    script.check(source + "\n")

    def test_dunder_attribute_access_is_refused(self):
        for source in ("().__class__.__base__.__subclasses__()",
                       "print.__self__.__dict__",
                       "x = [].__class__"):
            with self.subTest(source=source):
                with self.assertRaises(script.ScriptRefused):
                    script.check(source + "\n")

    def test_a_program_that_does_not_parse_is_refused(self):
        with self.assertRaises(script.ScriptRefused):
            script.check("def broken(:\n")

    def test_an_empty_or_oversized_program_is_refused(self):
        with self.assertRaises(script.ScriptRefused):
            script.check("   ")
        with self.assertRaises(script.ScriptRefused):
            script.check("x = 1\n" * 20_000)

    def test_relative_imports_are_refused(self):
        with self.assertRaises(script.ScriptRefused):
            script.check("from . import something\n")


class ItActuallyRunsRealWork(ScriptCase):
    """The point of all the refusals: ordinary computation over his files
    still works."""

    def test_a_program_reads_and_writes_in_the_workspace(self):
        (self.root / "data.csv").write_text("a,1\nb,2\nc,3\n", encoding="utf-8")
        program = (
            "import csv\n"
            "rows = list(csv.reader(open('data.csv')))\n"
            "total = sum(int(r[1]) for r in rows)\n"
            "open('total.txt', 'w').write(str(total))\n"
            "print(f'summed {len(rows)} rows to {total}')\n"
        )
        result = script.execute(program, label="sum")
        self.assertIn("summed 3 rows to 6", result["output"])
        self.assertEqual((self.root / "total.txt").read_text(), "6")

    def test_the_program_is_saved_before_it_runs_so_he_can_read_it(self):
        result = script.execute("print('hello')\n", label="greet")
        saved = self.root / result["program"]
        self.assertTrue(saved.is_file())
        self.assertIn("hello", saved.read_text(encoding="utf-8"))

    def test_it_runs_with_the_workspace_as_its_working_directory(self):
        result = script.execute(
            "import os\nprint(os.path.basename(os.getcwd()))\n", label="where")
        self.assertIn("ws", result["output"])

    def test_a_full_request_writes_the_program_and_runs_it(self):
        result = script.run("count to three",
                            think=self.thinks("for i in (1,2,3): print(i)\n"))
        self.assertIn("1", result["output"])
        self.assertIn("3", result["output"])

    def test_a_markdown_fence_from_the_model_is_stripped(self):
        result = script.run("say hi",
                            think=self.thinks("```python\nprint('hi')\n```"))
        self.assertIn("hi", result["output"])


class FailureIsHonest(ScriptCase):
    def test_a_crashing_program_reports_the_real_error(self):
        with self.assertRaises(script.ScriptError) as caught:
            script.execute("raise ValueError('the data was empty')\n", label="boom")
        self.assertIn("the data was empty", str(caught.exception))

    def test_a_looping_program_is_stopped(self):
        with mock.patch.object(script, "TIMEOUT_S", 2):
            with self.assertRaises(script.ScriptError) as caught:
                script.execute("while True: pass\n", label="loop")
        self.assertIn("looping", str(caught.exception))

    def test_the_model_saying_it_cannot_is_surfaced_not_swallowed(self):
        with self.assertRaises(script.ScriptError) as caught:
            script.execute("print('CANNOT: that needs the internet')\n",
                           label="nope")
        self.assertIn("needs the internet", str(caught.exception))

    def test_a_silent_program_is_reported_as_uninformative(self):
        result = script.execute("x = 1\n", label="quiet")
        self.assertIn("printed nothing", script.spoken(result))


class ItInheritsNothingOfHis(ScriptCase):
    def test_his_secrets_are_not_in_the_child_environment(self):
        with mock.patch.dict(os.environ, {"FLEET_TOKEN": "super-secret",
                                          "GITHUB_TOKEN": "also-secret"}):
            result = script.execute(
                "import os\nprint(sorted(os.environ))\n", label="env")
        self.assertNotIn("FLEET_TOKEN", result["output"])
        self.assertNotIn("GITHUB_TOKEN", result["output"])
        self.assertNotIn("super-secret", result["output"])

    def test_the_environment_builder_keeps_nothing_sensitive(self):
        with mock.patch.dict(os.environ, {"ALETHEIA_MACHINE_KEY": "/k",
                                          "AWS_SECRET_ACCESS_KEY": "s"}):
            env = script._environment()
        self.assertNotIn("ALETHEIA_MACHINE_KEY", env)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)


class ItStopsWhenToldTo(ScriptCase):
    def test_halt_prevents_a_run(self):
        policy.halt("stop", via="test")
        with self.assertRaises(policy.Halted):
            script.execute("print('nope')\n", label="halted")

    def test_halt_prevents_even_writing_the_program(self):
        policy.halt("stop", via="test")
        with self.assertRaises(policy.Halted):
            script.run("do a thing", think=self.thinks("print('x')\n"))


if __name__ == "__main__":
    unittest.main()
