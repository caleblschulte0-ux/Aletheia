"""ONE Thea interface — the same product on his PC and on his iPhone.

This replaces `tests/test_phone_interface.py`, which described two phone
surfaces (a front door that only talks, a console that only decides) and
which in turn replaced a five-tab "mobile" dashboard with a paste-JSON box.
The count kept going the wrong way: five HTML surfaces, three of them
rendering the same approval three different ways, two of them unusable.

There is one page now. Every rule those files protected is carried here —
installable, relative URLs, a token kept on the device, an honest word for
every state, a reply that can be read aloud, a button that says what it
does — plus the ones this pass is for: he never reads a hash, an ask typed
while she is unreachable is not lost, and "your phone is off the tailnet"
and "her PC is asleep" are different sentences.
"""
import json
import unittest
from pathlib import Path

from aletheia.fleet import REPO_ROOT

UI = REPO_ROOT / "interface"


def read(name):
    return (UI / name).read_text(encoding="utf-8")


def app():
    """Everything the one page is made of."""
    return read("thea.html") + read("thea-app.js") + read("thea.js")


class ThereIsOnlyOnePage(unittest.TestCase):
    """The consolidation itself, held as a rule rather than a memory."""

    def test_the_surfaces_it_replaced_are_gone(self):
        for old in ("command.html", "console.html", "console.js",
                    "phone.html", "talk.js", "mobile.html", "mobile.js",
                    "index.html"):
            with self.subTest(old):
                self.assertFalse((UI / old).exists(), old + " is still here")

    def test_what_is_left_is_the_page_the_wall_and_what_they_share(self):
        here = {p.name for p in UI.iterdir() if p.is_file()}
        self.assertEqual(here, {
            "thea.html", "thea-app.js", "thea.js", "qr.js",
            "wall.html", "voice.js", "sw.js",
            "manifest.webmanifest", "icon.svg", "mark.svg"})

    def test_the_one_page_both_asks_and_decides(self):
        """The old split — only the front door asks, only the console
        decides — cost a tap and a second codebase for no gain. One page
        does both, and the decision is still the SAME command the Core has
        always taken."""
        js = read("thea-app.js")
        self.assertIn("T.ask(", js)
        self.assertIn('kind: "approve"', js)
        self.assertIn('kind: "deny"', js)

    def test_it_adds_no_control_the_core_did_not_already_have(self):
        """No new approve / halt / send route: everything goes through
        /api/command, which is the intercom's grammar behind the intercom's
        gates."""
        js = read("thea-app.js") + read("thea.js")
        for invented in ("/api/approve", "/api/deny", "/api/halt", "/api/send"):
            with self.subTest(invented):
                self.assertNotIn(invented, js)
        self.assertIn('api("/api/command"', read("thea.js"))

    def test_the_wall_is_the_ambient_screen_and_says_so_by_where_it_is(self):
        """It earns its place across a room and nowhere else: it is not at
        `/`, it is not what the phone opens, and it has one way back."""
        from aletheia import core
        self.assertEqual(core.THE_PAGE, "/interface/thea.html")
        self.assertIn("/interface/thea.html", read("wall.html"))


