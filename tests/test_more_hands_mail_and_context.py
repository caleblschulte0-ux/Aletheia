"""Second build on the operator's PC (2026-09-02, "you keep building"):

- the code worker reads enough to act, picks what to read, and spends a
  grant slot only on a pull request that actually reaches GitHub;
- she reads the body of one unread email, named by sender or subject;
- desktop hands gained hotkeys from a safe list and select, with the same
  committing guard.
"""
import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import code_worker, computer, gh, intercom, journal, mail, policy, reasoner

FLEET = {"repos": {}}


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d / "private")})
        env.start(); self.addCleanup(env.stop)
        for target, attr, value in (
                (journal, "JOURNAL_PATH", d / "journal.jsonl"),
                (policy, "HALT_PATH", d / "halt.json"),
                (code_worker, "RUNS_DIR", d / "runs")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)


# ---- reasoner context ceiling ------------------------------------------------

class TheContextCeilingIsPerCall(Isolated):
    def test_the_default_is_unchanged(self):
        big = {"files": {"a.py": "x" * 9_000}}
        with self.assertRaises(reasoner.ReasonerUnavailable):
            reasoner.validate_input("s", "t", big)

    def test_a_caller_may_ask_for_more_within_the_ceiling(self):
        big = {"files": {"a.py": "x" * 9_000}}
        reasoner.validate_input("s", "t", big, max_context_bytes=64 * 1024)
        with self.assertRaises(ValueError):
            reasoner._bounded_context_limit(reasoner.MAX_CONTEXT_BYTES_CEILING + 1)
        with self.assertRaises(ValueError):
            reasoner._bounded_context_limit(1024)

    def test_the_code_worker_asks_for_more_than_the_default(self):
        self.assertGreater(code_worker.CONTEXT_BYTES, reasoner.MAX_CONTEXT_BYTES)
        self.assertLessEqual(code_worker.CONTEXT_BYTES, reasoner.MAX_CONTEXT_BYTES_CEILING)


# ---- code worker -------------------------------------------------------------

class FakeGitHub:
    def __init__(self, files):
        self.files = files
        self.posts = []

    def __call__(self, method, path, body=None):
        if method == "POST":
            self.posts.append((path, body))
            if path.endswith("/git/blobs"):
                return {"sha": "blob-sha"}
            if path.endswith("/git/trees"):
                return {"sha": "tree-new"}
            if path.endswith("/git/commits"):
                return {"sha": "commit-new"}
            if path.endswith("/git/refs"):
                return {"ref": body["ref"]}
            if path.endswith("/pulls"):
                return {"html_url": "https://github.com/me/repo/pull/9", "number": 9}
        if path == "/repos/me/repo":
            return {"private": False, "default_branch": "main"}
        if path.endswith("/git/ref/heads/main"):
            return {"object": {"sha": "base-sha"}}
        if path.endswith("/git/commits/base-sha"):
            return {"tree": {"sha": "tree-base"}}
        if "/git/trees/tree-base?recursive=1" in path:
            return {"truncated": False, "tree": [
                {"path": p, "type": "blob", "size": len(t), "mode": "100644"}
                for p, t in self.files.items()]}
        if "/contents/" in path:
            part = path.split("/contents/", 1)[1].split("?ref=", 1)[0]
            return {"encoding": "base64",
                    "content": base64.b64encode(self.files[part].encode()).decode(),
                    "sha": "old"}
        raise AssertionError((method, path, body))


def many_files():
    files = {f"src/mod{i}.py": f"def f{i}():\n    return {i}\n" for i in range(10)}
    files["src/app.py"] = "def answer():\n    return 1\n"
    files["tests/test_app.py"] = "from src.app import answer\n\ndef test():\n    assert answer() == 2\n"
    return files


