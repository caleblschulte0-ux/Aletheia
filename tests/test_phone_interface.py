"""The phone surface: installable, honest, and thumb-first.

The old mobile page was a five-tab dashboard with a "paste JSON
arguments" box — a developer tool that happened to be narrow — and it
carried a banner saying remote access did not exist, which stopped being
true when he set up Tailscale. This replaces it.
"""
import json
import unittest
from pathlib import Path

from aletheia.fleet import REPO_ROOT

UI = REPO_ROOT / "interface"


def read(name):
    return (UI / name).read_text(encoding="utf-8")


class ItIsInstallable(unittest.TestCase):
    """"Add to Home Screen" must give a real app icon, not a bookmark."""

    def test_the_manifest_is_valid_and_standalone(self):
        manifest = json.loads(read("manifest.webmanifest"))
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["start_url"], "/interface/phone.html")
        self.assertTrue(manifest["icons"])
        purposes = {i.get("purpose") for i in manifest["icons"]}
        self.assertIn("maskable", purposes,
                      "without a maskable icon Android crops the mark")

    def test_every_file_the_manifest_names_exists(self):
        manifest = json.loads(read("manifest.webmanifest"))
        for icon in manifest["icons"]:
            path = REPO_ROOT / icon["src"].lstrip("/")
            self.assertTrue(path.is_file(), icon["src"])
        self.assertTrue((REPO_ROOT / manifest["start_url"].lstrip("/")).is_file())

    def test_the_core_serves_the_manifest_and_icon_as_themselves(self):
        """Served as octet-stream, a browser ignores the manifest silently
        and produces a bookmark — a failure with no error message."""
        core = (REPO_ROOT / "aletheia" / "core.py").read_text(encoding="utf-8")
        self.assertIn('"webmanifest": "application/manifest+json"', core)
        self.assertIn('"svg": "image/svg+xml"', core)

    def test_both_pages_link_the_manifest_and_a_touch_icon(self):
        html = read("phone.html") + read("console.html")
        self.assertIn('rel="manifest"', html)
        self.assertIn('rel="apple-touch-icon"', html)
        self.assertIn('name="apple-mobile-web-app-capable"', html)

    def test_the_icon_is_vector_not_a_committed_binary(self):
        self.assertTrue(read("icon.svg").lstrip().startswith("<svg"))


class ItWorksOverTailscale(unittest.TestCase):
    def test_no_host_is_hard_coded(self):
        """It must behave the same on loopback, the tailnet name, and a
        `tailscale cert` hostname — so every URL is relative."""
        js = read("talk.js") + read("console.js") + read("thea.js")
        for absolute in ("http://127.0.0.1", "http://localhost", "https://",
                         ":8777"):
            self.assertNotIn(absolute, js, absolute)

    def test_it_carries_a_bearer_token_for_off_loopback_use(self):
        js = read("talk.js") + read("console.js") + read("thea.js")
        self.assertIn("Bearer", js)
        self.assertIn("localStorage", js, "the token stays on the device")

    def test_a_401_asks_for_a_token_instead_of_looking_broken(self):
        js = read("talk.js") + read("console.js") + read("thea.js")
        self.assertIn("unauthorized", js)
        self.assertIn("aletheia.access", js, "it names the command that mints one")


class ItIsHonest(unittest.TestCase):
    def test_api_responses_are_never_cached(self):
        """A phone showing yesterday's approvals as pending is worse than
        a phone showing nothing."""
        sw = read("sw.js")
        self.assertIn('startsWith("/api/")', sw)
        self.assertIn("return", sw.split('startsWith("/api/")')[1][:40])

    def test_status_is_never_colour_alone(self):
        """And it is said in human words, not diagnostics."""
        talk = read("talk.js")
        for word in ("Halted", "Here", "Not running"):
            self.assertIn(word, talk, word)
        console = read("console.js")
        for word in ("Thea is here", "Stopped", "Not running"):
            self.assertIn(word, console, word)

    def test_a_slow_ask_is_collected_rather_than_dropped(self):
        js = read("thea.js")
        self.assertIn("/api/voice/followup", js)
        self.assertIn("followup_id", js)
        # The answer is SHOWN before it is acknowledged: the GET is a pure
        # read, so a dropped response costs a retry rather than the answer.
        shown = js.index("show(answer.say)")
        acked = js.index("ack(answer.id)")
        self.assertLess(shown, acked, "acknowledge only after it has been shown")

    def test_a_browser_without_speech_says_so_rather_than_doing_nothing(self):
        """iOS Safari has no SpeechRecognition. The mark still means "I want
        you" and hands him the keyboard — and the hint says so BEFORE the
        tap, which is the part the first version got wrong."""
        self.assertIn("SpeechRecognition", read("thea.js"))
        self.assertIn("tap to write", read("talk.js"))

    def test_the_stale_remote_transport_banner_is_gone(self):
        """It said remote access did not exist. He has Tailscale now."""
        self.assertNotIn("remote transport is not",
                         read("phone.html") + read("console.html"))


