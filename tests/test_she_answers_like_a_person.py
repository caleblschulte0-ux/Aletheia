"""What she says back, judged by whether a person would say it.

Found by actually talking to her through the Core, 2026-09-06. Every one
of these was correct data delivered in a way that fails him:

    "free on 2026-09-07 at 09:00, 09:15, 09:30, 09:45 and more"
    "I can't do room.scene yet; filed 1 build task(s)."
    "1 step ready — free_time. Say approve to run it (intent-0a06bbb663)."

The first one is worse than it looks: he asked about the AFTERNOON, and
the nine o'clock is the qualifier being silently dropped. Answering a
different question than the one asked is the failure he cannot detect.
"""
import datetime as dt
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

import tempfile
from pathlib import Path

from aletheia import (calendar as cal, intents, intercom, planner,
                      policy, speech, voice)

CHICAGO = ZoneInfo("America/Chicago")


class HeSaidAfternoonCase(unittest.TestCase):
    """A part of the day is half of what he asked."""

    def slots(self, day="2026-09-07"):
        return cal.free_slots(dt.date.fromisoformat(day), duration_minutes=30,
                              timezone="America/Chicago", events=[])

    def test_the_qualifier_reaches_the_command(self):
        got = voice.interpret("thea am i free tomorrow afternoon")["command"]
        self.assertEqual(got["kind"], "free_time")
        self.assertEqual(got["part"], "afternoon")

    def test_afternoon_really_filters_the_hours(self):
        kept = cal.in_part(self.slots(), "afternoon")
        self.assertTrue(kept)
        for start, _end in kept:
            self.assertGreaterEqual(dt.datetime.fromisoformat(start).hour, 12)

    def test_no_part_named_means_the_whole_day(self):
        self.assertEqual(len(cal.in_part(self.slots(), "")), len(self.slots()))

    def test_an_unknown_word_does_not_silently_filter_everything(self):
        """Refusing to answer is fine; answering "you're never free" is not."""
        self.assertEqual(len(cal.in_part(self.slots(), "elevenses")),
                         len(self.slots()))

    def test_fifteen_minute_steps_become_stretches_of_time(self):
        merged = cal.merge_slots(self.slots())
        self.assertEqual(len(merged), 1, "an empty day is one free stretch")
        self.assertTrue(merged[0][0].endswith("09:00:00-05:00"))
        self.assertTrue(merged[0][1].endswith("17:00:00-05:00"))

    def test_a_meeting_splits_the_day_into_two_stretches(self):
        booked = [{"version": 1, "id": "e1", "title": "Standup",
                   "start": "2026-09-07T11:00:00-05:00",
                   "end": "2026-09-07T13:00:00-05:00", "status": "CONFIRMED",
                   "attendees": [], "created_at": "2026-09-01T00:00:00Z",
                   "updated_at": "2026-09-01T00:00:00Z"}]
        slots = cal.free_slots(dt.date(2026, 9, 7), duration_minutes=30,
                               timezone="America/Chicago", events=booked)
        self.assertEqual(len(cal.merge_slots(slots)), 2)


