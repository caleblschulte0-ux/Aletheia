"""Isolation for conversation and calendar tests: every store they touch, redirected.

Conversations reach nine stores (approvals, grants, claims, the channel-neutral
threads, mail poll state, events, contacts, the calendar, notifications) and
several bind their paths at import time, so each test gets its own directory
for all of them, a machine key of its own, his timezone pinned, and neither a
rehearsal nor a frontier-off flag leaking in from the environment.
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (authority, calendar, communications, contacts, events, journal, mail, memory,
                      notifications, policy)

TZ = "America/Chicago"


class Isolated(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = root = Path(tmp.name)
        env = {"ALETHEIA_PRIVATE_STATE": str(root / "private"), "ALETHEIA_MACHINE_KEY": str(root / "machine.key"),
               "ALETHEIA_TZ": TZ}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("ALETHEIA_REHEARSAL", "ALETHEIA_FRONTIER_OFF"):
            os.environ.pop(name, None)
        base = root / "private"
        # A fresh private root is under his 2026-09-24 outward-mail hold (no
        # file means on). These tests are about what a conversation does once
        # he has lifted it; the hold itself is tested in test_outward_mail_is_on_hold.
        from aletheia import mail as _mail
        _mail.lift_hold(via="test")
        for module, attr, value in (
                (journal, "JOURNAL_PATH", root / "journal.jsonl"),
                (policy, "APPROVALS_DIR", root / "approvals"),
                (policy, "HALT_PATH", root / "halt.json"),
                (authority, "GRANTS_DIR", base / "authority" / "grants"),
                (authority, "CLAIMS_DIR", base / "authority" / "claims"),
                (communications, "BASE_DIR", base / "communications"),
                (communications, "THREADS_DIR", base / "communications" / "threads"),
                (communications, "MESSAGES_DIR", base / "communications" / "messages"),
                (communications, "EXPECT_DIR", base / "communications" / "expectations"),
                (calendar, "CALENDAR_DIR", base / "calendar" / "events"),
                (contacts, "CONTACTS_DIR", base / "contacts"),
                (notifications, "NOTICES_DIR", base / "notifications"),
                (events, "EVENTS_DIR", base / "events"),
                (events, "WATCHERS_DIR", base / "watchers"),
                (memory, "MEMORY_DIR", base / "memory"),
                (mail, "MAIL_DIR", root / "mail")):
            p = mock.patch.object(module, attr, value)
            p.start()
            self.addCleanup(p.stop)
        (root / "approvals").mkdir(parents=True, exist_ok=True)
        # The live mail account is never reachable from a test.
        guard = mock.patch.object(mail, "SmtpImapTransport",
                                  side_effect=AssertionError("a test reached for the real mail account"))
        guard.start()
        self.addCleanup(guard.stop)
        self.now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)

    # ---- helpers -------------------------------------------------------------------

    def contact(self, name="Dana Reyes", email="dana@harborview-rentals.test", alias="the property manager"):
        return contacts.create(name.lower().replace(" ", "-"), name, emails=[email], aliases=[alias])

    def approve(self, approval_id, via="operator-cli"):
        return policy.decide(approval_id, "APPROVED", via=via, because="he said yes")

    def poll(self, transport):
        return mail.poll_events(limit=50, transport=transport)

    def later(self, **delta) -> dt.datetime:
        return self.now + dt.timedelta(**delta)