class TwoSurfaces(unittest.TestCase):
    """A front door that only talks, and everything one tap behind it.
    They are different moments — walking, and sitting down — and a page
    that serves both serves neither."""

    def test_the_front_door_is_the_start_url(self):
        manifest = json.loads(read("manifest.webmanifest"))
        self.assertEqual(manifest["start_url"], "/interface/phone.html")

    def test_each_page_reaches_the_other(self):
        self.assertIn("/interface/console.html", read("phone.html"))
        self.assertIn("/interface/phone.html", read("console.html"))

    def test_the_front_door_asks_and_the_console_does_not(self):
        """Two surfaces half-doing the same thing is how each ends up
        worse than one that commits. Asking itself lives in thea.js; what
        matters is that only the front door reaches for it."""
        self.assertIn("T.ask(", read("talk.js"))
        self.assertNotIn("T.ask(", read("console.js"))
        self.assertNotIn("/api/voice", read("console.js"))

    def test_the_console_decides_and_the_front_door_does_not(self):
        self.assertIn('"approve"', read("console.js"))
        self.assertNotIn('"approve"', read("talk.js"))

    def test_transport_lives_in_one_place_so_they_cannot_drift(self):
        shared = read("thea.js")
        self.assertIn("Bearer", shared)
        for page in ("talk.js", "console.js"):
            self.assertNotIn("fetch(", read(page),
                             page + " must go through thea.js, not its own fetch")

    def test_the_way_through_is_quiet_until_something_needs_him(self):
        """Not a pill reading 'Everything' — a small aperture, with one
        amber dot that appears only when there is a real reason."""
        html, js = read("phone.html"), read("talk.js")
        self.assertNotIn(">Everything<", html, "no clunky label pill")
        self.assertIn('class="dot"', html)
        self.assertIn('classList.toggle("needs"', js)

    def test_the_centre_object_is_her_not_the_input_method(self):
        """The first pass made a 152px microphone emoji the largest thing
        on screen — a promise about hardware, and on iOS Safari one the
        device cannot keep. The mark means Thea; how the words arrive is a
        detail underneath it."""
        html = read("phone.html")
        self.assertNotIn("&#127908;", html, "no microphone emoji")
        self.assertNotIn("🎤", html, "no microphone emoji")
        self.assertIn('class="her', html)
        self.assertIn("Speak to Thea", html)

    def test_the_hint_tells_the_truth_before_he_taps_not_after(self):
        """Without browser speech the mark still means 'I want you' — it
        hands him the keyboard — but the hint says so up front rather than
        letting him discover it by being lied to."""
        js = read("talk.js")
        self.assertIn("canListen", js)
        self.assertIn("tap to write", js)
        self.assertIn("focus()", js)

    def test_an_empty_console_says_so_rather_than_looking_broken(self):
        self.assertIn("Nothing needs you", read("console.html"))

    def test_the_service_worker_caches_both_pages(self):
        sw = read("sw.js")
        for f in ("phone.html", "console.html", "thea.js", "talk.js", "console.js"):
            self.assertIn(f, sw, f)


class TheSecurityBoundaryIsUnchanged(unittest.TestCase):
    """Carried over from tests/test_mobile_surface.py, which this replaces.
    A prettier phone page must not have bought its reach by weakening the
    thing that made loopback safe."""

    def test_binding_off_loopback_still_needs_a_token_and_tls(self):
        from aletheia import core
        with self.assertRaises(ValueError):
            core.make_server(host="0.0.0.0", port=0)

    def test_the_page_opens_no_socket_of_its_own(self):
        js = read("talk.js") + read("console.js") + read("thea.js")
        for reach in ("WebSocket", "EventSource", "XMLHttpRequest"):
            self.assertNotIn(reach, js, reach)