class TheSentenceCase(unittest.TestCase):
    """"free on 2026-09-07 at 09:00, 09:15, 09:30, 09:45 and more"."""

    def sentence(self, ranges, part="", day=dt.date(2026, 9, 7)):
        with mock.patch("aletheia.localtime.operator_tz", lambda: CHICAGO), \
             mock.patch("aletheia.speech.humanize_time",
                        lambda stamp, now=None: "tomorrow at 12 pm"):
            return intercom._free_sentence(ranges, day, part)

    def test_it_reads_as_a_stretch_of_time(self):
        said = self.sentence([("2026-09-07T12:00:00-05:00",
                               "2026-09-07T17:00:00-05:00")], "afternoon")
        self.assertEqual(said, "Free tomorrow afternoon 12 pm to 5 pm.")

    def test_no_machine_dates_and_no_machine_clocks(self):
        said = self.sentence([("2026-09-07T09:00:00-05:00",
                               "2026-09-07T17:00:00-05:00")])
        self.assertNotIn("2026-09-07", said)
        self.assertNotIn("09:00", said)

    def test_two_stretches_are_joined_the_way_a_person_joins_them(self):
        said = self.sentence([("2026-09-07T09:00:00-05:00",
                               "2026-09-07T11:00:00-05:00"),
                              ("2026-09-07T13:00:00-05:00",
                               "2026-09-07T17:00:00-05:00")])
        self.assertIn("9 am to 11 am and 1 pm to 5 pm", said)

    def test_an_empty_evening_says_why_it_is_empty(self):
        """"Nothing free this evening" alone is misleading — she only ever
        looks at working hours, so of course the evening is empty."""
        said = self.sentence([], "evening")
        self.assertIn("nine to five", said)

    def test_an_empty_afternoon_does_not_blame_the_work_window(self):
        said = self.sentence([], "afternoon")
        self.assertNotIn("nine to five", said)

    def test_today_takes_this_not_today(self):
        with mock.patch("aletheia.speech.humanize_time",
                        lambda stamp, now=None: "today at 12 pm"):
            said = intercom._free_sentence(
                [("2026-09-06T13:00:00-05:00", "2026-09-06T17:00:00-05:00")],
                dt.date(2026, 9, 6), "afternoon")
        self.assertIn("this afternoon", said)
        self.assertNotIn("today afternoon", said)


class NamingDaysCase(unittest.TestCase):
    def test_a_weekday_is_a_day(self):
        """Every weekday name used to come back "I couldn't parse the day"."""
        got = voice._spoken_day("friday")
        self.assertIsNotNone(got)
        self.assertEqual(dt.date.fromisoformat(got).strftime("%A"), "Friday")
        self.assertGreaterEqual(dt.date.fromisoformat(got), dt.date.today())

    def test_this_friday_is_the_same_friday(self):
        self.assertEqual(voice._spoken_day("this friday"),
                         voice._spoken_day("friday"))

    def test_next_friday_is_asked_about_rather_than_guessed(self):
        """It means the coming Friday to half the people who say it and the
        one after to the other half. Picking silently is how she confirms
        the wrong thing confidently."""
        said = voice.interpret("thea am i free next friday")
        self.assertIsNone(said["command"])
        self.assertIn("Which Friday", said["say"])
        self.assertRegex(said["say"], r"\d+(st|nd|rd|th)")

    def test_ordinals_are_sayable(self):
        self.assertEqual(
            [voice._ordinal(d) for d in (1, 2, 3, 11, 12, 13, 21, 22, 23)],
            ["1st", "2nd", "3rd", "11th", "12th", "13th", "21st", "22nd", "23rd"])

    def test_asking_is_instant_and_never_reaches_the_planner(self):
        """It fell through to the planner before — six and a half seconds
        for a question she can answer from a date and a calendar file."""
        self.assertIsNotNone(voice.interpret("thea am i free tomorrow")["command"])
        self.assertIsNotNone(
            voice.interpret("thea do i have time this afternoon")["command"])


class NotYetCase(unittest.TestCase):
    """"I can't do room.scene yet; filed 1 build task(s)." """

    def test_a_capability_id_is_never_spoken(self):
        said = intents._cannot_yet([{"capability": "room.scene"}],
                                   {"gap_tasks": ["t1"]})
        self.assertNotIn("room.scene", said)
        self.assertNotIn("(s)", said)

    def test_something_waiting_on_him_gives_him_the_command(self):
        said = intents._cannot_yet([{"capability": "room.scene"}], {})
        self.assertIn("python -m aletheia.apply room", said)
        self.assertIn("needs setting up", said)

    def test_something_that_does_not_exist_says_so_instead(self):
        """A hub he has not connected and a capability nobody has written
        are different answers. They used to be the same sentence."""
        said = intents._cannot_yet([{"capability": "message.send"}],
                                   {"gap_tasks": ["t1"]})
        self.assertIn("text message", said)
        self.assertIn("build list", said)
        self.assertNotIn("needs setting up", said)

    def test_the_registry_supplies_the_english(self):
        self.assertIn("text message", intents._in_english("message.send"))
        self.assertNotIn("message.send", intents._in_english("message.send"))

    def test_an_unknown_capability_still_produces_a_sentence(self):
        said = intents._in_english("nothing.at-all")
        self.assertTrue(said.strip())

    def test_a_broken_registry_does_not_break_her_mouth(self):
        with mock.patch("aletheia.capabilities.get",
                        side_effect=RuntimeError("registry gone")):
            said = intents._cannot_yet([{"capability": "message.send"}], {})
        self.assertTrue(said.strip())


