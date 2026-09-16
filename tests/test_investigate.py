"""A question about her work is looked into with her tools, in the live path.

`AgentSession` answered from its CLI and nowhere else. These hold the route
that puts it behind the real doors: which sentences reach it (positive,
negative and failure-shaped, about any of her work, not only jobs), which do
not (the world's questions, instructions, "what can't you do"), the order
that keeps it safe (quick first, the money door before anything), what the
room hears (spoken prose, the own-model disclosure, a guess said as one),
what she says while she looks, and that the exchange is remembered.

No test here calls a real model: every session thinks with a script.
"""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from aletheia import (access, agent_session, apply_run, converse, core, followups, intents,
                      investigate, journal, memory, notifications, plans, policy, quick, reasoner,
                      speech, tasks)

FLEET = {"repos": {}}


def scripted(*replies, provider="claude.cli:sonnet"):
    queue = list(replies)
    seen = []

    def think(system, text):
        seen.append(text)
        if not queue:
            raise AssertionError("the model was called more often than scripted")
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply, provider
    think.seen = seen
    return think


PALANTIR = {"id": "apply-3f9a2c1b7d", "state": "NEEDS_YOU", "company": "Palantir",
            "job_title": "Forward Deployed Engineer", "url": "https://jobs.lever.co/palantir/1",
            "captcha": "hCaptcha", "why": "an hCaptcha check only a person can pass"}


class WhichSentencesAreLookedInto(unittest.TestCase):
    def test_questions_about_any_of_her_work(self):
        for said in ("why didn't the Palantir one send", "is anything stuck",
                     "how is Barkly going", "where are we with the promo video",
                     "any update on barkly", "has the barkly build finished yet",
                     "what's the status of my applications", "which applications failed",
                     "why is the job hunt stopped", "what happened with the stripe application",
                     "what are you working on", "what do you need from me",
                     "tell me why the palantir one failed", "Thea, why didn't the Palantir one send?"):
            with self.subTest(said=said):
                self.assertTrue(investigate.wants_session(said), said)

    def test_negative_and_failure_shaped_phrasings_reach_it_too(self):
        # CLAUDE.md: the question asked in the negative reached nothing. Written
        # in the same sitting as the positive ones, on purpose.
        for said in ("what hasn't sent", "what's not working", "why hasn't barkly moved",
                     "why can't you finish the Palantir application", "why didn't you apply to anything today",
                     "did anything fail today", "what went wrong today", "is something wrong",
                     "what is blocking you", "what are you stuck on", "why are you halted",
                     "why is nothing sending", "what's holding up the stripe one",
                     "did the Palantir application go through", "have you sent anything today"):
            with self.subTest(said=said):
                self.assertTrue(investigate.wants_session(said), said)

    def test_the_worlds_questions_stay_with_conversation(self):
        for said in ("why is the sky blue", "whats the capital of iceland", "why do planes crash",
                     "why can't penguins fly", "what went wrong with the challenger launch",
                     "what happened with the election", "why did the roman empire fall",
                     "what's wrong with my car", "why is it so cold", "how is your day going",
                     "how are you", "how is it going", "what does a product manager do"):
            with self.subTest(said=said):
                self.assertFalse(investigate.wants_session(said), said)

    def test_instructions_stay_on_the_planner(self):
        for said in ("retry the palantir one", "look into why the palantir one failed",
                     "can you check why it failed", "why don't you retry the palantir one",
                     "send the palantir application", "apply to the stripe job",
                     "add a task to call the dentist", "buy the monitor", "order me a pizza"):
            with self.subTest(said=said):
                self.assertFalse(investigate.wants_session(said), said)

    def test_what_she_can_do_keeps_the_registry_and_referents_keep_the_thread(self):
        # "What can't you do" is the capability question `converse` carries the
        # registry for; "did you send it" names something said a moment ago.
        for said in ("what can't you do", "what cannot you do", "did you send it",
                     "why didn't it go through", "why did you say that", "are you halted",
                     "are you stopped"):
            with self.subTest(said=said):
                self.assertFalse(investigate.wants_session(said), said)

    def test_the_room_hears_it_is_on_it_early(self):
        from aletheia import asking
        with mock.patch.object(quick, "answer", return_value=None):
            self.assertEqual(asking.expectation("why didn't the Palantir one send"), "working")
            self.assertEqual(asking.expectation("what's the capital of iceland"), "quick")


