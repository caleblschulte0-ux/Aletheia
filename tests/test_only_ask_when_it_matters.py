"""Only ask him when the press actually commits something.

Fixtures shaped like the pages his job loop really met on 2026-09-19, the
morning thirty-eight approvals were waiting and ten of them asked him to
bless a press that sends nothing: a Workday "Create Account", a careers
site's "About Us" inside a page with a search box, "Show More Options",
"Search submit", a genuine Submit on a filled application, and a review
page's Confirm.

Both directions are asserted in every case, because only one of them is
about his attention and the other is about his name on an application:

    the junk ones raise NO approval, and
    every genuinely committing control still raises exactly one, still
    bound to the hash of the route, still pressable once.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (browse, browser_loop, browser_mission as bm, journal, needs_you,
                      page_state as ps, policy, webtask)


class FakePage:
    """Enough page for `_gate`: it reads `.url` and tries the form reader."""

    def __init__(self, url):
        self.url = url

    def title(self):
        return ""


def obs(url, text, targets, *, filled_here=False, title=""):
    """An observation the way `browser_loop.look` builds one, classified by
    the real classifier so the test exercises the rule and not a copy."""
    rows = []
    refs = {}
    for index, row in enumerate(targets, start=1):
        row = {"id": f"t{index}", **row}
        rows.append(row)
        refs[row["id"]] = f"#sel{index}"
    seen = {"url": url, "title": title, "text": text, "targets": rows, "_refs": refs,
            "filled_here": filled_here, "status": None}
    understood = ps.classify(seen)
    seen.update({"state": understood["state"], "evidence": understood["evidence"],
                 "controls": understood["controls"]})
    return seen


# ---- the pages -----------------------------------------------------------------

#: The live example, verbatim: approval `bm-apply-for-this-job-8bd36fb18a--g1-
#: commit-8db96ff9ba8e`, capability web.commit, "apply for this job — press
#: 'About Us' on https://jobs.grainger.com/job/MORGANTOWN-Account-Manager..."
GRAINGER = ("https://jobs.grainger.com/job/MORGANTOWN-Account-Manager%2C-"
            "Manufacturing-WV-26508/1420081900/?feedId=400000")


def grainger_posting():
    """A careers-site job posting: the site's own search boxes in the header,
    the site's own navigation drawn as <a role=button>."""
    return obs(GRAINGER, "Account Manager, Manufacturing. Morgantown, WV. "
                         "Search by Keyword Search by Location",
               [{"role": "textbox", "label": "Search by Keyword"},
                {"role": "textbox", "label": "Search by Location"},
                {"role": "button", "label": "Search", "type": "submit", "nav": True},
                {"role": "button", "label": "About Us", "href": "/content/About-Us/", "nav": True},
                {"role": "button", "label": "Products", "href": "/products", "nav": True},
                {"role": "button", "label": "Language", "haspopup": True, "nav": True},
                {"role": "link", "label": "Apply Now", "href": "/job/apply/1420081900"}],
               title="Account Manager, Manufacturing")


def sonepar_posting():
    """Sonepar's posting: a filter panel whose expander says so in ARIA."""
    return obs("https://career.sonepar.com/job/Sacramento-Account-Manager-CA-95834/",
               "Account Manager. Sacramento, CA. Search by Keyword",
               [{"role": "textbox", "label": "Search by Keyword"},
                {"role": "button", "label": "Show More Options", "expanded": False},
                {"role": "link", "label": "Apply now", "href": "/apply/1437721733"}])


def hubspot_posting():
    """HubSpot's posting: the search form's button is NAMED "Search submit"."""
    return obs("https://www.hubspot.com/careers/jobs/6244731",
               "Customer Success Manager. Search jobs",
               [{"role": "textbox", "label": "Search jobs"},
                {"role": "button", "label": "Search submit", "type": "submit", "nav": True},
                {"role": "link", "label": "Apply", "href": "/careers/jobs/6244731/apply"}])


def workday_signup():
    """Workday's account wall, after she filled it: a new password twice."""
    return obs("https://crowdstrike.wd5.myworkdayjobs.com/en-US/crowdstrikecareers/register",
               "Create Account. Email Address. Password. Verify New Password.",
               [{"role": "textbox", "label": "Email Address", "value": "openrangeinteractive@gmail.com"},
                {"role": "password", "label": "Password", "value": "(set)"},
                {"role": "password", "label": "Verify New Password", "value": "(set)"},
                {"role": "checkbox", "label": "I agree to the terms", "checked": True},
                {"role": "button", "label": "Create Account", "type": "submit", "in_form": True},
                {"role": "button", "label": "About Workday", "href": "/about", "nav": True}],
               filled_here=True, title="Create Account")


