"""A new project is a sentence, and so are a step and a drop.

    > Is it fluid tho I don't need a hard coded barkly area
    > Yes                                              — 2026-09-10

What these hold:

- Nothing in the code names a project; a charter file is a project's whole
  existence, and a sentence can make one.
- A drafted project is INERT until his yes. The builder, the pulse, the
  merge path and `plan_set` all leave it alone; `plans.confirm` is the one
  door, and only his reply reaches it.
- Drafts and edits land on the deploy branch through the contents API,
  because the Core's sync never pushes `plans/`, and his phone is asked at
  once through the Actions bot.
- "add milk to the list" and "drop it" are still the sentences they were.
"""
from __future__ import annotations

import base64
import copy
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from aletheia import (brief, charters, contracts, intercom, plans, policy,
                      project_merge, pulse, voice)
from aletheia.fleet import load_fleet
from tests.test_projects_are_carried import (FLEET, NOW, BranchSource, TempPlans,
                                             charter, item, pulse_of)


def a_draft(slug="pocket-chef"):
    plan = charter(slug=slug, base=f"claude/venture-{slug}")
    plan["state"] = "proposed"
    return plan


def fleet_as(owner="me"):
    fleet = copy.deepcopy(load_fleet())
    fleet["owner"] = owner
    return fleet


def think_returning(repo="Money_Machine", steps=None, title="Pocket Chef"):
    value = {
        "title": title,
        "goal": "A recipe app that plans a week of dinners from what is in the fridge",
        "repo": repo, "why": "because he asked",
        "steps": steps or [
            {"text": "Write the product brief in the repository", "owner": "thea", "needs": []},
            {"text": "Pick the three recipes to launch with", "owner": "caleb", "needs": []},
            {"text": "Build the first screen from the brief", "owner": "thea", "needs": [2]},
        ],
    }

    def think(system, text, *, context, model, validator, **_kw):
        think.calls.append({"system": system, "text": text, "context": context})
        return validator(copy.deepcopy(value))
    think.calls = []
    return think


class ADraftIsInertCase(TempPlans):
    def test_proposed_is_a_goal_state_only_a_charter_can_hold(self):
        self.assertEqual(contracts.validate_goal(a_draft()), [])
        loose = {"slug": "x", "title": "X", "goal": "g", "state": "proposed",
                 "created": "2026-09-10T00:00:00Z", "steps": []}
        self.assertTrue(plans.validate_plan(loose, load_fleet()))

    def test_nothing_works_on_a_draft(self):
        self.assertEqual(pulse.collect_projects(FLEET, BranchSource(), [a_draft()], now=NOW)["items"], [])
        self.assertEqual(list(project_merge._charters(FLEET, [a_draft()])), [])

    def test_plan_set_cannot_start_it_and_his_yes_can(self):
        """plan_set is reachable by voice and by the planner."""
        plans.save(a_draft())
        with self.assertRaises(ValueError):
            plans.set_plan("pocket-chef", "open")
        started = plans.confirm("pocket-chef", words="yes", via="test")
        self.assertEqual(started["state"], "open")
        self.assertEqual(started["confirmed"]["words"], "yes")
        self.assertEqual(contracts.validate_goal(started), [])

    def test_there_is_nothing_to_confirm_on_an_open_charter(self):
        plans.save(charter())
        with self.assertRaises(ValueError):
            plans.confirm("barkly", words="yes", via="test")

    def test_a_draft_can_be_turned_down(self):
        plans.save(a_draft())
        self.assertEqual(plans.set_plan("pocket-chef", "dropped")["state"], "dropped")


class WhoseStepFromHowHeSaidItCase(unittest.TestCase):
    def test_work_is_hers_and_his_life_is_his(self):
        for text, who in (("sound effects", plans.THEA),
                          ("write the README", plans.THEA),
                          ("I need to film the intro", plans.CALEB),
                          ("buy a domain", plans.CALEB),
                          ("pick the colours", plans.CALEB),
                          ("call the printer", plans.CALEB)):
            with self.subTest(text=text):
                self.assertEqual(plans.infer_owner(text), who)


