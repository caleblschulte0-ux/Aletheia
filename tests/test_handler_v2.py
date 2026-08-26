import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import context, handler


REG={"capabilities":[
    {"id":"a","status":"AVAILABLE"},
    {"id":"b","status":"NOT_BUILT","caller":"ticket"},
    {"id":"c","status":"AVAILABLE"},
]}


class HandlerCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        p=mock.patch.object(handler,"REQUESTS_DIR",root/"requests"); p.start(); self.addCleanup(p.stop)
        p=mock.patch.object(context,"REFS_DIR",root/"refs"); p.start(); self.addCleanup(p.stop)

    def test_ready_fallback_beats_blocked_primary(self):
        r=handler.create("x",intent="do it",candidates=[
            {"id":"primary","required_capabilities":["b"]},
            {"id":"fallback","required_capabilities":["a"]},
        ],registry=REG,materialize_gaps=False)
        self.assertEqual(r["state"],"READY"); self.assertEqual(r["selected_path"],"fallback")

    def test_least_blocked_path_selected_for_gap_work(self):
        reg={"capabilities":[{"id":"x","status":"NOT_BUILT","caller":"ticket"},{"id":"y","status":"NOT_BUILT","caller":"ticket"}]}
        r=handler.create("x",intent="do it",candidates=[
            {"id":"two","required_capabilities":["x","y"]},
            {"id":"one","required_capabilities":["x"]},
        ],registry=reg,materialize_gaps=False)
        self.assertEqual(r["selected_path"],"one"); self.assertEqual(r["state"],"BLOCKED_CAPABILITY")

    def test_success_without_evidence_waits_for_verification(self):
        handler.create("x",intent="do it",required_capabilities=["a"],registry=REG)
        r=handler.record_attempt("x",outcome="SUCCEEDED")
        self.assertEqual(r["state"],"AWAITING_VERIFICATION")
        self.assertEqual(handler.verify("x",evidence="observed result")["state"],"COMPLETED")

    def test_retry_is_bounded_and_due(self):
        now=dt.datetime(2026,8,26,20,tzinfo=dt.timezone.utc)
        handler.create("x",intent="do it",required_capabilities=["a"],registry=REG,max_attempts=2)
        first=handler.record_attempt("x",outcome="FAILED",failure_code="transport",now=now)
        self.assertEqual(first["state"],"RETRY_SCHEDULED")
        early=handler.refresh("x",registry=REG,now=now+dt.timedelta(seconds=1))
        self.assertEqual(early["state"],"RETRY_SCHEDULED")
        due=dt.datetime.fromisoformat(first["next_retry_at"].replace("Z","+00:00"))
        ready=handler.refresh("x",registry=REG,now=due+dt.timedelta(seconds=1))
        self.assertEqual(ready["state"],"READY")
        terminal=handler.record_attempt("x",outcome="FAILED",failure_code="transport",now=due+dt.timedelta(seconds=2))
        self.assertEqual(terminal["state"],"FAILED_TERMINAL")

    def test_waiting_external_requires_explicit_resume(self):
        handler.create("x",intent="wait",required_capabilities=["a"],registry=REG)
        self.assertEqual(handler.record_attempt("x",outcome="WAITING_EXTERNAL")["state"],"WAITING_EXTERNAL")
        self.assertEqual(handler.refresh("x",registry=REG)["state"],"WAITING_EXTERNAL")
        self.assertEqual(handler.resume_external("x")["state"],"READY")

    def test_context_resolution_refuses_ambiguity(self):
        context.remember("r1",kind="person",value="bob",label="Bob")
        context.remember("r2",kind="person",value="sam",label="Sam")
        with self.assertRaises(LookupError): handler.create("x",intent="call him",required_capabilities=[],references=[{"kind":"person"}],registry=REG)

    def test_evidence_can_complete_success_immediately(self):
        handler.create("x",intent="do it",required_capabilities=["a"],registry=REG)
        done=handler.record_attempt("x",outcome="SUCCEEDED",evidence="receipt 123")
        self.assertEqual(done["state"],"COMPLETED")


if __name__=="__main__": unittest.main()
