"""Calendar reasoning: travel buffers, his timezone, free slots, holds, deadlines.

Held here: two things in different places are not back to back; a window and a
sentence are in HIS zone whatever the process thinks; a hold is local and says
what it clashes with; a live write keeps calendar.write's hash-bound approval
and runs once; a deadline wakes before it is due.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from aletheia import (calendar, calendar_provider, calendar_reasoning as cr, notifications, policy, work_engine,
                      work_states as ws)
from tests.conversation_fixture import TZ, Isolated

CHI = ZoneInfo(TZ)


def at(day, hour, minute=0):
    return dt.datetime(2026, 10, day, hour, minute, tzinfo=CHI)


class Conflicts(Isolated):
    def event(self, eid, start, minutes=60, location=None, status="CONFIRMED"):
        return calendar.create(eid, eid.title(), start.isoformat(), (start + dt.timedelta(minutes=minutes)).isoformat(),
                               location=location, status=status)

    def test_overlap_and_travel(self):
        self.event("dentist", at(8, 13), location="Oak Dental, 200 Oak St")
        overlap = cr.conflicts_for(at(8, 13, 30).isoformat(), at(8, 14, 30).isoformat())
        self.assertEqual([c["kind"] for c in overlap], ["overlap"])
        tight = cr.conflicts_for(at(8, 14, 15).isoformat(), at(8, 15, 0).isoformat(), location="412 Elm St")
        self.assertEqual(tight[0]["kind"], "travel")
        self.assertEqual((tight[0]["gap_minutes"], tight[0]["needed_minutes"]), (15, cr.DEFAULT_TRAVEL_BUFFER_MIN))
        self.assertEqual(cr.conflicts_for(at(8, 14, 45).isoformat(), at(8, 15, 30).isoformat(),
                                          location="412 Elm St"), [])
        same_place = cr.conflicts_for(at(8, 14, 5).isoformat(), at(8, 15, 0).isoformat(),
                                      location="oak dental,  200 oak st")
        self.assertEqual(same_place, [])
        unknown = cr.conflicts_for(at(8, 14, 5).isoformat(), at(8, 15, 0).isoformat())
        self.assertEqual(unknown, [])

    def test_an_estimator_decides_the_buffer_and_a_broken_one_is_not_a_free_road(self):
        self.event("dentist", at(8, 13), location="Oak Dental")
        start, end = at(8, 14, 20).isoformat(), at(8, 15).isoformat()
        self.assertEqual(cr.conflicts_for(start, end, location="Elm", estimator=lambda a, b: 10), [])
        self.assertTrue(cr.conflicts_for(start, end, location="Elm", estimator=lambda a, b: 45))

        def broken(a, b):
            raise TimeoutError("maps down")
        self.assertTrue(cr.conflicts_for(start, end, location="Elm", estimator=broken))

    def test_cancelled_events_block_nothing(self):
        self.event("gone", at(8, 13), status="CANCELLED")
        self.assertEqual(cr.conflicts_for(at(8, 13).isoformat(), at(8, 14).isoformat()), [])

    def test_conflicts_now_reports_each_clash_once(self):
        now = at(7, 9).astimezone(dt.timezone.utc)
        self.event("dentist", at(8, 13), location="Oak Dental")
        self.event("tour", at(8, 14, 10), location="412 Elm St")
        clashes = cr.conflicts_now(now=now)
        self.assertEqual(len(clashes), 1)
        self.assertEqual(clashes[0]["kind"], "travel")


class TimeInHisZone(Isolated):
    def test_windows(self):
        wednesday_night_utc = dt.datetime(2026, 9, 17, 3, 30, tzinfo=dt.timezone.utc)   # Wed 22:30 in Chicago
        self.assertEqual(cr.window("tomorrow", now=wednesday_night_utc), (dt.date(2026, 9, 17), dt.date(2026, 9, 17)))
        self.assertEqual(cr.window("next week", now=wednesday_night_utc), (dt.date(2026, 9, 21), dt.date(2026, 9, 27)))
        self.assertEqual(cr.window("this weekend", now=wednesday_night_utc), (dt.date(2026, 9, 19), dt.date(2026, 9, 20)))
        with self.assertRaises(ValueError):
            cr.window("whenever works", now=wednesday_night_utc)

    def test_sentences_are_in_his_zone_not_the_process(self):
        stamp = "2026-10-09T03:00:00Z"                          # 10 pm on Thursday the 8th in Chicago
        said = cr.human(stamp, now=dt.datetime(2026, 10, 1, 12, tzinfo=dt.timezone.utc))
        self.assertEqual(said, "Thursday, October 8 at 10 pm")
        self.assertEqual(cr.human("2026-10-01T15:30:00Z", now=dt.datetime(2026, 10, 1, 12, tzinfo=dt.timezone.utc)),
                         "today at 10:30 am")


class FreeTime(Isolated):
    def test_free_slots_skip_the_past_the_busy_and_the_trip(self):
        now = at(8, 11).astimezone(dt.timezone.utc)
        calendar.create("dentist", "Dentist", at(8, 13).isoformat(), at(8, 14).isoformat(), location="Oak Dental")
        slots = cr.find_free(dt.date(2026, 10, 8), dt.date(2026, 10, 8), minutes=60, location="412 Elm St", now=now)
        starts = [calendar.parse_time(s["start"]).astimezone(CHI).strftime("%H:%M") for s in slots]
        self.assertNotIn("09:00", starts)                       # the past
        self.assertNotIn("13:00", starts)                       # the dentist
        self.assertNotIn("12:00", starts)                       # ends at 1, with no time to get to Oak Dental
        self.assertIn("11:30", starts)                          # ends 12:30: exactly the 30 minutes it takes
        self.assertNotIn("14:00", starts)                       # leaves no time to get from Oak Dental
        self.assertIn("11:00", starts)
        self.assertIn("14:30", starts)
        said = cr.free_words(slots, first=dt.date(2026, 10, 8), last=dt.date(2026, 10, 8), purpose="a tour")
        self.assertTrue(said.startswith("Free for a tour: Thursday 11 am"))

    def test_spread_offers_different_days(self):
        now = at(5, 8).astimezone(dt.timezone.utc)
        slots = cr.find_free(dt.date(2026, 10, 5), dt.date(2026, 10, 9), minutes=60, now=now)
        offered = cr.spread(slots, 3)
        self.assertEqual(len({s["start"][:10] for s in offered}), 3)

    def test_evaluate_marks_each_proposal(self):
        now = at(5, 8).astimezone(dt.timezone.utc)
        calendar.create("dentist", "Dentist", at(8, 13, 30).isoformat(), at(8, 14, 30).isoformat())
        checked = cr.evaluate([{"start": at(8, 14).isoformat(), "quote": "Thursday at 2pm"},
                               {"start": at(9, 10).isoformat(), "quote": "Friday at 10am"},
                               {"start": at(1, 10).isoformat(), "quote": "last Thursday"}], minutes=45, now=now)
        self.assertEqual([c["free"] for c in checked], [False, True, False])
        self.assertTrue(checked[2]["past"])
        self.assertEqual(checked[0]["conflicts"][0]["title"], "Dentist")


class Holds(Isolated):
    def test_a_hold_is_tentative_idempotent_and_refuses_a_clash(self):
        calendar.create("dentist", "Dentist", at(8, 13).isoformat(), at(8, 14).isoformat())
        first = cr.hold("Tour", at(9, 10).isoformat(), at(9, 11).isoformat(), thread_id="conv-1")
        again = cr.hold("Tour", at(9, 10).isoformat(), at(9, 11).isoformat(), thread_id="conv-1")
        self.assertTrue(first["created"])
        self.assertFalse(again["created"])
        self.assertEqual(first["event"]["status"], "TENTATIVE")
        clash = cr.hold("Coffee", at(8, 13, 30).isoformat(), at(8, 14, 30).isoformat())
        self.assertIsNone(clash["event"])
        self.assertIn("Dentist", clash["why"])
        self.assertEqual(policy.all_approvals(), [])             # nothing asked, nothing live

    def test_move_and_release(self):
        held = cr.hold("Tour", at(9, 10).isoformat(), at(9, 11).isoformat())
        moved = cr.move_hold(held["event"]["id"], at(9, 15).isoformat(), at(9, 16).isoformat())
        self.assertTrue(moved["moved"])
        released = cr.release_hold(held["event"]["id"])
        self.assertEqual(released["status"], "CANCELLED")

    def test_confirming_onto_a_live_calendar_asks_and_writes_once(self):
        provider = calendar_provider.InMemoryCalendarProvider("fake.calendar")
        held = cr.hold("Tour", at(9, 10).isoformat(), at(9, 11).isoformat(), location="412 Elm St")
        confirmed = cr.confirm_hold(held["event"]["id"], provider=provider)
        approval_id = confirmed["record"]["write_approval"]
        approval = policy.load(approval_id)
        self.assertEqual((approval["state"], approval["capability"]), ("PENDING", "calendar.write"))
        self.assertEqual(cr.execute_approved_writes(provider=provider), [])      # not before his yes
        policy.decide(approval_id, "APPROVED", via="operator-cli")
        wrote = cr.execute_approved_writes(provider=provider)
        self.assertEqual(wrote[0]["outcome"], "written")
        self.assertEqual(cr.execute_approved_writes(provider=provider), [])      # once
        self.assertEqual(len(provider.list_events(at(9, 0).isoformat(), at(10, 0).isoformat())), 1)

    def test_without_a_live_calendar_confirming_changes_only_her_calendar(self):
        held = cr.hold("Tour", at(9, 10).isoformat(), at(9, 11).isoformat())
        confirmed = cr.confirm_hold(held["event"]["id"])
        self.assertEqual(confirmed["event"]["status"], "CONFIRMED")
        self.assertNotIn("write_approval", confirmed["record"])


class Deadlines(Isolated):
    def test_a_deadline_wakes_before_it_is_due_and_finishes_when_it_is(self):
        now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        due = now + dt.timedelta(days=3)
        item = cr.track_deadline("lease application", due.isoformat(), lead_hours=24, now=now)
        self.assertEqual(item["state"], ws.BLOCKED_EXTERNAL)
        self.assertEqual(ws.problems(item), [])
        only_work = {"work": work_engine.source_native}
        work_engine.reconcile(now + dt.timedelta(days=1), probe=False, sources=only_work)
        self.assertEqual(notifications.all_notifications(), [])                   # not yet
        work_engine.reconcile(now + dt.timedelta(days=2, hours=1), probe=False, sources=only_work)
        titles = [n["title"] for n in notifications.all_notifications()]
        self.assertIn("Coming up: lease application", titles)
        held = work_engine.load_store()["items"][item["id"]]
        self.assertEqual(held["state"], ws.BLOCKED_EXTERNAL)
        work_engine.reconcile(now + dt.timedelta(days=3, hours=1), probe=False, sources=only_work)
        self.assertIn("Due now: lease application", [n["title"] for n in notifications.all_notifications()])
        self.assertEqual(work_engine.load_store()["items"][item["id"]]["state"], ws.DONE)
