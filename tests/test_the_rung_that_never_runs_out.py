"""She does things with NO model at all, and her own model repairs itself.

His words, 2026-09-21: "it's to the point I can say whatever I want and it
will do stuff even when no frontier models are available." Two builds hold
that, and both are tested here without a network, a model or a browser:

- `aletheia.rule_planner`: a sentence a rule owns whole is compiled from
  its words, through every gate a model's plan goes through, and the plan
  SAYS it was taken literally. A sentence no rule owns is never guessed at.
- `local_model_pool.ensure`: Ollama stopped is started, the configured
  model missing is pulled, once, in the background; and the Core's beat
  asks for it, so the rung that never runs out is actually there.
"""
import os
import tempfile
import unittest
from unittest import mock

from aletheia import intercom, local_planner, model_pool_config, planner, rule_planner


class TheRulesHoldToTheGrammar(unittest.TestCase):
    def test_every_kind_a_rule_names_is_real_and_allowed(self):
        for kind in rule_planner.kinds_named():
            with self.subTest(kind=kind):
                self.assertIn(kind, intercom.KIND_ARGS)
                self.assertNotIn(kind, intercom.PLANNER_FORBIDDEN)

    def test_a_forbidden_verb_is_never_compiled(self):
        for said in ("halt", "resume", "approve", "deny", "stop everything", "approve it"):
            self.assertIsNone(rule_planner.match(said), said)

    def test_what_no_rule_owns_is_none_not_a_guess(self):
        for said in ("text my sister that I'm late", "what's the weather in denver",
                     "why did the palantir one fail", "make me rich", "hmm",
                     "the thing we talked about", "buy a monitor"):
            with self.subTest(said=said):
                self.assertIsNone(rule_planner.match(said))

    def test_the_arguments_fit_the_grammar_exactly(self):
        for said in ("add a task to call the plumber", "put milk on the list", "play some music",
                     "open youtube", "read bbc.co.uk", "save Dana as a contact",
                     "how long does it take to get to the airport", "what's on my shopping list"):
            with self.subTest(said=said):
                kind, args, summary = rule_planner.match(said)
                required, optional = intercom.KIND_ARGS[kind]
                self.assertTrue(set(required) <= set(args), (kind, args))
                self.assertTrue(set(args) <= set(required) | set(optional), (kind, args))
                self.assertTrue(summary and summary[0].isupper(), summary)
                for machine in ("_", "kind", "None"):
                    self.assertNotIn(machine, summary)


class TheRulesUnderstandHim(unittest.TestCase):
    def test_the_ordinary_sentences(self):
        cases = {
            "add a task to call the plumber by friday": ("task_new", "call the plumber"),
            "put milk on the list": ("shopping_add", "milk"),
            "take eggs off the shopping list": ("shopping_off", "eggs"),
            "play some music": ("music", "play"),
            "next song": ("music", "next"),
            "read bbc.co.uk and tell me what it says": ("browse_read", "https://bbc.co.uk"),
            "open youtube": ("web_task", "Open youtube in the browser"),
            "go online and find the cheapest flight to denver": ("web_task", "find the cheapest flight to denver"),
            "sign me up for costco": ("web_task", "sign me up for costco"),
            "what do you know about my landlord": ("recall", "my landlord"),
            "find my resume pdf": ("file_find", "resume"),
            "take a screenshot": ("screenshot", None),
            "watch for an email from Stripe": ("watch_email_from", "Stripe"),
            "check my email": ("email_check", None),
            "cancel my Netflix subscription": ("subscription_cancel", "Netflix"),
            "read me my reminders": ("reminders", None),
            "what do I have to do today": ("tasks", None),
            "mark call the plumber as done": ("task_done", "call the plumber"),
        }
        for said, (kind, value) in cases.items():
            with self.subTest(said=said):
                found = rule_planner.match(said)
                self.assertIsNotNone(found, said)
                self.assertEqual(found[0], kind)
                if value is not None:
                    self.assertIn(value, found[1].values(), found[1])

    def test_filler_and_politeness_do_not_matter(self):
        for said in ("hey thea, can you add a task to call the plumber please",
                     "Add a task to call the plumber.", "just add a task to call the plumber for me"):
            self.assertEqual(rule_planner.match(said)[0], "task_new", said)

    def test_his_capitals_are_kept(self):
        kind, args, summary = rule_planner.match("save Dana Brooks as a contact, number 555-0100")
        self.assertEqual(args, {"name": "Dana Brooks", "phone": "555-0100"})
        self.assertIn("Dana Brooks", summary)

    def test_a_deadline_in_a_task_becomes_a_deadline(self):
        kind, args, summary = rule_planner.match("add a task to renew the registration by friday")
        self.assertEqual(args["description"], "renew the registration")
        self.assertRegex(args["deadline"], r"^\d{4}-\d{2}-\d{2}$")