def filled_application():
    """A real application, filled: his name, his resume - and the site's
    header sitting right above the form."""
    return obs("https://jobs.example.com/apply/4471",
               "Apply for Account Manager. First name. Last name. Resume.",
               [{"role": "textbox", "label": "First name", "value": "Caleb"},
                {"role": "textbox", "label": "Last name", "value": "Schulte"},
                {"role": "file", "label": "Resume/CV", "value": "Caleb_Schulte_Resume.pdf"},
                {"role": "button", "label": "About Us", "href": "/about-us", "nav": True},
                {"role": "button", "label": "Show More Options", "expanded": False},
                {"role": "button", "label": "Search submit", "type": "submit", "nav": True},
                {"role": "button", "label": "Submit Application", "type": "submit", "in_form": True}],
               filled_here=True)


def review_page():
    """Everything answered, one final button, nothing left to fill."""
    return obs("https://jobs.example.com/apply/4471/review",
               "Please review your application before you submit. Caleb Schulte.",
               [{"role": "checkbox", "label": "I certify the above is accurate", "checked": True},
                {"role": "button", "label": "Back", "type": "button"},
                {"role": "button", "label": "Confirm", "type": "submit", "in_form": True}],
               filled_here=True)


def prefilled_stranger():
    """A page she typed NOTHING into, whose values the site put there, and
    whose only button says nothing either way."""
    return obs("https://careers.example.org/opening/12",
               "Account Manager. Location.",
               [{"role": "combobox", "label": "Location", "value": "Sioux Falls"},
                {"role": "button", "label": "Weiter", "type": "submit", "in_form": True}])


# ---- the junk ones are not approvals anymore -----------------------------------

class TheSiteOwnFurnitureIsNotACommit(unittest.TestCase):
    def kinds(self, page):
        return {t["label"]: browser_loop._kind(t, page) for t in page["targets"]
                if t["role"] in ps.PRESS_ROLES}

    def test_the_live_example_about_us_on_a_grainger_posting(self):
        """`bm-apply-for-this-job-8bd36fb18a--g1-commit-8db96ff9ba8e`, the
        approval he was shown at 08:03 on 2026-09-19. Pressing "About Us"
        submits nothing, and it must never be a web.commit again."""
        page = grainger_posting()
        kinds = self.kinds(page)
        self.assertEqual(kinds["About Us"], ps.NAVIGATE)
        self.assertEqual(kinds["Products"], ps.NAVIGATE)
        self.assertEqual(kinds["Language"], ps.OTHER)
        self.assertEqual(kinds["Search"], ps.OTHER)
        self.assertNotIn(ps.COMMIT, browser_loop.controls(page))
        self.assertIsNone(browser_loop.final_control(page, "apply for this job"))

    def test_a_disclosure_that_the_page_itself_calls_a_disclosure(self):
        page = sonepar_posting()
        self.assertEqual(self.kinds(page)["Show More Options"], ps.OTHER)
        self.assertNotIn(ps.COMMIT, browser_loop.controls(page))

    def test_running_the_sites_search_is_reading_even_when_it_says_submit(self):
        page = hubspot_posting()
        self.assertEqual(self.kinds(page)["Search submit"], ps.OTHER)
        self.assertNotIn(ps.COMMIT, browser_loop.controls(page))
        for label in ("Search", "Search submit", "Search jobs", "Find", "Filter"):
            with self.subTest(label=label):
                self.assertEqual(ps.control_kind(label, on_form=True, sendable=True), ps.OTHER)

    def test_the_junk_ones_are_not_commits_even_on_a_page_holding_his_answers(self):
        """The "About Us link inside a form" case: the page CAN send something,
        and a link to another page still is not the thing that sends it."""
        kinds = self.kinds(filled_application())
        self.assertEqual(kinds["About Us"], ps.NAVIGATE)
        self.assertEqual(kinds["Show More Options"], ps.OTHER)
        self.assertEqual(kinds["Search submit"], ps.OTHER)
        self.assertEqual(kinds["Submit Application"], ps.COMMIT)

    def test_a_posting_with_only_search_boxes_holds_nothing_to_send(self):
        self.assertFalse(ps.could_send(grainger_posting()))
        self.assertFalse(ps.could_send(hubspot_posting()))
        self.assertTrue(ps.could_send(filled_application()))
        self.assertTrue(ps.could_send(workday_signup()))


