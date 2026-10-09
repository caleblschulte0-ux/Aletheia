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

    def test_five_a_week_is_enough(self):
        rows = {f"eventbrite.com/e/{i}": {"state": "registered", "at": NOW.isoformat()} for i in range(5)}
        with mock.patch.object(event_signup, "registered", return_value=rows):
            page = FakePage()
            self.assertEqual(self.sign_up(page)["state"], "enough_this_week")
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


if __name__ == "__main__":
    unittest.main()
