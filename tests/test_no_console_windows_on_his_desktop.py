"""Ambient software must be ambient.

`aletheia/proc.py` exists because of this exact bug, found by the operator
and not by a test, on 2026-08-27: the Core shelled out to `git` every sixty
seconds under a `pythonw.exe` parent with no console, so Windows gave every
short-lived child its OWN console window, and he watched black boxes pop up
on his desktop all day.

It happened again on 2026-09-13. `ears.py` — the voice-room watchdog, which
polls — called `subprocess.run(["powershell", ...])` directly, so every poll
flashed a PowerShell window and he could not use his computer. Same bug,
different module, eighteen days later, because the rule lived in a docstring
and nothing enforced it.

This test is the enforcement. A helper Aletheia spawns for its OWN
bookkeeping goes through `proc.run`, which adds CREATE_NO_WINDOW on Windows
and is a plain passthrough everywhere else.

What is deliberately ALLOWED: a process the operator is meant to see or
interact with inherits its parent's console on purpose — a browser he is
about to log in to, an app being driven, the Core under a visible console.
Those are listed by name below, with the reason, so an exemption is a
decision somebody made rather than a spawn nobody noticed.
"""
from __future__ import annotations

import ast
import os
import unittest

#: The tools Aletheia runs for its own bookkeeping. Every one of these
#: flashes a window on Windows when spawned from a console-less parent.
BOOKKEEPING = {
    "powershell", "powershell.exe", "pwsh", "pwsh.exe",
    "schtasks", "schtasks.exe", "git", "git.exe",
    "tasklist", "tasklist.exe", "taskkill", "taskkill.exe",
    "cmd", "cmd.exe", "wmic", "wmic.exe", "reg", "reg.exe",
}

#: Spawns he is MEANT to see. Each names why it is not bookkeeping.
ALLOWED = {
    # A browser window he logs into himself: it must be visible, and
    # proc.py says so in as many words.
    ("browse", "native_login"),
    # Opening Spotify for him. An app he is about to look at.
    ("music", "open_player"),
}


def _spawn_calls(path):
    """Every subprocess spawn in one module, with the function it is in."""
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    tree = ast.parse(source)

    # Module-level dicts that carry creationflags, so `**_NO_WINDOW` counts
    # as hidden. screenrec.py does exactly that and is correct; a checker
    # that only understood a literal keyword would have called it a bug and
    # sent somebody to "fix" working code.
    hiding_splats = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if isinstance(value, ast.IfExp):
            value = value.body
        if not isinstance(value, ast.Dict):
            continue
        keys = {k.value for k in value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        if keys & {"creationflags", "startupinfo"}:
            hiding_splats.update(t.id for t in node.targets
                                 if isinstance(t, ast.Name))

    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def enclosing(node):
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node.name
        return "<module>"

    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and getattr(node.func.value, "id", "") == "subprocess"
                and node.func.attr in ("run", "Popen", "call",
                                       "check_call", "check_output")):
            continue
        argv = []
        if node.args and isinstance(node.args[0], (ast.List, ast.Tuple)):
            argv = [e.value for e in node.args[0].elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        hidden = any(
            kw.arg in ("creationflags", "startupinfo")
            or (kw.arg is None and isinstance(kw.value, ast.Name)
                and kw.value.id in hiding_splats)
            for kw in node.keywords)
        out.append({"line": node.lineno, "func": enclosing(node),
                    "argv": argv, "hidden": hidden})
    return out


class NoHelperFlashesAWindow(unittest.TestCase):
    def _modules(self):
        for name in sorted(os.listdir("aletheia")):
            if name.endswith(".py"):
                yield name[:-3], os.path.join("aletheia", name)

    def test_every_bookkeeping_spawn_is_windowless(self):
        """The rule proc.py was written for, enforced instead of described."""
        offenders = []
        for module, path in self._modules():
            if module == "proc":
                continue        # proc.run IS the windowless one
            for call in _spawn_calls(path):
                if (module, call["func"]) in ALLOWED:
                    continue
                tool = os.path.basename(call["argv"][0]).casefold() if call["argv"] else ""
                if tool in BOOKKEEPING and not call["hidden"]:
                    offenders.append(
                        f"{module}.py:{call['line']} in {call['func']}() "
                        f"spawns {tool} with a console window — use proc.run")
        self.assertEqual(offenders, [], "\n" + "\n".join(offenders))

    def test_the_watchdog_that_caused_this_is_clean(self):
        """ears.py polls, so every one of its spawns fires repeatedly. This
        is the module that made his desktop unusable on 2026-09-13."""
        for call in _spawn_calls("aletheia/ears.py"):
            with self.subTest(line=call["line"]):
                self.assertTrue(
                    call["hidden"],
                    f"ears.py:{call['line']} in {call['func']}() spawns a "
                    "process that can open a window, and this module polls")

    def test_proc_still_hides_windows(self):
        """The whole test rests on proc.run actually setting the flag."""
        from aletheia import proc
        import subprocess
        want = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.assertEqual(proc.hidden_flags(), want)

    def test_an_explicit_console_request_is_left_alone(self):
        """CREATE_NO_WINDOW is mutually exclusive with DETACHED_PROCESS and
        CREATE_NEW_CONSOLE. A caller that asked for one keeps it, rather
        than getting flags that make the spawn fail outright."""
        from aletheia import proc
        import subprocess
        detached = getattr(subprocess, "DETACHED_PROCESS", 0)
        if detached:
            self.assertEqual(proc.hidden_flags(detached), detached)

    def test_the_allowlist_names_real_functions(self):
        """An exemption for a function that no longer exists is an
        exemption quietly covering something else."""
        for module, func in ALLOWED:
            path = os.path.join("aletheia", f"{module}.py")
            self.assertTrue(os.path.exists(path), path)
            names = {c["func"] for c in _spawn_calls(path)}
            self.assertIn(func, names,
                          f"{module}.{func} is exempted but spawns nothing")


if __name__ == "__main__":
    unittest.main()
