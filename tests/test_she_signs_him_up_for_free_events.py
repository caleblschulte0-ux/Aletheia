"""His words, 2026-10-09: "until I actually start getting into this, I need
uh, her to just start throwing shit on my calendar and signing me up for
stuff." A free event's form is filled with his name and email and Register
is pressed, under the sign-ups grant his ruling creates - and everything that
is not that (money, an account, a robot check, an agreement, a clash, a
sixth one this week) is left before anything is pressed."""
import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import event_signup, rulings, runtime

NOW = dt.datetime(2026, 10, 9, 15, 0, tzinfo=dt.timezone.utc)
URL = "https://www.eventbrite.com/e/sioux-falls-tech-hiring-night-12345"
FACTS = {"first_name": "Caleb", "last_name": "Schulte", "email": "caleb@openrange.example"}


def box(index, label, *, type_="text", required=True, tag="input", options=()):
    return {"index": index, "tag": tag, "type": type_, "name": "", "id": "", "placeholder": "",
            "aria": "", "autocomplete": "", "label": label, "required": required, "visible": True,
            "options": list(options)}


FORM = [box(0, "First name"), box(1, "Last name"), box(2, "Email", type_="email")]
BODY = ("Sioux Falls Tech Hiring Night\nThursday, October 15, 2026 6:00 PM - 8:00 PM CT\n"
        "Free\nMeet employers who are hiring.")


class FakePage:
    """The shape of a Playwright page the module touches, scripted."""

    def __init__(self, body=BODY, fields=FORM, *, captcha=False, after="You're registered! See you there.",
                 buttons=None):
        self.body, self.fields, self.captcha, self.after = body, list(fields), captcha, after
        self.buttons = buttons if buttons is not None else [
            {"index": 0, "text": "Register", "submit": True, "visible": True}]
        self.filled: dict[int, str] = {}
        self.clicked: list[int] = []

    def goto(self, url, **_):
        self.url = url

    def wait_for_load_state(self, *_):
        pass

    def wait_for_timeout(self, *_):
        pass

    def inner_text(self, selector):
        if selector == "h1":
            return "Sioux Falls Tech Hiring Night"
        return self.after if self.clicked else self.body

    def title(self):
        return "Sioux Falls Tech Hiring Night | Eventbrite"

    def evaluate(self, js):
        if js == event_signup._FIELDS_JS:
            return self.fields
        if js == event_signup._CAPTCHA_JS:
            return self.captcha
        if js == event_signup._BUTTONS_JS:
            return self.buttons
        raise AssertionError("unexpected script")

    def locator(self, selector):
        page = self

        class _Nth:
            def __init__(self, i):
                self.i = i

            def fill(self, value):
                page.filled[self.i] = value

            def select_option(self, label):
                page.filled[self.i] = label

            def click(self):
                page.clicked.append(self.i)

        class _Loc:
            def nth(self, i):
                return _Nth(i)

        return _Loc()


class Base(unittest.TestCase):
    def setUp(self):
        root = Path(tempfile.mkdtemp(prefix="sign-ups-"))
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(root)})
        env.start()
        self.addCleanup(env.stop)
        self.notes: list[tuple] = []
        self.written: list[dict] = []
        for target, value in (("aletheia.journal.append", None), ("aletheia.calendar.create", None),
                              ("aletheia.autonomy.record", None)):
            p = mock.patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def sign_up(self, page, *, grant="standing-sign-ups-1", busy=None, facts=FACTS):
        self.spent: list[tuple] = []

        def spender(capability, action_id):
            self.spent.append((capability, action_id))
            return grant

        return event_signup.register(
            URL, why="test", page=page, spender=spender, now=NOW, facts=dict(facts),
            busy=busy or (lambda start, end: []),
            calendar_writer=lambda **kw: self.written.append(kw) or {"state": "written"},
            notify=lambda title, body, **kw: self.notes.append((title, body)))