class TheOrderIsTheSafetyArgument(unittest.TestCase):
    def test_a_stored_answer_is_still_a_file_read(self):
        with mock.patch.object(quick, "answer", return_value="Nothing is waiting on you."), \
                mock.patch.object(investigate, "propose") as looked:
            record = intents.propose("what do you need from me", fleet=FLEET)
        looked.assert_not_called()
        self.assertEqual(intents.spoken(record), "Nothing is waiting on you.")

    def test_spending_is_refused_before_anything_is_looked_into(self):
        with mock.patch.object(investigate, "propose") as looked, \
                mock.patch.object(agent_session, "chain_think") as thinker:
            record = intents.propose("buy the monitor and use my saved card", fleet=FLEET)
        looked.assert_not_called()
        thinker.assert_not_called()
        self.assertTrue(record.get("refused_spending"))

    def test_an_instruction_never_starts_a_session(self):
        with mock.patch.object(agent_session, "AgentSession") as sessions, \
                mock.patch("aletheia.planner.compile", side_effect=RuntimeError("planner reached")):
            with self.assertRaises(RuntimeError):
                intents.propose("retry the palantir one", fleet=FLEET)
        sessions.assert_not_called()

    def test_a_question_about_her_work_is_answered_by_a_session(self):
        think = scripted({"tool": "applications.query", "args": {"company": "Palantir"}},
                         {"answer": "It stopped at an hCaptcha check only you can pass.", "basis": "looked"})
        with mock.patch.object(apply_run, "all_runs", return_value=[PALANTIR]), \
                mock.patch.object(agent_session, "chain_think", return_value=think), \
                mock.patch.object(converse, "answer", side_effect=AssertionError("converse reached")), \
                mock.patch("aletheia.planner.compile", side_effect=AssertionError("planner reached")):
            record = intents.propose("why didn't the Palantir one send", fleet=FLEET)
        self.assertEqual(record["investigated"]["outcome"], agent_session.ANSWERED)
        self.assertEqual(record["investigated"]["knowing"], agent_session.KNOWN)
        self.assertIn("hCaptcha", intents.spoken(record))
        self.assertIn("Palantir", think.seen[1])           # the observation reached the model

    def test_a_session_with_nothing_usable_hands_back_to_the_old_path(self):
        # It may only ever ADD an answer.
        think = scripted({"hmm": 1}, {"still": "no"})
        with mock.patch.object(agent_session, "chain_think", return_value=think), \
                mock.patch.object(converse, "answer", return_value={"answer": "From conversation."}):
            record = intents.propose("why is the job hunt stopped", fleet=FLEET)
        self.assertNotIn("investigated", record)
        self.assertEqual(intents.spoken(record), "From conversation.")

    def test_nobody_able_to_think_is_said_in_words(self):
        think = scripted(agent_session.ModelUnavailable(
            "neither Claude nor the ChatGPT browser could answer just now; and my own model is not running"))
        with mock.patch.object(agent_session, "chain_think", return_value=think):
            record = intents.propose("why is the job hunt stopped", fleet=FLEET)
        said = intents.spoken(record)
        self.assertTrue(said.startswith("I couldn't look into that just now"), said)
        self.assertNotIn("ModelUnavailable", said)
        # The first live run read the log note out, file path and all.
        for machine in ("receipts", ".json", "\\", "neither Claude nor"):
            self.assertNotIn(machine, said)

    def test_a_model_that_goes_away_mid_session_gets_the_old_path(self):
        think = scripted({"tool": "applications.query", "args": {}},
                         agent_session.ModelUnavailable("Claude reasoning timed out after 90s"))
        with mock.patch.object(apply_run, "all_runs", return_value=[]), \
                mock.patch.object(agent_session, "chain_think", return_value=think), \
                mock.patch.object(converse, "answer", return_value={"answer": "From conversation."}):
            record = intents.propose("why is the job hunt stopped", fleet=FLEET)
        self.assertEqual(intents.spoken(record), "From conversation.")

    def test_the_live_chain_is_given_the_rooms_deadline(self):
        with mock.patch.object(agent_session, "chain_think",
                               return_value=scripted({"answer": "x"}, {"answer": "x"})) as chain, \
                mock.patch.object(converse, "remember_exchange"):
            investigate.propose("is anything stuck", report=lambda line: None)
        self.assertEqual(chain.call_args.kwargs["deadline_s"],
                         investigate.LIVE_BUDGET_S + investigate.DEADLINE_GRACE_S)