class TheProjectHeMeansCase(unittest.TestCase):
    rows = [charter(), charter(slug="holdco-platform"), charter(slug="open-range-promo"), a_draft()]

    def find(self, name, rows=None):
        return plans.find_charter(name, rows if rows is not None else self.rows)

    def test_by_what_he_calls_it(self):
        for said, slug in (("Barkly", "barkly"), ("the holdco project", "holdco-platform"),
                           ("holdco", "holdco-platform"), ("open range", "open-range-promo"),
                           ("pocket chef", "pocket-chef")):
            with self.subTest(said=said):
                self.assertEqual(self.find(said)[0]["slug"], slug)

    def test_something_that_is_not_a_project(self):
        found, why = self.find("the list")
        self.assertIsNone(found)
        self.assertIn("don't have a project called", why)

    def test_two_that_fit_is_a_question(self):
        rows = [charter(slug="bark-app"), charter(slug="bark-toy")]
        found, why = self.find("bark", rows)
        self.assertIsNone(found)
        self.assertIn(" or ", why)

    def test_a_dropped_project_is_not_found(self):
        gone = charter()
        gone["state"] = "dropped"
        self.assertIsNone(self.find("barkly", [gone])[0])


class DraftingCase(unittest.TestCase):
    def test_a_new_idea_becomes_a_venture_on_its_own_branch(self):
        plan = charters.draft("a recipe app", fleet=load_fleet(), existing=[],
                              think=think_returning(), now=NOW)
        self.assertEqual(plan["state"], "proposed")
        self.assertEqual(plan["project"]["repo"], "money_machine")
        self.assertEqual(plan["project"]["base_branch"], "claude/venture-pocket-chef")
        self.assertEqual(plan["project"]["risk"], "low")
        self.assertEqual([s["owner"] for s in plan["steps"]], ["thea", "caleb", "thea"])
        self.assertEqual(plan["steps"][2]["needs"], [2])

    def test_an_idea_for_the_trader_waits_for_him_to_merge(self):
        plan = charters.draft("a stop-loss report", fleet=load_fleet(), existing=[],
                              think=think_returning(repo="schwab-trader", title="Stop report"), now=NOW)
        self.assertEqual(plan["project"]["risk"], "high")
        self.assertEqual(plan["project"]["base_branch"], "main")

    def test_a_step_that_spends_is_his_whatever_the_draft_said(self):
        steps = [{"text": "Buy the pocketchef.com domain", "owner": "thea", "needs": []},
                 {"text": "Write the product brief", "owner": "thea", "needs": []},
                 {"text": "Pick three recipes", "owner": "caleb", "needs": []}]
        plan = charters.draft("a recipe app", fleet=load_fleet(), existing=[],
                              think=think_returning(steps=steps), now=NOW)
        self.assertEqual(plan["steps"][0]["owner"], "caleb")

    def test_names_do_not_collide(self):
        plan = charters.draft("a recipe app", fleet=load_fleet(),
                              existing=[charter(slug="pocket-chef")],
                              think=think_returning(), now=NOW)
        self.assertEqual(plan["slug"], "pocket-chef-2")

    def test_a_draft_on_a_repository_the_builder_cannot_reach_is_refused(self):
        with self.assertRaises(ValueError):
            charters.draft("a thing", fleet=load_fleet(), existing=[],
                           think=think_returning(repo="fosstester"), now=NOW)

    def test_the_drafter_is_told_the_file_is_public(self):
        self.assertIn("PUBLIC", charters.DRAFT_SYSTEM)


class FakeContents:
    PREFIX = "/repos/me/Aletheia/contents/"

    def __init__(self, files=None):
        self.files = dict(files or {})
        self.calls, self.puts, self.dispatched = [], [], []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path))
        if method == "GET" and path.startswith(self.PREFIX):
            rel = path[len(self.PREFIX):].split("?")[0]
            if rel == "plans":
                return [{"name": p.split("/", 1)[1]} for p in self.files if p.startswith("plans/")]
            if rel in self.files:
                value, sha = self.files[rel]
                return {"encoding": "base64", "sha": sha,
                        "content": base64.b64encode(json.dumps(value).encode()).decode()}
            raise urllib.error.HTTPError(path, 404, "Not Found", None, None)
        if method == "PUT" and path.startswith(self.PREFIX):
            rel = path[len(self.PREFIX):]
            value = json.loads(base64.b64decode(body["content"]))
            self.puts.append((rel, value, body))
            self.files[rel] = (value, f"sha{len(self.puts)}")
            return {"content": {"sha": "new"}}
        if method == "POST" and path.endswith("/dispatches"):
            self.dispatched.append((path, body))
            return None
        raise AssertionError((method, path))


class TheQueueBecomesDraftsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(charters, "QUEUE_PATH", Path(self.tmp.name) / "asks.json")
        patch.start()
        self.addCleanup(patch.stop)
        self.fleet = fleet_as("me")

    def drain(self, gh, think=None):
        return charters.drain(request=gh, think=think or think_returning(), fleet=self.fleet, now=NOW)

    def test_a_new_ask_becomes_a_draft_and_his_phone_is_asked(self):
        charters.ask("new", text="a recipe app", via="test")
        gh = FakeContents({"plans/barkly.json": (charter(), "b1")})
        out = self.drain(gh)
        self.assertEqual(out["drafted"], ["pocket-chef"])
        rel, value, body = gh.puts[0]
        self.assertEqual((rel, value["state"], body["branch"]), ("plans/pocket-chef.json", "proposed", "live"))
        self.assertTrue(gh.dispatched[0][0].endswith("/actions/workflows/brief.yml/dispatches"))
        self.assertEqual(gh.dispatched[0][1]["ref"], "live")
        self.assertEqual(charters.pending(), [])

    def test_an_ask_replied_on_the_brief_is_drafted_too(self):
        replied = {"asks": [{"id": "a1", "kind": "new", "text": "a recipe app",
                             "state": "pending", "attempts": 0}]}
        gh = FakeContents({charters.REPLY_QUEUE: (replied, "q1")})
        self.drain(gh)
        queue_puts = [p for p in gh.puts if p[0] == charters.REPLY_QUEUE]
        self.assertEqual(queue_puts[0][1]["asks"][0]["state"], "drafted")
        self.assertEqual(queue_puts[0][2]["sha"], "q1")

    def test_a_step_edits_the_live_charter_at_its_current_version(self):
        charters.ask("step", text="sound effects", project="barkly", via="test")
        gh = FakeContents({"plans/barkly.json": (charter(), "b1")})
        out = self.drain(gh)
        self.assertEqual(out["edited"], ["barkly"])
        rel, value, body = gh.puts[0]
        self.assertEqual((rel, body["sha"]), ("plans/barkly.json", "b1"))
        self.assertEqual(value["steps"][-1], {"n": 5, "text": "sound effects", "state": "todo",
                                              "owner": "thea"})
        self.assertEqual(gh.dispatched, [])

    def test_a_drop_drops_it(self):
        charters.ask("drop", project="barkly", via="test")
        gh = FakeContents({"plans/barkly.json": (charter(), "b1")})
        self.drain(gh)
        self.assertEqual(gh.puts[0][1]["state"], "dropped")

    def test_a_failing_draft_is_tried_again_and_then_given_up(self):
        charters.ask("new", text="a recipe app", via="test")

        def broken(*_a, **_kw):
            raise ValueError("the model returned nothing usable")
        for attempt in range(charters.MAX_ATTEMPTS):
            self.drain(FakeContents(), think=broken)
        self.assertEqual(charters.pending(), [])
        row = charters._read_queue(charters.QUEUE_PATH)["asks"][0]
        self.assertEqual((row["state"], row["attempts"]), ("failed", charters.MAX_ATTEMPTS))

    def test_nothing_asked_costs_one_read_and_writes_nothing(self):
        gh = FakeContents()
        self.assertEqual(self.drain(gh), {"drafted": [], "edited": [], "failed": []})
        self.assertEqual([c[0] for c in gh.calls], ["GET"])

    def test_a_rehearsal_writes_nothing(self):
        charters.ask("new", text="a recipe app", via="test")
        gh = FakeContents()
        with mock.patch.dict(os.environ, {intercom.REHEARSAL: "1"}):
            self.assertEqual(self.drain(gh), {"rehearsal": True})
        self.assertEqual(gh.calls, [])

    def test_halt_stops_it(self):
        with mock.patch.object(charters.policy, "ensure_not_halted",
                               side_effect=policy.Halted("stop")):
            with self.assertRaises(policy.Halted):
                self.drain(FakeContents())


class HeSaysItCase(unittest.TestCase):
    def cmd(self, said):
        return (voice._interpret(said) or {}).get("command") or {}

    def test_a_new_project_is_a_sentence(self):
        for said, idea in (("new project: an Etsy shop for 3D prints", "an Etsy shop for 3D prints"),
                           ("start a new project called Pocket Chef", "Pocket Chef")):
            with self.subTest(said=said):
                got = self.cmd(said)
                self.assertEqual((got.get("kind"), got.get("idea")), ("project_new", idea))

    def test_a_step_names_a_project_that_exists(self):
        with mock.patch.object(plans, "all_plans", return_value=[charter()]):
            got = self.cmd("add sound effects to Barkly")
            self.assertEqual((got.get("kind"), got.get("project"), got.get("text")),
                             ("project_step", "barkly", "sound effects"))
            self.assertEqual(self.cmd("add milk to the list").get("kind"), "shopping_add")

    def test_drop_needs_a_project_that_exists(self):
        with mock.patch.object(plans, "all_plans", return_value=[charter(slug="holdco-platform")]):
            self.assertEqual(self.cmd("drop the holdco platform").get("kind"), "project_drop")
            self.assertNotEqual(self.cmd("drop it").get("kind"), "project_drop")


class TheVerbsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(charters, "QUEUE_PATH", Path(self.tmp.name) / "asks.json")
        patch.start()
        self.addCleanup(patch.stop)

    def test_queuing_is_routine_and_ending_one_is_his_alone(self):
        for kind in ("project_new", "project_step", "project_drop"):
            self.assertEqual(intercom.tier(kind), intercom.TIER_ROUTINE)
        self.assertIn("project_drop", intercom.PLANNER_FORBIDDEN)

    def test_a_new_project_is_queued_and_she_says_when(self):
        said = intercom.execute_command({"kind": "project_new", "idea": "a podcast about maps"}, {})
        self.assertIn("half an hour", said)
        self.assertEqual(charters.pending()[0]["text"], "a podcast about maps")

    def test_a_step_for_a_project_that_does_not_exist_says_so(self):
        with mock.patch.object(plans, "all_plans", return_value=[]):
            said = intercom.execute_command(
                {"kind": "project_step", "project": "zeppelin", "text": "fins"}, {})
        self.assertIn("don't have a project called", said)
        self.assertEqual(charters.pending(), [])

    def test_my_projects_names_what_she_carries_and_what_waits_for_him(self):
        from aletheia import projects
        with mock.patch.object(plans, "all_plans", return_value=[charter(), a_draft()]), \
             mock.patch.object(projects, "all_projects", return_value=[]):
            charters.ask("new", text="a podcast about maps", via="test")
            said = intercom.execute_command({"kind": "projects"}, {})
        self.assertIn("Barkly", said)
        self.assertIn("waiting for your yes", said)
        self.assertIn("a podcast about maps", said)


class TheBriefAsksAndHearsCase(TempPlans):
    def test_a_draft_waiting_for_his_yes_comes_first(self):
        thing = brief.pick_one_thing(pulse_of(item("barkly", yours={"n": 2, "text": "Pages"})),
                                     now=NOW, drafts=[a_draft()])
        self.assertEqual((thing["kind"], thing["slug"]), ("confirm", "pocket-chef"))
        self.assertIn("Reply yes", thing["text"])

    def test_yes_starts_it(self):
        plans.save(a_draft())
        brief._write_state(brief.ONE_THING_FILE, {"kind": "confirm", "slug": "pocket-chef",
                                                  "title": "Pocket Chef"})
        said = brief.reply("Yes!", now=NOW)
        self.assertEqual(plans.load("pocket-chef")["state"], "open")
        self.assertIn("Started", said)

    def test_no_turns_the_draft_down(self):
        plans.save(a_draft())
        brief._write_state(brief.ONE_THING_FILE, {"kind": "confirm", "slug": "pocket-chef",
                                                  "title": "Pocket Chef"})
        brief.reply("no", now=NOW)
        self.assertEqual(plans.load("pocket-chef")["state"], "dropped")

    def test_new_project_by_reply_is_queued_for_the_pc(self):
        said = brief.reply("New project: a newsletter about local history", now=NOW)
        queued = json.loads((brief.BRIEF_DIR / brief.PROJECT_ASKS_FILE).read_text(encoding="utf-8"))
        self.assertEqual(queued["asks"][0]["text"], "a newsletter about local history")
        self.assertIn("Got it", said)

    def test_add_a_step_by_reply_and_whose_it_is(self):
        plans.save(charter())
        brief.reply("add sound effects to Barkly", now=NOW)
        brief.reply("add buy a domain to barkly", now=NOW)
        steps = plans.load("barkly")["steps"]
        self.assertEqual([(s["text"], s["owner"]) for s in steps[-2:]],
                         [("sound effects", "thea"), ("buy a domain", "caleb")])

    def test_drop_by_name(self):
        plans.save(charter())
        brief.reply("drop barkly", now=NOW)
        self.assertEqual(plans.load("barkly")["state"], "dropped")

    def test_a_reply_that_names_no_project_is_not_a_command(self):
        plans.save(charter())
        said = brief.reply("add some thoughts to the doc", now=NOW)
        self.assertIn("nothing changed", said)
        self.assertEqual(len(plans.load("barkly")["steps"]), 4)


class ANewVentureBeforeItsBranchExistsCase(unittest.TestCase):
    def test_not_started_is_not_unreadable(self):
        class NoBranchYet(BranchSource):
            def branch_commits(self, gh, branch, n=30):
                raise urllib.error.HTTPError(branch, 404, "Not Found", None, None)
        plan = charter(slug="pocket-chef", base="claude/venture-pocket-chef")
        found = pulse.collect_projects(FLEET, NoBranchYet(), [plan], now=NOW)["items"][0]
        self.assertTrue(found["not_started"])
        self.assertNotIn("error", found)


if __name__ == "__main__":
    unittest.main()
