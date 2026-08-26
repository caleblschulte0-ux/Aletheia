"""Aletheia — the fleet's single pane of truth."""
import sys

if sys.version_info < (3, 10):  # fail with words, not a SyntaxError blizzard
    raise RuntimeError(
        "Aletheia needs Python 3.10 or newer; this is "
        f"{sys.version_info.major}.{sys.version_info.minor}. On Windows: "
        "winget install Python.Python.3.12, then re-run the bootstrap.")

__version__ = "0.1.0"
