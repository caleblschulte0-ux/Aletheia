"""The planner's local rung: the compact prompt, and the gates it does not move.

Measured on his laptop 2026-09-18 with the real models (see
`aletheia.local_planner`): the 28.7 KB planner prompt timed out at 180 s and
again at 300 s, so the local rung had never once carried a request. A 2 KB
prompt came back in 33 s warm and 163 s cold, a 4 KB one in 113 s. These tests
hold the two halves of the fix: the prompt is small and the catalog never
travels whole, and every gate is exactly where it was.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import brain, intercom, local_planner, planner, tools

FLEET = {"repos": {}}
REGISTRY = {
    "version": 1,
    "providers": {"aletheia.local": {}},
    "capabilities": [
        {"id": "task.persist", "status": "AVAILABLE", "provider": "aletheia.local"},
        {"id": "purchase.execute", "status": "NOT_BUILT", "provider": "aletheia.local"},
    ],
}


class ShortlistCase(unittest.TestCase):
    """The right kinds surface, and the catalog never travels whole."""

    def test_a_website_ask_surfaces_the_browser_verb(self):
        # The scenario D sentence that died with the frontier off.
        kinds = local_planner.shortlist(
            "go to books.toscrape.com and tell me the title of the first book "
            "in the travel category")
        self.assertIn("web_task", kinds)

    def test_a_reminder_with_an_odd_time_surfaces_the_reminder_verbs(self):
        kinds = local_planner.shortlist("remind me at 7:40 tomorrow morning to move the car")
        self.assertIn("remind_at", kinds)

    def test_a_write_it_down_ask_surfaces_the_writing_verbs(self):
        kinds = local_planner.shortlist(
            "write up a one page summary of the readme and save it as notes/summary.md")
        self.assertTrue({"compose", "file_write"} & set(kinds), kinds)

    def test_a_research_ask_surfaces_research(self):
        kinds = local_planner.shortlist(
            "look up what time the hardware store on main street closes today")
        self.assertIn("research", kinds)

    def test_the_whole_catalog_never_travels(self):
        """The defect this module exists for: 117 kinds on every ask."""
        everything = len([t for t in tools.catalog().values() if t.kind])
        for sentence in ("remind me tomorrow to call the bank",
                         "go to example.com and read the front page",
                         "what is the capital of Iceland",
                         "asdfghjkl"):
            kinds = local_planner.shortlist(sentence)
            self.assertLessEqual(len(kinds), local_planner.SHORTLIST_MAX)
            self.assertLess(len(kinds), everything / 4)

    def test_a_sentence_matching_nothing_still_gets_a_usable_floor(self):
        kinds = local_planner.shortlist("asdfghjkl qwertyuiop")
        self.assertTrue(kinds, "an empty catalog forces the model to invent one")
        self.assertTrue(set(kinds) <= set(local_planner.FALLBACK_KINDS))

    def test_shortlisting_is_deterministic(self):
        ask = "remind me at 8 tomorrow to call the bank"
        self.assertEqual(local_planner.shortlist(ask), local_planner.shortlist(ask))

    def test_every_hinted_kind_is_real_and_the_planner_may_emit_it(self):
        """The hand-kept verb table cannot drift into naming something that
        does not exist, or something the planner is forbidden to compile."""
        for pattern, kinds in local_planner.VERB_HINTS.items():
            for kind in kinds:
                self.assertIn(kind, intercom.KIND_ARGS, f"{pattern} -> {kind}")
                self.assertNotIn(kind, intercom.PLANNER_FORBIDDEN, f"{pattern} -> {kind}")
        for kind in local_planner.FALLBACK_KINDS:
            self.assertIn(kind, intercom.KIND_ARGS)
            self.assertNotIn(kind, intercom.PLANNER_FORBIDDEN)


class TheSizeBudgetIsEnforcedCase(unittest.TestCase):
    """A prompt over the budget is the whole defect, so the budget is a refusal."""

    def test_every_shortlist_fits_the_budget(self):
        for sentence in (
                "go to books.toscrape.com and tell me the title of the first book in the travel category",
                "remind me at 7:40 tomorrow morning to move the car",
                "write up a one page summary of the readme and save it as notes/summary.md",
                "look up what time the hardware store on main street closes today",
                "email brant about the invoice and put a hold in my calendar for friday",
                "asdfghjkl"):
            prompt = local_planner.compact_prompt(local_planner.shortlist(sentence))
            self.assertLessEqual(len(prompt.encode("utf-8")), local_planner.BUDGET_BYTES,
                                 sentence)

    def test_a_shortlist_too_big_for_the_budget_is_trimmed_not_sent(self):
        everything = sorted(k for k in intercom.KIND_ARGS
                            if k not in intercom.PLANNER_FORBIDDEN)
        prompt = local_planner.compact_prompt(everything)
        self.assertLessEqual(len(prompt.encode("utf-8")), local_planner.BUDGET_BYTES)
        named = [k for k in everything if f"  {k}(" in prompt]
        self.assertLess(len(named), len(everything) / 4)

    def test_the_budget_is_far_under_the_prompt_that_timed_out(self):
        """28.7 KB timed out at 180 s and at 300 s; a bigger budget is not the fix."""
        self.assertLess(local_planner.BUDGET_BYTES, len(planner.system_prompt()) / 4)

    def test_a_forbidden_kind_is_never_in_the_prompt_even_if_asked_for(self):
        prompt = local_planner.compact_prompt(["halt", "resume", "approve", "web_task"])
        for kind in ("halt", "resume", "approve"):
            self.assertNotIn(f"  {kind}(", prompt)
        self.assertIn("  web_task(", prompt)

    def test_a_closed_set_argument_says_its_values(self):
        """An argument whose value is a closed set reads like free text from a
        name alone, and the model fills it in with something reasonable and wrong."""
        prompt = local_planner.compact_prompt(["remember"])
        self.assertIn("domain is exactly one of:", prompt)


class TheGatesDoNotMoveCase(unittest.TestCase):
    """Same grammar, same gates. A smaller prompt is never a smaller gate."""

    def compile(self, output, request="do the thing"):
        return planner.compile(request, fleet=FLEET, registry=REGISTRY,
                               provider=_exploding(),
                               local=lambda req, **kw: (output, "qwen3:8b", ["web_task"]))

    def test_a_locally_compiled_forbidden_verb_is_still_refused(self):
        plan = self.compile({"intent": "plan", "summary": "s",
                             "steps": [{"kind": "resume"}]})
        self.assertEqual([s.status for s in plan.steps], [planner.REFUSED])
        self.assertIn("not a step a plan may take", plan.steps[0].detail)

    def test_a_locally_compiled_spending_step_is_still_refused(self):
        plan = self.compile({"intent": "plan", "summary": "s", "steps": [
            {"kind": "web_task", "goal": "buy the cheapest 4K monitor with my saved card"}]})
        self.assertEqual([s.status for s in plan.steps], [planner.REFUSED])

    def test_the_money_door_is_asked_before_her_own_model_is(self):
        """A refusal that arrives after a two-minute local round trip arrives
        too late and reads as consent in the meantime."""
        called = []

        def never(request, **kw):
            called.append(request)
            raise AssertionError("her own model must not be asked to spend his money")

        plan = planner.compile(
            "buy me the cheapest 4k monitor on amazon with my saved card",
            fleet=FLEET, registry=REGISTRY, provider=_exploding(), local=never)
        self.assertEqual(called, [])
        self.assertTrue(any(s.status == planner.REFUSED for s in plan.steps))

    def test_invalid_arguments_are_still_refused(self):
        plan = self.compile({"intent": "plan", "summary": "s", "steps": [
            {"kind": "remind_at", "at": "2026-09-19T08:00:00-05:00"}]})
        self.assertEqual([s.status for s in plan.steps], [planner.REFUSED])
        self.assertIn("missing args", plan.steps[0].detail)

    def test_a_closed_set_value_the_model_invented_is_still_refused(self):
        plan = self.compile({"intent": "plan", "summary": "s", "steps": [
            {"kind": "remember", "domain": "family", "memory_kind": "fact",
             "key": "sister", "value": "Mia"}]})
        self.assertEqual([s.status for s in plan.steps], [planner.REFUSED])

    def test_a_valid_local_step_is_executable_and_gated_at_execution(self):
        plan = self.compile({"intent": "plan", "summary": "s", "steps": [
            {"kind": "web_task", "goal": "read the first travel book title"}]})
        self.assertEqual([s.status for s in plan.steps], [planner.EXECUTABLE])

    def test_the_local_path_cannot_widen_authority(self):
        """Nothing the compact path can name is outside what the planner
        could already emit."""
        catalog = tools.catalog()
        for sentence in ("halt yourself", "resume yourself", "approve that",
                         "deny it", "open my resume", "close the tab",
                         "turn on the microphone", "start watching my screen",
                         "accept that study proposal"):
            for kind in local_planner.shortlist(sentence, catalog=catalog):
                self.assertNotIn(kind, intercom.PLANNER_FORBIDDEN, sentence)


class TheRetryCase(unittest.TestCase):
    """A compiled plan that fails validation is retried ONCE with the error."""

    def test_a_bad_shape_is_handed_back_once_and_repaired(self):
        seen = []

        def think(system_prompt, text, *, context=None):
            seen.append(text)
            if len(seen) == 1:
                return {"intent": "plan", "summary": "s", "steps": [], "oops": 1}, "qwen3:8b"
            return {"intent": "plan", "summary": "s", "steps": []}, "qwen3:8b"

        output, model, _kinds = local_planner.propose("do it", thinker=think)
        self.assertEqual(len(seen), 2)
        self.assertIn("REJECTED", seen[1])
        self.assertEqual(output["intent"], "plan")
        self.assertEqual(model, "qwen3:8b")

    def test_a_shape_that_stays_bad_is_reported_not_retried_forever(self):
        calls = []

        def always_bad(system_prompt, text, *, context=None):
            calls.append(text)
            return {"intent": "nonsense"}, "qwen3:8b"

        with self.assertRaises(local_planner.LocalPlanUnavailable):
            local_planner.propose("do it", thinker=always_bad)
        self.assertEqual(len(calls), 2)

    def test_too_many_steps_is_a_rejection_not_a_truncation(self):
        many = {"intent": "plan", "summary": "s",
                "steps": [{"kind": "notify_operator", "text": str(i)}
                          for i in range(local_planner.MAX_STEPS + 1)]}
        with self.assertRaises(brain.BrainOutputError):
            local_planner._validated(many)


class ProvenanceCase(unittest.TestCase):
    """A plan compiled locally SAYS so, where it matters."""

    def test_the_plan_names_the_rung_and_the_model(self):
        plan = planner.compile(
            "read the front page of example.com", fleet=FLEET, registry=REGISTRY,
            provider=_exploding(),
            local=lambda req, **kw: ({"intent": "plan", "summary": "Read it",
                                      "steps": [{"kind": "browse_read",
                                                 "url": "https://example.com"}]},
                                     "qwen3:8b", ["browse_read", "web_task"]))
        self.assertEqual(plan.compiled_by, local_planner.COMPILED_BY)
        self.assertIn("qwen3:8b", plan.provider)
        self.assertEqual(plan.shortlist, ["browse_read", "web_task"])
        self.assertIsNone(plan.degraded)

    def test_the_frontier_plan_says_nothing_about_a_local_model(self):
        plan = planner.compile("do the thing", fleet=FLEET, registry=REGISTRY,
                               provider=brain.Provider("stub", lambda t, c: {
                                   "intent": "plan", "summary": "s", "steps": []}))
        self.assertEqual(plan.compiled_by, "")
        self.assertEqual(plan.shortlist, [])

    def test_the_room_is_told_the_plan_is_from_her_own_model(self):
        from aletheia import intents
        said = intents.spoken({
            "compiled_by": local_planner.COMPILED_BY, "summary": "Read the page",
            "steps": [{"n": 1, "status": planner.EXECUTABLE,
                       "command": {"kind": "browse_read"}, "detail": ""}]})
        self.assertIn("my own model", said)
        self.assertIn("1 step ready", said)


class TheFallbackOrderCase(unittest.TestCase):
    """The frontier is preferred whenever it is available. This is a fallback."""

    def test_the_local_rung_is_not_asked_when_the_frontier_answered(self):
        asked = []
        plan = planner.compile(
            "do the thing", fleet=FLEET, registry=REGISTRY,
            provider=brain.Provider("stub", lambda t, c: {
                "intent": "plan", "summary": "s", "steps": []}),
            local=lambda *a, **kw: asked.append(1))
        self.assertEqual(asked, [])
        self.assertEqual(plan.provider, "stub")

    def test_an_injected_provider_keeps_the_old_behaviour_exactly(self):
        """A test/plugin boundary owns its own inputs: a supplied provider
        that fails degrades, and her own model is never reached behind it
        unless the caller asks for it by name."""
        with mock.patch("aletheia.local_planner.propose") as never:
            plan = planner.compile("do the thing", fleet=FLEET, registry=REGISTRY,
                                   provider=_exploding())
        self.assertTrue(plan.degraded)
        never.assert_not_called()

    def test_a_bad_shape_from_the_frontier_is_not_a_reason_to_go_local(self):
        """The repair retry above already covers it; going local for a shape
        problem would throw away the better model for a fixable answer."""
        self.assertFalse(planner._nobody_could_think("BrainOutputError: bad shape"))
        self.assertTrue(planner._nobody_could_think(
            "ReasonerUnavailable: the frontier models are switched off for this run"))


class TheAskDoesNotEvaporateCase(unittest.TestCase):
    """Continuity rule 3: every unfinished ask has a reason and a next condition."""

    def test_a_durable_item_is_filed_with_the_sentence_and_the_condition(self):
        filed = {}

        def add(title, **kw):
            filed.update({"title": title, **kw})
            return {"id": "work:abc123"}

        with mock.patch("aletheia.work_engine.add", add):
            wid = planner.queue_unplanned(
                "go to books.toscrape.com and tell me the first travel book",
                "ReasonerUnavailable: nothing could think")
        self.assertEqual(wid, "work:abc123")
        self.assertIn("books.toscrape.com", filed["title"])
        self.assertIn("frontier_reasoning", filed["requires"])
        self.assertEqual(filed["next"], "when Claude or Codex is back")
        self.assertIn("books.toscrape.com", filed["payload"]["request"])

    def test_the_state_is_the_shared_vocabulary_not_a_new_word(self):
        from aletheia import work_states
        filed = {}
        with mock.patch("aletheia.work_engine.add",
                        lambda title, **kw: (filed.update(kw), {"id": "w"})[1]):
            planner.queue_unplanned("x", "y")
        self.assertEqual(filed["state"], work_states.BLOCKED_MODEL)
        self.assertIn(filed["state"], work_states.WORK_STATES)

    def test_failing_to_file_never_fails_the_ask_as_well(self):
        with mock.patch("aletheia.work_engine.add", side_effect=OSError("disk")):
            self.assertEqual(planner.queue_unplanned("x", "y"), "")

    def test_nobody_could_plan_it_files_one(self):
        filed = []
        plan = planner.compile(
            "go to books.toscrape.com and tell me the first travel book",
            fleet=FLEET, registry=REGISTRY, provider=_exploding(), local=_no_local(),
            queue=lambda request, reason: filed.append((request, reason)) or "work:abc")
        self.assertEqual(plan.queued, "work:abc")
        self.assertEqual(len(filed), 1)
        self.assertIn("books.toscrape.com", filed[0][0])

    def test_and_the_room_is_told_it_is_on_the_list(self):
        from aletheia import intents
        said = intents.spoken({"degraded": "ReasonerUnavailable: nothing could think",
                               "steps": [], "queued_work": "work:abc"})
        self.assertIn("on my list", said)
        self.assertIn("Claude or Codex is back", said)
        self.assertNotIn("work:abc", said, "an id is not a thing he can say back")

    def test_nothing_is_queued_when_a_plan_actually_compiled(self):
        plan = planner.compile("do the thing", fleet=FLEET, registry=REGISTRY,
                               provider=brain.Provider("stub", lambda t, c: {
                                   "intent": "plan", "summary": "s",
                                   "steps": [{"kind": "notify_operator", "text": "hi"}]}))
        self.assertEqual(plan.queued, "")


def _exploding():
    from aletheia import reasoner

    def boom(text, context):
        raise reasoner.ReasonerUnavailable(
            "the frontier models are switched off for this run")
    return brain.Provider("stub.exploding", boom)


def _no_local():
    def never(*a, **kw):
        raise local_planner.LocalPlanUnavailable("her own model is not running")
    return never


if __name__ == "__main__":
    unittest.main()
