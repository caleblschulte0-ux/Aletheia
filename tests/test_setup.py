"""The operator's side, checked rather than assumed.

Six credentials lived in four documents, each ending in "and then it
should work". He would do three and stall on the one with the thinnest
instructions, and nothing would ever prove the finished ones actually
worked. Every step here carries a verifier that makes a real attempt.
"""
import unittest
from unittest import mock

from aletheia import capabilities, intercom, setup, voice


class ChecklistCase(unittest.TestCase):
    def setUp(self):
        # audit() caches for a minute; a test that patches the steps must
        # ask for a fresh answer or it will read the previous test's.
        setup._CACHE.update({"at": 0.0, "report": None})
        self.addCleanup(lambda: setup._CACHE.update({"at": 0.0, "report": None}))

    def test_every_step_names_a_real_capability(self):
        reg = capabilities.load_registry()
        known = {c["id"] for c in reg["capabilities"]}
        for step in setup.steps():
            self.assertIn(step.capability, known, step.capability)

    def test_every_step_says_what_to_do_and_why(self):
        for step in setup.steps():
            self.assertTrue(step.how, step.capability)
            self.assertTrue(step.why, step.capability)
            self.assertTrue(callable(step.verify), step.capability)

    def test_nothing_still_needing_configuration_is_left_unmapped(self):
        # the anti-drift check: this file must not silently omit a
        # NEEDS_CONFIGURATION capability, because an omission would read as
        # a finished step
        report = setup.audit(fresh=True)
        self.assertEqual(report["unmapped_needs_configuration"], [],
                         "a capability needs configuration and this checklist "
                         "does not mention it")

    def test_a_failing_verifier_is_reported_not_raised(self):
        def boom():
            raise RuntimeError("hub on fire")

        broken = [setup.Step("room.scene", "The room", 5, "why", ["how"], boom)]
        with mock.patch.object(setup, "steps", return_value=broken):
            report = setup.audit(fresh=True)
        self.assertEqual(report["steps"][0]["state"], setup.BROKEN)
        self.assertIn("hub on fire", report["steps"][0]["detail"])

    def test_optional_steps_do_not_block_readiness(self):
        rows = [setup.Step("room.scene", "Required", 5, "w", ["h"],
                           lambda: (setup.OK, "fine")),
                setup.Step("advisor.triage", "Nice to have", 1, "w", ["h"],
                           lambda: (setup.MISSING, "off"), optional=True)]
        with mock.patch.object(setup, "steps", return_value=rows):
            report = setup.audit(fresh=True)
        self.assertTrue(report["ready"])
        self.assertEqual(report["minutes_left"], 0)

    def test_minutes_left_counts_only_what_is_outstanding(self):
        rows = [setup.Step("room.scene", "Done", 10, "w", ["h"],
                           lambda: (setup.OK, "fine")),
                setup.Step("calendar.read", "Todo", 15, "w", ["h"],
                           lambda: (setup.MISSING, "no"))]
        with mock.patch.object(setup, "steps", return_value=rows):
            report = setup.audit(fresh=True)
        self.assertEqual(report["minutes_left"], 15)
        self.assertFalse(report["ready"])

    def test_the_render_shows_instructions_only_for_unfinished_steps(self):
        rows = [setup.Step("room.scene", "Done thing", 10, "why-done",
                           ["do-not-show-me"], lambda: (setup.OK, "fine")),
                setup.Step("calendar.read", "Todo thing", 15, "why-todo",
                           ["run-this"], lambda: (setup.MISSING, "no"))]
        with mock.patch.object(setup, "steps", return_value=rows):
            text = setup.render(setup.audit(fresh=True))
        self.assertIn("run-this", text)
        self.assertNotIn("do-not-show-me", text)


class CacheCase(unittest.TestCase):
    def setUp(self):
        setup._CACHE.update({"at": 0.0, "report": None})
        self.addCleanup(lambda: setup._CACHE.update({"at": 0.0, "report": None}))

    def test_a_second_question_does_not_re_run_the_network_checks(self):
        calls = []
        rows = [setup.Step("room.scene", "Room", 5, "w", ["h"],
                           lambda: calls.append(1) or (setup.OK, "fine"))]
        with mock.patch.object(setup, "steps", return_value=rows):
            setup.audit()
            setup.audit()
        self.assertEqual(len(calls), 1, "it verified twice for one answer")

    def test_fresh_always_re_checks(self):
        calls = []
        rows = [setup.Step("room.scene", "Room", 5, "w", ["h"],
                           lambda: calls.append(1) or (setup.OK, "fine"))]
        with mock.patch.object(setup, "steps", return_value=rows):
            setup.audit()
            setup.audit(fresh=True)
        self.assertEqual(len(calls), 2)

    def test_the_cache_expires_rather_than_serving_a_stale_done(self):
        calls = []
        rows = [setup.Step("room.scene", "Room", 5, "w", ["h"],
                           lambda: calls.append(1) or (setup.OK, "fine"))]
        with mock.patch.object(setup, "steps", return_value=rows):
            setup.audit()
            setup._CACHE["at"] -= setup.CACHE_SECONDS + 1
            setup.audit()
        self.assertEqual(len(calls), 2)


class SlowKindCase(unittest.TestCase):
    def test_asking_out_loud_does_not_hold_the_room_open(self):
        # measured live at 20.9s: real logins, a request to the hub, a
        # PowerShell probe. The room gets an acknowledgement instead.
        from aletheia import core
        self.assertIn("setup_status", core.SLOW_KINDS)