class ItIsInstallable(unittest.TestCase):
    """"Add to Home Screen" must give a real app icon, not a bookmark."""

    def test_the_manifest_is_valid_and_standalone(self):
        manifest = json.loads(read("manifest.webmanifest"))
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["start_url"], "/interface/thea.html")
        self.assertTrue(manifest["icons"])
        purposes = {i.get("purpose") for i in manifest["icons"]}
        self.assertIn("maskable", purposes,
                      "without a maskable icon Android crops the mark")

    def test_every_file_the_manifest_names_exists(self):
        manifest = json.loads(read("manifest.webmanifest"))
        for icon in manifest["icons"]:
            self.assertTrue((REPO_ROOT / icon["src"].lstrip("/")).is_file(), icon["src"])
        self.assertTrue((REPO_ROOT / manifest["start_url"].lstrip("/")).is_file())

    def test_the_core_serves_the_manifest_and_icon_as_themselves(self):
        """Served as octet-stream, a browser ignores the manifest silently
        and produces a bookmark — a failure with no error message."""
        core = (REPO_ROOT / "aletheia" / "core.py").read_text(encoding="utf-8")
        self.assertIn('"webmanifest": "application/manifest+json"', core)
        self.assertIn('"svg": "image/svg+xml"', core)

    def test_the_page_links_the_manifest_and_a_touch_icon(self):
        html = read("thea.html")
        self.assertIn('rel="manifest"', html)
        self.assertIn('rel="apple-touch-icon"', html)
        self.assertIn('name="apple-mobile-web-app-capable"', html)

    def test_the_icon_is_vector_not_a_committed_binary(self):
        self.assertTrue(read("icon.svg").lstrip().startswith("<svg"))

    def test_the_service_worker_caches_the_page_and_never_the_answers(self):
        """A phone showing yesterday's approvals as pending is worse than a
        phone showing nothing."""
        sw = read("sw.js")
        for f in ("thea.html", "thea.js", "thea-app.js", "qr.js"):
            self.assertIn(f, sw, f)
        self.assertIn('startsWith("/api/")', sw)
        self.assertIn("return", sw.split('startsWith("/api/")')[1][:40])

    def test_the_shell_fallback_cannot_answer_a_connection_probe(self):
        """It used to answer ANY failed GET with the page's HTML, so the
        page's own "can I reach her machine?" probe got a cheerful 200 full
        of yesterday's markup. A diagnosis that cannot fail is not one."""
        sw = read("sw.js")
        fallback = sw[sw.index(".catch(() => caches.match(e.request)"):]
        self.assertIn('mode === "navigate"', fallback)


class GettingItOntoHisPhone(unittest.TestCase):
    """First run must be a scan, not a sentence typed on glass."""

    def test_the_pc_offers_a_code_to_point_a_camera_at(self):
        self.assertIn("TheaQR", read("thea-app.js"))
        self.assertIn('id="qr"', read("thea.html"))
        self.assertIn("Add to Home Screen", read("thea.html"))

    def test_the_address_comes_from_tailscale_and_not_from_a_guess(self):
        from aletheia import core
        source = Path(core.__file__).read_text(encoding="utf-8")
        self.assertIn("def phone_link", source)
        self.assertIn("tailscale", source)
        self.assertIn("dns_name", source)

    def test_the_page_can_show_the_address_but_never_mint_a_credential(self):
        """Minting is a deliberate act at his own keyboard. A page that
        could create a credential would be a new authority, and this pass
        adds none."""
        from aletheia import core
        source = Path(core.__file__).read_text(encoding="utf-8")
        link = source[source.index("def phone_link"):source.index("def run_command")]
        self.assertNotIn("access.mint", link)
        self.assertIn("linked_devices()", link)

    def test_a_link_he_opens_once_saves_the_code_and_scrubs_it(self):
        js = read("thea.js")
        self.assertIn('searchParams.get("token")', js)
        self.assertIn("history.replaceState", js)

    def test_the_command_it_tells_him_to_run_actually_parses(self):
        """It once printed `aletheia.access mint`, which had started exiting
        with "the following arguments are required: label"."""
        import re
        import shlex
        from aletheia import access
        printed = re.search(r'"(python -m aletheia\.access mint [^"]*)"',
                            read("thea-app.js"))
        self.assertTrue(printed, "the page must name the command that mints one")
        argv = shlex.split(printed.group(1))[3:]      # drop "python -m aletheia.access"
        parsed = access.build_parser().parse_args(argv)
        self.assertEqual(parsed.cmd, "mint")
        self.assertTrue(parsed.label)
        self.assertEqual(parsed.scope, "full",
                         "the page approves and denies; a read token cannot")