class AFreeEvent(Base):
    def test_his_name_and_email_go_in_and_register_is_pressed(self):
        page = FakePage()
        out = self.sign_up(page)
        self.assertEqual(out["state"], "registered", out)
        self.assertEqual(page.filled, {0: "Caleb", 1: "Schulte", 2: "caleb@openrange.example"})
        self.assertEqual(page.clicked, [0])
        self.assertEqual(self.spent, [("event.register", self.spent[0][1])])

    def test_it_goes_on_his_calendar_at_the_pages_time_and_he_is_told(self):
        out = self.sign_up(FakePage())
        self.assertEqual(len(self.written), 1)
        start = dt.datetime.fromisoformat(self.written[0]["start"])
        self.assertEqual(start.astimezone(dt.timezone.utc), dt.datetime(2026, 10, 15, 23, 0, tzinfo=dt.timezone.utc))
        self.assertIn("Thursday, October 15 at 6 pm Central", out["say"])
        self.assertEqual(self.notes[0][0], "Signed you up: Sioux Falls Tech Hiring Night")

    def test_the_same_page_is_not_signed_up_twice(self):
        self.sign_up(FakePage())
        page = FakePage()
        self.assertEqual(self.sign_up(page)["state"], "already")
        self.assertEqual(page.clicked, [])

    def test_a_page_that_does_not_say_it_worked_is_said_plainly(self):
        out = self.sign_up(FakePage(after="Please enter a valid email"))
        self.assertEqual(out["state"], "unconfirmed")
        self.assertEqual(self.written, [])
        self.assertIn("didn't say it worked", self.notes[0][1])


class WhatSheLeaves(Base):
    def assertLeft(self, page, state, words, **kw):
        out = self.sign_up(page, **kw)
        self.assertEqual(out["state"], state, out)
        self.assertIn(words, out["say"])
        self.assertEqual(page.clicked, [], "nothing is pressed on a page she leaves")
        self.assertEqual(self.notes, [])

    def test_a_price_is_left_before_the_grant_is_spent(self):
        page = FakePage(body=BODY.replace("Free", "General admission $25.00"))
        self.assertLeft(page, "costs_money", "costs money")
        self.assertEqual(self.spent, [])

    def test_a_card_field_is_money(self):
        self.assertLeft(FakePage(fields=FORM + [box(3, "Card number")]), "costs_money", "card")

    def test_a_password_is_an_account(self):
        self.assertLeft(FakePage(fields=FORM + [box(3, "Password", type_="password")]), "blocked", "account")

    def test_a_robot_check_is_a_wall(self):
        self.assertLeft(FakePage(captcha=True), "blocked", "robot")

    def test_a_required_agreement_is_his(self):
        page = FakePage(fields=FORM + [box(3, "I agree to the terms of service", type_="checkbox")])
        self.assertLeft(page, "blocked", "agree")

    def test_a_question_she_cannot_answer_stops_her(self):
        self.assertLeft(FakePage(fields=FORM + [box(3, "What do you hope to learn?")]), "blocked", "hope to learn")

    def test_his_real_phone_is_never_given_to_an_event(self):
        page = FakePage(fields=FORM + [box(3, "Phone", type_="tel")])
        with mock.patch("aletheia.profile.known",
                        return_value={**FACTS, "phone": "605-555-0100"}):
            out = event_signup.register(URL, page=page, spender=lambda c, a: "g", now=NOW,
                                        busy=lambda s, e: [], notify=lambda *a, **k: None,
                                        calendar_writer=lambda **k: {})
        self.assertEqual(out["state"], "blocked")
        self.assertNotIn("605-555-0100", page.filled.values())

    def test_a_clash_with_his_calendar_is_left(self):
        page = FakePage()
        self.assertLeft(page, "clashes", "Via interview",
                        busy=lambda start, end: [{"title": "Via interview"}])

    def test_without_the_grant_nothing_is_pressed(self):
        page = FakePage()
        out = self.sign_up(page, grant=None)
        self.assertEqual(out["state"], "needs_grant")
        self.assertEqual(page.clicked, [])

    def test_three_a_week_is_enough(self):
        rows = {f"eventbrite.com/e/{i}": {"state": "registered", "at": NOW.isoformat()} for i in range(3)}
        with mock.patch.object(event_signup, "registered", return_value=rows):
            page = FakePage()
            self.assertEqual(self.sign_up(page)["state"], "enough_this_week")
        self.assertEqual(page.clicked, [])

    def test_his_working_day_is_left(self):
        page = FakePage(body=BODY.replace("6:00 PM - 8:00 PM", "11:00 AM - 12:00 PM"))
        self.assertLeft(page, "outside_hours", "working day")

    def test_a_weekend_morning_is_his(self):
        page = FakePage(body=BODY.replace("Thursday, October 15", "Saturday, October 17")
                        .replace("6:00 PM - 8:00 PM", "10:00 AM - 11:00 AM"))
        self.assertEqual(self.sign_up(page)["state"], "registered")

    def test_a_rehearsal_presses_nothing(self):
        page = FakePage()
        with mock.patch.dict(os.environ, {"ALETHEIA_REHEARSAL": "1"}):
            self.assertEqual(self.sign_up(page)["state"], "failed")
        self.assertEqual(page.clicked, [])

    def test_a_link_that_is_not_an_event_is_not_followed(self):
        out = event_signup.register("https://example.com/buy-now", page=FakePage(), spender=lambda c, a: "g")
        self.assertEqual(out["state"], "not_an_event")


