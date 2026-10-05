"""Thirty-seventh sandbox batch, 2026-10-05: her own surfaces, asked about.

    > how do I talk to you from my phone   [6.7s] "I don't have anything that says how"
    > what's the address of your page      [6.1s] "I won't guess at it"
    > show me the QR                       [11.5s]
    > how do I see the wall / what page do I open   two models, "I don't know where the wall lives"
    > where's the command center           a FILE search in Documents
    > what's on the wall                   [5.5s] "I don't have its current contents"
    > what did you post / when's the next post / what's scheduled to post   three models
"""
import unittest
from unittest import mock

from aletheia import quick, voice


class HerOwnSurfaces(unittest.TestCase):
    def test_her_address_on_the_pc_and_from_the_phone(self):
        with mock.patch("aletheia.core.phone_link", return_value={"url": "https://pc.tail.example/interface/thea.html", "why": ""}):
            said = quick.answer("what's the address of your page")
        self.assertIn("http://127.0.0.1:8777/interface/thea.html", said)
        self.assertIn("https://pc.tail.example/interface/thea.html", said)
        self.assertIn("QR code", said)
        with mock.patch("aletheia.core.phone_link", return_value={"url": None, "why": "Tailscale isn't installed on this PC, so your phone has no address to open."}):
            said = quick.answer("how do I talk to you from my phone")
        self.assertIn("From your phone: not yet. Tailscale isn't installed", said)
        for s in ("show me the QR", "how do I see the wall", "where's the command center", "what page do I open"):
            self.assertEqual(quick.match(s)[0], "her_page", s)
            self.assertNotEqual(voice.interpret(s)["command"].get("kind"), "file_find", s)

    def test_the_wall_is_the_pulse(self):
        with mock.patch("aletheia.quick._fleet", return_value="4 projects active, 2 dormant; no faults."):
            self.assertEqual(quick.answer("what's on the wall"),
                             "The wall shows the fleet, read from the pulse: 4 projects active, 2 dormant; no faults. Every panel on it links into the Thea page.")

    def test_the_posts_are_the_store(self):
        for s in ("what did you post", "when's the next post", "what's scheduled to post", "anything going out to instagram"):
            self.assertEqual(voice.interpret(s)["command"], {"kind": "instagram_posts"}, s)


if __name__ == "__main__":
    unittest.main()