class WhatTheRoomHears(unittest.TestCase):
    def result(self, **kw):
        base = dict(id="agent-x", question="q", outcome=agent_session.ANSWERED,
                    answer="**Two** things are stuck (apply-3f9a2c1b7d).", model="claude.cli:sonnet")
        base.update(kw)
        return agent_session.SessionResult(**base)

    def test_model_prose_goes_through_the_one_door(self):
        said = investigate.spoken_answer(self.result())
        self.assertNotIn("*", said)
        self.assertNotIn("apply-3f9a2c1b7d", said)

    def test_her_own_model_says_the_answer_is_hers(self):
        with mock.patch.object(reasoner, "resting_until", return_value=None):
            said = investigate.spoken_answer(self.result(model="ollama:qwen3:8b"))
        self.assertTrue(said.startswith(reasoner.own_model_lead()), said)
        self.assertIn("from my own model", said)

    def test_a_subscription_answer_carries_no_disclosure(self):
        self.assertNotIn("my own model", investigate.spoken_answer(self.result()))

    def test_one_disclosure_for_conversation_and_sessions(self):
        import datetime as dt
        until = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
        with mock.patch.object(reasoner, "resting_until", return_value=until):
            self.assertTrue(reasoner.own_model_lead().startswith("Claude's out until "))
        with mock.patch.object(reasoner, "local_text", return_value=("Hi.", "ollama:q")), \
                mock.patch.object(reasoner, "resting_until", return_value=None):
            said, _ = converse._from_my_own_model("prompt")
        self.assertEqual(said, reasoner.own_model_lead() + "Hi.")

    def test_a_guess_says_it_is_a_guess(self):
        think = scripted({"answer": "Probably the captcha."}, {"answer": "Probably the captcha."})
        with mock.patch.object(agent_session, "chain_think", return_value=think), \
                mock.patch.object(converse, "remember_exchange"):
            record = investigate.propose("why didn't the Palantir one send", report=lambda line: None)
        self.assertIn("guess", intents.spoken(record).lower())

    def test_the_exchange_is_remembered(self):
        think = scripted({"tool": "applications.query", "args": {}}, {"answer": "Nothing is stuck."})
        with mock.patch.object(apply_run, "all_runs", return_value=[]), \
                mock.patch.object(agent_session, "chain_think", return_value=think), \
                mock.patch.object(converse, "remember_exchange") as remembered:
            record = investigate.propose("is anything stuck", report=lambda line: None)
        remembered.assert_called_once_with("is anything stuck", intents.spoken(record))

    def test_she_says_what_she_is_looking_at_once_each(self):
        lines = []
        think = scripted({"tool": "applications.query", "args": {}},
                         {"tool": "applications.query", "args": {"state": "FAILED"}},
                         {"tool": "journal.query", "args": {"kind": "alert"}},
                         {"answer": "Nothing failed."})
        with mock.patch.object(apply_run, "all_runs", return_value=[]), \
                mock.patch.object(agent_session, "chain_think", return_value=think), \
                mock.patch.object(converse, "remember_exchange"):
            investigate.propose("did anything fail today", report=lines.append)
        self.assertEqual(lines, ["Looking at the application records.", "Looking at my journal."])
        for line in lines:
            self.assertEqual(line, speech.spoken_prose(line))


class TheFollowUpPath(unittest.TestCase):
    """Through the real voice door: the room gets the acknowledgement at once,
    hears what she is looking at, and the answer lands in the follow-up."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.patches = [
            mock.patch.object(journal, "JOURNAL_PATH", base / "j.jsonl"),
            mock.patch.object(tasks, "TASKS_DIR", base / "tasks"),
            mock.patch.object(plans, "PLANS_DIR", base / "plans"),
            mock.patch.object(memory, "MEMORY_DIR", base / "memory"),
            mock.patch.object(policy, "APPROVALS_DIR", base / "approvals"),
            mock.patch.object(policy, "HALT_PATH", base / "halt.json"),
            mock.patch.object(notifications, "NOTICES_DIR", base / "notices"),
            mock.patch.object(followups, "records_dir", return_value=base / "followups"),
            mock.patch.object(converse, "THREAD_PATH", base / "recent.json"),
        ]
        for p in cls.patches:
            p.start()
        cls.server = core.make_server(port=0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        for p in cls.patches:
            p.stop()
        cls.tmp.cleanup()

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return json.loads(r.read().decode("utf-8"))

    def _post(self, payload, path):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Aletheia-Local": access.local_secret()},
            method="POST")
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode("utf-8"))

    def test_the_room_is_never_blocked_and_the_answer_lands(self):
        released = threading.Event()
        think_script = scripted({"tool": "applications.query", "args": {"company": "Palantir"}},
                                {"answer": "The Palantir one stopped at an hCaptcha check; it needs you."})

        def slow_think(system, text):
            released.wait(5)
            return think_script(system, text)

        with mock.patch.object(apply_run, "all_runs", return_value=[PALANTIR]), \
                mock.patch.object(agent_session, "chain_think", return_value=slow_think), \
                mock.patch.object(quick, "answer", return_value=None):
            first = self._post({"transcript": "thea why didn't the Palantir one send?"}, "/api/voice")
            self.assertEqual(first["outcome"], "thinking")
            self.assertEqual(first["say"], speech.ACK_QUESTION)
            released.set()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                slot = self._get(f"/api/voice/followup?id={first['followup_id']}")
                if slot["state"] != followups.PENDING:
                    break
                time.sleep(0.05)
            else:
                self.fail("the follow-up never landed")
        self.assertEqual(slot["state"], followups.READY)
        self.assertIn("hCaptcha", slot["say"])
        self.assertIn("Looking at the application records.", slot.get("progress") or [])
        turns = converse._thread()
        self.assertEqual(turns[-1]["you"], "why didn't the Palantir one send?")
        self.assertEqual(turns[-1]["her"], slot["say"])
        self.assertEqual(len([t for t in turns if t["you"] == turns[-1]["you"]]), 1)


if __name__ == "__main__":
    unittest.main()