class TheWorkerChoosesWhatToRead(Isolated):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(gh, "token", return_value="token"); p.start(); self.addCleanup(p.stop)

    def test_with_more_candidates_than_fit_the_model_picks_and_those_are_read_first(self):
        api = FakeGitHub(many_files())
        calls = []

        def model(system, text, **kw):
            calls.append(system)
            if system is code_worker.CHOOSE_SYSTEM:
                return kw["validator"]({"paths": ["src/app.py", "tests/test_app.py"], "why": "the defect"})
            if system is code_worker.PROPOSE_SYSTEM:
                self.assertIn("src/app.py", kw["context"]["files"])
                self.assertIn("tests/test_app.py", kw["context"]["files"])
                return {"summary": "fix", "confidence": 0.9, "changes": [
                    {"path": "src/app.py", "content": "def answer():\n    return 2\n", "why": "c"}]}
            return {"approved": True, "summary": "ok", "findings": []}

        with mock.patch.object(code_worker.reasoner, "subscription_json", side_effect=model), \
             mock.patch.object(code_worker.code_trust, "claim", return_value={"slot": 1}):
            run = code_worker.prepare_pr("me/repo", "Fix the answer", task_id="t1", request=api)
        self.assertEqual(run["status"], "PR_OPEN")
        self.assertEqual(calls[0], code_worker.CHOOSE_SYSTEM, "choice comes first")

    def test_a_chosen_path_outside_the_manifest_is_refused_and_costs_nothing(self):
        ranked = [{"path": f"src/mod{i}.py", "size": 10} for i in range(10)]

        def bad(system, text, **kw):
            return kw["validator"]({"paths": ["config/fleet.json"], "why": "attack"})
        out = code_worker.choose_paths(ranked, "objective", "", think=bad)
        self.assertEqual(out, ranked, "ranked order stands when the choice is refused")

    def test_few_candidates_need_no_choice(self):
        ranked = [{"path": "a.py", "size": 1}, {"path": "b.py", "size": 1}]
        boom = mock.Mock(side_effect=AssertionError("must not be called"))
        self.assertEqual(code_worker.choose_paths(ranked, "o", "", think=boom), ranked)


class AGrantSlotIsSpentOnlyOnAPullRequest(Isolated):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(gh, "token", return_value="token"); p.start(); self.addCleanup(p.stop)
        self.files = {"src/app.py": "def answer():\n    return 1\n"}

    def run_with(self, proposal_changes, approved=True):
        api = FakeGitHub(self.files)

        def model(system, text, **kw):
            if system is code_worker.PROPOSE_SYSTEM:
                return {"summary": "s", "confidence": 0.5, "changes": proposal_changes}
            return {"approved": approved, "summary": "r", "findings": []}
        claim = mock.Mock(return_value={"slot": 1})
        with mock.patch.object(code_worker.reasoner, "subscription_json", side_effect=model), \
             mock.patch.object(code_worker.code_trust, "claim", claim):
            try:
                result = code_worker.prepare_pr("me/repo", "Fix", task_id="t", request=api)
            except code_worker.CodeWorkerError as exc:
                result = {"status": "DECLINED", "detail": str(exc)}
        return result, claim, api

    def test_a_declined_proposal_claims_nothing(self):
        result, claim, api = self.run_with([])
        self.assertEqual(result["status"], "DECLINED")
        claim.assert_not_called()
        self.assertEqual(api.posts, [])

    def test_a_rejected_review_claims_nothing(self):
        result, claim, api = self.run_with(
            [{"path": "src/app.py", "content": "def answer():\n    return 2\n", "why": "w"}],
            approved=False)
        self.assertEqual(result["status"], "REVIEW_REJECTED")
        claim.assert_not_called()
        self.assertEqual(api.posts, [])

    def test_a_pull_request_claims_once_before_the_first_write(self):
        order = []
        api = FakeGitHub(self.files)
        real_call = api.__call__

        def tracked(method, path, body=None):
            if method == "POST":
                order.append("write")
            return real_call(method, path, body)

        def model(system, text, **kw):
            if system is code_worker.PROPOSE_SYSTEM:
                return {"summary": "s", "confidence": 0.5, "changes": [
                    {"path": "src/app.py", "content": "def answer():\n    return 2\n", "why": "w"}]}
            return {"approved": True, "summary": "r", "findings": []}

        def claim(**kw):
            order.append("claim"); return {"slot": 1}
        with mock.patch.object(code_worker.reasoner, "subscription_json", side_effect=model), \
             mock.patch.object(code_worker.code_trust, "claim", side_effect=claim):
            result = code_worker.prepare_pr("me/repo", "Fix", task_id="t", request=tracked)
        self.assertEqual(result["status"], "PR_OPEN")
        self.assertEqual(order.count("claim"), 1)
        self.assertEqual(order[0], "claim", "claimed before the first GitHub write")