class ItIsBuiltForAThumb(unittest.TestCase):
    def test_it_respects_the_notch_and_the_home_bar(self):
        html = read("phone.html") + read("console.html")
        self.assertIn("viewport-fit=cover", html)
        self.assertIn("safe-area-inset-bottom", html)

    def test_the_text_input_will_not_zoom_on_ios(self):
        """Under 16px, Safari zooms the whole page on focus."""
        html = read("phone.html") + read("console.html")
        self.assertIn("font-size:16px", html.replace(" ", ""))

    def test_approve_and_deny_are_far_enough_apart_to_not_mis_tap(self):
        html = read("console.html")
        self.assertIn("min-height:50px", html.replace(" ", ""))
        self.assertIn("gap:10px", html.replace(" ", ""))

    def test_it_stops_polling_in_a_pocket(self):
        """Neither page may wake the radio for a screen nobody is reading."""
        self.assertIn("visibilitychange", read("talk.js"))
        self.assertIn("document.hidden", read("talk.js"))
        console = read("console.js")
        self.assertIn("visibilitychange", console)
        self.assertIn("clearInterval", console)

    def test_nothing_needing_attention_renders_as_nothing(self):
        js = read("console.js")
        self.assertIn('$("needsSec").hidden = html.length === 0', js)
        self.assertIn('$("calm").hidden', js,
                      "an empty page says it is empty rather than looking broken")


class TheInstructionItGIVESActuallyWorks(unittest.TestCase):
    """The one command he will type tonight, when the phone says it is not
    linked. It read `python -m aletheia.access mint` — which now exits with
    "the following arguments are required: label", because the per-device
    token work made the label mandatory. A dead end printed in a confident
    voice is worse than no instruction."""

    def test_the_command_the_console_prints_parses(self):
        import shlex
        from aletheia import access
        body = read("console.js")
        start = body.index("aletheia.access mint")
        printed = body[start:start + 120]
        # reassemble the string literal the page concatenates
        printed = printed.replace('"', "").replace("+", "").split(";")[0]
        argv = shlex.split(printed)[1:]      # drop "aletheia.access"
        parsed = access.build_parser().parse_args(argv)
        self.assertEqual(parsed.cmd, "mint")
        self.assertTrue(parsed.label)

    def test_it_asks_for_the_scope_the_console_actually_needs(self):
        """The console approves and denies; a read token cannot."""
        self.assertIn("--scope full", read("console.js"))


if __name__ == "__main__":
    unittest.main()


class ItLooksLikeHerAndNotLikeAnAIApp(unittest.TestCase):
    """The review that prompted this pass: "a nicely styled voice utility…
    generic enough that it could be a VPN app, network monitor, or fitness
    tracker." The identity has to be carried by a mark, not by a glowing
    circle and a blue accent."""

    def test_one_mark_serves_the_page_and_the_home_screen(self):
        mark = read("mark.svg")
        icon = read("icon.svg")
        self.assertIn("M158 372 L240 176", mark, "the left rise")
        self.assertIn("M158 372 L240 176", icon,
                      "the home-screen icon is the same mark, not a ring and dot")
        self.assertIn("M158 372 L240 176", read("phone.html"),
                      "and it is the object in the middle of the front door")

    def test_the_apex_is_open_which_is_what_the_name_means(self):
        """Aletheia is unconcealment. The two rises stop short of meeting."""
        mark = read("mark.svg")
        self.assertIn("L240 176", mark)
        self.assertIn("L272 176", mark)
        self.assertNotIn("L256 176", mark, "they must not meet at the apex")

    def test_the_icon_survives_a_maskable_crop(self):
        """Android crops a maskable icon to a circle; a mark that fills the
        tile loses its feet."""
        self.assertIn("scale(0.78)", read("icon.svg"))

    def test_the_generic_ai_cues_are_gone(self):
        surfaces = read("phone.html") + read("console.html") + read("icon.svg")
        for cue in ("🎤", "&#127908;", "#7cc6ff", "radial-gradient"):
            self.assertNotIn(cue, surfaces, cue)

    def test_amber_is_reserved_for_needing_him(self):
        """One accent, one meaning. If amber shows up, it is because
        something wants a decision."""
        html = read("console.html")
        self.assertIn("--amber", html)
        self.assertIn("border-left:3px solid var(--amber)", html.replace(" ", " "))


