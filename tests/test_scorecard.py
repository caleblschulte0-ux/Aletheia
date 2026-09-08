"""What the local model has earned, and what it can never earn.

Two kinds of test here and they matter differently.

The PROMOTION tests pin thresholds so a change to them is deliberate.
The SAFETY tests pin the things no amount of good performance may buy:
authority over dangerous work, and any authority at all over what may be
DONE. A scoreboard that can promote its way past a gate is not a
scoreboard, it is a back door.

The latency tests are the ones this system usually lacks. Measured on
this PC, local answers a short question in 2.4s and writes a two-sentence
email in 12.1s against a ~3.6s round trip - so a local model can be
excellent and still be the wrong choice, and promoting it on quality
alone would make his experience worse while the numbers said it was
improving.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from aletheia import agreement, scorecard


def _feed(task, n, *, ok=True, agreed=True, local_ms=1000, frontier_ms=3600,
          corrected=False, fingerprint="model@v1"):
    """Drive real `record()` calls. Use where the SEQUENCE is the point."""
    for _ in range(n):
        scorecard.record(task, fingerprint=fingerprint, ok=ok, agreed=agreed,
                         local_ms=local_ms, frontier_ms=frontier_ms,
                         corrected=corrected)


def _seed(task, n, *, ok=True, agreed=True, local_ms=1000, frontier_ms=3600,
          corrected=False, fingerprint="model@v1"):
    """Write one store representing n outcomes.

    Equivalent to `_feed` for everything the promotion rules read, and one
    disk write instead of n. The write path is covered separately; this is
    for the tests that are about the THRESHOLDS.
    """
    record = scorecard._blank(task, fingerprint)
    record.update(
        attempts=n,
        valid=n if ok else 0,
        compared=n if agreed is not None else 0,
        agreed=n if agreed else 0,
        corrections=n if corrected else 0,
        recent=[bool(ok)] * min(n, scorecard.RECENT),
        local_ms=([int(local_ms)] * min(n, scorecard.RECENT)
                  if local_ms is not None else []),
        frontier_ms=([int(frontier_ms)] * min(n, scorecard.RECENT)
                     if frontier_ms is not None else []),
    )
    record["status"] = scorecard._earned(record, task)[0]
    scorecard.stateio.write_json_atomic(scorecard._path(task), record)
    return record


class ScorecardCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ,
                            {"ALETHEIA_PRIVATE_STATE": self.tmp.name})
        p.start(); self.addCleanup(p.stop)


class StartsClosedCase(ScorecardCase):
    def test_nothing_is_trusted_before_it_is_measured(self):
        self.assertEqual(scorecard.status("simple_qa"), scorecard.UNPROVEN)
        self.assertEqual(scorecard.route_for("simple_qa"),
                         scorecard.ROUTE_FRONTIER)

    def test_every_task_type_starts_at_the_frontier(self):
        for kind in scorecard.everything():
            with self.subTest(task=kind):
                self.assertEqual(scorecard.everything()[kind]["route"],
                                 scorecard.ROUTE_FRONTIER)


class PromotionCase(ScorecardCase):
    def test_a_few_good_answers_are_not_enough(self):
        _seed("simple_qa", scorecard.LEARNING_AFTER + 1)
        self.assertEqual(scorecard.status("simple_qa"), scorecard.LEARNING)

    def test_thirty_good_fast_answers_reach_candidate(self):
        _seed("simple_qa", scorecard.CANDIDATE_ATTEMPTS)
        self.assertEqual(scorecard.status("simple_qa"), scorecard.CANDIDATE)
        self.assertEqual(scorecard.route_for("simple_qa"),
                         scorecard.ROUTE_HEDGED)

    def test_a_hundred_good_fast_answers_certify(self):
        _seed("simple_qa", scorecard.CERTIFIED_ATTEMPTS + 5)
        self.assertEqual(scorecard.status("simple_qa"), scorecard.CERTIFIED)
        self.assertEqual(scorecard.route_for("simple_qa"),
                         scorecard.ROUTE_LOCAL)

    def test_disagreeing_answers_never_certify(self):
        _seed("simple_qa", 150, agreed=False)
        self.assertNotEqual(scorecard.status("simple_qa"), scorecard.CERTIFIED)

    def test_unjudgeable_pairs_do_not_vote(self):
        """`agreed=None` is not agreement and not disagreement."""
        _seed("simple_qa", 150, agreed=None)
        record = scorecard.read("simple_qa")
        self.assertEqual(record["compared"], 0)
        self.assertNotEqual(scorecard.status("simple_qa"), scorecard.CERTIFIED)

    def test_corrections_hold_it_back(self):
        _seed("simple_qa", 150, corrected=True)
        self.assertEqual(scorecard.status("simple_qa"), scorecard.LEARNING)


class LatencyIsAGateCase(ScorecardCase):
    def test_good_but_slow_never_certifies(self):
        """The whole point. 97% as good and 4x slower has earned nothing."""
        _seed("simple_qa", 150, local_ms=14000, frontier_ms=3600)
        self.assertEqual(scorecard.status("simple_qa"), scorecard.CANDIDATE)
        self.assertIn("slower", scorecard.explain("simple_qa")["why_latency"])

    def test_good_and_fast_certifies(self):
        _seed("simple_qa", 150, local_ms=2400, frontier_ms=3600)
        self.assertEqual(scorecard.status("simple_qa"), scorecard.CERTIFIED)

    def test_a_little_slower_is_still_allowed(self):
        """LATENCY_MARGIN exists: independence is worth a small cost."""
        inside = int(3600 * scorecard.LATENCY_MARGIN) - 50
        _seed("simple_qa", 150, local_ms=inside, frontier_ms=3600)
        self.assertEqual(scorecard.status("simple_qa"), scorecard.CERTIFIED)

    def test_without_a_frontier_timing_nothing_certifies(self):
        """No comparison means no evidence, not benefit of the doubt."""
        _seed("simple_qa", 150, local_ms=100, frontier_ms=None)
        self.assertNotEqual(scorecard.status("simple_qa"), scorecard.CERTIFIED)


class RiskCase(ScorecardCase):
    def test_dangerous_work_never_certifies_on_evidence_alone(self):
        for task in ("coding", "debugging", "planning", "action", "research"):
            with self.subTest(task=task):
                _seed(task, 200, local_ms=100, frontier_ms=9000)
                self.assertNotEqual(scorecard.status(task), scorecard.CERTIFIED)

    def test_being_good_at_trivia_does_not_promote_anything_else(self):
        _seed("simple_qa", 150)
        self.assertEqual(scorecard.status("simple_qa"), scorecard.CERTIFIED)
        self.assertEqual(scorecard.status("planning"), scorecard.UNPROVEN)

    def test_unknown_work_is_treated_as_the_most_dangerous(self):
        self.assertEqual(scorecard.risk_of("unknown"), scorecard.RISK_CRITICAL)
        self.assertEqual(scorecard.risk_of("a task nobody defined"),
                         scorecard.RISK_CRITICAL)


class DemotionCase(ScorecardCase):
    def test_a_certified_model_that_starts_failing_is_demoted(self):
        _seed("simple_qa", 150)
        self.assertEqual(scorecard.status("simple_qa"), scorecard.CERTIFIED)
        _feed("simple_qa", scorecard.DEMOTE_WINDOW, ok=False, agreed=False)
        self.assertEqual(scorecard.status("simple_qa"), scorecard.PROBATION)
        self.assertEqual(scorecard.route_for("simple_qa"),
                         scorecard.ROUTE_FRONTIER)

    def test_probation_can_be_set_by_hand(self):
        _seed("simple_qa", 150)
        scorecard.probation("simple_qa", "he said so")
        self.assertEqual(scorecard.status("simple_qa"), scorecard.PROBATION)

    def test_a_different_model_does_not_inherit_certification(self):
        """Evidence is about a thing, and the thing changed."""
        _seed("simple_qa", 150, fingerprint="qwen3:8b@v1")
        self.assertEqual(scorecard.status("simple_qa", fingerprint="qwen3:8b@v1"),
                         scorecard.CERTIFIED)
        self.assertNotEqual(
            scorecard.status("simple_qa", fingerprint="something-else@v2"),
            scorecard.CERTIFIED)

    def test_recording_under_a_new_model_starts_the_evidence_again(self):
        _seed("simple_qa", 150, fingerprint="qwen3:8b@v1")
        scorecard.record("simple_qa", fingerprint="new-model@v2", ok=True)
        self.assertEqual(scorecard.read("simple_qa")["attempts"], 1)

    def test_reset_forgets_everything(self):
        _seed("simple_qa", 150)
        scorecard.reset("simple_qa")
        self.assertEqual(scorecard.status("simple_qa"), scorecard.UNPROVEN)


class ShadowGivesUpCase(ScorecardCase):
    """Training must never cost him interactive speed for nothing.

    There is no GPU on this machine, so a background student is four
    pegged cores. Spending them to re-learn that a model is three times
    too slow is the exact trade the plan says never to make.
    """

    def test_it_keeps_learning_while_local_is_competitive(self):
        _seed("simple_qa", 40, local_ms=2400, frontier_ms=3600)
        worth, _ = scorecard.worth_shadowing("simple_qa")
        self.assertTrue(worth)

    def test_it_gives_up_when_local_is_hopelessly_slow(self):
        _seed("writing", 40, local_ms=12100, frontier_ms=3600)
        worth, why = scorecard.worth_shadowing("writing")
        self.assertFalse(worth)
        self.assertIn("slower" if "slower" in why else "more than", why)

    def test_it_does_not_give_up_on_a_handful_of_samples(self):
        """A cold model load is not proof of anything."""
        _seed("writing", scorecard.GIVE_UP_AFTER - 1,
              local_ms=99000, frontier_ms=1000)
        self.assertTrue(scorecard.worth_shadowing("writing")[0])

    def test_it_stops_once_local_is_already_answering(self):
        _seed("simple_qa", 150, local_ms=2400, frontier_ms=3600)
        self.assertEqual(scorecard.status("simple_qa"), scorecard.CERTIFIED)
        self.assertFalse(scorecard.worth_shadowing("simple_qa")[0])

    def test_giving_up_is_recoverable(self):
        """Reset, or a new model, and it starts measuring again."""
        _seed("writing", 40, local_ms=12100, frontier_ms=3600)
        self.assertFalse(scorecard.worth_shadowing("writing")[0])
        scorecard.reset("writing")
        self.assertTrue(scorecard.worth_shadowing("writing")[0])

    def test_a_skip_is_recorded_rather_than_silent(self):
        scorecard.note_skip("writing", "too slow to be worth it")
        record = scorecard.read("writing")
        self.assertEqual(record["skips"], 1)
        self.assertIn("too slow", record["last_skip"])

    def test_when_in_doubt_it_shadows(self):
        with mock.patch.object(scorecard, "read",
                               side_effect=OSError("no store")):
            self.assertTrue(scorecard.worth_shadowing("simple_qa")[0])


class FailsOpenCase(ScorecardCase):
    def test_an_unreadable_store_means_the_frontier_answers(self):
        with mock.patch.object(scorecard, "read",
                               side_effect=OSError("disk gone")):
            self.assertEqual(scorecard.status("simple_qa"), scorecard.UNPROVEN)
            self.assertEqual(scorecard.route_for("simple_qa"),
                             scorecard.ROUTE_FRONTIER)

    def test_a_failed_write_is_never_raised_at_the_caller(self):
        """Evidence is not worth a broken reply."""
        with mock.patch("aletheia.stateio.write_json_atomic",
                        side_effect=OSError("read-only")):
            self.assertEqual(scorecard.record("simple_qa", ok=True), {})

    def test_corrupt_json_reads_as_no_evidence(self):
        path = scorecard._path("simple_qa")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json at all", encoding="utf-8")
        self.assertEqual(scorecard.status("simple_qa"), scorecard.UNPROVEN)


class ItStoresNoContentCase(ScorecardCase):
    def test_the_store_holds_no_prompt_and_no_answer(self):
        """Why this needs no training opt-in.

        Credential redaction is not privacy redaction, so the
        content-bearing corpus stays behind his setting. This store is
        counts and milliseconds, and the test says so rather than the
        docstring saying so.
        """
        scorecard.record("simple_qa", fingerprint="m@1", ok=True, agreed=True,
                         local_ms=900, frontier_ms=3600)
        raw = scorecard._path("simple_qa").read_text(encoding="utf-8")
        for leak in ("prompt", "answer", "context", "text", "response"):
            self.assertNotIn(leak, raw.lower())

    def test_recorded_fields_are_only_numbers_and_flags(self):
        scorecard.record("simple_qa", fingerprint="m@1", ok=True, agreed=True,
                         local_ms=900, frontier_ms=3600)
        record = scorecard.read("simple_qa")
        for key, value in record.items():
            if key in ("task_type", "fingerprint", "status",
                       "probation_reason", "updated_at"):
                continue
            with self.subTest(key=key):
                self.assertIsInstance(value, (int, float, list, bool))


class CertificationBuysNoAuthorityCase(ScorecardCase):
    def test_the_scoreboard_cannot_reach_any_gate(self):
        """No amount of good performance may touch what is PERMITTED."""
        with open(scorecard.__file__, encoding="utf-8") as handle:
            source = handle.read()
        for forbidden in ("policy", "approval", "intercom", "execute",
                          "webtask", "halt", "subprocess", "capabilities"):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, source.lower(),
                                 f"{forbidden} would let routing touch authority")

    def test_it_only_ever_answers_who_reasons(self):
        for kind in ("simple_qa", "planning", "action"):
            with self.subTest(task=kind):
                self.assertIn(scorecard.route_for(kind),
                              {scorecard.ROUTE_FRONTIER, scorecard.ROUTE_HEDGED,
                               scorecard.ROUTE_LOCAL})


class AgreementCase(unittest.TestCase):
    def test_matching_structured_answers_agree(self):
        self.assertIs(agreement.agrees({"answer": "Frank Herbert"},
                                       {"answer": "Frank Herbert"}), True)

    def test_different_structured_answers_disagree(self):
        self.assertIs(agreement.agrees({"answer": "Frank Herbert"},
                                       {"answer": "Isaac Asimov"}), False)

    def test_a_missing_field_is_a_real_difference(self):
        self.assertIs(agreement.agrees({"answer": "x", "confidence": 0.9},
                                       {"answer": "x"}), False)

    def test_disagreeing_numbers_decide_it(self):
        """"40 dollars" and "400 dollars" share every word but one fact."""
        self.assertIs(agreement.compare_text("it costs 40 dollars",
                                             "it costs 400 dollars"), False)

    def test_the_same_short_answer_worded_differently_agrees(self):
        self.assertIs(agreement.compare_text("Reykjavik is the capital",
                                             "The capital is Reykjavik"), True)

    def test_long_prose_is_not_judged_by_word_overlap(self):
        """Two good paragraphs share vocabulary whether or not they agree."""
        long_a = " ".join(f"word{i}" for i in range(120))
        long_b = " ".join(f"word{i}" for i in range(120))
        self.assertIsNone(agreement.compare_text(long_a, long_b))

    def test_it_says_it_cannot_tell_rather_than_guessing(self):
        self.assertIsNone(agreement.agrees(None, {"a": 1}))
        self.assertIsNone(agreement.agrees({"a": 1}, None))

    def test_a_comparator_failure_votes_none(self):
        with mock.patch.object(agreement, "compare_json",
                               side_effect=RuntimeError("boom")):
            self.assertIsNone(agreement.agrees({"a": 1}, {"a": 1}))


if __name__ == "__main__":
    unittest.main()