class VerifierCase(unittest.TestCase):
    """Verifiers make a real attempt and never claim success on faith."""

    def test_the_phone_is_not_done_until_a_call_has_happened(self):
        from aletheia import phone_windows
        with mock.patch.object(phone_windows, "preflight",
                               return_value={"transport_available": True,
                                             "reason": "ready"}), \
             mock.patch.object(capabilities, "get",
                               return_value={"status": "EXPERIMENTAL"}):
            state, detail = setup._phone()
        self.assertEqual(state, setup.MISSING)
        self.assertIn("no call has been placed", detail)

    def test_remote_access_needs_both_a_token_and_a_certificate(self):
        from aletheia import access
        with mock.patch.object(access, "enabled", return_value=True), \
             mock.patch.object(access, "live_tokens", return_value=[{"id": "t"}]), \
             mock.patch.dict("os.environ", {"ALETHEIA_TLS_CERT": ""}):
            state, detail = setup._remote()
        self.assertEqual(state, setup.BROKEN)
        self.assertIn("no TLS certificate", detail)

    def test_a_configured_but_refusing_mailbox_is_broken_not_missing(self):
        from aletheia import mail
        with mock.patch.object(mail, "available", return_value=(True, "configured")), \
             mock.patch.object(mail, "SmtpImapTransport",
                               side_effect=OSError("refused")):
            state, detail = setup._mail()
        self.assertEqual(state, setup.BROKEN)
        self.assertIn("refused", detail.lower())

    def test_the_relay_needs_evidence_a_command_arrived(self):
        # the contract file ships with the repo and proves nothing
        from aletheia import fleet
        with mock.patch.object(fleet, "REPO_ROOT", fleet.REPO_ROOT / "nowhere"):
            state, detail = setup._relay()
        self.assertEqual(state, setup.MISSING)
        self.assertIn("no command has ever been relayed", detail)

    def test_the_wall_microphone_is_honest_about_what_it_cannot_see(self):
        state, detail = setup._wall_voice()
        self.assertEqual(state, setup.MISSING)
        self.assertIn("cannot be checked from here", detail)


class ApplyCase(unittest.TestCase):
    """One pasted secret, and the machine does the rest."""

    def test_a_calendar_url_must_be_a_secret_ical_address(self):
        from aletheia import apply
        for bad in ("", "not a url", "http://insecure.example/cal.ics",
                    "https://example.com/page"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                apply.calendar(bad)

    def test_a_short_hub_token_is_refused_before_anything_is_written(self):
        from aletheia import apply
        with self.assertRaises(ValueError):
            apply.room("http://hub:8123", "too-short")

    def test_a_hub_url_needs_a_scheme(self):
        from aletheia import apply
        with self.assertRaises(ValueError):
            apply.room("hub:8123", "x" * 60)

    def test_a_refusing_hub_raises_rather_than_leaving_it_half_configured(self):
        from aletheia import apply, hass
        with mock.patch.object(apply, "_setx", return_value=(0, "")),              mock.patch.object(hass, "ping", return_value=(False, "401 refused")):
            with self.assertRaises(RuntimeError) as caught:
                apply.room("http://hub:8123", "x" * 60)
        self.assertIn("refused", str(caught.exception))

    def test_nothing_here_invents_a_credential(self):
        # every secret comes from him at a prompt he typed
        import inspect
        from aletheia import apply
        source = inspect.getsource(apply)
        for forbidden in ("webbrowser.open", "requests.post", "input("):
            self.assertNotIn(forbidden, source)


class SpokenCase(unittest.TestCase):
    def report(self, **over):
        base = {"steps": [], "unmapped_needs_configuration": [],
                "done": 2, "total": 4, "minutes_left": 25, "ready": False}
        base.update(over)
        return base

    def test_it_names_what_is_left_and_the_time_it_costs(self):
        said = setup.spoken(self.report(steps=[
            {"title": "Calendar", "state": setup.MISSING, "optional": False},
            {"title": "The room", "state": setup.MISSING, "optional": False}]))
        self.assertIn("2 of 4 done", said)
        self.assertIn("calendar and the room", said)
        self.assertIn("25 minutes", said)

    def test_a_broken_step_is_called_out_separately_from_a_missing_one(self):
        said = setup.spoken(self.report(steps=[
            {"title": "The room", "state": setup.BROKEN, "optional": False}]))
        self.assertIn("configured but failing", said)

    def test_when_everything_required_is_done_it_says_so(self):
        said = setup.spoken(self.report(ready=True, done=4, total=4, steps=[
            {"title": "Advisor", "state": setup.MISSING, "optional": True}]))
        self.assertIn("done and verified", said)
        self.assertIn("Advisor", said)


class ReachableCase(unittest.TestCase):
    def test_he_can_just_ask(self):
        for phrase in ("what do you still need from me", "whats left",
                       "am i done", "whats still missing"):
            out = voice.interpret(f"thea {phrase}")
            self.assertEqual(out["command"], {"kind": "setup_status"}, phrase)

    def test_asking_is_read_only(self):
        # it checks; it configures nothing, and no credential is ever created
        self.assertEqual(intercom.tier("setup_status"), intercom.TIER_READ)


if __name__ == "__main__":
    unittest.main()