class ItWorksOverTailscale(unittest.TestCase):
    def test_no_host_is_hard_coded(self):
        """It must behave the same on loopback, the tailnet name, and a
        `tailscale cert` hostname — so every URL is relative."""
        js = read("thea-app.js") + read("thea.js")
        for absolute in ("http://127.0.0.1", "http://localhost", "https://",
                         ":8777"):
            self.assertNotIn(absolute, js, absolute)

    def test_it_carries_a_bearer_token_for_off_loopback_use(self):
        js = read("thea.js")
        self.assertIn("Bearer", js)
        self.assertIn("localStorage", js, "the token stays on the device")

    def test_a_401_asks_for_a_code_instead_of_looking_broken(self):
        self.assertIn("unauthorized", read("thea.js"))
        self.assertIn("aletheia.access", read("thea-app.js"),
                      "it names the command that mints one")
        self.assertIn("isn't linked", read("thea-app.js"))

    def test_the_local_secret_and_the_token_are_still_separate_proofs(self):
        """They prove different things and the server checks them in
        separate branches. A phone with any stale token once silently never
        tried the local secret at all, because this was `else`-shaped."""
        js = read("thea.js")
        self.assertIn("X-Aletheia-Local", js)
        header = js[js.index('if (method !== "GET" && method !== "HEAD")'):]
        self.assertNotIn("else", header[:200])


class TheSecurityBoundaryIsUnchanged(unittest.TestCase):
    """A nicer page must not have bought its reach by weakening the thing
    that made loopback safe."""

    def test_binding_off_loopback_still_needs_a_token_and_tls(self):
        from aletheia import core
        with self.assertRaises(ValueError):
            core.make_server(host="0.0.0.0", port=0)

    def test_the_page_opens_no_socket_of_its_own(self):
        js = read("thea-app.js") + read("thea.js")
        for reach in ("WebSocket", "EventSource", "XMLHttpRequest"):
            self.assertNotIn(reach, js, reach)

    def test_the_painting_goes_through_the_one_transport(self):
        self.assertNotIn("fetch(", read("thea-app.js"),
                         "thea-app.js must go through thea.js, not its own fetch")


class ItIsHonestAboutBeingOffline(unittest.TestCase):
    """His phone has silently dropped off the tailnet before. A page that
    says "can't reach her" for that sends him to look at a PC that is fine."""

    def test_the_three_situations_get_three_sentences(self):
        js = read("thea-app.js")
        self.assertIn("no connection", js)          # the device has no signal
        self.assertIn("dropped off Tailscale", js)  # nothing answers at her address
        self.assertIn("asleep", js)                 # her machine answers, she does not

    def test_reconnecting_is_a_state_he_can_see(self):
        self.assertIn("Reconnecting", read("thea-app.js"))

    def test_the_probe_is_a_static_file_no_cache_can_answer_from_yesterday(self):
        js = read("thea.js")
        probe = js[js.index("async function diagnose"):]
        self.assertIn("probe=", probe)
        self.assertIn("Date.now()", probe)
        self.assertIn('cache: "no-store"', probe)

    def test_an_ask_typed_while_she_is_unreachable_is_kept_and_sent(self):
        shared, page = read("thea.js"), read("thea-app.js")
        self.assertIn("thea.outbox", shared)
        self.assertIn("queueAsk", page)
        self.assertIn("flushOutbox", page)
        self.assertIn("will send it when she is", page,
                      "it must SAY it was kept rather than look sent")

    def test_status_is_never_colour_alone_and_never_a_diagnostic(self):
        js = read("thea-app.js")
        for word in ("Stopped", "Here", "Not running", "Needs you"):
            self.assertIn(word, js, word)

    def test_a_heartbeat_age_stays_in_the_drawer(self):
        """A heartbeat age is a diagnostic. Checked against the CODE: the
        comments explain why it is absent, which would trip a naive search."""
        import re
        js = read("thea-app.js")
        ordinary = js[:js.index("function paintDrawer")]
        ordinary = re.sub(r"/\*.*?\*/", "", ordinary, flags=re.S)
        ordinary = re.sub(r"^\s*//.*$", "", ordinary, flags=re.M)
        self.assertNotIn("heartbeat_age", ordinary)
        # As a WORD: `OUTCOME` contains the letters and is not a timezone,
        # and a substring check that cannot tell those apart is a test that
        # goes red for a rename.
        self.assertNotRegex(ordinary, r"\bUTC\b", "he does not live in UTC")

    def test_times_are_local(self):
        self.assertIn("toLocaleTimeString", read("thea.js"))