class TheConservativeDefaultIsKept(unittest.TestCase):
    def test_an_unknown_button_on_a_page_holding_his_answers_is_still_a_commit(self):
        for label in ("Join the list", "Let's go", "Count me in", ""):
            with self.subTest(label=label):
                self.assertEqual(ps.control_kind(label, on_form=True, sendable=True), ps.COMMIT)
                self.assertEqual(ps.control_kind(label, on_form=True, sendable=False), ps.OTHER)

    def test_a_label_that_commits_commits_wherever_it_sits(self):
        """Evidence may only ever make an unknown control harmless. It never
        makes a committing word harmless - not in a header, not as a link."""
        chrome = {"nav": True, "href": "/somewhere", "expanded": False}
        for label, kind in (("Submit application", ps.COMMIT), ("Send message", ps.COMMIT),
                            ("Confirm", ps.COMMIT), ("Cancel my membership", ps.COMMIT),
                            ("Create account", ps.CREATE_ACCOUNT), ("Sign up", ps.CREATE_ACCOUNT),
                            ("Buy now", ps.SPEND), ("Complete purchase", ps.SPEND),
                            ("Submit order", ps.SPEND), ("Add to cart", ps.SPEND)):
            with self.subTest(label=label):
                self.assertEqual(ps.control_kind(label, target=dict(chrome), sendable=False), kind)
                self.assertEqual(ps.control_kind(label, role="link", target=dict(chrome),
                                                 sendable=False), kind)

    def test_the_old_behaviour_survives_where_nobody_looked_at_the_page(self):
        """`sendable=None` is "nobody asked", and it must read as it always
        did, so a caller holding only a label is not quietly loosened."""
        self.assertEqual(ps.control_kind("Join the list", on_form=True), ps.COMMIT)
        self.assertEqual(ps.control_kind("Join the list", on_form=False), ps.OTHER)


# ---- the gate: one approval, hash-bound, one press ------------------------------

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
        self.dir = d

    def pending(self):
        return [a for a in policy.all_approvals() if a.get("state") == "PENDING"]

    def gate(self, page, *, goal="apply for this job", filled=True, skill=None):
        """`_gate` on a fixture, with a mission whose route says whether she
        put any of his answers on the page."""
        record = bm.open_mission(goal, page["url"], inputs={})
        route = ([{"action": "type", "selector": "#sel1", "value": "Caleb"}] if filled else [])
        record["route"] = list(route)
        return browser_loop._gate(None, FakePage(page["url"]), page, record, goal,
                                  list(route), [], skill=skill)


class TheJunkOnesNeverReachHim(Isolated):
    def test_a_posting_page_raises_nothing_and_stalls_at_a_boundary_instead(self):
        for name, page in (("grainger", grainger_posting()), ("sonepar", sonepar_posting()),
                           ("hubspot", hubspot_posting())):
            with self.subTest(page=name):
                self.assertIsNone(self.gate(page, filled=False),
                                  "there is no final button on a job posting")
        self.assertEqual(self.pending(), [], "no approval was written for any of them")

    def test_a_press_she_cannot_judge_on_a_page_she_never_filled_is_a_boundary(self):
        """An approval is for a decision he can make. "Press this thing I do
        not understand" is not one, so it stops at NO_WAY_FORWARD."""
        stopped = self.gate(prefilled_stranger(), filled=False)
        self.assertIsNotNone(stopped)
        self.assertEqual(stopped["state"], bm.NEEDS_YOU)
        self.assertEqual(stopped["boundary"]["kind"], "NO_WAY_FORWARD")
        self.assertEqual(self.pending(), [])
        # ...and the same page, once she has put his answers into it, is the
        # conservative default again.
        raised = self.gate(prefilled_stranger(), filled=True)
        self.assertEqual(raised["state"], bm.AWAITING_APPROVAL)
        self.assertEqual(len(self.pending()), 1)


