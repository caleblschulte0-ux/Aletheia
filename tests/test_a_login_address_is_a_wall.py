"""A login address is a sign-in wall before anything is filled (2026-09-24).

Sent to developers.facebook.com to start his Instagram app, she was
redirected to business.facebook.com/business/loginpage/ - one email box and
"Next", no password yet, no "sign in" in the words - typed his email into
it and pressed on, when the goal said stop at any login. She wandered to
instagram.com/accounts/login/, which timed out, and the beat wrote the
mission off as "the page broke". The ADDRESS says it is the door.
"""
from __future__ import annotations

import unittest

from aletheia import page_state as ps


def _obs(url: str, boxes: list[dict] | None = None, text: str = "", title: str = "") -> dict:
    return {"url": url, "title": title, "text": text, "status": 200,
            "fields": boxes or [], "buttons": [{"label": "Next"}]}


class TheAddressIsTheDoor(unittest.TestCase):
    def test_login_addresses(self):
        for url in ("https://business.facebook.com/business/loginpage/?next=https%3A%2F%2Fdevelopers.facebook.com%2Fapps%2F",
                    "https://www.instagram.com/accounts/login/?next=%2Fb%2Fmedia_picker",
                    "https://example.com/signin", "https://example.com/sign-in", "https://example.com/auth/login",
                    "https://example.com/users/sign_in", "https://example.com/session/new",
                    "https://accounts.google.com/o/oauth2/v2/auth"):
            self.assertTrue(ps.url_is_sign_in(url), url)

    def test_ordinary_addresses_are_not(self):
        for url in ("https://developers.facebook.com/apps/", "https://boards.greenhouse.io/embed/job_app?for=esri",
                    "https://example.com/blog/how-to-login-later", "https://example.com/?next=/login", ""):
            self.assertFalse(ps.url_is_sign_in(url), url)

    def test_metas_email_first_login_page_classifies_as_a_login_wall(self):
        obs = _obs("https://business.facebook.com/business/loginpage/?next=https%3A%2F%2Fdevelopers.facebook.com%2Fapps%2F",
                   boxes=[{"role": "textbox", "label": "Email or phone number", "selector": "#e"}],
                   text="Log in to Meta Business Suite Email or phone number Next", title="Meta Business Suite")
        out = ps.classify(obs)
        self.assertEqual(out["state"], ps.ACCOUNT_LOGIN, out)

    def test_a_job_form_on_an_ordinary_address_still_fills(self):
        obs = _obs("https://boards.greenhouse.io/embed/job_app?for=esri&token=1",
                   boxes=[{"role": "textbox", "label": "First Name", "selector": "#f"}],
                   text="Apply for this job First Name Last Name Submit application", title="Job Application")
        self.assertNotEqual(ps.classify(obs)["state"], ps.ACCOUNT_LOGIN)


if __name__ == "__main__":
    unittest.main()