class ItSpeaksHumanAndKeepsTheMachineInTheDrawer(unittest.TestCase):
    def test_an_approval_asks_in_WORDS_and_never_in_a_digest(self):
        """`requested_action` is a digest for anything content-bound —
        "browser.interact:9f3c…" — and a phone that asks you to approve a
        hash is asking you to guess.

        This used to assert `a.label`, which was one implementation of the
        rule: the page read `/api/approvals` and picked the field itself.
        It reads `/api/needs` now, where every row has already been through
        `voice.approval_label` and `speech.for_reading`, so the rule holds
        harder — there is no field on the row that COULD be a digest — and
        the exact thing is still one tap down."""
        js = read("thea-app.js")
        row = js[js.index("function decisionRow"):js.index("function noticeCard")]
        self.assertIn("n.what", row, "the line is the collector's sentence")
        self.assertIn("n.which", row, "and which one of them it is")
        self.assertNotIn("requested_action", row)
        self.assertNotIn("consequence", row)
        self.assertIn("what exactly?", row, "the detail is one tap down")
        for detail in ("n.why", "n.if_ignored", "n.how"):
            self.assertIn(detail, row, detail)

    def test_the_page_never_assembles_the_needs_list_itself(self):
        """One list, computed once, so the screen and the spoken answer
        cannot disagree about what is waiting on him."""
        js = read("thea-app.js")
        self.assertIn('"/api/needs', js)
        self.assertNotIn("/api/approvals", js)

    def test_the_collectors_state_words_are_translated_not_shouted(self):
        js = read("thea-app.js")
        self.assertIn("STATE_WORD", js)
        self.assertIn('"NEEDS YOU": "Needs you"', js)
        self.assertIn('IDLE: "Resting"', js)

    def test_the_developer_things_live_in_the_drawer(self):
        html = read("thea.html")
        drawer = html[html.index('class="drawer"'):]
        for machine in ("Exact command", "codeLine", "receipts", "/api/mission"):
            self.assertIn(machine, drawer, machine)
        above = html[:html.index('class="drawer"')]
        for machine in ("/api/", "Exact command"):
            self.assertNotIn(machine, above, machine)

    def test_the_drawer_starts_shut(self):
        html = read("thea.html")
        drawer = html[html.index('<details class="drawer"'):]
        self.assertNotIn("open", drawer[:drawer.index(">")])

    def test_nothing_needing_him_says_so_rather_than_looking_broken(self):
        js = read("thea-app.js")
        # The empty sentence is the COLLECTOR's ("Nothing needs you right
        # now."), the same one she says out loud, with the page's own words
        # only as the fallback for a read that failed.
        self.assertIn("needs.says", js)
        self.assertIn("Nothing needs you right now.", js)
        self.assertIn("Nothing is in flight right now.", js)

    def test_the_readiness_check_is_a_button_and_never_a_poll(self):
        """A page polling /api/setup every two minutes spent his day opening
        and closing his signed-in ChatGPT window."""
        js = read("thea-app.js")
        self.assertIn('$("setupBtn").addEventListener', js)
        loop = js[js.index("async function refresh"):js.index("function turn(")]
        self.assertNotIn("/api/setup", loop)

    def test_it_stops_polling_in_a_pocket(self):
        js = read("thea-app.js")
        self.assertIn("visibilitychange", js)
        self.assertIn("document.hidden", js)
        self.assertIn("clearInterval", js)


class ACutSentenceMustNotSayTheOppositeThing(unittest.TestCase):
    """Found by rendering the page against his real state. The headline of
    an irreversible decision read:

        It presses a button that says 'Create Account'. That is not
        something she can

    `approval_label` cut at eighty characters with a slice, so the word the
    whole sentence turned on — "undo" — was the word that fell off, and the
    fragment left behind reads as its opposite."""

    def test_the_label_is_cut_at_a_boundary_not_at_a_character(self):
        from aletheia import voice
        said = voice.approval_label({"consequence": (
            "It presses a button that says 'Create Account'. That is not "
            "something she can undo.")})
        self.assertFalse(said.endswith("can"), said)
        self.assertTrue(said.endswith("."), said)

    def test_a_whole_sentence_beats_a_fragment(self):
        from aletheia import speech
        said = speech.shorten("It presses a button that says 'Create "
                              "Account'. That is not something she can "
                              "undo.", 80)
        self.assertEqual(said, "It presses a button that says 'Create Account'.")

    def test_but_never_at_the_cost_of_the_answer(self):
        """A short opening sentence must not swallow the thing he asked
        for: the boundary is only taken when it is most of the way to the
        limit."""
        from aletheia import speech
        said = speech.shorten("Yes. The plumber is booked for Tuesday at "
                              "nine in the morning and he knows about the "
                              "leak under the sink.", 80)
        self.assertIn("Tuesday", said)