class FromHisMail(Base):
    def test_an_invitation_about_his_job_hunt_is_signed_up_for(self):
        with mock.patch.object(event_signup, "status", return_value={"on": True}):
            seen = []
            out = event_signup.consider_mail(
                {"id": "e1"}, subject="You're invited: Sioux Falls tech hiring webinar",
                text=f"Employers are hiring. Register here: {URL}.",
                registrar=lambda url, **kw: seen.append(url) or {"state": "registered"})
        self.assertEqual(seen, [URL])
        self.assertEqual(out["state"], "registered")

    def test_a_vendors_webinar_is_not_his_business(self):
        with mock.patch.object(event_signup, "status", return_value={"on": True}):
            seen = []
            event_signup.consider_mail(
                {"id": "e1"}, subject="Webinar: 10 ways to grow your Shopify sales",
                text=f"Register now: {URL}", registrar=lambda url, **kw: seen.append(url))
        self.assertEqual(seen, [])

    def test_off_means_nothing(self):
        with mock.patch.object(event_signup, "status", return_value={"on": False}):
            seen = []
            event_signup.consider_mail({"id": "e1"}, subject="Career fair", text=f"Register: {URL} hiring",
                                       registrar=lambda url, **kw: seen.append(url))
        self.assertEqual(seen, [])

    def test_the_beat_hands_an_event_email_to_it_and_not_his_own(self):
        event = {"id": "e9", "kind": "mail.received", "summary": "Career fair next week",
                 "attributes": {"sender": "events@college.example", "message_id": "<m1>"}}
        with mock.patch.object(event_signup, "status", return_value={"on": True}), \
             mock.patch.object(runtime, "_body_of", return_value=f"Hiring employers. RSVP {URL}"), \
             mock.patch.object(event_signup, "consider_mail", return_value={"state": "registered"}) as seen, \
             mock.patch.object(runtime, "_his_own_mail", return_value=False):
            self.assertEqual(runtime._event_invitation(event), {"state": "registered"})
        seen.assert_called_once()
        with mock.patch.object(runtime, "_his_own_mail", return_value=True), \
             mock.patch.object(event_signup, "consider_mail") as seen:
            self.assertIsNone(runtime._event_invitation(event))
        seen.assert_not_called()


class HisRuling(Base):
    def test_the_ruling_carries_his_words(self):
        with mock.patch.object(rulings, "DEFAULT_PATH", rulings.REPO_RULINGS):
            ruling = rulings.for_switch("sign_ups")
            self.assertTrue(ruling["on"])
            self.assertIn("signing me up for stuff", rulings.quote(ruling))
            self.assertEqual(event_signup.status()["ruled_by"], "sign-ups-on")

    def test_his_hand_at_the_keyboard_wins(self):
        with mock.patch.object(rulings, "DEFAULT_PATH", rulings.REPO_RULINGS), \
             mock.patch("aletheia.standing.sign_ups_disable", return_value=True) as revoked:
            self.assertFalse(event_signup.set_switch(False)["on"])
        revoked.assert_called_once()

    def test_the_beat_creates_the_grant_from_his_words(self):
        runtime._RULINGS_CHECKED["at"] = -1e12
        with mock.patch.object(rulings, "DEFAULT_PATH", rulings.REPO_RULINGS), \
             mock.patch("aletheia.interviews.status", return_value={"on": False, "window": {}}), \
             mock.patch("aletheia.standing.sign_ups_active", return_value=None), \
             mock.patch("aletheia.standing.sign_ups_enable", return_value={"id": "standing-sign-ups-1"}) as enable:
            out = runtime._apply_rulings(now_s=9e9)
        self.assertIn({"ruling": "sign-ups-on", "grant": "standing-sign-ups-1"}, out)
        self.assertIn("signing me up for stuff", enable.call_args.kwargs["quote"])

    def test_the_grant_never_reaches_money(self):
        from aletheia import standing
        self.assertEqual(standing.SIGN_UP_CAPABILITIES, ("event.register", "calendar.write"))
        from aletheia import capabilities
        entry = capabilities.get("event.register")
        self.assertEqual(entry["approval_policy"], "registry_grant")
        self.assertNotEqual(entry["risk_class"], "high")


