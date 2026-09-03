"""His life stays on his machine (2026-09-03).

The operator: *"is there a reason that that can't live on my personal
machine?"* There was not. The repository is public because GitHub Pages
requires it, and Pages serves the wall, which reads exactly one file —
`state/pulse/latest.json`. The journal, the approvals and the mail
password were never required to be there.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, mail, policy
from aletheia.fleet import REPO_ROOT


class NothingPrivateIsTrackedCase(unittest.TestCase):
    """Belt to the code's braces: ask git itself."""

    def tracked(self, pathspec: str) -> str:
        return subprocess.run(["git", "ls-files", pathspec], cwd=str(REPO_ROOT),
                              capture_output=True, text=True).stdout

    def test_the_pc_journal_is_not_tracked(self):
        self.assertNotIn("journal-pc.jsonl", self.tracked("state/journal"))

    def test_no_approval_is_tracked(self):
        self.assertEqual(self.tracked("state/approvals").strip(), "")

    def test_private_state_is_not_tracked(self):
        self.assertEqual(self.tracked("state/private").strip(), "")

    def test_the_wall_still_has_what_it_reads(self):
        # the one file Pages genuinely needs, and it holds no personal text
        self.assertIn("state/pulse/latest.json", self.tracked("state/pulse"))


class PrivateLocationsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ,
                              {"ALETHEIA_PRIVATE_STATE": self.tmp.name})
        env.start(); self.addCleanup(env.stop)

    def test_the_pc_journal_lands_in_private_state(self):
        original = journal.JOURNAL_PATH
        self.addCleanup(setattr, journal, "JOURNAL_PATH", original)
        path = journal.use_pc_journal()
        self.assertTrue(str(path).startswith(self.tmp.name), path)
        self.assertEqual(path.name, "journal-pc.jsonl")

    def test_entries_still_read_the_private_writer(self):
        original = journal.JOURNAL_PATH
        self.addCleanup(setattr, journal, "JOURNAL_PATH", original)
        journal.use_pc_journal()
        journal.append("note", "pc", "a private local action")
        journal.JOURNAL_PATH = REPO_ROOT / "state" / "journal" / "journal.jsonl"
        texts = [e["text"] for e in journal.entries()]
        self.assertIn("a private local action", texts,
                      "a reader pointed at the repo journal lost the local stream")

    def test_approvals_resolve_into_private_state(self):
        self.assertTrue(str(policy._approvals_dir()).startswith(self.tmp.name))

    def test_an_explicit_override_still_wins_for_tooling(self):
        with mock.patch.dict(os.environ,
                             {"ALETHEIA_APPROVALS_DIR": r"D:\elsewhere"}):
            self.assertEqual(policy._approvals_dir(), Path(r"D:\elsewhere"))


class MailSecretCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / "mail.json"
        p = mock.patch.object(mail, "CONFIG_FILE", self.config)
        p.start(); self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start(); self.addCleanup(env.stop)
        os.environ.pop("ALETHEIA_MAIL_PASSWORD", None)

    def write(self, **kw):
        self.config.write_text(json.dumps(kw), encoding="utf-8")

    def test_the_vault_is_preferred_over_the_plaintext_file(self):
        self.write(address="a@b.c", password="from-the-file")
        with mock.patch.object(mail, "stored_password", return_value="from-the-vault"):
            self.assertEqual(mail._config()["password"], "from-the-vault")

    def test_the_legacy_file_still_works_while_he_migrates(self):
        self.write(address="a@b.c", password="from-the-file")
        with mock.patch.object(mail, "stored_password", return_value=""):
            self.assertEqual(mail._config()["password"], "from-the-file")

    def test_an_explicit_environment_override_beats_both(self):
        self.write(address="a@b.c", password="from-the-file")
        with mock.patch.dict(os.environ, {"ALETHEIA_MAIL_PASSWORD": "from-env"}), \
                mock.patch.object(mail, "stored_password", return_value="from-the-vault"):
            self.assertEqual(mail._config()["password"], "from-env")

    def test_a_machine_without_a_vault_does_not_crash(self):
        with mock.patch("aletheia.secret_store.get", side_effect=RuntimeError("no DPAPI")):
            self.assertEqual(mail.stored_password(), "")

    def test_migration_seals_the_secret_and_strips_the_file(self):
        self.write(address="a@b.c", password="s3cret", imap_host="imap.x")
        vault = {}
        with mock.patch("aletheia.secret_store.available", return_value=(True, "ok")), \
                mock.patch("aletheia.secret_store.put",
                           side_effect=lambda n, s, **k: vault.__setitem__(n, s)), \
                mock.patch("aletheia.secret_store.get", side_effect=vault.get), \
                mock.patch.object(journal, "append"):
            result = mail.migrate_password_to_vault()
        self.assertTrue(result["moved"])
        self.assertEqual(vault[mail.SECRET_NAME], "s3cret")
        left = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertNotIn("password", left)
        self.assertEqual(left["address"], "a@b.c", "it kept the rest of the config")

    def test_migration_never_deletes_what_it_could_not_store(self):
        self.write(address="a@b.c", password="s3cret")
        with mock.patch("aletheia.secret_store.available", return_value=(True, "ok")), \
                mock.patch("aletheia.secret_store.put"), \
                mock.patch("aletheia.secret_store.get", return_value="something else"):
            result = mail.migrate_password_to_vault()
        self.assertFalse(result["moved"])
        self.assertIn("read back", result["reason"])
        self.assertIn("password", json.loads(self.config.read_text(encoding="utf-8")))

    def test_migration_is_idempotent_and_honest_when_there_is_nothing_to_do(self):
        self.write(address="a@b.c")
        with mock.patch("aletheia.secret_store.available", return_value=(True, "ok")):
            self.assertFalse(mail.migrate_password_to_vault()["moved"])


if __name__ == "__main__":
    unittest.main()
