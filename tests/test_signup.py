"""Making an account — and the four things that must never slip.

His ask, 2026-09-13: "I need this to be able to apply to jobs any where on
the web." Greenhouse and Lever were the only two she could reach because
they are the only two with no login. This is the wall.

The four:
  * a CAPTCHA stops her, always, before anything is typed;
  * the password reaches the vault and nothing else;
  * the phone on a signup is his Google Voice number, never the one an
    employer would ring;
  * one employer gets one account, not one per visit.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import signup


def field(label="", **kw):
    return {"label": label, **kw}


class TellingAWallFromAJobTitle(unittest.TestCase):
    def test_real_signup_walls_are_recognised(self):
        for text in (
            "Create an account to apply",
            "Create your account",
            "Sign up to apply for this role",
            "You must sign in to continue",
            "Create a candidate profile",
            "Already have an account? Log in",
            "Set a password to finish",
        ):
            with self.subTest(text=text):
                self.assertTrue(signup.wants_an_account(text))

    def test_account_executive_is_a_job_not_a_wall(self):
        """Half of Greenhouse's listings contain the word 'account'. A
        pattern that matched it would send her signing up for every sales
        job on the internet."""
        for text in ("Account Executive, Growth",
                     "Senior Account Manager",
                     "Manage a book of key accounts",
                     "Accounts Payable Specialist"):
            with self.subTest(text=text):
                self.assertFalse(signup.wants_an_account(text))

    def test_a_sign_in_page_is_not_a_sign_up_page(self):
        """Filling a login form with a brand-new password fails, loudly,
        on every attempt — and looks exactly like a broken signup."""
        self.assertTrue(signup.looks_like_sign_in(
            "Welcome back. Sign in to your account."))
        self.assertFalse(signup.looks_like_sign_in(
            "Create an account. Already have an account? Sign in"))


class TheCaptchaIsAFullStop(unittest.TestCase):
    def test_a_captcha_widget_in_the_field_list_is_caught(self):
        """Turnstile renders no sentence at all, so the widget is the
        reliable half."""
        for name in ("g-recaptcha-response", "h-captcha-response",
                     "cf-turnstile-response"):
            with self.subTest(name=name):
                self.assertTrue(signup.has_captcha("", [field(name=name)]))

    def test_captcha_words_are_caught_too(self):
        for text in ("I'm not a robot", "Please verify you are human",
                     "Complete the security challenge", "Press and hold"):
            with self.subTest(text=text):
                self.assertTrue(signup.has_captcha(text))

    def test_an_ordinary_signup_form_is_not_a_captcha(self):
        self.assertFalse(signup.has_captcha(
            "Create an account", [field("Email"), field("Password")]))

    def test_prepare_refuses_a_captcha_before_anything_is_typed(self):
        """The order is the safety argument: she must not fill half a form
        she cannot finish."""
        out = signup.prepare([field(name="g-recaptcha-response")],
                             host="jobs.example.com")
        self.assertEqual(out["state"], signup.CAPTCHA)
        self.assertNotIn("password", out)
        self.assertNotIn("fill", out)

    def test_a_captcha_is_checked_before_the_vault(self):
        """Even with no vault at all, a CAPTCHA is the reason given — it is
        the one he can act on."""
        with mock.patch.object(signup, "vault_ready", lambda: (False, "no dpapi")):
            out = signup.prepare([field(name="g-recaptcha-response")],
                                 host="jobs.example.com")
        self.assertEqual(out["state"], signup.CAPTCHA)

    def test_nothing_in_this_module_solves_one(self):
        """A solver is a paid service, and paying is the one permanent
        rule. This is a guard against a future edit, not against today."""
        with open("aletheia/signup.py", encoding="utf-8") as fh:
            src = fh.read().casefold()
        for word in ("2captcha", "anti-captcha", "anticaptcha", "capsolver",
                     "deathbycaptcha", "solve_captcha"):
            self.assertNotIn(word, src)


class ThePassword(unittest.TestCase):
    def test_it_has_every_character_class(self):
        """A site that silently requires a symbol and rejects the form is
        indistinguishable from a site that is broken."""
        for _ in range(50):
            pw = signup.new_password()
            self.assertTrue(any(c.islower() for c in pw))
            self.assertTrue(any(c.isupper() for c in pw))
            self.assertTrue(any(c.isdigit() for c in pw))
            self.assertTrue(any(c in signup._SYMBOLS for c in pw))

    def test_passwords_are_not_repeated(self):
        self.assertEqual(len({signup.new_password() for _ in range(200)}), 200)

    def test_a_short_password_is_refused(self):
        with self.assertRaises(ValueError):
            signup.new_password(8)

    def test_no_vault_means_no_account(self):
        """Better no account than a password he does not know exists."""
        with mock.patch.object(signup, "vault_ready", lambda: (False, "not Windows")):
            out = signup.prepare([field("Email")], host="jobs.example.com")
        self.assertEqual(out["state"], signup.NO_VAULT)
        self.assertNotIn("password", out)

    def test_remember_puts_the_password_in_the_vault_and_not_the_record(self):
        vault, written = {}, {}

        class FakeVault:
            @staticmethod
            def put(name, secret, **kw):
                vault[name] = secret

        with mock.patch.object(signup, "_vault", lambda: FakeVault), \
             mock.patch.object(signup.stateio, "read_json", lambda p: {}), \
             mock.patch.object(signup.stateio, "write_json_atomic",
                               lambda p, v: written.update(v)), \
             mock.patch.object(signup.journal, "append", lambda *a, **k: None):
            record = signup.remember("jobs.example.com", username="c@example.com",
                                     password="hunter2-SECRET")

        self.assertEqual(vault["signup.jobs.example.com"], "hunter2-SECRET")
        self.assertNotIn("hunter2-SECRET", str(record))
        self.assertNotIn("hunter2-SECRET", str(written))

    def test_the_journal_records_the_account_never_the_password(self):
        lines = []

        class FakeVault:
            @staticmethod
            def put(*a, **k): pass

        with mock.patch.object(signup, "_vault", lambda: FakeVault), \
             mock.patch.object(signup.stateio, "read_json", lambda p: {}), \
             mock.patch.object(signup.stateio, "write_json_atomic", lambda p, v: None), \
             mock.patch.object(signup.journal, "append",
                               lambda *a, **k: lines.append(" ".join(map(str, a)))):
            signup.remember("jobs.example.com", username="c@example.com",
                            password="hunter2-SECRET")
        self.assertTrue(lines)
        self.assertNotIn("hunter2-SECRET", " ".join(lines))


class ThePhoneOnASignupIsNotHis(unittest.TestCase):
    KNOWN = {"email": "c@example.com", "first_name": "Caleb",
             "phone": "605-555-0100", "signup_phone": "510-394-4076"}

    def test_a_phone_box_gets_the_signup_number(self):
        out = signup.plan([field("Phone")], host="x.com", known=self.KNOWN)
        row = next(r for r in out["fill"] if r["is"] == "signup_phone")
        self.assertEqual(row["value"], "510-394-4076")

    def test_his_real_number_never_appears_on_a_signup(self):
        fields = [field("Phone"), field("Mobile"), field("Cell phone"),
                  field("Telephone number")]
        out = signup.plan(fields, host="x.com", known=self.KNOWN)
        self.assertNotIn("605-555-0100", str(out["fill"]))

    def test_no_signup_number_on_file_is_a_named_gap_not_his_real_one(self):
        known = dict(self.KNOWN)
        known.pop("signup_phone")
        out = signup.plan([field("Phone")], host="x.com", known=known)
        self.assertEqual(out["fill"], [])
        self.assertEqual(out["missing"][0]["needs"], "signup_phone")
        self.assertNotIn("605-555-0100", str(out))

    def test_ordinary_facts_still_come_from_his_profile(self):
        out = signup.plan([field("Email"), field("First name")],
                          host="x.com", known=self.KNOWN)
        got = {r["is"]: r["value"] for r in out["fill"]}
        self.assertEqual(got.get("email"), "c@example.com")
        self.assertEqual(got.get("first_name"), "Caleb")


class ThePasswordBoxes(unittest.TestCase):
    def test_password_and_confirm_are_told_apart_by_label_not_order(self):
        """A form that puts 'Confirm password' first would otherwise swap
        them, and the only error it returns is 'passwords do not match'."""
        fields = [field("Confirm password", type="password"),
                  field("Password", type="password")]
        new, confirm = signup.password_fields(fields)
        self.assertEqual(new[0]["label"], "Password")
        self.assertEqual(confirm[0]["label"], "Confirm password")

    def test_both_boxes_get_the_same_password(self):
        fields = [field("Password", type="password"),
                  field("Re-enter password", type="password")]
        out = signup.plan(fields, host="x.com", known={})
        values = {r["value"] for r in out["fill"] if r["is"] == "password"}
        self.assertEqual(len(values), 1)
        self.assertEqual(len(out["fill"]), 2)

    def test_a_password_box_with_no_label_is_still_found(self):
        new, _ = signup.password_fields([field("", type="password", name="pwd")])
        self.assertEqual(len(new), 1)


class OneEmployerOneAccount(unittest.TestCase):
    def test_the_alias_is_stable_across_visits(self):
        self.assertEqual(signup.account_alias("www.Example.com"),
                         signup.account_alias("example.com"))

    def test_a_host_is_required(self):
        with self.assertRaises(ValueError):
            signup.account_alias("")

    def test_an_existing_account_short_circuits(self):
        """A second visit signs in; it does not register again."""
        with mock.patch.object(signup, "known_account",
                               lambda h: {"alias": "signup.x.com", "username": "c"}):
            out = signup.prepare([field("Email")], host="x.com")
        self.assertEqual(out["state"], signup.ALREADY)
        self.assertNotIn("password", out)

    def test_an_empty_store_still_proves_the_store(self):
        with mock.patch.object(signup.stateio, "read_json", lambda p: {}):
            self.assertEqual(signup.accounts(), [])

    def test_an_unreadable_store_is_not_an_empty_one_silently(self):
        def boom(p):
            raise OSError("gone")
        with mock.patch.object(signup.stateio, "read_json", boom):
            self.assertEqual(signup.accounts(), [])
            self.assertIsNone(signup.known_account("x.com"))


class PrepareTypesNothing(unittest.TestCase):
    def test_prepare_only_decides(self):
        """It returns a plan. Pressing anything is browse.interact's job,
        under an approval bound to that exact page."""
        with mock.patch.object(signup, "vault_ready", lambda: (True, "ok")), \
             mock.patch.object(signup, "known_account", lambda h: None):
            out = signup.prepare([field("Email")], host="x.com",
                                 known={"email": "c@example.com"})
        self.assertEqual(out["state"], signup.OK)
        self.assertIn("fill", out)

    def test_this_module_makes_no_browser_calls(self):
        """Checked on the CALLS, not on the text — the docstring names
        browse.interact on purpose, to say whose job pressing things is.
        An assertion over raw source would fail for the explanation."""
        import ast
        with open("aletheia/signup.py", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        pressing = {"click", "fill", "press", "goto", "type", "interact",
                    "check", "select_option"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                base = getattr(node.func.value, "id", "")
                if base in ("page", "browse", "webtask"):
                    self.fail(f"signup calls {base}.{node.func.attr} — this "
                              "module decides, it does not drive a browser")
                if node.func.attr in pressing and base not in ("", "self", "re"):
                    self.fail(f"signup calls {base}.{node.func.attr}")


if __name__ == "__main__":
    unittest.main()


class AnAccountWallIsNotAnApplication(unittest.TestCase):
    """`formfill` drops password inputs, which is right for an application
    and means a Workday login page used to read as a form whose only real
    inputs vanished — staging a record with nothing in it that could never
    be submitted. It is named now, so the account can be made instead."""

    def test_a_login_page_is_a_signup_form(self):
        self.assertTrue(signup.is_signup_form(
            [field("Email", type="email"), field("Password", type="password")]))

    def test_an_application_that_also_sets_a_password_is_still_an_application(self):
        """Some sites really do put 'create a password' at the bottom of a
        long application. A page that takes his CV is an application."""
        self.assertFalse(signup.is_signup_form([
            field("Full name"), field("Resume", type="file"),
            field("Create a password", type="password")]))

    def test_an_ordinary_application_is_not_a_signup(self):
        self.assertFalse(signup.is_signup_form(
            [field("Full name"), field("Email"), field("Why do you want this job?")]))

    def test_apply_run_stages_needs_account_instead_of_an_empty_application(self):
        from aletheia import apply_run
        written = {}
        fields = [field("Email", type="email"), field("Password", type="password")]
        with mock.patch.object(apply_run.formfill, "read_form", lambda u, reader=None: fields), \
             mock.patch.object(apply_run.policy, "ensure_not_halted", lambda: None), \
             mock.patch.object(apply_run.stateio, "write_json_atomic",
                               lambda p, v: written.update(v)), \
             mock.patch.object(apply_run.journal, "append", lambda *a, **k: None), \
             mock.patch.object(signup, "vault_ready", lambda: (True, "ok")), \
             mock.patch.object(signup, "known_account", lambda h: None):
            record = apply_run.stage("https://acme.myworkdayjobs.com/apply")

        self.assertEqual(record["state"], "NEEDS_ACCOUNT")
        self.assertEqual(record["host"], "acme.myworkdayjobs.com")
        self.assertTrue(record["why"].strip())
        self.assertNotIn("approval", record)

    def test_the_record_never_carries_the_password(self):
        from aletheia import apply_run
        fields = [field("Email", type="email"), field("Password", type="password")]
        with mock.patch.object(apply_run.formfill, "read_form", lambda u, reader=None: fields), \
             mock.patch.object(apply_run.policy, "ensure_not_halted", lambda: None), \
             mock.patch.object(apply_run.stateio, "write_json_atomic", lambda p, v: None), \
             mock.patch.object(apply_run.journal, "append", lambda *a, **k: None), \
             mock.patch.object(signup, "vault_ready", lambda: (True, "ok")), \
             mock.patch.object(signup, "known_account", lambda h: None):
            record = apply_run.stage("https://acme.myworkdayjobs.com/apply")
        self.assertNotIn("password", record)