class GrantingAuthorityIsNotAButton(unittest.TestCase):
    """The room microphone refuses these because anything in the room could
    say them. This page IS authenticated, so the reason has to be a
    different one — and it is: `standing.enable` creates its own approval
    and decides it, so a control here would be a one-tap grant with no
    approval object to read first, a shape nothing else on this page has.
    The drawer NAMES the commands, on the PC where the terminal is; it does
    not run them."""

    def test_the_page_grants_nothing(self):
        js = read("thea-app.js") + read("thea.js")
        for verb in ("standing", "authority", "grant"):
            self.assertNotIn('kind: "' + verb, js, verb)
        self.assertNotIn("/api/authority", js)
        self.assertNotIn("/api/standing", js)

    def test_the_drawer_tells_him_where_to_type_them(self):
        html = read("thea.html")
        drawer = html[html.index('class="drawer"'):]
        self.assertIn("aletheia.standing on", drawer)
        self.assertIn("aletheia.conversations grant", drawer)

    def test_both_of_those_commands_are_real(self):
        """A dead end printed in a confident voice is worse than no
        instruction."""
        import importlib
        for module, argv in (("aletheia.standing", ["on"]),
                             ("aletheia.conversations", ["grant", "--help"])):
            with self.subTest(module):
                self.assertTrue(hasattr(importlib.import_module(module), "main"))

    def test_the_grammar_still_refuses_to_compile_one(self):
        """Adding a control here must never have added a command kind: the
        planner, the agenda and the relay lanes all read that grammar."""
        from aletheia import intercom
        for kind in intercom.KIND_ARGS:
            with self.subTest(kind):
                self.assertNotIn("standing", kind)
                self.assertNotEqual(kind, "grant")


class TheHealthViewIsThereOnlyWhenItIsNeeded(unittest.TestCase):
    """Outcome 6 asks for "a simple health view when something is broken" —
    which means both halves: in the open without opening a drawer when
    something is wrong, and not on the page at all when nothing is."""

    def test_the_page_hides_it_on_the_cores_own_answer(self):
        js = read("thea-app.js")
        self.assertIn('api("/api/health")', js)
        self.assertIn("h.well", js)
        self.assertIn('$("health").hidden', js)

    def test_the_sentence_and_the_strip_cannot_disagree(self):
        """`headline` and `all_well` share `_every_expected_part_is_up`, so
        a quiet strip beside a sentence saying the Core is down is not a
        state this can reach."""
        from aletheia import running
        parts = [{"part": "core", "up": True, "what": ""},
                 {"part": "supervisor", "up": True, "what": ""},
                 {"part": "voice", "up": False, "what": ""}]
        well = {"parts": parts, "listening": False, "closed": False,
                "halted": False, "running_old_code": False}
        self.assertTrue(running.all_well(well))
        self.assertEqual(running.headline(well).split(".")[0],
                         "Everything's running")
        broken = dict(well, parts=[dict(p, up=p["part"] != "core") for p in parts])
        self.assertFalse(running.all_well(broken))
        self.assertIn("except", running.headline(broken))

    def test_old_code_is_something_to_look_at(self):
        """Three days of stale code once hid behind a line that read like
        good news."""
        from aletheia import running
        state = {"parts": [{"part": "core", "up": True, "what": ""}],
                 "listening": True, "closed": False, "halted": False,
                 "running_old_code": True}
        self.assertFalse(running.all_well(state))

    def test_it_never_pays_for_the_slow_half(self):
        """`?tasks=1` is a 0.6s scheduled-task query. A strip that polls
        every fifteen seconds must not ask for it."""
        self.assertNotIn("/api/health?tasks=1", read("thea-app.js"))


