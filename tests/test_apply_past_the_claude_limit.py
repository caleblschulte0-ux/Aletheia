"""When he hits his Claude limit, the job hunt keeps applying.

His words, 2026-09-13: *"make it so that tomorrow when I hit my Claude limit it
still is applying for jobs."*

What was true that day:

- The hunt's models went Claude CLI -> the ChatGPT BROWSER, and an always-on
  process can never open the browser (it drops the lease so no window lands
  on his screen). So with Claude out, nobody could think, and `apply_forever`
  waited for the reset (PR #106).
- The Codex CLI is OpenAI's own client on his ChatGPT subscription, installed
  and "Logged in using ChatGPT" - with an EXPIRED refresh token, so every
  `codex exec` failed until he signs in again.
- Her own model fits on the laptop only with memory to spare: loading qwen3:8b
  beside his browsers got background processes killed.

No test here runs Codex, Claude or Ollama.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (apply_forever, apply_run, authority, campaign, job_fit, local_model_pool,
                      notifications, proc, reasoner, runtime)

import tests.test_apply_run as apply_base

UTC = dt.timezone.utc
LATER = dt.datetime(2030, 1, 1, 16, 40, tzinfo=UTC)
EXPIRED = ("ERROR: Your access token could not be refreshed because your refresh token has "
           "expired. Please log out and sign in again.")
GB = 1024 ** 3


def _forget_everything():
    for path in (reasoner._rest_path(), reasoner._codex_rest_path(),
                 reasoner._codex_rest_path().parent / "work-provider.json"):
        try:
            path.unlink()
        except OSError:
            pass
    reasoner._CODEX_STATUS.update({"at": None, "path": "", "ok": False, "why": ""})


class Clean(unittest.TestCase):
    def setUp(self):
        _forget_everything()
        self.addCleanup(_forget_everything)


class FakeCodex:
    """Stands in for `proc.run_tree` running codex.exe."""

    def __init__(self, answer='{"realistic": true, "why": "it fits"}', code=0, stderr=""):
        self.answer, self.code, self.stderr = answer, code, stderr
        self.calls = []

    def __call__(self, argv, timeout_s, **kw):
        seen = {"argv": list(argv), "timeout_s": timeout_s, **kw}
        if "--output-schema" in argv:
            seen["schema"] = json.loads(
                Path(argv[argv.index("--output-schema") + 1]).read_text(encoding="utf-8"))
        root = argv[argv.index("-C") + 1] if "-C" in argv else ""
        seen["root_was_empty"] = bool(root) and os.listdir(root) == []
        self.calls.append(seen)
        if self.answer is not None and "--output-last-message" in argv:
            Path(argv[argv.index("--output-last-message") + 1]).write_text(
                self.answer, encoding="utf-8")
        return subprocess.CompletedProcess(argv, self.code, "", self.stderr)


def ask_codex(fake, **kw):
    with mock.patch.object(reasoner, "codex_path", return_value="C:/Codex/bin/abc/codex.exe"), \
         mock.patch.object(reasoner.proc, "run_tree", side_effect=fake):
        return reasoner.codex_json("Decide.", "the resume", context={"job": "Ops Analyst"},
                                   schema=job_fit.FIT_SCHEMA,
                                   validator=job_fit._fit_validator, **kw)


def titled(title):
    return [n for n in notifications.all_notifications() if n.get("title") == title]


class CodexIsAskedHeadlessAndReadOnlyCase(Clean):
    def test_the_invocation_touches_nothing_and_shows_nothing(self):
        fake = FakeCodex()
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-not-his"}):
            value = ask_codex(fake)
        self.assertEqual(value, {"realistic": True, "why": "it fits"})
        call = fake.calls[0]
        argv = call["argv"]
        self.assertEqual(argv[1], "exec")
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
        for flag in ("--ephemeral", "--ignore-user-config", "--skip-git-repo-check",
                     "--output-schema", "--output-last-message"):
            self.assertIn(flag, argv)
        self.assertNotIn("danger", " ".join(argv))
        self.assertNotIn("workspace-write", argv)
        self.assertEqual(call["schema"], job_fit.FIT_SCHEMA)
        self.assertEqual(argv[-1], "-", "the prompt travels on stdin")
        self.assertIn("the resume", call["input"])
        self.assertIn("Ops Analyst", call["input"])
        self.assertTrue(call["root_was_empty"], "its working root is an empty directory")
        self.assertEqual(call["creationflags"] & proc.hidden_flags(), proc.hidden_flags())
        self.assertNotIn("OPENAI_API_KEY", call["env"], "his subscription, never a key")

    def test_a_timeout_is_unavailable_in_words(self):
        def slow(argv, timeout_s, **kw):
            raise subprocess.TimeoutExpired(argv, timeout_s)
        with self.assertRaises(reasoner.ReasonerUnavailable) as caught:
            ask_codex(slow, timeout_s=5)
        self.assertIn("longer than 5 seconds", str(caught.exception))

    def test_not_installed_is_said(self):
        with mock.patch.object(reasoner, "codex_path", return_value=None):
            with self.assertRaises(reasoner.ReasonerUnavailable) as caught:
                reasoner.codex_json("Decide.", "resume")
            self.assertIn("not installed", str(caught.exception))
            self.assertFalse(reasoner.codex_available()[0])

    def test_it_is_found_where_the_app_puts_it_when_not_on_path(self):
        root = Path(reasoner._workdir())
        self.addCleanup(reasoner._discard_workdir, str(root))
        exe = root / "OpenAI" / "Codex" / "bin" / "fb2111b9" / "codex.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("", encoding="utf-8")
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(root), reasoner.CODEX_ENV: ""}), \
             mock.patch.object(reasoner.shutil, "which", return_value=None):
            self.assertEqual(reasoner.codex_path(), str(exe))

    def test_checking_it_spends_no_request(self):
        fake = mock.Mock(return_value=subprocess.CompletedProcess([], 0, "Logged in using ChatGPT", ""))
        with mock.patch.object(reasoner, "codex_path", return_value="codex.exe"), \
             mock.patch.object(reasoner.proc, "run_tree", fake):
            self.assertTrue(reasoner.codex_available()[0])
            self.assertTrue(reasoner.codex_available()[0])
        fake.assert_called_once()
        self.assertEqual(fake.call_args.args[0], ["codex.exe", "login", "status"])

    def test_an_answer_that_mentions_a_limit_is_an_answer(self):
        ask_codex(FakeCodex('{"realistic": false, "why": "it has a usage limit on travel"}'))
        self.assertIsNone(reasoner.codex_resting())


class AnExpiredSignInIsHeardOnceCase(Clean):
    def test_it_is_recognized_remembered_and_he_is_told_once(self):
        fake = FakeCodex(answer=None, code=1, stderr=EXPIRED)
        with self.assertRaises(reasoner.CodexResting) as caught:
            ask_codex(fake)
        self.assertIn("codex login", str(caught.exception))
        self.assertEqual(reasoner.codex_resting()[1], reasoner.CODEX_LOGIN)
        with self.assertRaises(reasoner.CodexResting):
            ask_codex(fake)
        self.assertEqual(len(fake.calls), 1, "not asked again while the sign-in is known expired")
        self.assertFalse(reasoner.codex_available()[0])
        self.assertEqual(len(titled("Codex needs you to sign in again")), 1)

        # Half an hour on it is asked again, is still expired - and he is not
        # told a second time about the same expired sign-in.
        record = json.loads(reasoner._codex_rest_path().read_text(encoding="utf-8"))
        record["until"] = "2020-01-01T00:00:00Z"
        reasoner._codex_rest_path().write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(reasoner.CodexResting):
            ask_codex(fake)
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(len(titled("Codex needs you to sign in again")), 1)

        # He signs in; an answer clears what was remembered.
        record = json.loads(reasoner._codex_rest_path().read_text(encoding="utf-8"))
        record["until"] = "2020-01-01T00:00:00Z"
        reasoner._codex_rest_path().write_text(json.dumps(record), encoding="utf-8")
        ask_codex(FakeCodex())
        self.assertFalse(reasoner._codex_rest_path().exists())

    def test_a_spent_usage_window_is_remembered_until_its_reset(self):
        now = dt.datetime.now(UTC)
        fake = FakeCodex(answer=None, code=1,
                         stderr="You've hit your usage limit. Try again in 2 hours 5 minutes.")
        with self.assertRaises(reasoner.CodexResting):
            ask_codex(fake)
        until, why = reasoner.codex_resting()
        self.assertEqual(why, reasoner.CODEX_LIMIT)
        self.assertAlmostEqual((until - now).total_seconds(), 7500, delta=120)
        self.assertEqual(titled("Codex needs you to sign in again"), [])

    def test_other_failures_are_not_remembered(self):
        with self.assertRaises(reasoner.ReasonerUnavailable) as caught:
            ask_codex(FakeCodex(answer=None, code=1, stderr="stream disconnected"))
        self.assertNotIsInstance(caught.exception, reasoner.CodexResting)
        self.assertIsNone(reasoner.codex_resting())


class TheChainCase(Clean):
    VALUE = {"realistic": True, "why": "fits"}

    def chain(self, *, free=8 * GB, held=0, enabled=True, reachable=True,
              codex=None, claude=None):
        run = local_model_pool.LocalRun("fast", "qwen3:8b", False, self.VALUE, None, 1)
        patches = [
            mock.patch.object(reasoner, "infer_json",
                              **({"side_effect": claude} if isinstance(claude, Exception)
                                 else {"return_value": claude or self.VALUE})),
            mock.patch.object(reasoner, "codex_json",
                              **({"side_effect": codex} if isinstance(codex, Exception)
                                 else {"return_value": codex or self.VALUE})),
            mock.patch.object(reasoner, "_free_memory_bytes", return_value=free),
            mock.patch.object(reasoner, "_ollama_holds_bytes", return_value=held),
            mock.patch("aletheia.model_pool_config.enabled", return_value=enabled),
            mock.patch.object(local_model_pool, "reachable", return_value=reachable),
            mock.patch.object(local_model_pool, "auto_json", return_value=run),
            mock.patch("aletheia.journal.append"),
        ]
        mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.claude, self.codex, *_rest, self.local, self.journal = mocks
        return lambda **kw: reasoner.work_json_with_provider(
            "Decide.", "resume", validator=job_fit._fit_validator,
            local_prompt="Decide strictly.", **kw)

    def test_claude_answers_first(self):
        ask = self.chain()
        self.assertEqual(ask()[1], f"claude.cli:{reasoner.INTERPRET_MODEL}")
        self.codex.assert_not_called()
        self.local.assert_not_called()

    def test_while_claude_rests_it_is_not_asked_and_codex_answers(self):
        reasoner._rest(LATER, "You've hit your session limit · resets 4:40pm (UTC)")
        ask = self.chain()
        self.assertEqual(ask(), (self.VALUE, "codex.cli"))
        self.claude.assert_not_called()
        self.local.assert_not_called()

    def test_codex_expired_falls_to_her_own_model_only_with_room(self):
        reasoner._rest(LATER, "You've hit your session limit")
        ask = self.chain(codex=reasoner.CodexResting(LATER, reasoner.CODEX_LOGIN), free=7 * GB)
        value, provider = ask(timeout_s=900)
        self.assertEqual(provider, "ollama:qwen3:8b")
        kw = self.local.call_args.kwargs
        self.assertEqual(kw["preferred_role"], "fast")
        self.assertFalse(kw["allow_failover"], "never escalates to the model that does not fit")
        self.assertLessEqual(kw["timeout_s"], 300)
        self.assertEqual(self.local.call_args.args[0], "Decide strictly.")

    def test_too_little_memory_is_an_honest_no(self):
        reasoner._rest(LATER, "You've hit your session limit")
        ask = self.chain(codex=reasoner.CodexResting(LATER, reasoner.CODEX_LOGIN), free=3 * GB)
        with self.assertRaises(reasoner.ReasonerUnavailable) as caught:
            ask()
        self.local.assert_not_called()
        said = str(caught.exception)
        self.assertIn("Claude is out", said)
        self.assertIn("codex login", said)
        self.assertIn("memory", said)

    def test_the_model_she_already_loaded_counts_as_room(self):
        reasoner._rest(LATER, "You've hit your session limit")
        ask = self.chain(codex=reasoner.ReasonerUnavailable("no"), free=2 * GB, held=5 * GB)
        self.assertTrue(ask()[1].startswith("ollama:"))

    def test_ollama_off_or_switched_off_is_no(self):
        for kw in ({"reachable": False}, {"enabled": False}):
            with self.subTest(**kw):
                _forget_everything()
                reasoner._rest(LATER, "You've hit your session limit")
                ask = self.chain(codex=reasoner.ReasonerUnavailable("no"), **kw)
                with self.assertRaises(reasoner.ReasonerUnavailable):
                    ask()

    def test_a_switch_is_journaled_once_per_rest_not_per_call(self):
        reasoner._rest(LATER, "You've hit your session limit")
        ask = self.chain()
        for _ in range(3):
            ask()
        lines = [c for c in self.journal.call_args_list if "job hunt" in str(c)]
        self.assertEqual(len(lines), 1)
        self.assertIn("other subscription", str(lines[0]))
        self.assertNotIn("Codex", str(lines[0]))

    def test_subscription_json_keeps_its_contract(self):
        """Everything else - code included - is still Claude then the browser."""
        from aletheia import browser_reasoner
        reasoner._rest(LATER, "You've hit your session limit")
        with mock.patch.object(reasoner, "codex_json") as codex, \
             mock.patch.object(local_model_pool, "auto_json") as local, \
             mock.patch.object(browser_reasoner, "infer_json",
                               side_effect=RuntimeError("no lease")), \
             mock.patch.dict(os.environ, {"ALETHEIA_LOCAL_AI_SHADOW": "0"}):
            with self.assertRaises(reasoner.ReasonerUnavailable):
                reasoner.subscription_json("sys", "review this code")
        codex.assert_not_called()
        local.assert_not_called()


class WhoJudgedTheJobCase(unittest.TestCase):
    JOB = {"title": "Operations Analyst", "company": "Acme", "description": "Run operations."}

    def judged_by(self, provider, realistic=True):
        with mock.patch.object(reasoner, "work_json_with_provider",
                               return_value=({"realistic": realistic, "why": "read it"},
                                             provider)) as chain:
            said = job_fit.verdict(self.JOB, "resume", {})
        return said, chain

    def test_the_verdict_names_the_provider(self):
        self.assertEqual(self.judged_by("codex.cli")[0]["by"], "model:codex")
        self.assertEqual(self.judged_by("claude.cli:haiku")[0]["by"], "model:claude")
        said, chain = self.judged_by("ollama:qwen3:8b")
        self.assertEqual(said["by"], "model:local")
        self.assertTrue(job_fit.by_a_model(said))
        self.assertIs(chain.call_args.kwargs["local_prompt"], job_fit.LOCAL_FIT_BRIEF)
        self.assertEqual(chain.call_args.kwargs["schema"], job_fit.FIT_SCHEMA)

    def test_her_own_model_is_told_unsure_means_no(self):
        self.assertIn("say NOT realistic", job_fit.LOCAL_FIT_BRIEF)
        self.assertNotIn("When you are unsure, say realistic.", job_fit.LOCAL_FIT_BRIEF)
        self.assertIn("When you are unsure, say realistic.", job_fit.FIT_BRIEF)

    def test_a_local_yes_never_beats_the_rules(self):
        with mock.patch.object(reasoner, "work_json_with_provider") as chain:
            said = job_fit.verdict({"title": "Business Development Representative - Spanish Speaking",
                                    "company": "Acme"}, "resume", {})
        self.assertEqual((said["realistic"], said["by"]), (False, "rules"))
        chain.assert_not_called()

    def test_a_codex_or_local_verdict_is_a_current_model_judgment(self):
        with mock.patch.object(job_fit, "preferences_changed_at", return_value=""):
            for by in ("model", "model:codex", "model:local", "model:claude"):
                self.assertTrue(job_fit.fit_is_current({"realistic": True, "by": by, "at": "x"}), by)
            self.assertFalse(job_fit.fit_is_current({"realistic": True, "by": "", "at": "x"}))


class ALocalYesWaitsForHisOkCase(apply_base.ApplyCase):
    LOCAL = {"realistic": True, "by": "model:local", "why": "fits", "at": "2026-09-14T09:00:00Z"}

    def test_only_a_local_judgment_waits(self):
        self.assertEqual(apply_run.waits_for_his_ok({"fit": self.LOCAL}), apply_run.JUDGED_LOCALLY)
        for by in ("model:codex", "model:claude", "model"):
            self.assertEqual(apply_run.waits_for_his_ok({"fit": {**self.LOCAL, "by": by}}), "", by)

    def test_a_job_only_her_own_model_judged_is_not_sent_on_the_grant(self):
        out = self.staged(extra={"#felony": "No", "#cert": True})
        apply_run.remember(out["id"], company="Acme", job_title="Operations Analyst", fit=self.LOCAL)
        with mock.patch.object(authority, "satisfy", return_value="claim-1"), \
             mock.patch.object(runtime, "_submit_in_its_own_process",
                               side_effect=AssertionError("sent on the grant")):
            self.assertEqual(runtime.send_approved_applications(), [])
        notices = titled("A job my own model picked is waiting for your OK")
        self.assertEqual(len(notices), 1)
        self.assertIn("Operations Analyst at Acme", notices[0]["body"])

    def test_his_own_yes_sends_it(self):
        self.assertEqual(apply_run.waits_for_his_ok({"fit": self.LOCAL}), apply_run.JUDGED_LOCALLY)
        with mock.patch.object(apply_run.policy, "load",
                               return_value={"state": "APPROVED", "decided_via": "operator"}):
            self.assertEqual(apply_run.waits_for_his_ok({"fit": self.LOCAL, "approval": "a-1"}), "")


class EssaysAreNeverHerOwnModelsCase(unittest.TestCase):
    def test_with_claude_out_codex_writes_it_and_her_own_model_never_does(self):
        with mock.patch.object(reasoner, "subscription_text",
                               side_effect=reasoner.ReasonerUnavailable("out")), \
             mock.patch.object(reasoner, "codex_json",
                               return_value={"answer": "Because the work is real."}) as codex, \
             mock.patch.object(reasoner, "local_text", side_effect=AssertionError("local essay")):
            self.assertEqual(campaign._any_model_writes("Why Figma?", "resume", timeout_s=60),
                             "Because the work is real.")
        self.assertEqual(codex.call_args.kwargs["schema"], campaign.ESSAY_SCHEMA)

    def test_her_own_model_writes_when_no_subscription_can(self):
        """His 2026-09-12 ruling: an essay is AI's to write and does not come
        back to him. It holds past Claude's limit and a spent Codex too."""
        with mock.patch.object(reasoner, "subscription_text",
                               side_effect=reasoner.ReasonerUnavailable("out")), \
             mock.patch.object(reasoner, "codex_json",
                               side_effect=reasoner.CodexResting(LATER, reasoner.CODEX_LOGIN)), \
             mock.patch.object(reasoner, "local_text",
                               return_value=("I build partner programs.", "ollama:qwen3:8b")) as local:
            self.assertEqual(campaign._any_model_writes("Why us?", "resume", timeout_s=900),
                             "I build partner programs.")
        self.assertLessEqual(local.call_args.kwargs["timeout_s"], 300.0)

    def test_nobody_to_write_leaves_the_question_his(self):
        record = {"url": "https://x", "job_title": "AE",
                  "questions": [{"selector": "#why", "type": "textarea", "label": "Why us?"}]}
        with mock.patch.object(reasoner, "subscription_text",
                               side_effect=reasoner.ReasonerUnavailable("out")), \
             mock.patch.object(reasoner, "codex_json",
                               side_effect=reasoner.CodexResting(LATER, reasoner.CODEX_LOGIN)), \
             mock.patch.object(reasoner, "local_text",
                               side_effect=reasoner.ReasonerUnavailable("no memory for it")):
            self.assertEqual(campaign.draft_essays(record, "resume"), {})