LIST_URL = "https://siouxfallschamber.example/news/"
LIST_BODY = "Stay in the loop\nSubscribe to our newsletter for upcoming events."
LIST_FORM = [box(0, "Email address", type_="email")]


class FoundOnHerOwn(Base):
    """A page a mission found, on a host that is not an event site."""

    def test_an_event_page_anywhere_is_registered_for_when_it_says_it_is_an_event(self):
        page = FakePage(body=BODY + "\nA networking event for young professionals.")
        out = event_signup.register("https://chamber.example/events/hiring-night", page=page, now=NOW,
                                    facts=dict(FACTS), any_host=True, spender=lambda c, a: "g",
                                    busy=lambda s, e: [], calendar_writer=lambda **k: {},
                                    notify=lambda *a, **k: None)
        self.assertEqual(out["state"], "registered", out)

    def test_a_shops_sign_up_is_not_an_event(self):
        page = FakePage(body="Sign up for 10% off your first order")
        out = event_signup.register("https://shop.example/signup", page=page, now=NOW, facts=dict(FACTS),
                                    any_host=True, spender=lambda c, a: "g", busy=lambda s, e: [])
        self.assertEqual(out["state"], "not_an_event")
        self.assertEqual(page.clicked, [])


    def test_a_newsletter_box_under_upcoming_events_is_a_list_not_an_event(self):
        pages = [FakePage(body=LIST_BODY, fields=LIST_FORM), FakePage(body=LIST_BODY, fields=LIST_FORM,
                 after="Thanks for subscribing!",
                 buttons=[{"index": 0, "text": "Subscribe", "submit": True, "visible": True}])]
        with mock.patch.object(event_signup, "_facts", return_value=dict(FACTS)), \
             mock.patch("aletheia.authority.satisfy", return_value="g"), \
             mock.patch("aletheia.notifications.publish"), \
             mock.patch("aletheia.browse.available", return_value=(True, "")), \
             mock.patch("aletheia.browse._Session") as session:
            session.return_value.__enter__.return_value.new_page.side_effect = pages
            out = event_signup.sign_up_tool(LIST_URL)
        self.assertEqual(out["state"], "joined", out)
        self.assertEqual(pages[0].clicked, [])


class MailingLists(Base):
    def join(self, page, grant="g"):
        return event_signup.join_list(LIST_URL, page=page, now=NOW, facts={**FACTS, "phone": "605-555-0100"},
                                      spender=lambda c, a: grant, notify=lambda t, b, **k: self.notes.append((t, b)))

    def test_only_his_email_goes_on_a_free_list(self):
        page = FakePage(body=LIST_BODY, fields=LIST_FORM, after="Thanks for subscribing!",
                        buttons=[{"index": 0, "text": "Subscribe", "submit": True, "visible": True}])
        out = self.join(page)
        self.assertEqual(out["state"], "joined", out)
        self.assertEqual(page.filled, {0: "caleb@openrange.example"})
        self.assertIn("event invitations come to you", self.notes[0][1])

    def test_a_page_with_no_list_is_left_and_not_tried_again(self):
        page = FakePage(body="About the Chamber", fields=[])
        self.assertEqual(self.join(page)["state"], "no_list")
        self.assertEqual(self.join(FakePage(body=LIST_BODY, fields=LIST_FORM))["state"], "already")

    def test_a_paid_membership_is_money(self):
        page = FakePage(body=LIST_BODY + "\nMembership fee: $75 per year", fields=LIST_FORM)
        self.assertEqual(self.join(page)["state"], "costs_money")
        self.assertEqual(page.clicked, [])

    def test_without_the_grant_nothing_is_pressed(self):
        page = FakePage(body=LIST_BODY, fields=LIST_FORM)
        self.assertEqual(self.join(page, grant=None)["state"], "needs_grant")
        self.assertEqual(page.clicked, [])

    def test_one_list_a_day_from_the_registry_and_only_when_on(self):
        event_signup._LISTS_TRIED["day"] = ""
        seen = []
        with mock.patch.object(event_signup, "status", return_value={"on": True}):
            event_signup.join_lists(now=NOW, joiner=lambda url, **k: seen.append(url) or {"state": "joined"})
            event_signup.join_lists(now=NOW, joiner=lambda url, **k: seen.append(url) or {"state": "joined"})
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].startswith("https://"))
        event_signup._LISTS_TRIED["day"] = ""
        with mock.patch.object(event_signup, "status", return_value={"on": False}):
            self.assertEqual(event_signup.join_lists(now=NOW, joiner=lambda url, **k: seen.append(url)), [])
        self.assertEqual(len(seen), 1)