class TheButtonsSayWhatTheyDo(unittest.TestCase):
    """The defect this inherits a fix for: a button labelled "Not now" that
    sent a DENY and then toasted "Left pending" — three meanings, one tap."""

    def test_not_now_sends_nothing_and_really_leaves_it_pending(self):
        js = read("thea-app.js")
        later = js[js.index("if (later) {"):js.index("if (no &&")]
        self.assertNotIn("T.command", later, "Not now must not send a decision")
        self.assertNotIn("T.api(", later)
        self.assertIn("deferred.add", later)

    def test_refusing_is_its_own_action_and_asks_first(self):
        js = read("thea-app.js")
        self.assertIn('data-deny="', js)
        self.assertIn('confirm("Say no to this?', js)
        self.assertIn('"Approved" : "Refused"', js,
                      "the toast must match the verb on the button")

    def test_stopping_everything_is_set_apart_from_ordinary_controls(self):
        html = read("thea.html")
        emergency = html[html.index('class="emergency"'):html.index('<details class="drawer"')]
        self.assertIn("haltBtn", emergency)
        self.assertNotIn("tokenBtn", emergency,
                         "the off switch does not sit next to a settings button")

    def test_stop_reads_as_start_again_once_she_is_stopped(self):
        js = read("thea-app.js")
        self.assertIn("Let her start again", js)
        self.assertIn('kind: "resume"', js)


class ItIsBuiltForAThumb(unittest.TestCase):
    def test_it_respects_the_notch_and_the_home_bar(self):
        html = read("thea.html")
        self.assertIn("viewport-fit=cover", html)
        self.assertIn("safe-area-inset-bottom", html)

    def test_the_text_input_will_not_zoom_on_ios(self):
        """Under 16px, Safari zooms the whole page on focus."""
        self.assertIn("font-size:16px", read("thea.html").replace(" ", ""))

    def test_approve_and_deny_are_far_enough_apart_to_not_mis_tap(self):
        """The row form put them on one line, so the gap between them is the
        whole of the protection. The render test measures the real
        rectangles; this holds the intent in the stylesheet."""
        css = read("thea.html").replace(" ", "")
        self.assertIn(".row-ask.acts{display:flex;gap:10px", css)
        self.assertIn("min-height:44px", css)

    def test_it_is_one_page_that_reflows_rather_than_two_codebases(self):
        css = read("thea.html")
        self.assertIn("@media(min-width:900px)", css.replace(" ", ""))
        self.assertIn("grid-template-columns", css)


class ItLooksLikeHerAndNotLikeAnAIApp(unittest.TestCase):
    """"A nicely styled voice utility… generic enough that it could be a VPN
    app, network monitor, or fitness tracker." The identity is carried by a
    mark, not by a glowing circle and a blue accent."""

    def test_one_mark_serves_the_page_and_the_home_screen(self):
        self.assertIn("M158 372 L240 176", read("mark.svg"), "the left rise")
        self.assertIn("M158 372 L240 176", read("icon.svg"),
                      "the home-screen icon is the same mark, not a ring and dot")
        self.assertIn("M158 372 L240 176", read("thea.html"),
                      "and it is on the page itself")

    def test_the_apex_is_open_which_is_what_the_name_means(self):
        mark = read("mark.svg")
        self.assertIn("L240 176", mark)
        self.assertIn("L272 176", mark)
        self.assertNotIn("L256 176", mark, "they must not meet at the apex")

    def test_the_icon_survives_a_maskable_crop(self):
        self.assertIn("scale(0.78)", read("icon.svg"))

    def test_the_generic_ai_cues_are_gone(self):
        surfaces = read("thea.html") + read("icon.svg")
        for cue in ("🎤", "&#127908;", "#7cc6ff", "radial-gradient"):
            self.assertNotIn(cue, surfaces, cue)

    def test_amber_is_reserved_for_needing_him(self):
        """One accent, one meaning. If amber shows up, it is because
        something wants a decision."""
        html = read("thea.html")
        self.assertIn("--amber", html)
        self.assertIn("border-left:3px solid var(--amber)", html)

    def test_motion_yields_to_the_system_setting(self):
        self.assertIn("prefers-reduced-motion", read("thea.html"))


