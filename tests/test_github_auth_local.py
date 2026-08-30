import os
import subprocess
import unittest
from unittest import mock

from aletheia import gh, github_auth


class GitHubTokenCase(unittest.TestCase):
    def test_environment_token_still_wins(self):
        with mock.patch.dict(os.environ, {"FLEET_TOKEN": "env-token"}, clear=True), \
             mock.patch.object(gh.os, "name", "nt"), \
             mock.patch("aletheia.secret_store.get") as get:
            self.assertEqual(gh.token(), "env-token")
        get.assert_not_called()

    def test_windows_falls_back_to_dpapi_alias(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(gh.os, "name", "nt"), \
             mock.patch("aletheia.secret_store.get", return_value=" vault-token ") as get:
            self.assertEqual(gh.token(), "vault-token")
        get.assert_called_once_with("github.fleet")

    def test_missing_local_secret_is_no_token_not_a_crash(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(gh.os, "name", "nt"), \
             mock.patch("aletheia.secret_store.get", side_effect=KeyError("missing")):
            self.assertIsNone(gh.token())


class GitHubAuthImportCase(unittest.TestCase):
    def test_cli_import_verifies_then_vaults_without_returning_plaintext(self):
        completed = subprocess.CompletedProcess(["gh"], 0, stdout="secret-token\n", stderr="")
        with mock.patch.object(github_auth, "cli_path", return_value="gh.exe"), \
             mock.patch.object(github_auth.subprocess, "run", return_value=completed), \
             mock.patch.object(github_auth.gh, "request", return_value={"login": "operator"}) as request, \
             mock.patch.object(github_auth.secret_store, "available", return_value=(True, "ready")), \
             mock.patch.object(github_auth.secret_store, "put",
                               return_value={"name": "github.fleet", "provider": "github.com", "kind": "api_token"}) as put:
            result = github_auth.import_from_cli()
        self.assertEqual(result["login"], "operator")
        self.assertNotIn("secret-token", str(result))
        request.assert_called_once_with("GET", "/user", tok="secret-token")
        self.assertEqual(put.call_args.args[:2], ("github.fleet", "secret-token"))
        self.assertEqual(put.call_args.kwargs["allowed_hosts"], ["api.github.com"])

    def test_bad_cli_auth_never_writes_vault(self):
        completed = subprocess.CompletedProcess(["gh"], 1, stdout="", stderr="login failed secret-ish")
        with mock.patch.object(github_auth, "cli_path", return_value="gh.exe"), \
             mock.patch.object(github_auth.subprocess, "run", return_value=completed), \
             mock.patch.object(github_auth.secret_store, "available", return_value=(True, "ready")), \
             mock.patch.object(github_auth.secret_store, "put") as put:
            with self.assertRaises(github_auth.GitHubAuthError):
                github_auth.import_from_cli()
        put.assert_not_called()


if __name__ == "__main__":
    unittest.main()