class TheApprovalIdCase(unittest.TestCase):
    def test_the_hex_id_is_not_read_out_loud(self):
        """§145: he approves by saying "approve". A hash is a handle he
        cannot hold in his head, and the sentence told him to say it back."""
        record = {
            "steps": [{"n": 1, "status": planner.EXECUTABLE,
                       "capability": "email.send",
                       "command": {"kind": "email_draft"}, "detail": ""}],
            "approval": "intent-0a06bbb663", "intent": "plan",
        }
        said = intents.spoken(record)
        self.assertNotIn("0a06bbb663", said)
        self.assertIn("Say approve", said)

    def test_a_tier_voice_cannot_approve_does_not_say_say_approve(self):
        """The room microphone is an input device, not an authentication
        device: voice may approve only the ROUTINE tier. Telling him to
        "say approve" for a desktop or world-touching plan sent him
        straight into a refusal, so the sentence names the surface that
        can actually take the decision."""
        from aletheia import intercom
        record = {
            "steps": [{"n": 1, "status": planner.EXECUTABLE,
                       "capability": "computer.act",
                       "command": {"kind": "computer"}, "detail": ""}],
            "approval": "intent-0a06bbb663", "intent": "plan",
            "tier": intercom.TIER_WORLD,
        }
        said = intents.spoken(record)
        self.assertNotIn("Say approve", said)
        self.assertIn("phone", said)

    def test_an_absent_tier_keeps_the_ordinary_wording(self):
        """An unknown tier is not evidence of a dangerous one. Treating it
        as one took "say approve" away from every caller that does not set
        a tier, which is the normal path."""
        record = {
            "steps": [{"n": 1, "status": planner.EXECUTABLE,
                       "capability": "task.create",
                       "command": {"kind": "task_new"}, "detail": ""}],
            "approval": "intent-0a06bbb663", "intent": "plan",
        }
        self.assertIn("Say approve", intents.spoken(record))

class TheKillSwitchIsNotGuessedAtCase(unittest.TestCase):
    """"Resume yourself" reached the planner, which is FORBIDDEN from
    emitting `resume` — so its only remaining move was to compile
    something else. It compiled `brief`, ran it, and answered "Resume
    normal operation and surface current state" while resuming nothing.

    A silent substitution is bad anywhere. On the kill switch it is the
    difference between an emergency control that works and one that
    reports success.
    """

    def command(self, sentence):
        return voice.interpret(f"thea {sentence}")

    def test_the_reflexive_phrasings_really_resume(self):
        for sentence in ("resume yourself", "unhalt yourself", "un-halt thea",
                         "lift the halt", "turn yourself back on",
                         "resume aletheia please", "resume now"):
            with self.subTest(sentence=sentence):
                got = self.command(sentence)["command"]
                self.assertEqual(got, {"kind": "resume"}, sentence)

    def test_an_order_about_her_switch_that_does_not_match_asks_for_the_word(self):
        """One syllable is the honest answer; a substituted action is not."""
        said = self.command("resume it for me")
        self.assertIsNone(said["command"])
        self.assertIn("resume", said["say"])

    def test_it_never_reaches_the_planner(self):
        for sentence in ("resume yourself", "unhalt aletheia", "resume it now"):
            with self.subTest(sentence=sentence):
                got = self.command(sentence)["command"]
                self.assertNotEqual((got or {}).get("kind"), "intent", sentence)

    def test_an_ordinary_sentence_that_starts_with_the_same_verb_is_untouched(self):
        """"Resume the download" and "stop the music" are not the kill
        switch, and swallowing them would trade one silent substitution
        for another."""
        for sentence in ("resume the download when you can", "stop the music",
                         "read my resume"):
            with self.subTest(sentence=sentence):
                got = self.command(sentence)["command"] or {}
                self.assertNotIn(got.get("kind"), ("resume", "halt"), sentence)

    def test_the_resume_noun_still_does_not_unhalt_her(self):
        """The English noun is the same six letters as the kind that lifts
        the kill switch — the reason this pattern is a fullmatch."""
        got = self.command("read my resume")["command"] or {}
        self.assertNotEqual(got.get("kind"), "resume")


