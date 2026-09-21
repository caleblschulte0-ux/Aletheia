"""One declarative source of truth, and the tests that prove the rest agree.

His continuity brief, Part III item 9: *"Consolidate the tool/capability model
toward one declarative source of truth, gradually, without destabilizing working
safety systems."*

GRADUALLY is the word that decides the shape of this file. The working gates -
`intercom.KIND_ARGS`, the tiers, the capability registry, the approval policies
- run his machine today and are each held by their own tests. Rewriting them
into declarations would have been a hundred and twenty-seven chances to disagree
with the code that executes them. So the descriptors are DERIVED from them, and
what is held here is that the derivation and the legacy table cannot drift:

    grammar          `tools.catalog()[k].input_schema` vs `intercom.KIND_ARGS`
    tiers            `.risk` vs `intercom.tier`
    approvals        `tools.approval_of` vs `policy.required_approval`
    capabilities     `.capability` names a real registry entry
    the spoken groups moved INTO tools.py; `quick` reads them (one table now)
    the session catalog is the descriptors, and nothing else offers tools

Where a table had to stay where it was, its test is here and it fails when the
two disagree. Where a table could move, it moved.
"""
from __future__ import annotations

import unittest

from aletheia import capabilities, intercom, policy, quick, tools


class TheGrammarAndTheDescriptorsCannotDrift(unittest.TestCase):
    def setUp(self):
        self.catalog = tools.catalog(fresh=True)

    def test_every_kind_has_one_descriptor_and_no_descriptor_invents_a_kind(self):
        kinds = {t.kind for t in self.catalog.values() if t.kind}
        self.assertEqual(kinds, set(intercom.KIND_ARGS))

    def test_the_schema_reproduces_the_grammar_exactly(self):
        """The descriptor is the only thing a model is shown, so a schema that
        drifts from the grammar is a request that validates and then fails."""
        for kind, (required, optional) in intercom.KIND_ARGS.items():
            schema = self.catalog[kind].input_schema
            with self.subTest(kind=kind):
                self.assertEqual(set(schema["required"]), required)
                self.assertEqual(set(schema["properties"]), required | optional)

    def test_the_risk_is_the_tier_and_the_visibility_is_the_forbidden_set(self):
        for kind in intercom.KIND_ARGS:
            with self.subTest(kind=kind):
                self.assertEqual(self.catalog[kind].risk, intercom.tier(kind))
                self.assertEqual(self.catalog[kind].planner_visible,
                                 kind not in intercom.PLANNER_FORBIDDEN)


class TheApprovalPolicyHasOneAnswer(unittest.TestCase):
    def setUp(self):
        self.catalog = tools.catalog(fresh=True)
        self.registry = capabilities.load_registry()

    def test_the_descriptor_agrees_with_the_registry_wherever_the_registry_names_it(self):
        owners = tools.capability_for_kind(self.registry)
        self.assertTrue(owners, "the check needs a subject")
        for kind, entry in owners.items():
            with self.subTest(kind=kind):
                self.assertEqual(self.catalog[kind].approval,
                                 policy.required_approval(entry["id"]))

    def test_every_capability_a_descriptor_names_is_a_real_registry_entry(self):
        ids = {c["id"] for c in self.registry.get("capabilities", [])}
        for name, tool in self.catalog.items():
            if tool.capability:
                with self.subTest(tool=name):
                    self.assertIn(tool.capability, ids, name)

    def test_approval_of_is_the_one_function_that_answers_it(self):
        """The broker used to compute this inline. Two callers, one answer."""
        for name, tool in self.catalog.items():
            with self.subTest(tool=name):
                self.assertEqual(tools.approval_of(tool), tool.approval)

    def test_a_high_risk_registry_entry_is_never_reversible_in_the_descriptor(self):
        """`operator_always` is his standing judgement that something is not
        hers. Nothing consequence-based may contradict it."""
        for name, tool in self.catalog.items():
            if tool.approval == "operator_always":
                with self.subTest(tool=name):
                    self.assertFalse(tools.runs_unattended(tool), name)


