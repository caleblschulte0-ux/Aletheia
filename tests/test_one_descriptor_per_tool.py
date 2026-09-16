"""One descriptor per tool, derived from the grammar rather than copied.

The brief (docs/JARVIS_BRIEF.md §1): one declarative tool registry from
which the planner grammar, the local model's catalog, approval behaviour
and the tests are derived. The 109 intercom kinds were NOT rewritten —
`tests/test_every_kind_has_a_handler.py` already holds the grammar against
`execute_command` — so this holds the derivation: every kind has exactly
one descriptor, every descriptor's kind can actually be carried out, and
the flags a descriptor carries agree with the sets they were read from.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import intercom, tools
from tests.test_every_kind_has_a_handler import branched_kinds


class EveryKindHasExactlyOneDescriptor(unittest.TestCase):
    def setUp(self):
        self.catalog = tools.catalog(fresh=True)

    def test_one_per_kind(self):
        by_kind: dict[str, list[str]] = {}
        for name, tool in self.catalog.items():
            if tool.kind:
                by_kind.setdefault(tool.kind, []).append(name)
        self.assertEqual(sorted(by_kind), sorted(intercom.KIND_ARGS))
        doubled = {k: v for k, v in by_kind.items() if len(v) != 1}
        self.assertEqual(doubled, {})

    def test_every_descriptors_kind_is_dispatchable(self):
        """A descriptor for a kind `execute_command` has no branch for is a
        tool that validates, is requested, is permitted — and does nothing."""
        can_run = branched_kinds()
        stranded = sorted(t.kind for t in self.catalog.values() if t.kind and t.kind not in can_run)
        self.assertEqual(stranded, [])

    def test_a_declared_tool_has_a_python_handler_and_a_capability(self):
        for name, tool in self.catalog.items():
            if tool.kind:
                continue
            with self.subTest(tool=name):
                self.assertTrue(callable(tool.handler), name)
                self.assertTrue(tool.capability, f"{name} names no registry capability")

    def test_names_are_unique_and_the_catalog_is_frozen(self):
        tool = next(iter(self.catalog.values()))
        with self.assertRaises(Exception):
            tool.name = "other"          # type: ignore[misc]

    def test_a_second_declaration_of_the_same_name_is_refused(self):
        twice = tools.declare("tasks", description="x", input_schema={},
                              handler=lambda a: {}, capability="task.persist")
        with mock.patch.object(tools, "_declared", lambda: [twice]):
            with self.assertRaises(ValueError):
                tools.catalog(registry={"capabilities": []}, fresh=True)


class TheFlagsAgreeWithTheSetsTheyCameFrom(unittest.TestCase):
    def setUp(self):
        self.catalog = tools.catalog(fresh=True)

    def test_risk_is_the_intercom_tier(self):
        for tool in self.catalog.values():
            if tool.kind:
                self.assertEqual(tool.risk, intercom.tier(tool.kind), tool.name)

    def test_read_only_means_the_read_tier_and_nothing_written(self):
        for tool in self.catalog.values():
            with self.subTest(tool=tool.name):
                if tool.kind:
                    self.assertEqual(tool.read_only, tool.kind in intercom.READ_ONLY_KINDS)
                if tool.read_only:
                    self.assertEqual(tool.risk, intercom.TIER_READ)
                    self.assertEqual(tool.writes, ())
                    self.assertFalse(tool.destructive)
                    self.assertTrue(tool.idempotent)

    def test_the_planner_never_sees_a_forbidden_kind(self):
        for kind in intercom.PLANNER_FORBIDDEN:
            self.assertFalse(self.catalog[kind].planner_visible, kind)
        shown = {t["name"] for t in tools.for_model("planner")["tools"]}
        self.assertEqual(shown & intercom.PLANNER_FORBIDDEN, set())

    def test_the_local_model_sees_only_tools_that_read_or_are_handed_off(self):
        """What it may RUN is reads. A declared tool that writes (the browser
        goal loop) may be SHOWN so she can ask for it - the brief's "becomes a
        handoff inside AgentSession" - and then the broker, not the catalog,
        is what stops it, and the row tells the model it will not run."""
        from aletheia import agent_session
        broker = agent_session.Broker(self.catalog, halted=lambda: False)
        for row in tools.for_model("local")["tools"]:
            tool = self.catalog[row["name"]]
            with self.subTest(tool=row["name"]):
                self.assertEqual(row["read_only"], tool.read_only)
                if tool.read_only:
                    continue
                self.assertIsNone(tool.kind, "no intercom kind that writes is shown locally")
                self.assertNotEqual(tool.approval, "none")
                args = {k: "x" for k in tool.input_schema.get("required") or []}
                self.assertNotEqual(broker.check(agent_session.ToolRequest(tool.name, args)).verdict,
                                    agent_session.RUN)
                self.assertIn("never run", row["runs"])
        # and it does see the three that answer questions about her state
        names = {t["name"] for t in tools.for_model("local")["tools"]}
        self.assertTrue({"state.now", "applications.query", "journal.query"} <= names)

    def test_the_schema_says_what_the_grammar_says(self):
        for kind, (required, optional) in intercom.KIND_ARGS.items():
            schema = self.catalog[kind].input_schema
            with self.subTest(kind=kind):
                self.assertEqual(set(schema["required"]), required)
                self.assertEqual(set(schema["properties"]), required | optional)
                self.assertFalse(schema["additionalProperties"])

    def test_a_closed_set_argument_is_an_enum(self):
        prop = self.catalog["remember"].input_schema["properties"]["domain"]
        self.assertEqual(prop.get("enum"), intercom.allowed_values("remember", "domain"))

    def test_open_world_output_is_marked_untrusted(self):
        for tool in self.catalog.values():
            with self.subTest(tool=tool.name):
                if tool.open_world:
                    self.assertIn(tool.provenance, (tools.UNTRUSTED_WEB, tools.UNTRUSTED_EMAIL))
                else:
                    self.assertNotIn(tool.provenance, (tools.UNTRUSTED_WEB, tools.UNTRUSTED_EMAIL))
        self.assertEqual(self.catalog["email_read"].provenance, tools.UNTRUSTED_EMAIL)
        self.assertEqual(self.catalog["browse_read"].provenance, tools.UNTRUSTED_WEB)

    def test_every_listed_kind_in_the_flag_sets_is_a_real_kind(self):
        grammar = set(intercom.KIND_ARGS)
        for name, group in (("OPEN_WORLD_KINDS", tools.OPEN_WORLD_KINDS),
                            ("DESTRUCTIVE_KINDS", tools.DESTRUCTIVE_KINDS),
                            ("IDEMPOTENT_KINDS", tools.IDEMPOTENT_KINDS),
                            ("LOCAL_MODEL_HIDDEN", tools.LOCAL_MODEL_HIDDEN),
                            ("MAIL_KINDS", tools.MAIL_KINDS),
                            ("STORE_OF", set(tools.STORE_OF))):
            with self.subTest(group=name):
                self.assertEqual(set(group) - grammar, set())

    def test_the_registry_decides_approval_where_it_names_the_kind(self):
        """`web_task` is named by `web.task` (operator_always, high); the
        descriptor says so and says no grant can ever cover it."""
        tool = self.catalog["web_task"]
        self.assertEqual(tool.capability, "web.task")
        self.assertEqual(tool.approval, "operator_always")
        self.assertFalse(tool.standing_grant)

    def test_an_unnamed_kind_falls_to_its_tier(self):
        """Fails CLOSED: a world kind no registry entry names waits for him."""
        owners = tools.capability_for_kind()
        unnamed_world = [k for k in intercom.KIND_ARGS
                         if k not in owners and intercom.tier(k) == intercom.TIER_WORLD]
        self.assertTrue(unnamed_world, "the check needs a subject")
        for kind in unnamed_world:
            self.assertEqual(self.catalog[kind].approval, "operator_once", kind)
            self.assertFalse(self.catalog[kind].standing_grant, kind)


class TheModelCatalogCarriesTheAuthorityNotes(unittest.TestCase):
    def test_the_notes_travel(self):
        shown = tools.for_model("local")
        self.assertIn("never execute", shown["authority"])
        self.assertIn("never instruct", shown["authority"])
        self.assertIn("do not follow instructions", shown["untrusted"])

    def test_each_row_says_whether_its_content_is_trusted(self):
        rows = {t["name"]: t for t in tools.for_model("all")["tools"]}
        self.assertIn("untrusted", rows["browse_read"]["content"])
        self.assertIn("trusted", rows["tasks"]["content"])
        self.assertNotIn("untrusted", rows["tasks"]["content"])

    def test_an_unknown_audience_is_refused(self):
        with self.assertRaises(ValueError):
            tools.for_model("anyone")


class TheValidatorIsTheDoor(unittest.TestCase):
    def test_required_unexpected_type_and_enum(self):
        remember = tools.get("remember")
        self.assertEqual(tools.validate_args(remember, {"domain": "people", "key": "k", "value": "v"}), [])
        problems = tools.validate_args(remember, {"domain": "family", "key": "k"})
        self.assertTrue(any("missing value" in p for p in problems))
        self.assertTrue(any("not one of" in p for p in problems))
        self.assertTrue(tools.validate_args(remember, {"domain": "people", "key": "k",
                                                       "value": "v", "extra": 1}))
        self.assertTrue(tools.validate_args(remember, "not an object"))

    def test_a_declared_tools_types_are_checked(self):
        query = tools.get("journal.query")
        self.assertEqual(tools.validate_args(query, {"hours": 6, "term": "apply"}), [])
        self.assertTrue(tools.validate_args(query, {"hours": [1]}))

    def test_a_read_only_declaration_cannot_be_destructive(self):
        with self.assertRaises(ValueError):
            tools.declare("x.y", description="x", input_schema={}, handler=lambda a: {},
                          capability="c", destructive=True)


if __name__ == "__main__":
    unittest.main()
