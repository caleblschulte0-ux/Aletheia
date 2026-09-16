"""The general browser loop's rules, without a browser.

The torture suite (`test_browser_loop_torture`) drives real pages. This
holds the parts that must stay true whatever a page does: the vocabulary
knows no job, a control that sends something is never a harmless click,
the manual-only floor cannot be lifted by a learned skill, the general
skill types only the goal's own inputs, and a submission is never pressed
twice without proof the first press failed - through the REAL press path.
"""
from __future__ import annotations

import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (agent_session, browse, browser_loop, browser_mission as bm, journal,
                      page_state as ps, policy, site_skills, tools, webtask)

REPO = Path(__file__).resolve().parents[1]


def t(role, label, **extra):
    return {"role": role, "label": label, **extra}


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        (d / "approvals").mkdir()
        (d / "webtasks").mkdir()
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)})
        env.start()
        self.addCleanup(env.stop)
        for target, attr, value in ((journal, "JOURNAL_PATH", d / "j.jsonl"),
                                    (policy, "APPROVALS_DIR", d / "approvals"),
                                    (policy, "HALT_PATH", d / "halt.json"),
                                    (webtask, "runs_dir", lambda: d / "webtasks")):
            patch = mock.patch.object(target, attr, value)
            patch.start()
            self.addCleanup(patch.stop)