class TheMarkIsAlive(unittest.TestCase):
    def test_it_has_a_state_for_each_thing_she_is_doing(self):
        css = read("phone.html")
        for state in ("her.ready", "her.listening", "her.thinking",
                      "her.answering", "her.halted"):
            self.assertIn("." + state, css, state)

    def test_every_state_is_driven_from_one_place(self):
        js = read("talk.js")
        self.assertIn('her.className = "her " + mode', js,
                      "one element, one state — not a pile of toggles")

    def test_motion_yields_to_the_system_setting(self):
        self.assertIn("prefers-reduced-motion", read("phone.html"))


class TheReplyMorphsToFitTheAnswer(unittest.TestCase):
    """A 22-character centred column is right for "Done" and wrong for
    anything substantial."""

    def test_a_short_answer_is_a_sentence_and_a_long_one_is_a_card(self):
        js = read("talk.js")
        self.assertIn("body.length > 150", js)
        self.assertIn('className = "card"', js)
        self.assertIn('class="sentence', js)

    def test_the_card_can_be_read_and_scrolled(self):
        css = read("phone.html")
        self.assertIn("#reply .card", css)
        self.assertIn("overflow-y:auto", css.replace(" ", ""))

    def test_it_returns_to_rest_rather_than_holding_yesterdays_answer(self):
        self.assertIn("restTimer", read("talk.js"))


class TheButtonsSayWhatTheyDo(unittest.TestCase):
    """The defect this pass fixes: a button labelled "Not now" that sent a
    DENY command and then toasted "Left pending" — three meanings for one
    tap."""

    def test_not_now_sends_nothing_and_really_leaves_it_pending(self):
        js = read("console.js")
        later = js[js.index("if (later) {"):js.index("if (no &&")]
        self.assertNotIn("api(", later, "Not now must not send a decision")
        self.assertIn("Left pending", later)
        self.assertIn("deferred.add", later)

    def test_refusing_is_its_own_action_and_says_deny(self):
        js = read("console.js")
        self.assertIn(">Deny this<", js,
                      "the cards are rendered in console.js, not the HTML")
        self.assertIn("data-deny=", js)
        self.assertIn('"Approved" : "Denied"', js,
                      "the toast must match the verb on the button")
        self.assertNotIn('"Left pending")', js.split("if (later) {")[1]
                         .split("if (no &&")[1],
                         "a denial must never report itself as pending")

    def test_denying_asks_first_because_it_cannot_be_taken_back(self):
        self.assertIn('confirm("Deny this?', read("console.js"))


class TheConsoleSpeaksHuman(unittest.TestCase):
    def test_no_heartbeat_ages_or_utc_on_the_ordinary_page(self):
        """Checked against the CODE, not the prose: the comments explain why
        UTC is absent, which would trip a naive search."""
        import re
        js = read("console.js")
        ordinary = js[:js.index("function paintSystem")]
        ordinary = re.sub(r"/\*.*?\*/", "", ordinary, flags=re.S)
        ordinary = re.sub(r"^\s*//.*$", "", ordinary, flags=re.M)
        self.assertNotIn("heartbeat_age", ordinary,
                         "a heartbeat age is a diagnostic; it belongs in System")
        self.assertNotIn("UTC", ordinary, "he does not live in UTC")

    def test_times_are_local(self):
        self.assertIn("toLocaleTimeString", read("console.js"))

    def test_the_administrative_things_are_behind_the_system_sheet(self):
        html = read("console.html")
        sheet = html[html.index('id="sheet"'):]
        for admin in ("tokenBtn", "connDetail", "linkState"):
            self.assertIn(admin, sheet, admin + " must live in the sheet")

    def test_counting_tiles_are_gone(self):
        """Counting is not deciding. Only show what changes what he does."""
        html = read("console.html")
        self.assertNotIn("At a glance", html)
        self.assertNotIn('class="tile"', html)

    def test_halt_is_set_apart_from_ordinary_controls(self):
        html = read("console.html")
        self.assertIn('class="emergency"', html)
        emergency = html[html.index('class="emergency"'):html.index('id="sheet"')]
        self.assertNotIn("tokenBtn", emergency,
                         "the off switch does not sit next to a settings button")
        self.assertIn("haltBtn", emergency)

    def test_halt_reads_as_resume_once_she_is_stopped(self):
        js = read("console.js")
        self.assertIn("Let her start again", js)
        self.assertIn('kind: "resume"', js)


