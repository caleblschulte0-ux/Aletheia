import json
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from aletheia import core, journal, memory, notifications, plans, policy, tasks
from aletheia.fleet import REPO_ROOT


class MobileSurfaceCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        base=Path(self.tmp.name)
        patches=[
            mock.patch.object(journal,"JOURNAL_PATH",base/"j.jsonl"),
            mock.patch.object(tasks,"TASKS_DIR",base/"tasks"),
            mock.patch.object(plans,"PLANS_DIR",base/"plans"),
            mock.patch.object(memory,"MEMORY_DIR",base/"memory"),
            mock.patch.object(policy,"APPROVALS_DIR",base/"approvals"),
            mock.patch.object(policy,"HALT_PATH",base/"halt.json"),
            mock.patch.object(notifications,"NOTICES_DIR",base/"notices"),
        ]
        for p in patches: p.start(); self.addCleanup(p.stop)
        self.server=core.make_server(port=0); self.addCleanup(self.server.server_close)
        self.port=self.server.server_address[1]
        thread=threading.Thread(target=self.server.serve_forever,daemon=True); thread.start()
        self.addCleanup(self.server.shutdown)

    def test_mobile_html_and_js_are_served_by_existing_loopback_core(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/mobile.html") as r:
            body=r.read().decode("utf-8"); self.assertEqual(r.status,200)
        self.assertIn("Thea Mobile",body); self.assertIn("remote transport is not",body)
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/mobile.js") as r:
            js=r.read().decode("utf-8"); self.assertEqual(r.status,200)
        for endpoint in ("/api/state","/api/notifications","/api/approvals","/api/tasks","/api/schedules","/api/runtime","/api/command"):
            self.assertIn(endpoint,js)

    def test_the_buttons_actually_work_not_just_the_panels(self):
        """The page carries the local secret, so writes are not 401.

        Every read this page makes is open on loopback, so all five
        panels fill in whether or not the secret is wired up. Found by
        POSTing rather than by reading: mobile.js originally sent no
        secret at all, which meant Approve, Deny, HALT, Resume and the
        command box each failed while the page looked perfectly alive.
        Asserting on the served HTML and a real POST together is the
        only way that stays caught.
        """
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/mobile.html") as r:
            html = r.read().decode("utf-8")
        # The Core injects the secret into the page it serves on loopback.
        match = re.search(
            r'<meta name="aletheia-local" content="([^"]+)">', html)
        self.assertIsNotNone(match, "Core did not inject the local secret")
        secret = match.group(1)

        # and the script reads that tag back out rather than ignoring it
        js = (REPO_ROOT / "interface" / "mobile.js").read_text(encoding="utf-8")
        self.assertIn('meta[name="aletheia-local"]', js)
        self.assertIn("X-Aletheia-Local", js)

        # Without it: refused. This is the state the page shipped in.
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/command",
            data=json.dumps({"kind": "note", "text": "mobile write probe"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 401)

        # With it: through the ordinary gates, like every other surface.
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/command",
            data=json.dumps({"kind": "note", "text": "mobile write probe"}).encode(),
            headers={"Content-Type": "application/json",
                     "X-Aletheia-Local": secret}, method="POST")
        with urllib.request.urlopen(request) as r:
            self.assertEqual(r.status, 200)

    def test_mobile_does_not_add_network_listener_or_auth_bypass(self):
        with self.assertRaises(ValueError): core.make_server(host="0.0.0.0",port=0)
        html=(REPO_ROOT/"interface"/"mobile.html").read_text(encoding="utf-8")
        self.assertIn("127.0.0.1",html)
        self.assertNotIn("fetch('http://",html)
        self.assertNotIn('fetch("http://',html)


if __name__=="__main__": unittest.main()