class AMissionStep(Base):
    def setUp(self):
        super().setUp()
        from aletheia import tools
        self.tool = tools.catalog(fresh=True)["event.register"]

    def test_the_tool_is_in_the_catalog_and_the_broker_still_hands_it_off(self):
        from aletheia import agent_session, tools
        self.assertEqual(self.tool.approval, "registry_grant")
        self.assertEqual(self.tool.consequence, tools.OUTWARD)
        decision = agent_session.Broker({"event.register": self.tool}, audience="all", halted=lambda: None) \
            .check(agent_session.ToolRequest("event.register", {"url": URL}))
        self.assertEqual(decision.verdict, agent_session.HANDOFF)

    def test_a_mission_need_finds_it(self):
        from aletheia import program_compose, tools
        tool, _score = program_compose.best_tool("register for the Chamber networking event", tools.catalog())
        self.assertEqual(tool.name, "event.register")

    def run_step(self, result, on=True):
        from aletheia import program_run, tools
        fake = tools.with_handler(self.tool, lambda args: result)
        task = {"title": "Sign up for a networking night"}
        with mock.patch.object(event_signup, "status", return_value={"on": on}):
            done = program_run._signed_up_under_grant(fake, {"url": URL}, task, 0, NOW)
        return done, task

    def test_under_the_grant_the_step_runs_instead_of_asking_him(self):
        done, task = self.run_step({"state": "registered", "said": "I signed you up"})
        self.assertTrue(done)
        self.assertEqual(task["results"][-1]["sign_up"], "registered")

    def test_a_left_page_is_settled_too(self):
        self.assertTrue(self.run_step({"state": "costs_money", "said": "it costs money"})[0])

    def test_no_grant_or_switch_off_goes_to_him_as_before(self):
        self.assertFalse(self.run_step({"state": "needs_grant"})[0])
        self.assertFalse(self.run_step({"state": "failed"})[0])
        self.assertFalse(self.run_step({"state": "registered"}, on=False)[0])

    def test_no_other_tool_takes_this_door(self):
        from aletheia import program_run, tools
        other = tools.catalog()["browser.pursue"]
        with mock.patch.object(event_signup, "status", return_value={"on": True}):
            self.assertFalse(program_run._signed_up_under_grant(other, {"url": URL}, {}, 0, NOW))


if __name__ == "__main__":
    unittest.main()


