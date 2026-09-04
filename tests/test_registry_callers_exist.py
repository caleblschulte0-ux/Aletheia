"""A capability's caller has to be REACHABLE, not just written down.

`test_contracts` already checks that every capability names a caller and
that a NOT_BUILT one names a ticket. Nothing checked that the thing it
names EXISTS — and that is how `subscription.cancel` sat in the registry
for weeks pointing at a path whose only entry point was hand-typing a
JSON list of browser selectors at a command line, and how `secret.fill`
described `python -m aletheia.secret_browser` as "the front door" while
that command ran and did nothing at all, silently, exit 0.

A documented command that is a no-op is worse than a missing one: it
reads as a capability somebody already built. This is §104 and §106 with
teeth — never hallucinate a capability, never fake one.
"""
import importlib
import re
import unittest
from pathlib import Path

from aletheia import capabilities, intercom

# `aletheia.foo` in a caller string. Deliberately not matching a file
# name — "start-aletheia.bat" is a batch script, not a module.
MODULE = re.compile(r"(?<![\w.-])aletheia\.([a-z_][a-z0-9_]*)")
CLI = re.compile(r"python -m aletheia\.([a-z_][a-z0-9_]*)")
# "intercom kind 'x'" — and ONLY that. `agenda.execute` truthfully says
# "aletheia.mission kind 'anything'", which is a MISSION kind: a caller
# naming a different registry's vocabulary is not a lie, and a check that
# calls it one gets switched off within the week.
KINDS = re.compile(
    r"intercom\s+kinds?\s+((?:'[a-z_]+'(?:\s*(?:,|and|or)\s*)?)+)")
MISSION_KINDS = re.compile(
    r"mission\s+kinds?\s+((?:'[a-z_]+'(?:\s*(?:,|and|or)\s*)?)+)")

# Prose that happens to fit the shape. Each one is a deliberate exception
# with a reason, not a silencer: the list is short on purpose.
NOT_A_MODULE = {
    "bat",   # "start-aletheia.bat", a Windows batch script
}


def callers():
    registry = capabilities.load_registry()
    for entry in registry["capabilities"]:
        if entry["status"] == "NOT_BUILT":
            continue          # a ticket, checked by test_contracts
        yield entry["id"], entry.get("caller", "")


class EveryNamedModuleExists(unittest.TestCase):
    def test_it_imports(self):
        for cap, caller in callers():
            for name in sorted(set(MODULE.findall(caller)) - NOT_A_MODULE):
                with self.subTest(capability=cap, module=name):
                    try:
                        importlib.import_module(f"aletheia.{name}")
                    except Exception as exc:      # noqa: BLE001
                        self.fail(f"{cap} names aletheia.{name}: {exc}")


class EveryNamedCommandRUNS(unittest.TestCase):
    def test_python_dash_m_actually_does_something(self):
        """`python -m aletheia.secret_browser` exited 0 having done
        nothing, while the registry called it the front door."""
        for cap, caller in callers():
            for name in sorted(set(CLI.findall(caller))):
                with self.subTest(capability=cap, command=name):
                    module = importlib.import_module(f"aletheia.{name}")
                    self.assertTrue(
                        callable(getattr(module, "main", None)),
                        f"{cap} says `python -m aletheia.{name}`, which has "
                        "no main() — the command does nothing")


class EveryNamedIntercomKindExists(unittest.TestCase):
    def test_he_can_actually_say_it(self):
        for cap, caller in callers():
            for blob in KINDS.findall(caller):
                for kind in re.findall(r"'([a-z_]+)'", blob):
                    with self.subTest(capability=cap, kind=kind):
                        self.assertIn(
                            kind, intercom.KIND_ARGS,
                            f"{cap} names intercom kind {kind!r}, which does "
                            "not exist — nothing he says can reach it")