class TheRungIsWiredIntoThePlanner(unittest.TestCase):
    FLEET = {"repos": {}}
    REGISTRY = {"capabilities": [{"id": "task.persist", "status": "AVAILABLE", "provider": "aletheia.local"}]}

    def nobody(self):
        from aletheia import brain, reasoner
        def dead(text, ctx):
            raise reasoner.ReasonerUnavailable("the frontier models are switched off for this run")
        return brain.Provider("stub.exploding", dead)

    def test_with_nobody_thinking_a_rule_plans_it_and_says_so(self):
        def no_model(request, **kw):
            raise RuntimeError("LocalPoolUnavailable: not running")
        plan = planner.compile("add a task to call the plumber", fleet=self.FLEET,
                               registry=self.REGISTRY, provider=self.nobody(), local=no_model)
        self.assertEqual(plan.compiled_by, local_planner.COMPILED_BY_RULES)
        self.assertEqual(plan.provider, rule_planner.PROVIDER)
        self.assertEqual(plan.steps[0].command["kind"], "task_new")
        self.assertIsNone(plan.degraded)
        from aletheia import intents
        record = {"compiled_by": plan.compiled_by, "intent": "plan", "summary": plan.summary,
                  "steps": [{"n": 1, "status": "EXECUTABLE", "capability": None,
                             "command": plan.steps[0].command, "detail": ""}], "tier": "routine"}
        with mock.patch.object(intents, "_due_to_mention", lambda *a: False):
            said = intents.spoken(record)
        self.assertIn("took this one literally, with no model", said)
        self.assertIn("Add a task: call the plumber", said)

    def test_rules_come_before_her_model_so_a_plain_sentence_never_waits(self):
        asked = []
        def slow_model(request, **kw):
            asked.append(request)
            return ({"intent": "plan", "summary": "x", "steps": [], "confidence": 0.1}, "qwen", [])
        plan = planner.compile("put milk on the list", fleet=self.FLEET, registry=self.REGISTRY,
                               provider=self.nobody(), local=slow_model)
        self.assertEqual(asked, [])
        self.assertEqual(plan.compiled_by, local_planner.COMPILED_BY_RULES)

    def test_a_sentence_no_rule_owns_still_reaches_her_model(self):
        asked = []
        def model(request, **kw):
            asked.append(request)
            return ({"intent": "plan", "summary": "Text your sister", "steps": [], "confidence": 0.5}, "qwen", [])
        plan = planner.compile("text my sister that I'm late", fleet=self.FLEET, registry=self.REGISTRY,
                               provider=self.nobody(), local=model)
        self.assertEqual(asked, ["text my sister that I'm late"])
        self.assertEqual(plan.compiled_by, local_planner.COMPILED_BY)

    def test_the_money_door_is_asked_before_the_rules(self):
        plan = planner.compile("go online and buy me a monitor", fleet=self.FLEET,
                               registry=self.REGISTRY, provider=self.nobody(),
                               local=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
        self.assertNotEqual(plan.compiled_by, local_planner.COMPILED_BY_RULES)
        self.assertTrue(any(s.status == "REFUSED" for s in plan.steps) or plan.provider.endswith("refused"))


class HerOwnModelRepairsItself(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": self.tmp.name})
        env.start(); self.addCleanup(env.stop)
        from aletheia import local_model_pool
        self.pool = local_model_pool
        self.pool.forget_reachability()
        self.addCleanup(self.pool.forget_reachability)
        self.spawned = []
        self.spawner = lambda args: self.spawned.append(args) or 4242

    def test_switched_off_means_nothing_is_started(self):
        out = self.pool.ensure(spawner=self.spawner, binary="/bin/ollama", probe=lambda base: False)
        self.assertFalse(out["enabled"])
        self.assertEqual(self.spawned, [])

    def test_ollama_stopped_is_started_once_and_not_again_for_a_while(self):
        model_pool_config.save_settings(enabled=True)
        with mock.patch.object(self.pool, "SERVE_WAIT_S", 0.0):
            out = self.pool.ensure(spawner=self.spawner, binary="/bin/ollama", probe=lambda base: False)
        self.assertTrue(out["started"])
        self.assertEqual(self.spawned, [["/bin/ollama", "serve"]])
        self.assertFalse(out["reachable"])
        with mock.patch.object(self.pool, "SERVE_WAIT_S", 0.0):
            again = self.pool.ensure(spawner=self.spawner, binary="/bin/ollama", probe=lambda base: False)
        self.assertEqual(len(self.spawned), 1)          # rate-limited
        self.assertIn("recently", again["why"])

    def test_no_ollama_installed_is_said_not_attempted(self):
        model_pool_config.save_settings(enabled=True)
        out = self.pool.ensure(spawner=self.spawner, binary="", probe=lambda base: False)
        self.assertEqual(self.spawned, [])
        self.assertIn("not installed", out["why"])

    def test_a_missing_model_is_pulled_once_in_the_background(self):
        model_pool_config.save_settings(enabled=True)
        wanted = model_pool_config.resolve("fast")["model"]
        with mock.patch("aletheia.local_brain.status",
                        return_value={"online": True, "model_available": False, "detail": "model not pulled"}), \
             mock.patch("aletheia.proc.pid_alive", return_value=True):
            out = self.pool.ensure(spawner=self.spawner, binary="/bin/ollama", probe=lambda base: True)
            self.assertEqual(out["pulling"], wanted)
            self.assertEqual(self.spawned, [["/bin/ollama", "pull", wanted]])
            again = self.pool.ensure(spawner=self.spawner, binary="/bin/ollama", probe=lambda base: True)
        self.assertEqual(len(self.spawned), 1)
        self.assertIn("still downloading", again["why"])

    def test_a_reachable_pool_with_its_model_is_simply_ok(self):
        model_pool_config.save_settings(enabled=True)
        with mock.patch("aletheia.local_brain.status",
                        return_value={"online": True, "model_available": True}):
            out = self.pool.ensure(spawner=self.spawner, binary="/bin/ollama", probe=lambda base: True)
        self.assertTrue(out["ok"])
        self.assertEqual(self.spawned, [])

    def test_activation_repairs_before_it_judges(self):
        with mock.patch.object(self.pool, "ensure", return_value={"enabled": True, "ok": True}) as heal, \
             mock.patch("aletheia.local_brain.status",
                        return_value={"online": True, "model_available": True}), \
             mock.patch.object(self.pool, "run_json") as run:
            run.return_value = type("R", (), {"duration_ms": 1})()
            self.pool.smoke()
        heal.assert_called_once()

    def test_the_beat_asks_for_it(self):
        from aletheia import runtime
        self.assertIn("_heal_local_ai", dir(runtime))
        import inspect
        self.assertIn('guarded("local_ai"', inspect.getsource(runtime.tick))


if __name__ == "__main__":
    unittest.main()


class AQuestionARuleOwnsIsAnsweredFromTheStore(unittest.TestCase):
    def test_when_conversation_cannot_think_a_read_only_rule_answers(self):
        from aletheia import converse, intents, intercom
        record = {}
        with mock.patch.object(converse, "answer",
                               side_effect=converse.ConverseError("I can't think just now")), \
             mock.patch.object(intercom, "execute_command",
                               return_value="Your landlord is Mr Okafor.") as run:
            intents._speak_answer(record, "what do you know about my landlord", {"repos": {}})
        self.assertIn("looked that up myself", record["spoken"])
        self.assertIn("Mr Okafor", record["spoken"])
        self.assertEqual(run.call_args.args[0], {"kind": "recall", "about": "my landlord"})

    def test_a_rule_that_would_start_something_never_runs_from_an_answer(self):
        from aletheia import converse, intents, intercom
        record = {}
        with mock.patch.object(converse, "answer",
                               side_effect=converse.ConverseError("I can't think just now")), \
             mock.patch.object(intercom, "execute_command") as run:
            intents._speak_answer(record, "put milk on the list", {"repos": {}})
        run.assert_not_called()
        self.assertEqual(record["spoken"], "I can't think just now")