class ReadingIsNotOnlyTheWebCase(unittest.TestCase):
    """"Read my resume" answered "I need a web address to read".

    `read|open|check|look at` assumed a URL and dead-ended on anything
    else — including a FILE she can genuinely read, and one of the
    sentences he is most likely to say.
    """

    def test_a_file_reaches_the_planner_instead_of_being_refused(self):
        got = voice.interpret("thea read my resume")
        self.assertEqual((got["command"] or {}).get("kind"), "intent")
        self.assertNotIn("web address", str(got["say"]))

    def test_a_real_url_still_goes_straight_to_the_browser(self):
        for sentence in ("read example.com", "browse reddit.com",
                         "read https://example.com"):
            with self.subTest(sentence=sentence):
                got = voice.interpret(f"thea {sentence}")["command"]
                self.assertEqual(got["kind"], "browse_read")


class LookingForWorkCase(unittest.TestCase):
    """"How many jobs are open at Anthropic" spent 94 seconds driving a
    browser at the open web and failed. `jobs.search` answers from the
    boards' own APIs in three — the planner simply had no verb for it."""

    JOBS = [
        {"company": "Anthropic", "title": "Software Engineer",
         "location": "Austin, TX", "apply_url": "u", "id": "1",
         "provider": "greenhouse", "url": "u"},
        {"company": "Stripe", "title": "Software Engineer",
         "location": "Toronto", "apply_url": "u", "id": "2",
         "provider": "greenhouse", "url": "u"},
    ]

    def found(self, matches=None, failed=()):
        return {"matches": self.JOBS if matches is None else matches,
                "searched": 36, "matched": 2, "failed": list(failed),
                "role": "software engineer", "where": ""}

    def test_a_place_he_named_is_a_filter_not_a_preference(self):
        """`search` only PENALISES a location mismatch, so "react jobs in
        Austin" came back led by Toronto. Naming a city he did not ask for
        is the same defect as dropping "afternoon"."""
        with mock.patch("aletheia.jobs.search", return_value=self.found()):
            said = intercom._jobs_answer(
                {"role": "software engineer", "where": "austin"})
        self.assertIn("Anthropic", said)
        self.assertNotIn("Toronto", said)

    def test_remote_counts_as_anywhere(self):
        remote = [dict(self.JOBS[1], location="Remote - US")]
        with mock.patch("aletheia.jobs.search", return_value=self.found(remote)):
            said = intercom._jobs_answer(
                {"role": "software engineer", "where": "austin"})
        self.assertIn("Stripe", said)

    def test_nothing_in_that_city_says_so_rather_than_offering_elsewhere(self):
        with mock.patch("aletheia.jobs.search",
                        return_value=self.found([self.JOBS[1]])):
            said = intercom._jobs_answer(
                {"role": "software engineer", "where": "austin"})
        self.assertIn("Nothing open", said)
        self.assertIn("austin", said)

    def test_a_company_count_needs_no_role_at_all(self):
        """Demanding a role is exactly why the planner could not use this
        for "how many jobs are open at Anthropic"."""
        board = {"provider": "greenhouse", "token": "anthropic",
                 "company": "Anthropic"}
        with mock.patch("aletheia.jobs.boards", return_value=[board]), \
             mock.patch.dict("aletheia.jobs.PROVIDERS",
                             {"greenhouse": lambda b: self.JOBS}):
            said = intercom._jobs_answer({"company": "anthropic"})
        self.assertIn("Anthropic", said)
        self.assertIn("2 open", said)

    def test_a_company_she_does_not_follow_says_where_the_list_lives(self):
        with mock.patch("aletheia.jobs.boards", return_value=[]):
            said = intercom._jobs_answer({"company": "acme"})
        self.assertIn("job_boards.json", said)

    def test_no_role_and_no_company_asks_rather_than_guessing(self):
        said = intercom._jobs_answer({})
        self.assertIn("What kind of role", said)

    def test_a_board_that_did_not_answer_is_mentioned(self):
        """Fewer companies searched than the file claims is worth saying."""
        with mock.patch("aletheia.jobs.search",
                        return_value=self.found(failed=[{"board": "x",
                                                         "company": "X"}])):
            said = intercom._jobs_answer({"role": "software engineer"})
        self.assertIn("didn't answer", said)

    def test_looking_for_work_needs_no_approval(self):
        self.assertIn("jobs", intercom.READ_ONLY_KINDS)