class TheCommittingOnesStillAsk(Isolated):
    def test_a_genuine_submit_on_a_filled_application(self):
        page = filled_application()
        record = self.gate(page)
        self.assertEqual(record["state"], bm.AWAITING_APPROVAL)
        self.assertEqual(record["gate"]["button"], "Submit Application")
        self.assertEqual(record["boundary"]["kind"], "SUBMIT_APPROVAL")
        waiting = self.pending()
        self.assertEqual(len(waiting), 1, "exactly one approval, never two")
        self.assertEqual(waiting[0]["capability"], "web.commit")
        self.assertFalse(waiting[0]["reversible"])

    def test_the_approval_is_bound_to_the_hash_of_this_exact_route(self):
        page = filled_application()
        record = self.gate(page)
        approval = policy.load(record["approval"])
        action = browse.approval_action(page["url"], [
            {"action": "type", "selector": "#sel1", "value": "Caleb"},
            {"action": "click", "selector": "#sel7"}])
        self.assertEqual(approval["requested_action"], action)
        self.assertTrue(record["approval"].endswith(webtask._digest(action)))
        self.assertTrue(record["gate"]["digest"], "the page he saw is fingerprinted too")

    def test_a_workday_create_account_is_still_its_own_gate(self):
        record = self.gate(workday_signup(), goal="apply for this job")
        self.assertEqual(record["gate"]["kind"], ps.CREATE_ACCOUNT)
        self.assertEqual(record["boundary"]["kind"], "ACCOUNT_CREATION_APPROVAL")
        self.assertEqual(len(self.pending()), 1)

    def test_a_review_pages_confirm(self):
        page = review_page()
        self.assertEqual(page["state"], ps.REVIEW)
        record = self.gate(page)
        self.assertEqual(record["gate"]["button"], "Confirm")
        self.assertEqual(len(self.pending()), 1)

    def test_one_press_only_and_never_a_second_without_proof(self):
        page = filled_application()
        record = self.gate(page)
        bm.begin_submit(record, button="Submit Application", url=page["url"])
        with self.assertRaises(bm.DuplicateSubmission):
            bm.begin_submit(record, button="Submit Application", url=page["url"])
        self.assertFalse(bm.may_submit_here(record, button="Submit Application", url=page["url"])[0])

    def test_spending_is_still_refused_and_never_gated(self):
        page = obs("https://shop.example/checkout", "Order total: $21.40",
                   [{"role": "textbox", "label": "Card number", "value": "4242"},
                    {"role": "button", "label": "Place order", "type": "submit", "in_form": True}],
                   filled_here=True)
        record = self.gate(page, goal="order the thing")
        self.assertEqual(record["state"], bm.REFUSED)
        self.assertEqual(self.pending(), [], "a refusal never leaves an approval lying about")


# ---- which job -----------------------------------------------------------------

class AnApprovalSaysWhichJob(Isolated):
    class NamedSkill(browser_loop.GeneralSkill):
        name = "job_application"

        def subject(self, record):
            return "Account Manager, Manufacturing — Grainger"

    def test_the_reason_names_the_employer_and_the_role(self):
        record = self.gate(filled_application(), skill=self.NamedSkill())
        reason = policy.load(record["approval"])["reason"]
        self.assertIn("Account Manager, Manufacturing — Grainger", reason)
        self.assertIn("Submit Application", reason)

    def test_a_skill_that_cannot_name_it_changes_nothing(self):
        record = self.gate(filled_application())
        self.assertTrue(policy.load(record["approval"])["reason"].startswith("apply for this job —"))

    def test_the_row_he_reads_names_it_too_for_approvals_already_on_disk(self):
        """The sixteen already queued were raised before the reason changed,
        so the label reads the mission beside them."""
        from aletheia import voice
        record = self.gate(filled_application())
        record["skill"] = "named-for-the-test"
        bm.save(record)
        named = self.NamedSkill()
        named.name = "named-for-the-test"
        browser_loop.register(named)
        self.addCleanup(browser_loop.SKILLS.pop, "named-for-the-test", None)
        said = voice.approval_label(policy.load(record["approval"]))
        self.assertIn("Account Manager, Manufacturing", said)
        self.assertIn("Submit Application", said)


# ---- the read-only report ------------------------------------------------------

