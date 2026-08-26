"""Email vertical slice: draft -> approve -> send -> verify, gates first."""
import json
import subprocess
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest import mock

from aletheia import journal, mail, memory, policy, voice


class FakeTransport:
    def __init__(self, unread=None):
        self.sent: list[EmailMessage] = []
        self.unread = unread or []

    def fetch_unread(self, limit):
        return self.unread[:limit]

    def send(self, msg):
        self.sent.append(msg)


class MailCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        for target, attr in ((mail, "MAIL_DIR"), (policy, "APPROVALS_DIR"),
                             (policy, "HALT_PATH"), (journal, "JOURNAL_PATH"),
                             (memory, "MEMORY_DIR")):
            p = mock.patch.object(target, attr, d / attr.lower())
            p.start(); self.addCleanup(p.stop)

    def approved_draft(self, **kw):
        d = mail.draft(kw.get("to", "bob@example.com"),
                       kw.get("subject", "Hi"), kw.get("body", "hello there"))
        policy.decide(d["id"], "APPROVED", via="test")
        return d


class TestAddresses(MailCase):
    def test_spoken_address_resolves(self):
        addr, name = mail.resolve_address("bob at example dot com")
        self.assertEqual(addr, "bob@example.com")

    def test_name_resolves_through_memory(self):
        memory.remember("people", "landlord", "lord@land.example", source="test")
        addr, name = mail.resolve_address("Landlord")
        self.assertEqual(addr, "lord@land.example")
        self.assertEqual(name, "Landlord")

    def test_unknown_name_is_an_honest_refusal_not_a_guess(self):
        with self.assertRaises(ValueError) as ctx:
            mail.draft("someone i never mentioned", "s", "body")
        self.assertIn("add them privately", str(ctx.exception))
        self.assertEqual(policy.all_approvals(), [])  # nothing filed


class TestApprovalBinding(MailCase):
    def test_draft_files_operator_always_approval_bound_to_content(self):
        d = mail.draft("bob@example.com", "Rent", "coming friday")
        ap = policy.load(d["id"])
        self.assertEqual(ap["state"], "PENDING")
        self.assertTrue(ap["requested_action"].startswith("email.send:"))
        self.assertFalse(ap["reversible"])
        # privacy: the committed approval carries no address
        self.assertNotIn("bob@example.com", json.dumps(ap))

    def test_pending_draft_is_never_sent(self):
        mail.draft("bob@example.com", "Hi", "hello")
        t = FakeTransport()
        self.assertEqual(mail.send_approved(t), [])
        self.assertEqual(t.sent, [])

    def test_approved_draft_sends_exactly_once(self):
        self.approved_draft()
        t = FakeTransport()
        first = mail.send_approved(t)
        second = mail.send_approved(t)
        self.assertEqual([r["outcome"] for r in first], ["sent"])
        self.assertEqual(second, [])
        self.assertEqual(len(t.sent), 1)
        self.assertEqual(t.sent[0]["To"], "bob@example.com")

    def test_draft_edited_after_approval_is_refused(self):
        d = self.approved_draft()
        path = mail.MAIL_DIR / f"{d['id']}.json"
        tampered = json.loads(path.read_text())
        tampered["body"] = "now with different words"
        path.write_text(json.dumps(tampered))
        t = FakeTransport()
        results = mail.send_approved(t)
        self.assertEqual(results[0]["outcome"], "refused")
        self.assertIn("changed after approval", results[0]["detail"])
        self.assertEqual(t.sent, [])

    def test_denied_draft_retires_without_sending(self):
        d = mail.draft("bob@example.com", "Hi", "hello")
        policy.decide(d["id"], "DENIED", via="test", because="no")
        t = FakeTransport()
        results = mail.send_approved(t)
        self.assertEqual(results[0]["outcome"], "refused")
        self.assertEqual(t.sent, [])
        self.assertEqual(mail.send_approved(t), [])  # retired, not retried

    def test_transport_failure_leaves_draft_for_retry(self):
        self.approved_draft()
        class Boom(FakeTransport):
            def send(self, msg):
                raise OSError("smtp down")
        self.assertEqual(mail.send_approved(Boom()), [])
        t = FakeTransport()
        self.assertEqual([r["outcome"] for r in mail.send_approved(t)], ["sent"])


class TestCheckAndVoice(MailCase):
    def test_check_unread_is_speakable(self):
        t = FakeTransport(unread=[
            {"from": "Ada <ada@example.com>", "subject": "Lunch?", "date": ""}])
        say = mail.check_unread(transport=t)
        self.assertIn("Lunch?", say)
        self.assertIn("Ada", say)

    def test_check_empty_inbox(self):
        self.assertEqual(mail.check_unread(transport=FakeTransport()),
                         "No unread email.")

    def test_voice_check_email(self):
        for phrase in ("Thea, check my email", "thea any new mail",
                       "Thea, do I have any email?"):
            out = voice.interpret(phrase)
            self.assertEqual(out["command"], {"kind": "email_check"}, phrase)

    def test_voice_email_someone(self):
        out = voice.interpret("Thea, email landlord that rent is coming friday")
        self.assertEqual(out["command"],
                         {"kind": "email_draft", "to": "landlord",
                          "body": "rent is coming friday"})

    def test_mail_unconfigured_is_honest(self):
        with mock.patch.dict("os.environ", {"ALETHEIA_MAIL_ADDRESS": "",
                                            "ALETHEIA_MAIL_PASSWORD": ""}):
            with mock.patch.object(mail, "CONFIG_FILE",
                                   Path(self.tmp.name) / "nope.json"):
                ok, reason = mail.available()
        self.assertFalse(ok)
        self.assertIn("ALETHEIA_MAIL_ADDRESS", reason)


class TestPrivacy(unittest.TestCase):
    def test_mail_dir_is_gitignored(self):
        """Drafts hold addresses and bodies; the repo is public. This must
        never regress."""
        from aletheia.fleet import REPO_ROOT
        proc = subprocess.run(
            ["git", "check-ignore", "state/mail/x.json"],
            cwd=str(REPO_ROOT), capture_output=True)
        self.assertEqual(proc.returncode, 0,
                         "state/mail/ must be in .gitignore — drafts are private")


if __name__ == "__main__":
    unittest.main()
