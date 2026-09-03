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

    def test_the_page_links_the_manifest_and_a_touch_icon(self):
        html = read("phone.html")
        self.assertIn('rel="manifest"', html)
        self.assertIn('rel="apple-touch-icon"', html)
        self.assertIn('name="apple-mobile-web-app-capable"', html)

    def test_the_icon_is_vector_not_a_committed_binary(self):
        self.assertTrue(read("icon.svg").lstrip().startswith("<svg"))


class ItWorksOverTailscale(unittest.TestCase):
    def test_no_host_is_hard_coded(self):
        """It must behave the same on loopback, the tailnet name, and a
        `tailscale cert` hostname — so every URL is relative."""
        js = read("phone.js")
        for absolute in ("http://127.0.0.1", "http://localhost", "https://",
                         ":8777"):
            self.assertNotIn(absolute, js, absolute)

    def test_it_carries_a_bearer_token_for_off_loopback_use(self):
        js = read("phone.js")
        self.assertIn("Bearer", js)
        self.assertIn("localStorage", js, "the token stays on the device")

    def test_a_401_asks_for_a_token_instead_of_looking_broken(self):
        js = read("phone.js")
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
        js = read("phone.js")
        for sentence in ("Halted", "Running", "not running"):
            self.assertIn(sentence, js, sentence)

    def test_a_slow_ask_is_collected_rather_than_dropped(self):
        js = read("phone.js")
        self.assertIn("/api/voice/followup", js)
        self.assertIn("followup_id", js)
        speak = js.index("say(answer.say)")
        ack = js.index("/api/voice/followup/ack")
        self.assertLess(speak, ack, "acknowledge only after it has been seen")

    def test_a_browser_without_speech_says_so_rather_than_doing_nothing(self):
        js = read("phone.js")
        self.assertIn("SpeechRecognition", js)
        self.assertIn("can't listen", js,
                      "iOS Safari has none; a dead mic button is worse than none")

    def test_the_stale_remote_transport_banner_is_gone(self):
        """It said remote access did not exist. He has Tailscale now."""
        self.assertNotIn("remote transport is not", read("phone.html"))


class TheSecurityBoundaryIsUnchanged(unittest.TestCase):
    """Carried over from tests/test_mobile_surface.py, which this replaces.
    A prettier phone page must not have bought its reach by weakening the
    thing that made loopback safe."""

    def test_binding_off_loopback_still_needs_a_token_and_tls(self):
        from aletheia import core
        with self.assertRaises(ValueError):
            core.make_server(host="0.0.0.0", port=0)

    def test_the_page_opens_no_socket_of_its_own(self):
        js = read("phone.js")
        for reach in ("WebSocket", "EventSource", "XMLHttpRequest"):
            self.assertNotIn(reach, js, reach)


class ItIsBuiltForAThumb(unittest.TestCase):
    def test_it_respects_the_notch_and_the_home_bar(self):
        html = read("phone.html")
        self.assertIn("viewport-fit=cover", html)
        self.assertIn("safe-area-inset-bottom", html)

    def test_the_text_input_will_not_zoom_on_ios(self):
        """Under 16px, Safari zooms the whole page on focus."""
        html = read("phone.html")
        self.assertIn("font-size:16px", html.replace(" ", ""))

    def test_approve_and_deny_are_far_enough_apart_to_not_mis_tap(self):
        html = read("phone.html")
        self.assertIn("min-height:50px", html.replace(" ", ""))
        self.assertIn("gap:10px", html.replace(" ", ""))

    def test_it_stops_polling_in_a_pocket(self):
        js = read("phone.js")
        self.assertIn("visibilitychange", js)
        self.assertIn("stopPolling", js)

    def test_nothing_needing_attention_renders_as_nothing(self):
        js = read("phone.js")
        self.assertIn("hidden = cards.length === 0", js)


if __name__ == "__main__":
    unittest.main()