class NoDeadCode(unittest.TestCase):
    """console.js previously carried two refresh() definitions, the first
    dead and calling a bare api() that does not exist on that page. It
    worked only because the later declaration wins."""

    def test_no_function_is_defined_twice(self):
        import re
        for name in ("thea.js", "talk.js", "console.js"):
            body = read(name)
            defined = re.findall(r"^\s*(?:async\s+)?function\s+(\w+)", body,
                                 re.MULTILINE)
            dupes = {n for n in defined if defined.count(n) > 1}
            self.assertEqual(dupes, set(), f"{name} defines {dupes} twice")

    def test_the_pages_only_call_the_shared_transport(self):
        for name in ("talk.js", "console.js"):
            self.assertNotIn("fetch(", read(name),
                             name + " must go through thea.js")


class SheCanTalkBack(unittest.TestCase):
    """`speak()` sat in the transport, exported, and called by NOTHING.

    A phone assistant that cannot answer out loud is half of one, and an
    unwired capability is the exact thing rule zero forbids. This is the
    other half of the loop: he asks her something on the way to the car and
    hears the answer.
    """

    def test_speaking_is_actually_wired(self):
        self.assertIn("T.speak(", read("talk.js"))

    def test_a_spoken_question_gets_a_spoken_answer(self):
        body = read("talk.js")
        self.assertIn("ask(heard, true)", body)
        self.assertIn("aloud || speakBack", body)

    def test_typing_stays_silent_unless_he_asked_for_voice(self):
        """Typing in a quiet room and having the phone start talking is
        wrong; no setting is needed to express "voice in, voice out"."""
        body = read("talk.js")
        send = body[body.index('$("send").addEventListener'):]
        self.assertNotIn("true", send[:send.index("\n")],
                         "the send button must not claim the ask was spoken")

    def test_ios_gets_an_explicit_choice_because_it_cannot_be_inferred(self):
        """Safari has no SpeechRecognition, so his dictated question arrives
        as typing. A device that cannot detect a spoken question cannot
        infer that he wanted a spoken answer."""
        self.assertIn('id="voiceBtn"', read("phone.html"))
        body = read("talk.js")
        self.assertIn("thea.speak", body)          # remembered on the device
        self.assertIn("localStorage", body)

    def test_it_reads_a_reply_not_a_document(self):
        """6,000 characters read aloud is a hostage situation."""
        body = read("thea.js")
        self.assertIn("SPEAK_CHARS", body)
        self.assertIn("The rest is on screen", body)

    def test_talking_over_her_stops_her(self):
        self.assertIn("T.hush()", read("talk.js"))

    def test_leaving_the_page_does_not_leave_her_talking(self):
        body = read("talk.js")
        vis = body[body.index('visibilitychange'):]
        self.assertIn("T.hush()", vis[:200])

    def test_ios_needs_the_gesture_so_the_gesture_primes_it(self):
        """By the time an answer exists, the tap that asked for it is
        several awaits in the past and iOS refuses to start speaking."""
        self.assertIn("unlockSpeech", read("talk.js"))
        self.assertIn("volume = 0", read("thea.js"))


class TheInstructionItGIVESActuallyWorks(unittest.TestCase):
    """The one command he will type tonight, when the phone says it is not
    linked. It read `python -m aletheia.access mint` — which now exits with
    "the following arguments are required: label", because the per-device
    token work made the label mandatory. A dead end printed in a confident
    voice is worse than no instruction."""

    def test_the_command_the_console_prints_parses(self):
        import shlex
        from aletheia import access
        body = read("console.js")
        start = body.index("aletheia.access mint")
        printed = body[start:start + 120]
        # reassemble the string literal the page concatenates
        printed = printed.replace('"', "").replace("+", "").split(";")[0]
        argv = shlex.split(printed)[1:]      # drop "aletheia.access"
        parsed = access.build_parser().parse_args(argv)
        self.assertEqual(parsed.cmd, "mint")
        self.assertTrue(parsed.label)

    def test_it_asks_for_the_scope_the_console_actually_needs(self):
        """The console approves and denies; a read token cannot."""
        self.assertIn("--scope full", read("console.js"))


if __name__ == "__main__":
    unittest.main()