class SayingNoCase(unittest.TestCase):
    """"Cancel that" asked for an approval in order to cancel an approval.

    The deny pattern was "deny/denied/no to" only, so every natural way of
    saying no fell to the planner — which is forbidden from emitting
    `deny`, so it compiled something else and offered THAT: "1 step ready
    — Cancel the pending approval waiting on his decision. Say approve to
    run it."
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        for target, attr in ((policy, "APPROVALS_DIR"), (policy, "HALT_PATH")):
            p = mock.patch.object(target, attr, d / attr.lower())
            p.start(); self.addCleanup(p.stop)

    def test_the_words_he_would_actually_use_deny_the_pending_one(self):
        sentences = ("cancel that", "cancel it", "never mind", "nevermind",
                     "forget it", "forget that", "drop it", "scrap that",
                     "call it off", "don't do that", "deny")
        for n, sentence in enumerate(sentences):
            with self.subTest(sentence=sentence):
                aid = f"ap-{n}"   # exactly one PENDING at a time
                policy.request(aid, "a", "r", "c", True,
                               capability="journal.append")
                got = voice.interpret(f"thea {sentence}")["command"]
                self.assertIsNotNone(got, sentence)
                self.assertEqual(got["kind"], "deny", sentence)
                self.assertEqual(got["id"], aid, sentence)
                policy.decide(aid, "DENIED", via="test")

    def test_cancelling_a_real_thing_is_not_a_denial(self):
        """"Cancel my gym membership" must still reach the capability that
        really cancels things."""
        got = voice.interpret("thea cancel my gym membership")["command"]
        self.assertEqual(got["kind"], "intent")

    def test_with_several_waiting_it_asks_in_HIS_verb(self):
        """Answering "never mind" with "say approve the first" tells him to
        do the opposite of what he just asked for."""
        policy.request("ap-1", "a", "r", "c", True)
        policy.request("ap-2", "b", "r", "c", True)
        said = voice.interpret("thea never mind")["say"]
        self.assertIn("say deny the first", said)
        self.assertNotIn("say approve", said)
        self.assertNotIn("Command Center", said)

    def test_nothing_waiting_says_so(self):
        self.assertIn("Nothing is waiting",
                      voice.interpret("thea forget it")["say"])


class ConverseIsSpeechTooCase(unittest.TestCase):
    """`converse` reads her stores, so its answers carry the ids in them —
    "there are two pending approvals (intent-1b32747ddb, intent-a3d2ad3434)"
    — read out loud, in a room. It goes through the same sieve now."""

    def test_ids_in_a_conversational_answer_are_stripped(self):
        said = speech.tidy(speech.strip_ids(
            "two pending approvals (intent-1b32747ddb, intent-a3d2ad3434) "
            "and 2 unread notifications"))
        self.assertNotIn("1b32747ddb", said)
        self.assertNotIn("(", said)
        self.assertIn("two pending approvals", said)

    def test_parentheses_with_real_words_survive(self):
        self.assertEqual(speech.tidy("a note (see below) stays"),
                         "a note (see below) stays")

class ApprovingSaysWhatWasApprovedCase(unittest.TestCase):
    """"approval intent-0a06bbb663 -> APPROVED" was the receipt, and once
    the id was stripped the room heard "approval -> APPROVED": an arrow,
    out loud, saying nothing about what he had just authorised."""

    def test_the_label_is_what_will_happen(self):
        """The reason on an intent approval is `operator said: "spoken to
        the wall: thea remember that my landlord is called Mr Okafor"` — a
        quote inside a quote inside a transport label, truncated mid-word
        when read out. The consequence is the plan's own summary."""
        said = voice.approval_label({
            "capability": "intent.execute.routine",
            "requested_action": "run 1 step(s): remember",
            "reason": 'operator said: "spoken to the wall: thea remember '
                      'that my landlord is called Mr Okafor"',
            "consequence": "Remember the landlord's name is Mr Okafor"})
        self.assertEqual(said, "Remember the landlord's name is Mr Okafor")

    def test_a_placeholder_consequence_falls_back_to_his_words(self):
        said = voice.approval_label({
            "capability": "x", "requested_action": "a",
            "reason": 'operator said: "spoken to the wall: thea book a table"',
            "consequence": "see the plan"})
        self.assertEqual(said, "book a table")

    def test_the_transport_labels_are_peeled_off(self):
        for wrapped in ('operator said: "spoken to the wall: thea do the thing"',
                        'typed into the command center: do the thing',
                        'operator said: "do the thing"'):
            with self.subTest(reason=wrapped):
                self.assertEqual(voice._unwrap(wrapped).rstrip('"'),
                                 "do the thing")

    def test_the_spoken_receipt_names_it(self):
        said = speech.spoken_receipt(
            "approve", "approved — Remember the landlord's name")
        self.assertEqual(said, "Approved: Remember the landlord's name.")
        self.assertNotIn("->", said)

