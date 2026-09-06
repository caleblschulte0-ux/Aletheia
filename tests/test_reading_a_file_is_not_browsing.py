"""A dot does not make a web address.

    "read notes.md"
    -> "That failed: Error: Page.goto: net::ERR_TUNNEL_CONNECTION_FAILED
        at https://notes.md/"

She tried to visit his file. `_spoken_url` accepted anything containing a
dot, so every filename with an extension was a domain — and `.md` `.pdf`
`.docx` are exactly the files he would ask her to read.

Whitelisting the endings that really are top-level domains is the safe
direction: an unusual one falls through to the planner, which is slower
and can still do the right thing. Blacklisting file extensions is not,
because `.md` `.sh` `.it` `.co` `.io` `.me` `.tv` are all both.
"""
import unittest

from aletheia import voice


class AFileIsNotADomainCase(unittest.TestCase):
    def test_a_file_he_names_reaches_the_planner(self):
        for said in ("read notes.md", "read my resume.pdf",
                     "open report.docx", "read the budget.xlsx"):
            with self.subTest(said=said):
                got = voice.interpret(f"thea {said}")["command"]
                self.assertEqual(got["kind"], "intent", said)

    def test_a_real_address_still_opens(self):
        for said, url in (("read example.com", "https://example.com"),
                          ("read example dot com", "https://example.com"),
                          ("browse github.com", "https://github.com"),
                          ("go to bbc.co.uk", "https://bbc.co.uk")):
            with self.subTest(said=said):
                got = voice.interpret(f"thea {said}")["command"]
                self.assertEqual(got, {"kind": "browse_read", "url": url})

    def test_an_explicit_scheme_is_always_a_url(self):
        """Even a filename-shaped host: if he said https, he meant the web."""
        got = voice.interpret("thea read https://notes.md/page")["command"]
        self.assertEqual(got["kind"], "browse_read")

    def test_a_path_after_the_host_does_not_confuse_it(self):
        got = voice.interpret("thea read example.com/index.html")["command"]
        self.assertEqual(got["kind"], "browse_read")

    def test_spoken_url_declines_rather_than_guessing(self):
        for text in ("notes.md", "resume.pdf", "a.b", "just words"):
            with self.subTest(text=text):
                self.assertIsNone(voice._spoken_url(text), text)


class ListingFilesIsInstantCase(unittest.TestCase):
    """"What files do you have" reached the planner, which sometimes
    compiled `file_list` and sometimes let `converse` answer — and
    `converse` does not know she can list a directory, so it replied "no
    FILE HE NAMED was passed with this question"."""

    def test_the_ways_he_would_ask(self):
        for said in ("what files do you have", "which files are there",
                     "list my files", "list files",
                     "whats in my workspace", "what's in my workspace",
                     "show me my files"):
            with self.subTest(said=said):
                got = voice.interpret(f"thea {said}")["command"]
                self.assertEqual(got, {"kind": "file_list"}, said)

    def test_naming_a_file_is_not_listing_them(self):
        got = voice.interpret("thea what files did dana send me")["command"]
        self.assertEqual(got["kind"], "intent")


if __name__ == "__main__":
    unittest.main()
