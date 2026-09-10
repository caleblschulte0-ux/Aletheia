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
    def test_a_file_he_names_is_never_browsed_to(self):
        """The rule this class is named for.

        It asserted `kind == "intent"`, which was the CONSEQUENCE of the
        rule when it was written — nothing could handle a filename, so it
        fell through to the planner — rather than the rule. The planner is
        six seconds and a guess for a sentence with a filename in it, and
        "read rename.py" is the sentence her own answer tells him to say
        after she writes a script. What must never happen is that
        `notes.md` is treated as a host and opened in a browser.
        """
        for said in ("read notes.md", "read my resume.pdf",
                     "open report.docx", "read the budget.xlsx"):
            with self.subTest(said=said):
                got = voice.interpret(f"thea {said}")["command"]
                self.assertNotEqual(got["kind"], "browse_read", said)
                self.assertEqual(got["kind"], "file_read", said)

    def test_the_file_he_named_is_the_file_she_opens(self):
        for said, path in (("read notes.md", "notes.md"),
                           ("read my resume.pdf", "resume.pdf"),
                           ("open report.docx", "report.docx"),
                           ("read the budget.xlsx", "budget.xlsx")):
            with self.subTest(said=said):
                got = voice.interpret(f"thea {said}")["command"]
                self.assertEqual(got["path"], path)

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

    def test_none_of_them_reach_the_planner(self):
        """The rule this class is named for, stated instead of a string.

        It asserted `{"kind": "file_list"}` for all seven, which froze a
        WRONG answer for three of them: `file_list` lists HER WORKSPACE,
        so "list MY files" replied "(empty)" — true about a directory he
        has never opened, in reply to a question about his own disk. The
        thing being protected is that none of these cost a round trip.
        """
        for said in ("what files do you have", "which files are there",
                     "list my files", "list files",
                     "whats in my workspace", "what's in my workspace",
                     "show me my files"):
            with self.subTest(said=said):
                got = voice.interpret(f"thea {said}")["command"]
                self.assertNotEqual(got["kind"], "intent",
                                    f"{said} reached the planner")
                self.assertIn(got["kind"], ("file_list", "file_find"))

    def test_hers_and_his_are_different_questions(self):
        """The possessive is the whole signal, and it was being dropped."""
        for said, kind in (
                ("what files do you have", "file_list"),
                ("what's in my workspace", "file_list"),
                ("list your files", "file_list"),
                ("list my files", "file_find"),
                ("show me my files", "file_find"),
                ("what files do i have", "file_find"),
                # No possessive at all, said in a room, means his.
                ("list files", "file_find")):
            with self.subTest(said=said):
                got = voice.interpret(f"thea {said}")["command"]
                self.assertEqual(got["kind"], kind, said)

    def test_naming_a_file_is_not_listing_them(self):
        got = voice.interpret("thea what files did dana send me")["command"]
        self.assertEqual(got["kind"], "intent")


if __name__ == "__main__":
    unittest.main()