class EveryNamedMissionKindExists(unittest.TestCase):
    def test_a_budgeted_goal_can_actually_be_that_kind(self):
        from aletheia import mission
        for cap, caller in callers():
            for blob in MISSION_KINDS.findall(caller):
                for kind in re.findall(r"'([a-z_]+)'", blob):
                    with self.subTest(capability=cap, kind=kind):
                        self.assertIn(kind, mission.KINDS,
                                      f"{cap} names mission kind {kind!r}")


class NoPROPOSAL_POINTS_AT_A_DEAD_END(unittest.TestCase):
    """Twice now a module has recorded a proposal naming a capability
    that nothing could actually run — `subscription.cancel` and
    `reservation.book`, both reachable only by hand-typing a JSON list of
    browser selectors at a command line. The record said WAITING forever,
    nothing carried it out, and nothing said what was stopping it.

    A proposal may only name a capability that either RUNS or is
    deliberately refused. Those are the two honest answers; "written down
    and unreachable" is not one of them."""

    # `purchase.execute` is refused on purpose — his standing rule is that
    # this system does not spend money, and a capability that exists to be
    # refused is honest. It is listed so that adding a new one is a
    # decision somebody makes, not a thing that happens.
    DELIBERATELY_REFUSED = {"purchase.execute"}

    def proposals(self):
        found = []
        for path in sorted(Path("aletheia").glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(
                    r'"required_capability":\s*"([a-z_.]+)"', text):
                found.append((path.name, match.group(1)))
        return found

    def test_there_are_proposals_to_check(self):
        self.assertTrue(self.proposals(), "the check must have something to do")

    def test_each_one_names_something_that_can_actually_HAPPEN(self):
        registry = {c["id"]: c for c in capabilities.load_registry()["capabilities"]}
        for module, capability in self.proposals():
            with self.subTest(module=module, capability=capability):
                self.assertIn(capability, registry,
                              f"{module} proposes {capability}, which is not "
                              "in the registry at all")
                if capability in self.DELIBERATELY_REFUSED:
                    continue
                entry = registry[capability]
                self.assertNotEqual(
                    entry["status"], "NOT_BUILT",
                    f"{module} proposes {capability}, which is NOT_BUILT — the "
                    "record will say WAITING forever")
                caller = entry.get("caller", "")
                self.assertTrue(
                    CLI.search(caller) or KINDS.search(caller)
                    or "runtime.tick" in caller,
                    f"{module} proposes {capability}, whose caller "
                    f"({caller[:80]!r}) is not a command, an intercom kind or "
                    "the beat — so nothing he says or does can reach it")


class TheCheckItselfHasTeeth(unittest.TestCase):
    """A test that cannot fail is a comment. These prove it can."""

    def test_it_would_catch_a_missing_module(self):
        self.assertEqual(MODULE.findall("aletheia.nope drives it"), ["nope"])
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("aletheia.nope")

    def test_it_would_catch_a_missing_kind(self):
        self.assertEqual(KINDS.findall("intercom kind 'not_a_kind' does it"),
                         ["'not_a_kind'"])
        self.assertNotIn("not_a_kind", intercom.KIND_ARGS)

    def test_it_does_not_call_ANOTHER_registrys_vocabulary_a_lie(self):
        """`agenda.execute` says "aletheia.mission kind 'anything'", and
        that is true — of missions. A check that flags a true statement
        gets switched off within the week."""
        caller = "python -m aletheia.agenda; aletheia.mission kind 'anything'"
        self.assertEqual(KINDS.findall(caller), [])
        self.assertEqual(MISSION_KINDS.findall(caller), ["'anything'"])

    def test_it_does_not_trip_over_a_batch_file(self):
        self.assertEqual(MODULE.findall("start-aletheia.bat runs it"), [])

    def test_it_reads_the_real_registry(self):
        found = dict(callers())
        self.assertIn("web.task", found)
        self.assertTrue(found["web.task"].strip())


if __name__ == "__main__":
    unittest.main()