class SheCanTalkBack(unittest.TestCase):
    def test_a_slow_ask_is_collected_rather_than_dropped(self):
        js = read("thea.js")
        self.assertIn("/api/voice/followup", js)
        self.assertIn("followup_id", js)
        # The answer is SHOWN before it is acknowledged: the GET is a pure
        # read, so a dropped response costs a retry rather than the answer.
        self.assertLess(js.index("show(answer.say)"), js.index("ack(answer.id)"))

    def test_speaking_is_actually_wired(self):
        self.assertIn("T.speak(", read("thea-app.js"))

    def test_a_spoken_question_gets_a_spoken_answer(self):
        js = read("thea-app.js")
        self.assertIn("send(heard, true)", js)
        self.assertIn("spoken || speakBack", js)

    def test_typing_stays_silent_unless_he_asked_for_voice(self):
        """Typing in a quiet room and having the phone start talking is
        wrong; no setting is needed to express "voice in, voice out"."""
        js = read("thea-app.js")
        submit = js[js.index('$("askForm").addEventListener'):]
        self.assertNotIn("true", submit[:submit.index("\n")],
                         "the send button must not claim the ask was spoken")

    def test_ios_gets_an_explicit_choice_because_it_cannot_be_inferred(self):
        """Safari has no SpeechRecognition, so his dictated question arrives
        as typing. A device that cannot detect a spoken question cannot
        infer that he wanted a spoken answer."""
        self.assertIn('id="voiceBtn"', read("thea.html"))
        js = read("thea-app.js")
        self.assertIn("thea.speak", js)          # remembered on the device
        self.assertIn("localStorage", js)

    def test_a_browser_without_speech_says_so_rather_than_doing_nothing(self):
        self.assertIn("SpeechRecognition", read("thea.js"))
        js = read("thea-app.js")
        self.assertIn("canListen", js)
        self.assertIn("can't listen", js)
        self.assertIn("focus()", js)

    def test_it_reads_a_reply_not_a_document(self):
        """6,000 characters read aloud is a hostage situation."""
        js = read("thea.js")
        self.assertIn("SPEAK_CHARS", js)
        self.assertIn("The rest is on screen", js)

    def test_talking_over_her_stops_her(self):
        self.assertIn("T.hush()", read("thea-app.js"))

    def test_leaving_the_page_does_not_leave_her_talking(self):
        js = read("thea-app.js")
        vis = js[js.index("visibilitychange"):]
        self.assertIn("T.hush()", vis[:200])

    def test_ios_needs_the_gesture_so_the_gesture_primes_it(self):
        """By the time an answer exists, the tap that asked for it is
        several awaits in the past and iOS refuses to start speaking."""
        self.assertIn("unlockSpeech", read("thea-app.js"))
        self.assertIn("volume = 0", read("thea.js"))


class NoDeadCode(unittest.TestCase):
    """console.js once carried two refresh() definitions, the first dead and
    calling a bare api() that did not exist on that page. It worked only
    because the later declaration wins."""

    def test_no_function_is_defined_twice(self):
        import re
        for name in ("thea.js", "thea-app.js", "qr.js"):
            body = read(name)
            defined = re.findall(r"^\s*(?:async\s+)?function\s+(\w+)", body, re.M)
            dupes = {n for n in defined if defined.count(n) > 1}
            self.assertEqual(dupes, set(), f"{name} defines {dupes} twice")

    def test_everything_thea_js_exports_has_a_caller(self):
        """Rule zero: never build a capability and leave it unwired.
        `speak()` sat exported and called by nothing for a whole release."""
        shared, callers = read("thea.js"), read("thea-app.js")
        returned = shared[shared.rindex("return {"):]
        names = [n.strip() for n in
                 returned[returned.index("{") + 1:returned.index("}")].split(",")]
        unused = [n for n in names if n and f"T.{n}" not in callers]
        self.assertEqual(unused, [], f"thea.js exports nothing calls: {unused}")


if __name__ == "__main__":
    unittest.main()
