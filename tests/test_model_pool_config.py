import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import model_pool_config


class TestModelPoolConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = mock.patch.dict(os.environ, {
            model_pool_config.ENV_CONFIG_DIR: self.tmp.name,
        }, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop(model_pool_config.ENV_FAST_MODEL, None)
        os.environ.pop(model_pool_config.ENV_DEEP_MODEL, None)

    def test_defaults_match_operator_selected_roles(self):
        fast = model_pool_config.resolve_profile("fast")
        deep = model_pool_config.resolve_profile("deep")
        self.assertEqual(fast["model"], "qwen3:8b")
        self.assertFalse(fast["think"])
        self.assertEqual(deep["model"], "qwen3.6:27b")
        self.assertTrue(deep["think"])

    def test_profiles_are_machine_local_and_swappable(self):
        path = model_pool_config.save_profile("fast", model="gemma3:4b", think=False)
        self.assertTrue(path.is_relative_to(Path(self.tmp.name)))
        self.assertEqual(model_pool_config.resolve_profile("fast")["model"], "gemma3:4b")
        self.assertEqual(model_pool_config.resolve_profile("deep")["model"], "qwen3.6:27b")

    def test_environment_can_override_model_without_code_change(self):
        model_pool_config.save_profile("deep", model="qwen3.6:27b", think=True)
        with mock.patch.dict(os.environ, {model_pool_config.ENV_DEEP_MODEL: "future-model:70b"}):
            profile = model_pool_config.resolve_profile("deep")
        self.assertEqual(profile["model"], "future-model:70b")
        self.assertTrue(profile["think"])
        self.assertEqual(profile["source"], "environment")


if __name__ == "__main__":
    unittest.main()
