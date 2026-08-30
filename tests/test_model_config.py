import os
import tempfile
import unittest
from unittest import mock

from aletheia import local_brain, model_config


class TestModelConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = mock.patch.dict(os.environ, {
            model_config.ENV_CONFIG_DIR: self.tmp.name,
        }, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.old_model = os.environ.pop(model_config.ENV_MODEL, None)
        self.addCleanup(self._restore_model_env)

    def _restore_model_env(self):
        if self.old_model is not None:
            os.environ[model_config.ENV_MODEL] = self.old_model
        else:
            os.environ.pop(model_config.ENV_MODEL, None)

    def test_saved_model_changes_without_code_edit(self):
        self.assertEqual(model_config.resolve_model(), model_config.DEFAULT_MODEL)
        model_config.save_model("qwen3:14b")
        self.assertEqual(model_config.resolve_model(), "qwen3:14b")
        cfg = local_brain.OllamaConfig.from_env()
        self.assertEqual(cfg.model, "qwen3:14b")

    def test_environment_can_temporarily_override_saved_model(self):
        model_config.save_model("qwen3:14b")
        with mock.patch.dict(os.environ, {model_config.ENV_MODEL: "gemma3:4b"}, clear=False):
            self.assertEqual(model_config.resolve_model(), "gemma3:4b")
        self.assertEqual(model_config.resolve_model(), "qwen3:14b")

    def test_explicit_model_has_highest_precedence(self):
        model_config.save_model("saved-model")
        with mock.patch.dict(os.environ, {model_config.ENV_MODEL: "env-model"}, clear=False):
            self.assertEqual(model_config.resolve_model("explicit-model"), "explicit-model")

    def test_show_reports_local_config_source(self):
        model_config.save_model("qwen3:14b")
        shown = model_config.show()
        self.assertEqual(shown["model"], "qwen3:14b")
        self.assertEqual(shown["source"], "local_config")


if __name__ == "__main__":
    unittest.main()
