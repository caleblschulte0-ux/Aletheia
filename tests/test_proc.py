"""No Aletheia bookkeeping process may flash a console window.

The operator watched black `git.exe` windows pop up on his desktop every
60 seconds on 2026-08-27 and asked what had infected his computer. That
is a product defect in ambient software, so it gets a test.
"""
import ast
import pathlib
import subprocess
import sys
import unittest
from unittest import mock

from aletheia import proc
from aletheia.fleet import REPO_ROOT

# Modules whose subprocess calls are Aletheia talking to itself. Anything
# the operator is meant to SEE (the Core in a visible console, a browser,
# an app being driven) is deliberately absent.
BOOKKEEPING = ["sync.py", "supervisor.py", "voice_room.py", "pulse.py"]


class TestFlags(unittest.TestCase):
    def test_adds_no_window_flag(self):
        with mock.patch.object(proc.subprocess, "run") as run:
            proc.run(["git", "status"], capture_output=True)
        self.assertEqual(run.call_args.kwargs["creationflags"], proc.NO_WINDOW)

    def test_never_fights_an_explicit_detached_request(self):
        detached = getattr(subprocess, "DETACHED_PROCESS", 0)
        if not detached:  # posix: nothing to conflict with
            self.skipTest("Windows-only flag combination")
        self.assertEqual(proc.hidden_flags(detached), detached)

    def test_helper_executes_a_real_command_cross_platform(self):
        # `true` is a POSIX utility and does not exist on Windows. Use the
        # current Python executable so this test exercises proc.run on the
        # operator's real Windows machine as well as Linux CI.
        result = proc.run([sys.executable, "-c", "raise SystemExit(0)"], capture_output=True)
        self.assertEqual(result.returncode, 0)


class TestNoRawSubprocessInBookkeeping(unittest.TestCase):
    """Static check: these modules must call proc.run, not subprocess.run."""

    def test_bookkeeping_modules_use_the_windowless_helper(self):
        """A raw subprocess call is allowed ONLY with an explicit
        `# proc: visible-by-design` marker above it saying why the operator
        is meant to see that window. Silence is a defect."""
        offenders = []
        for name in BOOKKEEPING:
            path = REPO_ROOT / "aletheia" / name
            source = path.read_text(encoding="utf-8")
            lines = source.splitlines()
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                if (isinstance(f, ast.Attribute) and f.attr in ("run", "Popen")
                        and isinstance(f.value, ast.Name) and f.value.id == "subprocess"):
                    above = "\n".join(lines[max(0, node.lineno - 8):node.lineno])
                    if "proc: visible-by-design" not in above:
                        offenders.append(f"{name}:{node.lineno}")
        self.assertEqual(offenders, [],
                         "these spawn a console window on Windows — use "
                         "aletheia.proc.run: " + ", ".join(offenders))


if __name__ == "__main__":
    unittest.main()