class TheVocabularyIsGeneral(unittest.TestCase):
    def test_no_job_state_and_no_job_code_underneath(self):
        self.assertNotIn("JOB_POST", ps.STATES)
        self.assertNotIn("APPLICATION", ps.STATES)
        job_modules = {"job_skill", "apply_run", "campaign", "jobs", "applications", "apply"}
        for name in ("browser_loop", "page_state", "browser_mission", "site_skills"):
            tree = ast.parse((REPO / "aletheia" / f"{name}.py").read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    imported |= {a.name for a in node.names} | {str(node.module or "").rsplit(".", 1)[-1]}
                elif isinstance(node, ast.Import):
                    imported |= {a.name.rsplit(".", 1)[-1] for a in node.names}
            with self.subTest(module=name):
                self.assertEqual(imported & job_modules, set(), f"{name} imports job code")


class PagesAreClassifiedFromWhatTheyShow(unittest.TestCase):
    def state(self, **obs):
        return ps.classify(obs)["state"]

    def test_the_states(self):
        self.assertEqual(self.state(text="We are open 9 to 5.", targets=[t("link", "Hours")]), ps.CONTENT)
        self.assertEqual(self.state(text="Contact", targets=[t("textbox", "Name"), t("button", "Send")]),
                         ps.FORM)
        self.assertEqual(self.state(text="Step 2 of 4", targets=[t("textbox", "City"), t("button", "Next")]),
                         ps.MULTI_PAGE_WIZARD)
        self.assertEqual(self.state(text="Sign in", targets=[t("textbox", "Email"), t("password", "Password"),
                                                             t("button", "Sign in")]), ps.ACCOUNT_LOGIN)
        self.assertEqual(self.state(text="Create your account", targets=[
            t("textbox", "Email"), t("password", "Password"), t("password", "Confirm password"),
            t("button", "Create account")]), ps.ACCOUNT_SIGNUP)
        self.assertEqual(self.state(text="We emailed you a verification code.",
                                    targets=[t("textbox", "Code"), t("button", "Verify")]),
                         ps.EMAIL_VERIFICATION)
        self.assertEqual(self.state(text="We texted a code to your phone. Enter the code.",
                                    targets=[t("textbox", "Code"), t("button", "Verify")]),
                         ps.SMS_VERIFICATION)
        self.assertEqual(self.state(text="Please review your request", targets=[t("button", "Submit request")]),
                         ps.REVIEW)
        self.assertEqual(self.state(text="Thank you. Your request has been received."), ps.SUCCESS)
        self.assertEqual(self.state(text="Please verify you are a human", targets=[t("textbox", "Email")]),
                         ps.CAPTCHA)
        self.assertEqual(self.state(text="Hello", status=503), ps.ERROR)
        self.assertEqual(self.state(text="Internal Server Error"), ps.ERROR)
        self.assertEqual(self.state(text=""), ps.UNKNOWN)

    def test_a_captcha_widget_outranks_everything(self):
        self.assertEqual(ps.classify({"text": "Apply", "captcha": "recaptcha",
                                      "targets": [t("textbox", "Name")]})["state"], ps.CAPTCHA)


class AControlIsJudgedByWhatPressingItDoes(unittest.TestCase):
    def test_kinds(self):
        k = ps.control_kind
        self.assertEqual(k("Next"), ps.PROGRESS)
        self.assertEqual(k("Continue ›"), ps.PROGRESS)
        self.assertEqual(k("Submit application", on_form=True), ps.COMMIT)
        self.assertEqual(k("Send message"), ps.COMMIT)
        self.assertEqual(k("Buy now"), ps.SPEND)
        self.assertEqual(k("Complete purchase", on_form=True), ps.SPEND)
        self.assertEqual(k("Create account"), ps.CREATE_ACCOUNT)
        self.assertEqual(k("Sign up"), ps.CREATE_ACCOUNT)
        self.assertEqual(k("Sign in"), ps.SIGN_IN)
        self.assertEqual(k("Back"), ps.BACK)
        self.assertEqual(k("About us", role="link"), ps.NAVIGATE)
        self.assertEqual(k("Cancel my membership", role="link"), ps.COMMIT)

    def test_an_unfamiliar_button_on_a_form_is_a_commit(self):
        """"Join the list" says no committing word and is a submit button."""
        for label in ("Join the list", "Let's go", "Count me in", ""):
            with self.subTest(label=label):
                self.assertEqual(ps.control_kind(label, on_form=True), ps.COMMIT)
        self.assertEqual(ps.control_kind("Add another", on_form=True), ps.OTHER)
        self.assertEqual(ps.control_kind("Join the list", on_form=False), ps.OTHER)


class SiteSkillsAreDataAndTheFloorHolds(Isolated):
    def test_the_manual_only_floor_cannot_be_lifted_by_a_learned_skill(self):
        site_skills.learn("https://www.linkedin.com/jobs/view/1", state=ps.FORM)
        learned = site_skills.learned("linkedin.com")
        learned["mode"] = site_skills.AUTONOMOUS
        path = site_skills._path("linkedin.com")
        from aletheia import stateio
        stateio.write_json_atomic(path, learned)
        self.assertEqual(site_skills.for_domain("https://linkedin.com/x")["mode"], site_skills.MANUAL_ONLY)
        self.assertEqual(site_skills.for_domain("https://uk.indeed.com/x")["mode"], site_skills.MANUAL_ONLY)
        self.assertEqual(site_skills.for_domain("https://clinic.example/x")["mode"], site_skills.AUTONOMOUS)

    def test_an_alias_learned_on_one_goal_serves_another(self):
        site_skills.learn("https://clinic.example/a", aliases={"Given name": "first_name"})
        site = site_skills.for_domain("https://clinic.example/other")
        self.assertEqual(browser_loop.match_key("Given name *", {"first_name": "Caleb"}, site), "first_name")
        # and a different site does not inherit it
        other = site_skills.for_domain("https://elsewhere.example/")
        self.assertIsNone(browser_loop.match_key("Given name *", {"first_name": "Caleb"}, other))

    def test_ats_families_are_seeded_as_optimisations(self):
        self.assertEqual(site_skills.for_domain("https://acme.wd5.myworkdayjobs.com/en-US/x")["families"],
                         ["workday"])
        self.assertEqual(site_skills.for_domain("https://unknown-employer.example")["families"], [])


class TheGeneralSkillTypesOnlyHisInputs(unittest.TestCase):
    def test_labels_map_to_inputs_and_the_rest_are_questions(self):
        obs = {"url": "https://x.example/f", "targets": [
            {"id": "t1", "role": "textbox", "label": "Full name *", "required": True},
            {"id": "t2", "role": "textbox", "label": "Phone *", "required": True},
            {"id": "t3", "role": "textbox", "label": "Company name"},
            {"id": "t4", "role": "combobox", "label": "Preferred day", "options": ["Monday", "Tuesday"]}],
            "_refs": {"t1": "#a", "t2": "#b", "t3": "#c", "t4": "#d"}}
        record = {"inputs": {"name": "Caleb Schulte", "preferred day": "tuesday"}}
        with mock.patch("aletheia.profile.known", return_value={"phone": "(512) 555-0134"}):
            plan = browser_loop.GENERAL.plan(obs, record, {})
        typed = {item["selector"]: item["value"] for item in plan["fill"]}
        self.assertEqual(typed, {"#a": "Caleb Schulte", "#d": "Tuesday"})
        self.assertEqual(plan["ask"], ["Phone *"], "a profile fact is not an input of this goal")
        self.assertNotIn("#c", typed, "'name' never answers 'company name'")


class TheSubmissionInvariant(Isolated):
    def record(self):
        return bm.open_mission("send the form", "https://x.example/f", inputs={})

    def test_only_proof_of_failure_allows_a_second_press(self):
        for verdict, allowed in (("pending", False), ("confirmed", False), ("submitted, unconfirmed", False),
                                 ("error", False), ("rejected", True), ("not_pressed", True)):
            with self.subTest(verdict=verdict):
                record = self.record()
                record["submits"] = []
                bm.begin_submit(record, button="Send", url="https://x.example/f")
                record["submits"][-1]["verdict"] = verdict
                ok, why = bm.may_submit(record, button="Send", url="https://x.example/f")
                self.assertEqual(ok, allowed, why)
                if not allowed:
                    with self.assertRaises(bm.DuplicateSubmission):
                        bm.begin_submit(record, button="Send", url="https://x.example/f")

    def test_a_different_submission_of_the_same_mission_is_its_own(self):
        record = self.record()
        bm.begin_submit(record, button="Create account", url="https://x.example/signup")
        bm.end_submit(record, verdict="confirmed")
        self.assertTrue(bm.may_submit(record, button="Submit application", url="https://x.example/apply")[0])
        self.assertFalse(bm.may_submit(record, button="Create account", url="https://x.example/signup")[0])

    def test_submit_clicked_is_on_disk_before_the_press(self):
        record = self.record()
        bm.begin_submit(record, button="Send", url="https://x.example/f")
        on_disk = bm.load(record["id"])
        self.assertEqual(on_disk["last_checkpoint"], bm.SUBMIT_CLICKED)
        self.assertEqual(on_disk["submits"][-1]["verdict"], "pending")


class TheRealPressPathEnforcesIt(Isolated):
    """Through `webtask.commit` - the path the Core's beat presses with -
    with a stand-in presser and no browser."""

    def gate(self):
        record = bm.open_mission("send the form", "https://x.example/f", inputs={})
        route = [{"action": "type", "selector": "#m", "value": "hi"}]
        record.update({"route": route, "gates": 1, "webtask_run": record["id"] + "--g1",
                       "gate": {"button": "Send", "kind": ps.COMMIT, "url": "https://x.example/f"}})
        action = browse.approval_action("https://x.example/f", route + [{"action": "click", "selector": "#go"}])
        approval = f"{record['webtask_run']}-commit-x"
        if policy.request(approval, action, reason="t", consequence="t",
                          reversible=False)["state"] == "PENDING":
            policy.decide(approval, "APPROVED", via="test")
        record["approval"] = approval
        bm.stop_at(record, bm.AWAITING_APPROVAL, {"kind": "SUBMIT_APPROVAL", "say": "waiting"})
        from aletheia import stateio
        stateio.write_json_atomic(webtask._record_path(record["webtask_run"]), {
            "id": record["webtask_run"], "goal": "send the form", "state": webtask.COMMIT,
            "approval": approval, "button": "Send", "button_selector": "#go", "typed": route,
            "attached": [], "replay_from": "https://x.example/f", "url": "https://x.example/f",
            "mission": record["id"]})
        return record

    def test_a_confirmed_press_finishes_the_mission_and_a_crash_mid_press_blocks_another(self):
        record = self.gate()
        done = browser_loop.commit(record["id"], presser=lambda r: {
            "verdict": "confirmed", "evidence": "Thank you, received", "url": "https://x.example/ok"})
        self.assertEqual(done["state"], bm.DONE)
        self.assertEqual([c["name"] for c in done["checkpoints"]][-3:],
                         [bm.SUBMIT_CLICKED, bm.RECEIPT_VERIFIED, bm.FINISHED])

        # A second gate for the SAME button, as if the mission were reset:
        record = self.gate()
        record = bm.load(record["id"])
        self.assertEqual(len(record["submits"]), 1)
        with self.assertRaises(webtask.WebTaskError) as caught:
            browser_loop.commit(record["id"], presser=lambda r: self.fail("pressed twice"))
        self.assertIn("pressed", str(caught.exception))

    def test_a_press_that_dies_is_not_proof(self):
        record = self.gate()

        def dies(_):
            raise RuntimeError("browser crashed after the click")
        with self.assertRaises(RuntimeError):
            browser_loop.commit(record["id"], presser=dies)
        after = bm.load(record["id"])
        self.assertEqual(after["state"], bm.SUBMITTED_UNCONFIRMED)
        self.assertFalse(bm.may_submit(after, button="Send", url="https://x.example/f")[0])

    def test_a_server_error_after_the_press_is_not_proof(self):
        record = self.gate()
        after = browser_loop.commit(record["id"], presser=lambda r: {
            "verdict": "rejected", "evidence": "502 Bad Gateway", "url": "https://x.example/f"})
        self.assertEqual(after["submits"][-1]["verdict"], "error")
        self.assertFalse(bm.may_submit(after, button="Send", url="https://x.example/f")[0])


class TheBrokerRunsReadsAndHandsOffTheRest(unittest.TestCase):
    def test_observe_runs_pursue_is_handed_off_and_spending_is_refused(self):
        catalog = tools.catalog()
        broker = agent_session.Broker(catalog, halted=lambda: False)
        check = lambda name, args: broker.check(agent_session.ToolRequest(name, args))  # noqa: E731
        self.assertEqual(check("browser.observe", {"url": "https://clinic.example"}).verdict,
                         agent_session.RUN)
        self.assertEqual(check("browser.missions", {}).verdict, agent_session.RUN)
        self.assertEqual(check("browser.pursue", {"goal": "request an appointment",
                                                  "url": "https://clinic.example"}).verdict,
                         agent_session.HANDOFF)
        self.assertEqual(check("browser.act", {"mission": "bm-x", "act": "click",
                                               "target": "t1"}).verdict, agent_session.HANDOFF)
        self.assertEqual(check("browser.code", {"mission": "bm-x", "code": "123456"}).verdict,
                         agent_session.HANDOFF)
        refused = check("browser.pursue", {"goal": "buy the monitor", "url": "https://shop.example"})
        self.assertEqual(refused.verdict, agent_session.REFUSED)
        self.assertTrue(refused.permanent)


class SpendingIsRefusedBeforeABrowserOpens(Isolated):
    def test_a_spending_goal(self):
        with mock.patch.object(browse, "_Session", side_effect=AssertionError("opened a browser")):
            record = browser_loop.pursue("buy a new monitor", "https://shop.example/monitor")
        self.assertEqual(record["state"], bm.REFUSED)
        self.assertEqual(record["boundary"]["kind"], "SPENDING")


if __name__ == "__main__":
    unittest.main()