class EveryPathThroughHerMouthCase(unittest.TestCase):
    """`spoken()` is the last thing between a record and the room. Three of
    its branches returned model prose straight through — and model prose
    about her own state carries her ids in it:

        "the only open item I see is a pending approval
         (intent-7aed1b5dcd) waiting on you"
    """

    def test_a_clarifying_question_is_stripped(self):
        said = intents.spoken({
            "intent": "clarify",
            "summary": "Which one? A pending approval (intent-7aed1b5dcd) "
                       "is waiting on you."})
        self.assertNotIn("7aed1b5dcd", said)
        self.assertIn("Which one", said)

    def test_a_read_only_answer_is_stripped(self):
        said = intents.spoken({
            "intent": "answer", "read_only": True,
            "receipts": [{"outcome": "done",
                          "detail": "run-a1b2c3d4e5f6 finished"}]})
        self.assertNotIn("a1b2c3d4e5f6", said)

    def test_a_direct_work_answer_is_stripped(self):
        said = intents.spoken({
            "direct_work": True,
            "spoken": "did it — session work-9f8e7d6c5b4a3210"})
        self.assertNotIn("9f8e7d6c5b4a3210", said)

    def test_a_record_missing_its_steps_still_produces_a_sentence(self):
        """A KeyError here is silence where a sentence should be."""
        self.assertTrue(intents.spoken({}).strip())
        self.assertTrue(intents.spoken({"intent": "plan"}).strip())



if __name__ == "__main__":
    unittest.main()