# ---- email bodies -------------------------------------------------------------

class FakeMailbox:
    def __init__(self, unread, bodies):
        self.unread, self.bodies = unread, bodies
        self.fetched = []

    def fetch_unread(self, limit):
        return self.unread[:limit]

    def fetch_body(self, message_id):
        self.fetched.append(message_id)
        return self.bodies[message_id]

    def send(self, msg):
        raise AssertionError("reading never sends")


UNREAD = [
    {"from": "Dr. Ana Ruiz <office@smiles.test>", "subject": "Your appointment",
     "date": "", "message_id": "<a@smiles>"},
    {"from": "Bank <alerts@bank.test>", "subject": "Statement ready", "date": "",
     "message_id": "<b@bank>"},
    {"from": "Bank <alerts@bank.test>", "subject": "Card alert", "date": "",
     "message_id": "<c@bank>"},
]
BODIES = {"<a@smiles>": {"from": "Dr. Ana Ruiz <office@smiles.test>", "subject": "Your appointment",
                          "date": "", "message_id": "<a@smiles>",
                          "text": "We can see you Wednesday at 5:45pm. Reply to confirm."}}


class SheReadsOneBody(Isolated):
    def test_exactly_one_match_is_read(self):
        box = FakeMailbox(UNREAD, BODIES)
        message = mail.read_body("ana", transport=box)
        self.assertIn("Wednesday at 5:45pm", message["text"])
        self.assertEqual(box.fetched, ["<a@smiles>"])
        texts = " ".join(e["text"] for e in journal.entries())
        self.assertNotIn("5:45pm", texts, "the body is never journaled")
        self.assertIn("Your appointment", texts)

    def test_ambiguity_is_a_question_back_not_a_guess(self):
        box = FakeMailbox(UNREAD, BODIES)
        with self.assertRaises(mail.MailError) as caught:
            mail.read_body("bank", transport=box)
        self.assertIn("which one", str(caught.exception))
        self.assertEqual(box.fetched, [])

    def test_no_match_is_honest(self):
        with self.assertRaises(mail.MailError):
            mail.read_body("dentist", transport=FakeMailbox(UNREAD, BODIES))

    def test_html_only_mail_is_stripped_to_text(self):
        from email.message import EmailMessage
        msg = EmailMessage()
        msg.set_content("<html><body><p>Hello <b>there</b></p><script>x()</script></body></html>",
                        subtype="html")
        self.assertEqual(mail._body_text(msg).split(), ["Hello", "there"])

    def test_the_kind_is_read_only_and_local(self):
        self.assertIn("email_read", intercom.KIND_ARGS)
        self.assertIn("email_read", intercom.LOCAL_KINDS)
        self.assertEqual(intercom.tier("email_read"), intercom.TIER_READ)
        with mock.patch.object(mail, "read_body", return_value=BODIES["<a@smiles>"]):
            answer = intercom.execute_command({"kind": "email_read", "which": "ana"}, FLEET)
        self.assertIn("Wednesday", answer)


# ---- more hands ----------------------------------------------------------------

class FakeDesktop:
    def __init__(self):
        self.performed = []

    def describe_control(self, step):
        return {"name": step["control"].get("title", "")}

    def perform(self, step):
        self.performed.append((step["action"], step.get("keys") or step.get("value")))
        return {"action": step["action"], "verified": True}


WIN = {"title_re": ".*Notepad.*"}