class TheHuntUsesTheChainCase(unittest.TestCase):
    def test_roles_and_the_resume_are_read_through_it_with_a_schema(self):
        with mock.patch.object(reasoner, "work_json",
                               return_value={"roles": ["Operations Analyst"]}) as chain, \
             mock.patch.object(campaign.profile, "known", return_value={}):
            self.assertEqual(campaign.roles_for("resume"), ["Operations Analyst"])
        self.assertEqual(chain.call_args.kwargs["schema"], campaign.ROLES_SCHEMA)
        with mock.patch.object(reasoner, "work_json", return_value={}) as chain, \
             mock.patch.object(campaign.profile, "known", return_value={}):
            campaign.learn_more("resume")
        self.assertEqual(chain.call_args.kwargs["schema"], campaign.LEARN_SCHEMA)

    def test_nobody_answering_a_form_is_an_empty_answer_not_a_crash(self):
        with mock.patch.object(reasoner, "work_json",
                               side_effect=reasoner.ReasonerUnavailable("nobody")) as chain:
            self.assertEqual(campaign._any_model_answers("b", "r", context={}, validator=dict,
                                                         max_context_bytes=8192), {})
        self.assertEqual(chain.call_args.kwargs["schema"], campaign.ANSWERS_SCHEMA)


class TheLoopWaitsOnlyForNobodyCase(unittest.TestCase):
    def setUp(self):
        apply_forever._SAID_REST.clear()
        apply_forever._LAST_REFILL[:] = [0.0]
        self.addCleanup(apply_forever._LAST_REFILL.clear)
        for target, name, kw in ((apply_forever.campaign, "running", {"return_value": None}),
                                 (apply_forever.policy, "ensure_not_halted", {}),
                                 (apply_forever, "_claude_rests_until", {"return_value": LATER}),
                                 (apply_forever, "_waiting", {"return_value": 0}),
                                 (apply_forever.journal, "append", {})):
            patch = mock.patch.object(target, name, **kw)
            patch.start()
            self.addCleanup(patch.stop)

    def test_claude_out_and_codex_able_is_a_batch(self):
        started = []
        with mock.patch.object(apply_forever, "_another_mind", return_value=(True, "codex")):
            out = apply_forever.once(starter=lambda **kw: started.append(kw) or {"started": True},
                                     clock=lambda: 10.0)
        self.assertTrue(out["started"])
        self.assertEqual(len(started), 1)

    def test_claude_out_and_nobody_else_waits_and_says_why(self):
        with mock.patch.object(apply_forever, "_another_mind",
                               return_value=(False, "Codex needs you to sign in again")):
            out = apply_forever.once(starter=lambda **kw: self.fail("started with nobody to think"))
        self.assertIn("resting_until", out)
        self.assertIn("sign in", out["why"])

    def test_who_else_can_think(self):
        with mock.patch.object(reasoner, "codex_available", return_value=(True, "ok")), \
             mock.patch.object(reasoner, "local_allowed",
                               side_effect=AssertionError("asked needlessly")):
            self.assertEqual(apply_forever._another_mind(), (True, "codex"))
        with mock.patch.object(reasoner, "codex_available", return_value=(False, "sign in")), \
             mock.patch.object(reasoner, "local_allowed", return_value=(True, "room")):
            self.assertEqual(apply_forever._another_mind(), (True, "local"))
        with mock.patch.object(reasoner, "codex_available", return_value=(False, "sign in")), \
             mock.patch.object(reasoner, "local_allowed", return_value=(False, "3 GB free")):
            ok, why = apply_forever._another_mind()
        self.assertFalse(ok)
        self.assertIn("sign in", why)
        self.assertIn("3 GB free", why)


class ATreeRunTakesStdinCase(unittest.TestCase):
    def test_input_reaches_the_child(self):
        done = proc.run_tree([sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
                             60, input="codex prompt")
        self.assertEqual(done.stdout.strip(), "CODEX PROMPT")


if __name__ == "__main__":
    unittest.main()
