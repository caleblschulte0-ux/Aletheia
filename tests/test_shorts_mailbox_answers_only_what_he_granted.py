"""Shorts-pipeline's mailboxes, answered from his PC - and nothing wider.

His ruling, 2026-10-07T01:22Z: *"Alethea may write files into a shorts
review, rewrite, and ask mailbox. ... That's certified by me. Every 30
minutes is unnecessary. We only post in the morning, so maybe it needs to
run two, three times in the morning, and that's it"*.

Each class here holds one half of that: the grant is the answer files in
three folders and nothing else (refused before any network call), the
schedule is three morning rounds on his clock, the beat only launches, and
nothing malformed is ever written - a malformed grade becomes a HOLD that
burns the request on Shorts' side.
"""
import base64
import copy
import datetime as dt
import io
import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from aletheia import act, browser_reasoner, closed, journal, policy, reasoner, shorts_mailbox
from aletheia.fleet import FleetError, load_fleet, validate

CHICAGO = ZoneInfo("America/Chicago")
FULL = "caleblschulte0-ux/Shorts-pipeline"
MEDIA = f"https://raw.githubusercontent.com/{FULL}/preview-renders/reviews/20261006/r1"
SHA = "a" * 64


def _http(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://api.github.com/x", code, "nope", None, io.BytesIO(b""))


class FakeGitHub:
    """gh.request for the Contents API: files is {path: text}; records every
    call; `conflicts` PUTs answer 409 first."""

    def __init__(self, files=None, conflicts=0):
        self.files = dict(files or {})
        self.calls = []
        self.conflicts = conflicts

    def _path(self, url):
        return url.split("/contents/", 1)[1].split("?", 1)[0]

    def __call__(self, method, path, body=None, tok=None):
        self.calls.append((method, path, copy.deepcopy(body)))
        where = self._path(path)
        if method == "GET":
            if where not in self.files:
                raise _http(404)
            text = self.files[where]
            return {"sha": f"sha-{len(text)}", "encoding": "base64",
                    "content": base64.b64encode(text.encode()).decode()}
        if method == "PUT":
            if self.conflicts:
                self.conflicts -= 1
                raise _http(409)
            self.files[where] = base64.b64decode(body["content"]).decode()
            return {"commit": {"sha": "c0ffee"}}
        raise AssertionError(method)

    def puts(self):
        return [c for c in self.calls if c[0] == "PUT"]


#: The grant as drafted. It is NOT in config/fleet.json until he says yes in
#: this project (asked 2026-10-07): the words below were said in another
#: project, and a worker's claim of his permission is not a grant. These
#: tests hold what the door does once it is open.
GRANT = {
    "answers": ["exchange/reviews/", "exchange/rewrites/", "exchange/asks/"],
    "answers_ruling": {
        "by": "Caleb", "on": "2026-10-07T01:22Z", "where": "his Claude project thread",
        "said": ("Alethea may write files into a shorts review, rewrite, and ask mailbox. ... That's certified by "
                 "me. Every 30 minutes is unnecessary. We only post in the morning, so maybe it needs to run two, "
                 "three times in the morning, and that's it"),
        "means": "Answer files only, in these three mailbox folders, at most three rounds a morning.",
    },
}


def granted_fleet() -> dict:
    fleet = copy.deepcopy(load_fleet())
    fleet["repos"]["shorts_pipeline"]["front_door"].update(copy.deepcopy(GRANT))
    return fleet


class Isolated(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        for patch in (mock.patch.object(journal, "JOURNAL_PATH", tmp / "j.jsonl"),
                      mock.patch.object(shorts_mailbox, "state_dir", lambda: tmp / "mailbox"),
                      mock.patch.object(policy, "HALT_PATH", tmp / "halt.json"),
                      mock.patch.object(closed, "is_closed", lambda: False)):
            patch.start()
            self.addCleanup(patch.stop)
        self.fleet = granted_fleet()
        self.tmp = tmp


# ---------------------------------------------------------------- the grant

class TheGrantIsAnswerFilesInThreeFoldersAndNothingElse(Isolated):
    REFUSED = [
        "exchange/bundles/20261007/response.json",              # another mailbox
        "exchange/reviews/20261006/r1.request.json",            # the ask itself
        "exchange/reviews/20261006/r1.done.json",               # Shorts' settlement
        "exchange/reviews/OPEN.json",                           # the index
        "scripts/claim_reviews.py",                             # code
        "exchange/reviews/../../scripts/x.verdict.json",        # out of the folder
        "/exchange/reviews/20261006/r1.verdict.json",
        "exchange/reviews//r1.verdict.json",
    ]

    def test_every_path_outside_the_grant_is_refused_with_zero_api_calls(self):
        for path in self.REFUSED:
            with self.subTest(path=path):
                api = FakeGitHub()
                with self.assertRaises(act.Refused):
                    act.put_answer(self.fleet, "shorts_pipeline", path, "{}",
                                   message="exchange: mailbox round 20261007 (aletheia)", request=api)
                self.assertEqual(api.calls, [])

    def test_a_repo_with_no_answers_grant_is_refused_with_zero_api_calls(self):
        api = FakeGitHub()
        with self.assertRaises(act.Refused):
            act.put_answer(self.fleet, "schwab_trader", "exchange/reviews/x/r.verdict.json", "{}",
                           message="m", request=api)
        self.assertEqual(api.calls, [])

    def test_the_three_answer_kinds_in_the_three_folders_are_allowed(self):
        for path in ("exchange/reviews/20261006/r1.verdict.json",
                     "exchange/rewrites/20261006/s__ab.answer.json",
                     "exchange/asks/20261006.answers.json"):
            self.assertEqual(act.check_answer_path(self.fleet, "shorts_pipeline", path), path)

    def test_halted_or_closed_writes_nothing(self):
        api = FakeGitHub()
        policy.HALT_PATH.write_text('{"reason": "test"}')
        with self.assertRaises(policy.Halted):
            act.put_answer(self.fleet, "shorts_pipeline", "exchange/reviews/x/r.verdict.json", "{}",
                           message="m", request=api)
        policy.HALT_PATH.unlink()
        with mock.patch.object(closed, "is_closed", lambda: True), self.assertRaises(act.Refused):
            act.put_answer(self.fleet, "shorts_pipeline", "exchange/reviews/x/r.verdict.json", "{}",
                           message="m", request=api)
        self.assertEqual(api.calls, [])

    def test_a_skip_ci_message_is_refused_because_the_push_is_the_point(self):
        api = FakeGitHub()
        for message in ("exchange: x [skip ci]", "[ci skip] x", "x [no ci]"):
            with self.assertRaises(act.Refused):
                act.put_answer(self.fleet, "shorts_pipeline", "exchange/reviews/x/r.verdict.json", "{}",
                               message=message, request=api)
        self.assertEqual(api.calls, [])


class TheFleetValidatorHoldsTheDoorShut(unittest.TestCase):
    def _with(self, **front_door):
        fleet = granted_fleet()
        fd = fleet["repos"]["shorts_pipeline"]["front_door"]
        fd.update(front_door)
        return fleet

    def test_the_registry_as_committed_keeps_the_door_shut_until_he_says_yes(self):
        fd = load_fleet()["repos"]["shorts_pipeline"]["front_door"]
        self.assertNotIn("answers", fd)
        self.assertNotIn("answers_ruling", fd)
        self.assertFalse(shorts_mailbox._granted(load_fleet()))

    def test_the_grant_as_drafted_validates_and_carries_his_words(self):
        validate(granted_fleet())
        fd = granted_fleet()["repos"]["shorts_pipeline"]["front_door"]
        self.assertIn("That's certified by me", fd["answers_ruling"]["said"])

    def test_a_prefix_outside_exchange_or_the_whole_of_exchange_is_refused(self):
        for bad in (["scripts/"], ["exchange/"], ["exchange/../scripts/"], ["exchange/reviews"],
                    "exchange/reviews/", [3], ["exchange\\reviews/"]):
            with self.subTest(answers=bad), self.assertRaises(FleetError):
                validate(self._with(answers=bad))

    def test_a_grant_without_his_words_is_not_a_grant(self):
        with self.assertRaises(FleetError):
            validate(self._with(answers_ruling={"on": "2026-10-07", "said": " "}))
        fleet = self._with()
        del fleet["repos"]["shorts_pipeline"]["front_door"]["answers_ruling"]
        with self.assertRaises(FleetError):
            validate(fleet)

    def test_an_unknown_door_is_refused(self):
        with self.assertRaises(FleetError):
            validate(self._with(pushes=["main"]))

    def test_words_with_no_grant_are_refused_as_dead_data(self):
        fleet = granted_fleet()
        fleet["repos"]["schwab_trader"]["front_door"]["answers_ruling"] = {"on": "x", "said": "y"}
        with self.assertRaises(FleetError):
            validate(fleet)


# ---------------------------------------------------------------- grades

def good_grades():
    return {
        "dimensions": {"hook": 3, "data_demo": 4, "mascot": 2, "craft": 2, "pace": 1, "payoff": 2},
        "checks": {k: {"present": False, "evidence": f"{k}: nothing like it in any frame"}
                   for k in shorts_mailbox.CHECKS},
        "weakest_scene": {"id": "seg1", "index": 2, "failure_class": "decorative_mascot",
                          "visible_evidence": "he points beside the bar", "root_cause": "no agency",
                          "repair_goal": "he pours the jar"},
        "depictions": [{"id": "seg0", "kind": "machine", "bespoke": 1, "proves_claim": 2, "note": "a tube"},
                       {"id": "seg1", "kind": "nonsense", "bespoke": 1, "proves_claim": 1}],
        "one_line": "fine", "problems": ["a"], "fixes": ["b"],
    }


class AGradeThatWouldBurnTheRequestIsNeverWritten(unittest.TestCase):
    def test_a_well_formed_grade_passes_and_leaves_the_decision_to_shorts(self):
        g = good_grades()
        g["dimensions"]["temporal_craft"] = 3
        out = shorts_mailbox.validate_grades(g)
        self.assertNotIn("temporal_craft", out["dimensions"])
        self.assertEqual([d["id"] for d in out["depictions"]], ["seg0"])
        self.assertEqual(set(out["checks"]), set(shorts_mailbox.CHECKS))

    def test_floats_bools_and_out_of_range_dimensions_are_refused(self):
        for bad in (3.0, True, 5, -1, "3", None):
            g = good_grades()
            g["dimensions"]["hook"] = bad
            with self.subTest(hook=bad), self.assertRaises(ValueError):
                shorts_mailbox.validate_grades(g)

    def test_a_missing_or_half_answered_check_is_refused(self):
        g = good_grades()
        del g["checks"]["unreadable"]
        with self.assertRaises(ValueError):
            shorts_mailbox.validate_grades(g)
        for broken in ({"present": "no", "evidence": "x"}, {"present": False, "evidence": "  "},
                       {"present": False}):
            g = good_grades()
            g["checks"]["dead_air"] = broken
            with self.subTest(check=broken), self.assertRaises(ValueError):
                shorts_mailbox.validate_grades(g)

    def test_a_grade_that_decides_is_refused(self):
        for key in ("score", "verdict", "ship", "block"):
            g = good_grades()
            g[key] = 90
            with self.subTest(key=key), self.assertRaises(ValueError):
                shorts_mailbox.validate_grades(g)

    def test_the_weakest_scene_is_required_and_structured(self):
        g = good_grades()
        g["weakest_scene"]["index"] = "2"
        with self.assertRaises(ValueError):
            shorts_mailbox.validate_grades(g)


# ---------------------------------------------------------------- rewrites

RULES = ["PACE: each SAY is ONE spoken sentence of at most 16 words — the number and what it means, "
         "nothing else; the HOOK at most 14 words, the CLOSING at most 10, the QUESTION at most 8.",
         "TOPIC labels are printed on the video: at most 4 words, no clause."]


def rewrite_request(rules=RULES):
    seg = lambda i, topic, say, pts: {"index": i, "topic": topic, "say": say, "role": "x",
                                      "data": {"unit": "percent", "title": "Drinking among adults",
                                               "points": pts}}
    return {
        "schema": "shorts-rewrite-request/v1", "id": "genz-drinking__ad4d", "slug": "genz-drinking",
        "current": {"title": "Gen Z Broke A Drinking Habit", "hook": "Your drinking is dying: 72% now 50%.",
                    "closing": "Sober is the norm.", "question": "Drink less?",
                    "segments": [{"topic": "Drinking decline", "say": "Drinking fell from 72% to 50%."},
                                 {"topic": "Young drinking", "say": "It dropped from 70% to 35%."}]},
        "segments": [seg(0, "Drinking decline", "Drinking fell from 72% to 50%.",
                         [{"label": "2003", "value": 72}, {"label": "2025", "value": 50}]),
                     seg(1, "Young drinking", "It dropped from 70% to 35%.",
                         [{"label": "then", "value": 70}, {"label": "now", "value": 35}])],
        "rules": rules, "answer_path": "exchange/rewrites/20261006/genz-drinking__ad4d.answer.json",
    }


def good_words():
    return {"title": "Why Gen Z Drinking Fell By Half", "hook": "Your bar tab vanished: drinking fell from 72% to 50%.",
            "closing": "Sober is becoming the norm.", "question": "Do you drink less?",
            "segments": [{"topic": "Drinking falls", "say": "Drinking among adults fell from 72% to 50%."},
                         {"topic": "Young drinking halves", "say": "Among the youngest, drinking dropped from 70% to 35%."}]}


class ARewriteItsOwnRulesWouldRefuseNeverLeaves(unittest.TestCase):
    def test_a_rewrite_inside_every_rule_passes(self):
        out = shorts_mailbox.prevalidate_rewrite(rewrite_request(), good_words())
        self.assertEqual(len(out["segments"]), 2)

    def test_a_derived_number_is_allowed(self):
        w = good_words()
        w["segments"][0]["say"] = "Drinking among adults fell 22 points, from 72% to 50%."
        shorts_mailbox.prevalidate_rewrite(rewrite_request(), w)

    def refused(self, mutate, req=None):
        w = good_words()
        mutate(w)
        with self.assertRaises(ValueError):
            shorts_mailbox.prevalidate_rewrite(req or rewrite_request(), w)

    def test_the_wrong_number_of_segments_is_refused(self):
        self.refused(lambda w: w["segments"].pop())

    def test_a_say_over_its_cap_or_of_two_sentences_is_refused(self):
        self.refused(lambda w: w["segments"][0].update(
            say="Drinking among all of the adults in this whole country fell from 72% to 50% over two decades."))
        self.refused(lambda w: w["segments"][0].update(say="Drinking fell. It went from 72% to 50%."))

    def test_the_caps_come_from_the_requests_own_rule(self):
        tight = [RULES[0].replace("at most 16 words", "at most 6 words"), RULES[1]]
        self.refused(lambda w: None, req=rewrite_request(tight))

    def test_a_long_topic_a_long_hook_or_an_empty_title_is_refused(self):
        self.refused(lambda w: w["segments"][0].update(topic="The great big drinking decline"))
        self.refused(lambda w: w.update(hook="Your bar tab vanished because drinking among adults fell from 72% to 50% in twenty years flat."))
        self.refused(lambda w: w.update(title=""))

    def test_a_number_the_data_cannot_show_is_refused(self):
        self.refused(lambda w: w["segments"][1].update(say="Among the youngest, drinking dropped from 70% to 12%."))
        self.refused(lambda w: w.update(hook="Your bar tab vanished: 9 in 10 stopped drinking."))

    def test_a_number_written_as_a_word_is_refused_when_unsure(self):
        self.refused(lambda w: w["segments"][0].update(say="Drinking fell from 72% to 50% in twenty years."))

    def test_a_new_name_is_refused(self):
        self.refused(lambda w: w["segments"][0].update(say="Drinking in Texas fell from 72% to 50%."))

    def test_a_topic_with_no_bridge_to_the_title_is_refused(self):
        self.refused(lambda w: w["segments"][1].update(topic="Youth habits"))


# ---------------------------------------------------------------- schedule

def chicago(y, mo, d, h, mi):
    return dt.datetime(y, mo, d, h, mi, tzinfo=CHICAGO)


class ThreeRoundsAMorningOnHisClockAndThatsIt(Isolated):
    def test_each_slot_opens_on_his_clock_and_nothing_outside_one(self):
        self.assertEqual(shorts_mailbox.slot_for(chicago(2026, 10, 7, 6, 45), CHICAGO), ("2026-10-07", "0630"))
        self.assertEqual(shorts_mailbox.slot_for(chicago(2026, 10, 7, 8, 0), CHICAGO), ("2026-10-07", "0800"))
        self.assertEqual(shorts_mailbox.slot_for(chicago(2026, 10, 7, 10, 29), CHICAGO), ("2026-10-07", "0930"))
        for h, m in ((5, 0), (6, 29), (7, 30), (10, 30), (13, 0), (23, 59)):
            with self.subTest(at=f"{h:02d}:{m:02d}"):
                self.assertIsNone(shorts_mailbox.slot_for(chicago(2026, 10, 7, h, m), CHICAGO))

    def test_it_is_chicago_time_not_utc_in_summer_and_winter(self):
        utc = dt.timezone.utc
        self.assertIsNone(shorts_mailbox.slot_for(dt.datetime(2026, 10, 7, 6, 45, tzinfo=utc), CHICAGO))
        self.assertEqual(shorts_mailbox.slot_for(dt.datetime(2026, 10, 7, 11, 45, tzinfo=utc), CHICAGO)[1], "0630")
        self.assertEqual(shorts_mailbox.slot_for(dt.datetime(2026, 12, 1, 12, 45, tzinfo=utc), CHICAGO)[1], "0630")
        with mock.patch.dict(os.environ, {"ALETHEIA_TZ": ""}), \
                mock.patch("aletheia.memory.recall", return_value=None):
            self.assertEqual(shorts_mailbox.slot_for(dt.datetime(2026, 10, 7, 13, 0, tzinfo=utc))[1], "0800")

    def test_a_slot_runs_once_and_a_morning_never_more_than_three_times(self):
        claimed = [shorts_mailbox.claim_slot(chicago(2026, 10, 7, h, m), CHICAGO)
                   for h, m in ((6, 31), (6, 50), (8, 1), (9, 31), (10, 0))]
        self.assertEqual([c and c["slot"] for c in claimed], ["0630", None, "0800", "0930", None])
        self.assertEqual(len(shorts_mailbox.receipts_for("2026-10-07")), 3)
        self.assertIsNotNone(shorts_mailbox.claim_slot(chicago(2026, 10, 8, 6, 31), CHICAGO))

    def test_three_receipts_already_there_close_the_morning_whatever_their_names(self):
        d = shorts_mailbox._receipts_dir()
        d.mkdir(parents=True)
        for name in ("a", "b", "c"):
            (d / f"2026-10-07-{name}.json").write_text("{}")
        self.assertIsNone(shorts_mailbox.claim_slot(chicago(2026, 10, 7, 6, 31), CHICAGO))


class TheBeatOnlyLaunches(Isolated):
    def setUp(self):
        super().setUp()
        p = mock.patch.dict(os.environ, {shorts_mailbox.OFF_ENV: "", "ALETHEIA_REHEARSAL": ""})
        p.start()
        self.addCleanup(p.stop)
        self.spawned = []

    def spawner(self, args):
        self.spawned.append(args)
        return 4242

    def test_in_a_slot_it_starts_one_detached_round_and_does_no_work_itself(self):
        with mock.patch.object(shorts_mailbox, "once", side_effect=AssertionError("ran inline")), \
                mock.patch("aletheia.reasoner.work_json_with_provider", side_effect=AssertionError("thought")):
            out = shorts_mailbox.kick(self.fleet, now=chicago(2026, 10, 7, 6, 40), tz=CHICAGO,
                                      spawner=self.spawner)
        self.assertTrue(out["started"])
        self.assertEqual(self.spawned, [[sys.executable, "-m", "aletheia.shorts_mailbox", "once",
                                         "--slot", "2026-10-07-0630"]])
        again = shorts_mailbox.kick(self.fleet, now=chicago(2026, 10, 7, 6, 41), tz=CHICAGO,
                                    spawner=self.spawner)
        self.assertFalse(again["started"])
        self.assertEqual(len(self.spawned), 1)

    def test_outside_a_slot_nothing_starts(self):
        out = shorts_mailbox.kick(self.fleet, now=chicago(2026, 10, 7, 14, 0), tz=CHICAGO,
                                  spawner=self.spawner)
        self.assertFalse(out["started"])
        self.assertEqual(self.spawned, [])

    def test_a_launch_that_fails_does_not_spend_the_slot(self):
        with self.assertRaises(OSError):
            shorts_mailbox.kick(self.fleet, now=chicago(2026, 10, 7, 6, 40), tz=CHICAGO,
                                spawner=mock.Mock(side_effect=OSError("no")))
        self.assertTrue(shorts_mailbox.kick(self.fleet, now=chicago(2026, 10, 7, 6, 41), tz=CHICAGO,
                                            spawner=self.spawner)["started"])

    def test_no_grant_halted_or_switched_off_starts_nothing(self):
        fleet = copy.deepcopy(self.fleet)
        del fleet["repos"]["shorts_pipeline"]["front_door"]["answers"]
        self.assertFalse(shorts_mailbox.kick(fleet, now=chicago(2026, 10, 7, 6, 40), tz=CHICAGO,
                                             spawner=self.spawner)["started"])
        policy.HALT_PATH.write_text('{"reason": "test"}')
        self.assertFalse(shorts_mailbox.kick(self.fleet, now=chicago(2026, 10, 7, 6, 40), tz=CHICAGO,
                                             spawner=self.spawner)["started"])
        policy.HALT_PATH.unlink()
        with mock.patch.dict(os.environ, {shorts_mailbox.OFF_ENV: "1"}):
            self.assertFalse(shorts_mailbox.kick(self.fleet, now=chicago(2026, 10, 7, 6, 40), tz=CHICAGO,
                                                 spawner=self.spawner)["started"])
        self.assertEqual(self.spawned, [])

    def test_the_core_beat_reaches_the_launcher(self):
        from aletheia import runtime
        with mock.patch.object(shorts_mailbox, "kick", return_value={"started": False}) as kick:
            runtime._kick_shorts_mailbox(self.fleet, chicago(2026, 10, 7, 6, 40))
        kick.assert_called_once()


class MainDropsTheLeaseFirst(Isolated):
    def test_the_lease_is_gone_before_the_round_begins(self):
        order = []
        with mock.patch.dict(os.environ, {browser_reasoner.ALLOW_ENV: "1"}), \
                mock.patch.object(browser_reasoner, "drop_lease", side_effect=lambda env=None: order.append("drop")), \
                mock.patch.object(shorts_mailbox, "once", side_effect=lambda **k: order.append("once") or {}):
            self.assertEqual(shorts_mailbox.main(["once", "--force"]), 0)
        self.assertEqual(order, ["drop", "once"])

    def test_once_by_hand_without_force_refuses_outside_a_slot(self):
        out = shorts_mailbox.once(fleet=self.fleet, request=FakeGitHub(), read=lambda p: None)
        self.assertEqual(out["outcome"], "refused")


# ---------------------------------------------------------------- the PUT

class TheContentsApiWriteIsTheShapeGitHubWants(Isolated):
    MESSAGE = "exchange: mailbox round 20261007 (aletheia)"

    def test_a_new_answer_is_created_without_a_sha_on_main(self):
        api = FakeGitHub()
        out = act.put_answer(self.fleet, "shorts_pipeline", "exchange/reviews/x/r.verdict.json", '{"a": 1}\n',
                             message=self.MESSAGE, request=api)
        self.assertTrue(out["written"])
        method, path, body = api.puts()[0]
        self.assertEqual(path, f"/repos/{FULL}/contents/exchange/reviews/x/r.verdict.json")
        self.assertEqual(body["branch"], "main")
        self.assertNotIn("sha", body)
        self.assertNotIn("skip ci", body["message"].lower())
        self.assertEqual(base64.b64decode(body["content"]).decode(), '{"a": 1}\n')
        self.assertEqual(shorts_mailbox.commit_message(chicago(2026, 10, 7, 6, 40), CHICAGO), self.MESSAGE)

    def test_an_answer_already_there_is_never_overwritten(self):
        api = FakeGitHub({"exchange/reviews/x/r.verdict.json": "{}"})
        out = act.put_answer(self.fleet, "shorts_pipeline", "exchange/reviews/x/r.verdict.json", "{}",
                             message=self.MESSAGE, request=api)
        self.assertFalse(out["written"])
        self.assertEqual(api.puts(), [])

    def test_a_merge_updates_with_the_sha_and_keeps_what_was_there(self):
        path = "exchange/asks/20261006.answers.json"
        api = FakeGitHub({path: json.dumps({"schema": "shorts-ask-answers/v1",
                                            "answers": {"k1": {"answer": "old", "by": "chatgpt"}}})})
        act.put_answer(self.fleet, "shorts_pipeline", path, "", message=self.MESSAGE, request=api,
                       merge=lambda old: shorts_mailbox.merge_answers(
                           old, {"k1": {"answer": "new"}, "k2": {"answer": "two", "by": "aletheia:claude"}}))
        body = api.puts()[0][2]
        self.assertTrue(body["sha"].startswith("sha-"))
        written = json.loads(api.files[path])
        self.assertEqual(written["answers"]["k1"]["answer"], "old")
        self.assertEqual(written["answers"]["k2"]["by"], "aletheia:claude")

    def test_a_sha_conflict_is_reread_and_tried_once_more(self):
        api = FakeGitHub(conflicts=1)
        out = act.put_answer(self.fleet, "shorts_pipeline", "exchange/rewrites/x/s.answer.json", "{}",
                             message=self.MESSAGE, request=api)
        self.assertTrue(out["written"])
        self.assertEqual([c[0] for c in api.calls], ["GET", "PUT", "GET", "PUT"])
        self.assertEqual(sum(1 for e in journal.entries() if e["kind"] == "action"), 1)


class CodexSeesTheFramesAsAttachedImages(Isolated):
    def test_each_frame_is_an_image_flag_and_the_prompt_still_comes_on_stdin(self):
        import subprocess
        frames = []
        for name in ("sheet.jpg", "f00.jpg"):
            (self.tmp / name).write_bytes(b"x")
            frames.append(str(self.tmp / name))
        seen = {}

        def run_tree(argv, budget, **kw):
            seen["argv"], seen["input"] = argv, kw.get("input")
            last = argv[argv.index("--output-last-message") + 1]
            Path(last).write_text(json.dumps(good_grades()), encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch.object(reasoner, "codex_path", return_value="codex"), \
                mock.patch.object(reasoner, "codex_resting", return_value=None), \
                mock.patch.object(reasoner.proc, "run_tree", side_effect=run_tree):
            out = reasoner.codex_json("Grade.", "the prompt", images=frames,
                                      validator=shorts_mailbox.validate_grades)
        argv = seen["argv"]
        self.assertEqual(argv[1], "exec")
        self.assertEqual([argv[i + 1] for i, a in enumerate(argv) if a == "--image"], frames)
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
        self.assertEqual(argv[-1], "-")
        self.assertIn("the prompt", seen["input"])
        self.assertEqual(out["dimensions"]["hook"], 3)

    def test_an_image_that_is_not_a_file_is_refused_before_codex_runs(self):
        with mock.patch.object(reasoner, "codex_path", return_value="codex"), \
                mock.patch.object(reasoner, "codex_resting", return_value=None), \
                mock.patch.object(reasoner.proc, "run_tree", side_effect=AssertionError("ran")):
            with self.assertRaises(ValueError):
                reasoner.codex_json("Grade.", "x", images=[str(self.tmp / "missing.jpg")])


# ---------------------------------------------------------------- a whole round

REVIEW_ID = "recycling__2fc8146a7c"
REVIEW_ANSWER = f"exchange/reviews/20261006/{REVIEW_ID}.verdict.json"
REWRITE_ANSWER = "exchange/rewrites/20261006/genz-drinking__ad4d.answer.json"


def mailbox_files():
    review_req = {
        "schema": "shorts-review-request/v1", "id": REVIEW_ID, "slug": "recycling", "video_sha256": SHA,
        "sheet_url": f"{MEDIA}/sheet.jpg",
        "frames": [{"label": "hook@0.3", "t": 0.3, "url": f"{MEDIA}/f00.jpg"},
                   {"label": "seg0:mid", "t": 4.1, "url": f"{MEDIA}/f01.jpg"},
                   {"label": "evil", "t": 5, "url": "https://example.com/x.jpg"}],
        "prompt": "Grade this video. Return ONLY this JSON ...", "answer_path": REVIEW_ANSWER,
    }
    blocked = dict(rewrite_request(), id="recycling__99", slug="recycling",
                   answer_path="exchange/rewrites/20261006/recycling__99.answer.json")
    return {
        "exchange/reviews/OPEN.json": {"schema": "shorts-review-index/v1", "open": [
            {"id": REVIEW_ID, "slug": "recycling", "request": f"exchange/reviews/20261006/{REVIEW_ID}.request.json",
             "answer_path": REVIEW_ANSWER}]},
        f"exchange/reviews/20261006/{REVIEW_ID}.request.json": review_req,
        "exchange/rewrites/OPEN.json": {"schema": "shorts-rewrite-index/v1", "open": [
            {"id": "recycling__99", "slug": "recycling",
             "request": "exchange/rewrites/20261006/recycling__99.request.json",
             "answer_path": "exchange/rewrites/20261006/recycling__99.answer.json"},
            {"id": "genz-drinking__ad4d", "slug": "genz-drinking",
             "request": "exchange/rewrites/20261006/genz-drinking__ad4d.request.json",
             "answer_path": REWRITE_ANSWER}]},
        "exchange/rewrites/20261006/recycling__99.request.json": blocked,
        "exchange/rewrites/20261006/genz-drinking__ad4d.request.json": rewrite_request(),
        "exchange/asks/OPEN.json": {"schema": "shorts-ask-index/v1", "open": [
            {"batch": "exchange/asks/20260921.json", "answer_path": "exchange/asks/20260921.answers.json",
             "keys": ["old"]},
            {"batch": "exchange/asks/20261006.json", "answer_path": "exchange/asks/20261006.answers.json",
             "keys": ["k1"]}]},
        "exchange/asks/20261006.json": {"answer_path": "exchange/asks/20261006.answers.json",
                                        "asks": {"k1": {"system": "Answer true or false.", "user": "Is it?"}}},
    }


class AWholeRoundWritesAValidVerdictAndRewrite(Isolated):
    def test_one_round_against_stubbed_reads_api_and_models(self):
        files = {k: json.dumps(v) for k, v in mailbox_files().items()}
        api = FakeGitHub()
        fetched = []

        def fetch(url):
            fetched.append(url)
            return b"\xff\xd8jpeg"

        looked = []

        def claude_look(req, folder, images):
            looked.append(sorted(p.name for p in folder.iterdir()))
            return shorts_mailbox.validate_grades(good_grades())

        def think(system, text, *, validator=None, **kw):
            value = good_words() if "segments" in system else {"answer": "true"}
            return validator(value), "claude.cli:sonnet"

        report = shorts_mailbox.once(force=True, fleet=self.fleet, read=files.get, request=api,
                                     fetch=fetch, routes=[("claude", claude_look)], think=think,
                                     now=chicago(2026, 10, 7, 6, 40), tz=CHICAGO)
        self.assertEqual(report["outcome"], "ok")
        self.assertNotIn("https://example.com/x.jpg", fetched)
        self.assertEqual(looked, [["f00.jpg", "f01.jpg", "sheet.jpg"]])

        verdict = json.loads(api.files[REVIEW_ANSWER])
        self.assertEqual(verdict["schema"], "shorts-review-verdict/v1")
        self.assertEqual((verdict["request_id"], verdict["video_sha256"], verdict["by"]),
                         (REVIEW_ID, SHA, "aletheia:claude"))
        self.assertEqual(shorts_mailbox.validate_grades(verdict["grades"]), verdict["grades"])
        self.assertFalse({"score", "verdict", "ship", "block"} & (set(verdict) | set(verdict["grades"])))

        answer = json.loads(api.files[REWRITE_ANSWER])
        self.assertEqual((answer["schema"], answer["request_id"], answer["slug"], answer["by"]),
                         ("shorts-rewrite-answer/v1", "genz-drinking__ad4d", "genz-drinking", "aletheia:claude"))
        self.assertEqual(len(answer["segments"]), 2)
        self.assertNotIn("exchange/rewrites/20261006/recycling__99.answer.json", api.files,
                         "a rewrite whose video still waits on a review must wait too")

        asked = json.loads(api.files["exchange/asks/20261006.answers.json"])
        self.assertEqual(asked["answers"]["k1"]["answer"], "true")
        self.assertNotIn("exchange/asks/20260921.answers.json", api.files, "only the newest batch")

        for _, _, body in api.puts():
            self.assertEqual(body["message"], "exchange: mailbox round 20261007 (aletheia)")
        latest = json.loads((self.tmp / "mailbox" / "latest.json").read_text())
        self.assertEqual(latest["outcome"], "ok")
        self.assertFalse((self.tmp / "mailbox" / "run.json").exists(), "the lock is released")

    def test_a_grade_nobody_could_give_is_not_written(self):
        files = {k: json.dumps(v) for k, v in mailbox_files().items()}
        api = FakeGitHub()

        def bad_look(req, folder, images):
            g = good_grades()
            g["dimensions"]["hook"] = 3.5
            return shorts_mailbox.validate_grades(g)

        def resting(req, folder, images):
            raise reasoner.ReasonerUnavailable("Codex is out")

        report = shorts_mailbox.once(force=True, fleet=self.fleet, read=files.get, request=api,
                                     fetch=lambda u: b"x", routes=[("claude", bad_look), ("codex", resting)],
                                     think=mock.Mock(side_effect=reasoner.ReasonerUnavailable("nobody")))
        self.assertNotIn(REVIEW_ANSWER, api.files)
        self.assertIn("nobody could grade", report["reviews"][0]["skipped"])
        self.assertEqual(api.puts(), [])

    def test_two_rounds_never_overlap(self):
        shorts_mailbox.state_dir().mkdir(parents=True)
        (shorts_mailbox.state_dir() / "run.json").write_text(json.dumps(
            {"pid": os.getpid(), "started_epoch": time.time()}))
        with mock.patch("aletheia.proc.pid_alive", return_value=True):
            out = shorts_mailbox.once(force=True, fleet=self.fleet, read=lambda p: None, request=FakeGitHub())
        self.assertEqual(out["outcome"], "busy")


if __name__ == "__main__":
    unittest.main()