class HotkeysAndSelect(Isolated):
    def test_only_safe_hotkeys_validate(self):
        ok = computer.validate_steps([{"action": "hotkey", "window": WIN, "keys": "ctrl+a"}])
        self.assertEqual(ok, [])
        for keys in ("enter", "alt+f4", "delete", "ctrl+enter", "ctrl+w", "{ENTER}"):
            with self.subTest(keys=keys):
                problems = computer.validate_steps([{"action": "hotkey", "window": WIN, "keys": keys}])
                self.assertTrue(problems, keys)

    def test_hands_may_use_them(self):
        desk = FakeDesktop()
        result = computer.act([
            {"action": "hotkey", "window": WIN, "keys": "ctrl+a"},
            {"action": "select", "window": WIN, "control": {"control_type": "ComboBox"}, "value": "UTF-8"},
        ], backend=desk)
        self.assertEqual(result["steps_done"], 2)
        self.assertEqual(desk.performed, [("hotkey", "ctrl+a"), ("select", "UTF-8")])

    def test_selecting_a_committing_entry_is_refused(self):
        desk = FakeDesktop()
        with self.assertRaises(computer.CommittingControl):
            computer.act([{"action": "select", "window": WIN,
                           "control": {"control_type": "Menu"}, "value": "Delete"}], backend=desk)
        self.assertEqual(desk.performed, [])

    def test_the_grammar_gate_knows_the_new_moves(self):
        steps = [{"action": "hotkey", "window": WIN, "keys": "enter"}]
        self.assertTrue(intercom.validate_kind_args({"kind": "computer_do", "steps": steps}, FLEET))
        steps = [{"action": "hotkey", "window": WIN, "keys": "escape"}]
        self.assertEqual(intercom.validate_kind_args({"kind": "computer_do", "steps": steps}, FLEET), [])


if __name__ == "__main__":
    unittest.main()


class ThePromptTravelsOnStdin(Isolated):
    """Windows caps a command line at 32,767 characters; the code worker's
    whole-file context passed that on 2026-09-02 and every repository read
    as "Claude failed". The prompt goes over stdin, the flags stay in argv."""

    def test_the_user_prompt_is_not_an_argument(self):
        big = "hello " * 8_000
        fake = mock.Mock(return_value=mock.Mock(returncode=0, stdout='{"result": "{\\"ok\\": true}"}', stderr=""))
        with mock.patch.object(reasoner, "cli_path", return_value="claude"), \
             mock.patch.object(reasoner.subprocess, "run", fake):
            reasoner._run_cli("system", big, "haiku", 10)
        argv = fake.call_args.args[0]
        self.assertNotIn(big, argv)
        self.assertEqual(fake.call_args.kwargs["input"], big)
        self.assertIn("-p", argv)
        self.assertLess(sum(len(a) for a in argv), 4_000)


class MachineMadeIssuesAreNotDefects(Isolated):
    """The first live sweeps spent every attempt on fleet alerts, a watchdog
    notice and a daily tracking issue; the proposer declined all of them,
    correctly. They are skipped before a model is asked, and a decline is
    recorded so the next sweep moves on."""

    REPO = {"full_name": "me/repo", "private": False, "observation_complete": True}

    def issues(self, rows):
        def request(method, path, body=None):
            if "/pulls?" in path:
                return []
            if "/issues?" in path:
                return rows
            if "/actions/runs" in path:
                return {"workflow_runs": []}
            raise AssertionError(path)
        return request

    def test_bots_alerts_and_tracking_issues_are_skipped(self):
        from aletheia import project_loop
        rows = [
            {"number": 1, "title": "Daily Shorts Pipeline - Reports", "user": {"login": "me", "type": "User"}},
            {"number": 2, "title": "Fleet alert: Shorts-pipeline", "user": {"login": "me", "type": "User"}},
            {"number": 3, "title": "Executor stalled - bot.py not running", "user": {"login": "me", "type": "User"}},
            {"number": 4, "title": "Crash on empty config", "user": {"login": "dependabot[bot]", "type": "Bot"}},
            {"number": 5, "title": "Crash on empty config", "user": {"login": "me", "type": "User"}, "body": "trace"},
        ]
        work = project_loop.choose_work(self.REPO, request=self.issues(rows))
        self.assertEqual(work["task_id"], "issue-5")

    def test_a_declined_issue_is_not_asked_again(self):
        from aletheia import project_loop
        code_worker._save_run("me/repo", "issue-5", {"version": 1, "status": "DECLINED",
                                                     "repo": "me/repo", "task_id": "issue-5"})
        rows = [{"number": 5, "title": "Crash on empty config", "user": {"login": "me", "type": "User"}},
                {"number": 6, "title": "Wrong sum in the invoice", "user": {"login": "me", "type": "User"}}]
        work = project_loop.choose_work(self.REPO, request=self.issues(rows))
        self.assertEqual(work["task_id"], "issue-6")
        self.assertTrue(code_worker.declined("me/repo", "issue-5"))