class WhereHerMissionWasStuck(unittest.TestCase):
    """His PC, 2026-10-09: 7 of 10 Project Reboot tasks waiting on him for
    things she should have done herself."""

    def setUp(self):
        from aletheia import tools
        self.catalog = tools.catalog()

    def test_looking_for_events_reads_the_web_instead_of_asking_him(self):
        from aletheia import program_compose as pc
        tool, _ = pc.best_tool("Search for upcoming job fairs, hiring events, networking events and info sessions",
                               self.catalog)
        self.assertTrue(tool.read_only, tool.name)
        self.assertTrue(tool.open_world, tool.name)

    def test_a_doing_tool_named_for_a_look_up_is_swapped_for_a_reader(self):
        from aletheia import program_compose as pc
        steps = pc.compose({"title": "Search for upcoming hiring events in Sioux Falls", "uses": ["web_task"]},
                           self.catalog)["steps"]
        self.assertTrue(all(self.catalog[s["tool"]].read_only for s in steps), steps)

    def test_a_check_does_not_ask_him_for_a_calendar_time(self):
        from aletheia import program_compose as pc
        steps = pc.compose({"title": "Check the confidentiality of the setup",
                            "detail": "confirm which calendar holds are written to",
                            "uses": ["calendar.propose"]}, self.catalog)["steps"]
        self.assertTrue(all(self.catalog[s["tool"]].read_only for s in steps), steps)

    def test_a_sweep_whose_every_need_looks_something_up_reads_too(self):
        from aletheia import program_compose as pc
        steps = pc.compose({"title": "Weekly sweep for new job-search events",
                            "does": ["search for newly listed events"], "uses": ["web_task"]},
                           self.catalog)["steps"]
        self.assertTrue(all(self.catalog[s["tool"]].read_only for s in steps), steps)

    def test_a_search_for_events_asks_the_web_not_her_own_repository(self):
        """2026-10-10: "search for newly listed events" tied research with repo.list."""
        from aletheia import program_compose as pc
        for need in ("search for newly listed events", "search event listings and local sources"):
            tool, _ = pc.best_tool(need, self.catalog)
            self.assertTrue(tool.open_world, (need, tool.name))

    def test_a_check_whose_need_names_a_writer_still_only_reads(self):
        from aletheia import program_compose as pc
        steps = pc.compose({"title": "Check the confidentiality of the setup",
                            "detail": "confirm which calendar holds are written to",
                            "does": ["confirm which calendar holds are written to"]}, self.catalog)["steps"]
        self.assertTrue(steps and all(self.catalog[s["tool"]].read_only for s in steps), steps)

    def test_a_window_to_look_over_is_not_a_question_for_him(self):
        from aletheia import program_compose as pc
        tool = self.catalog["calendar_find_free"]
        task = {"title": "Find free windows for the events found", "does": ["find free evening and weekend windows"]}
        self.assertEqual(pc.default_args(tool, task, ["when"]), {"when": "next two weeks"})
        self.assertEqual(pc.default_args(tool, {"title": "Find a free slot this weekend"}, ["when"]),
                         {"when": "this weekend"})
        # ...but a time to BOOK is his: a writer gets no made-up start.
        self.assertEqual(pc.default_args(self.catalog["calendar_hold"], task, ["start"]), {})

    def test_a_new_file_of_hers_gets_a_name_instead_of_a_question(self):
        from aletheia import program_compose as pc
        task = {"title": "Write the move criteria from Caleb's answers"}
        path = pc.default_args(self.catalog["file_write"], task, ["path"])["path"]
        self.assertTrue(path.startswith("missions/write-the-move-criteria") and path.endswith(".md"), path)
        self.assertEqual(pc.default_args(self.catalog["file_write"], task, ["path"])["path"], path)  # stable
        for other in ("file_delete", "file_move", "file_edit"):    # an existing file is never guessed
            self.assertEqual(pc.default_args(self.catalog[other], task, ["path"]), {}, other)

    def test_doing_is_still_doing(self):
        from aletheia import program_compose as pc
        self.assertEqual(pc.best_tool("register for the Chamber networking event", self.catalog)[0].name,
                         "event.register")
        self.assertEqual(pc.best_tool("join the Chamber mailing list", self.catalog)[0].name, "event.register")
        self.assertEqual(pc.best_tool("make a list called packing", self.catalog)[0].name, "list_new")

    def test_saving_his_answers_to_her_workspace_is_not_spending(self):
        from aletheia import agent_session as a
        broker = a.Broker(self.catalog, audience="all", halted=lambda: None)
        text = "Pay floor 95K, rent budget 1200 a month, buy a house next year"
        self.assertEqual(broker.check(a.ToolRequest("file_write", {"path": "reboot/answers.md", "text": text}))
                         .verdict, a.RUN)
        # ...and the same words on a tool that reaches the world are still refused.
        self.assertEqual(broker.check(a.ToolRequest("web_task", {"goal": "buy a house next year"})).verdict,
                         a.REFUSED)
