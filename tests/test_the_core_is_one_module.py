"""The Core is one module, however it was launched (2026-09-24).

The supervisor runs `python -m aletheia.core`, so the Core's code runs as
`__main__`. The intercom's `from aletheia import core` then imported a
SECOND copy of the file, whose hooks were empty - and his "Update now"
tap answered "nothing is running that could update - start her from the
PC" while she was running under the supervisor the whole time. Restart
had the same hole. The running copy registers itself as `aletheia.core`.
"""
from __future__ import annotations

import sys
import types
import unittest

from aletheia import core


class OneModule(unittest.TestCase):
    def test_the_main_copy_becomes_the_importable_one(self):
        fake = types.ModuleType("__main__")
        fake.__file__ = core.__file__
        name = "aletheia._one_module_test"
        sys.modules.pop(name, None)
        try:
            core._be_the_one_module(fake, name)
            self.assertIs(sys.modules[name], fake)
            # A copy already imported is replaced too, so the hooks are shared.
            other = types.ModuleType(name)
            sys.modules[name] = other
            core._be_the_one_module(fake, name)
            self.assertIs(sys.modules[name], fake)
        finally:
            sys.modules.pop(name, None)

    def test_the_hooks_are_reachable_through_the_import_name(self):
        # In this process core was imported normally; the alias is a no-op and
        # the two names are one object.
        core._be_the_one_module(sys.modules["aletheia.core"], "aletheia.core")
        from aletheia import core as again
        self.assertIs(again, core)
        self.assertIs(again._UPDATE_HOOK, core._UPDATE_HOOK)


if __name__ == "__main__":
    unittest.main()
