import json
import re
import subprocess
import unittest
from pathlib import Path

from aletheia.fleet import REPO_ROOT

EMAIL_RE=re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",re.I)


class PublicRepoPrivacyCase(unittest.TestCase):
    def test_private_runtime_roots_are_gitignored(self):
        ignore=(REPO_ROOT/".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("state/private/",ignore)
        self.assertIn("state/mail/",ignore)
        self.assertIn("cache/",ignore)

    def test_no_private_runtime_file_is_currently_tracked(self):
        result=subprocess.run(["git","ls-files","state/private","state/mail","cache"],cwd=REPO_ROOT,text=True,capture_output=True,check=True)
        self.assertEqual(result.stdout.strip(),"",f"private runtime path is tracked: {result.stdout}")

    def test_public_people_memory_contains_no_email_address(self):
        path=REPO_ROOT/"memory"/"people.json"
        text=path.read_text(encoding="utf-8")
        json.loads(text)  # must remain valid JSON
        self.assertIsNone(EMAIL_RE.search(text),"public memory/people.json contains an email-like personal address; use private contacts")

    def test_private_store_rule_is_documented_in_mail_and_stateio(self):
        mail=(REPO_ROOT/"aletheia"/"mail.py").read_text(encoding="utf-8")
        stateio=(REPO_ROOT/"aletheia"/"stateio.py").read_text(encoding="utf-8")
        self.assertIn("state/mail",mail)
        self.assertIn("private_dir",stateio)


if __name__=="__main__": unittest.main()