class TheReportOnlyReads(Isolated):
    def queue(self, page, *, filled):
        record = self.gate(page, filled=filled)
        record["skill"] = "job_application"
        bm.save(record)
        return record

    def test_it_names_what_would_no_longer_be_raised_and_decides_nothing(self):
        junk = self.queue(prefilled_stranger(), filled=False)
        real = self.queue(filled_application(), filled=True)
        rows = {r["id"]: r for r in needs_you.would_not_ask_now()}
        self.assertEqual(len(rows), 1, "the stalled one never became an approval at all")
        self.assertTrue(rows[real["approval"]]["still_asked"])
        self.assertIsNone(junk.get("approval"))
        self.assertEqual([a["state"] for a in policy.all_approvals()], ["PENDING"],
                         "the report decides nothing; denying is his")

    def test_a_queued_junk_approval_is_reported_as_one_to_deny(self):
        """An approval raised by the OLD rule, judged by the new one."""
        record = self.gate(filled_application())
        record["gate"]["button"] = "About Us"
        record["route"] = []
        record["checkpoints"] = [c for c in record["checkpoints"] if c["name"] != bm.FILLED]
        record["skill"] = "job_application"
        bm.save(record)
        row = next(r for r in needs_you.would_not_ask_now() if r["id"] == record["approval"])
        self.assertFalse(row["still_asked"])
        self.assertEqual(row["button"], "About Us")
        self.assertEqual(policy.load(record["approval"])["state"], "PENDING")

    def test_a_committing_button_is_kept_even_on_a_mission_that_filled_nothing(self):
        """The report mirrors `_gate`, including which half of the rule
        applies: an empty route excuses an unknown button, never a Submit."""
        record = self.gate(filled_application())
        record["route"] = []
        record["checkpoints"] = [c for c in record["checkpoints"] if c["name"] != bm.FILLED]
        bm.save(record)
        row = next(r for r in needs_you.would_not_ask_now() if r["id"] == record["approval"])
        self.assertTrue(row["still_asked"])
        self.assertEqual(row["kind"], ps.COMMIT)


# ---- the same page, read by a real browser -------------------------------------

#: The careers-site shape that cost him ten approvals, as HTML: the site's
#: navigation drawn as <a role=button>, its search form in the header, an
#: expander on the application, and the application's own Submit.
CAREERS_PAGE = """<!doctype html><html><body>
<header>
  <nav>
    <a role="button" href="/about-us">About Us</a>
    <a role="button" href="/products">Products</a>
    <button aria-haspopup="true">Language</button>
  </nav>
  <form role="search"><input name="q" aria-label="Search by Keyword">
    <button type="submit">Search submit</button></form>
</header>
<main><form id="app">
  <label for="fn">First name</label><input id="fn" name="fn" value="Caleb">
  <button type="button" aria-expanded="false">Show More Options</button>
  <button type="submit">Submit Application</button>
</form></main>
</body></html>"""


class ARealPageSaysWhatItsControlsAre(unittest.TestCase):
    """The evidence is only worth anything if the page really hands it over.

    Everything above reads a hand-written observation; this drives one
    headless page through the real `OBSERVE_JS` and `look`, so a JS change
    that silently stopped carrying `href`, `nav` or `aria-expanded` fails
    here instead of on his machine at three in the morning.
    """

    @classmethod
    def setUpClass(cls):
        from tests.test_browser_loop_torture import BROWSER_OK, BROWSER_WHY
        if not BROWSER_OK:
            raise unittest.SkipTest(f"browser control absent: {BROWSER_WHY}")

    def test_the_page_hands_over_its_own_evidence_and_the_kinds_follow(self):
        with browse._Session() as ctx:
            page = ctx.new_page()
            page.set_content(CAREERS_PAGE)
            seen = browser_loop.look(page)
        rows = {t["label"]: t for t in seen["targets"]}
        self.assertEqual(rows["About Us"]["href"], "/about-us")
        self.assertTrue(rows["About Us"]["nav"])
        self.assertTrue(rows["Language"]["haspopup"])
        self.assertIs(rows["Show More Options"]["expanded"], False)
        self.assertEqual(rows["Submit Application"]["type"], "submit")
        self.assertTrue(rows["Submit Application"]["in_form"])
        kinds = {label: browser_loop._kind(t, seen) for label, t in rows.items()
                 if t["role"] in ps.PRESS_ROLES}
        self.assertEqual(kinds, {"About Us": ps.NAVIGATE, "Products": ps.NAVIGATE,
                                 "Language": ps.OTHER, "Search submit": ps.OTHER,
                                 "Show More Options": ps.OTHER,
                                 "Submit Application": ps.COMMIT})
        self.assertEqual(browser_loop.final_control(seen, "apply for this job")["label"],
                         "Submit Application")


if __name__ == "__main__":
    unittest.main()