class TheSpokenGroupsAreOneTable(unittest.TestCase):
    """They lived in `quick.py`; they live beside the descriptors now, and
    `quick` reads them. This is the only table this wave actually MOVED, and
    the test is that both readers see the same one."""

    def test_quick_reads_the_table_that_lives_with_the_descriptors(self):
        self.assertIs(quick._HE_CAN_ASK_FOR, tools.SPOKEN_GROUPS_BY_NAME)
        self.assertIs(quick._NOT_A_THING_HE_ASKS_FOR, tools.INTERNAL_KINDS)

    def test_every_grouped_name_is_a_real_descriptor(self):
        catalog = tools.catalog()
        for label, kinds in tools.SPOKEN_GROUPS_BY_NAME.items():
            for kind in kinds:
                with self.subTest(group=label, kind=kind):
                    self.assertIn(kind, catalog, f"{label} names {kind}, which is not a tool")

    def test_nothing_he_can_say_goes_unmentioned(self):
        grouped = {k for kinds in tools.SPOKEN_GROUPS_BY_NAME.values() for k in kinds}
        self.assertEqual(set(intercom.KIND_ARGS) - grouped - tools.INTERNAL_KINDS, set())

    def test_group_of_finds_the_label(self):
        self.assertEqual(tools.group_of("task_new"), "your tasks and reminders")
        self.assertEqual(tools.group_of("state.now"), "")


class TheSessionCatalogIsTheDescriptors(unittest.TestCase):
    def test_a_session_offers_nothing_the_catalog_does_not_hold(self):
        catalog = tools.catalog()
        for audience in ("local", "planner", "all"):
            with self.subTest(audience=audience):
                shown = {row["name"] for row in tools.for_model(audience)["tools"]}
                self.assertEqual(shown - set(catalog), set())

    def test_every_row_carries_the_descriptor_s_own_answers(self):
        catalog = tools.catalog()
        for row in tools.for_model("all")["tools"]:
            tool = catalog[row["name"]]
            with self.subTest(tool=row["name"]):
                self.assertEqual(row["risk"], tool.risk)
                self.assertEqual(row["read_only"], tool.read_only)
                self.assertEqual(row["consequence"], tool.consequence)


class WhatStillHasTwoSources(unittest.TestCase):
    """Named honestly rather than quietly: these are still two tables, and
    these are the tests that fail when they disagree. Rule zero says name what
    is missing rather than pretend it is done."""

    def test_the_flag_sets_only_name_real_kinds(self):
        grammar = set(intercom.KIND_ARGS)
        for name, group in (("OPEN_WORLD_KINDS", tools.OPEN_WORLD_KINDS),
                            ("DESTRUCTIVE_KINDS", tools.DESTRUCTIVE_KINDS),
                            ("IDEMPOTENT_KINDS", tools.IDEMPOTENT_KINDS),
                            ("LOCAL_MODEL_HIDDEN", tools.LOCAL_MODEL_HIDDEN),
                            ("LOCAL_MODEL_WRITES", tools.LOCAL_MODEL_WRITES),
                            ("MAIL_KINDS", tools.MAIL_KINDS),
                            ("SWITCH_KINDS", tools.SWITCH_KINDS),
                            ("STORE_OF", set(tools.STORE_OF)),
                            ("CONSEQUENCE_OF", {k for k in tools.CONSEQUENCE_OF if "." not in k}),
                            ("OUTWARD_ALWAYS", {k for k in tools.OUTWARD_ALWAYS if "." not in k})):
            with self.subTest(group=name):
                self.assertEqual(set(group) - grammar, set(),
                                 f"{name} names something the grammar does not have")

    def test_the_store_table_agrees_with_the_writer_reader_list(self):
        """`tests/test_every_writer_has_a_reader.py` keeps the other half of
        this by hand, for its own stated reason. This is the half that can be
        checked mechanically: a kind that writes a store names one."""
        catalog = tools.catalog()
        for kind, store in tools.STORE_OF.items():
            with self.subTest(kind=kind):
                tool = catalog[kind]
                self.assertIn(store, set(tool.reads) | set(tool.writes))
                if not tool.read_only:
                    self.assertEqual(tool.writes, (store,))


if __name__ == "__main__":
    unittest.main()
