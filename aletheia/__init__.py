"""Aletheia — the fleet's single pane of truth."""
import sys

# Named once, because something else has to be able to ASK it: the setup
# checklist picks the interpreter word it prints by testing candidates
# against this (`setup.python_word`), after every `python -m aletheia...`
# line it printed turned out to hit a 3.9 first on his PATH.
MIN_PYTHON = (3, 10)

if sys.version_info < MIN_PYTHON:  # fail with words, not a SyntaxError blizzard
    raise RuntimeError(
        f"Aletheia needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer; this is "
        f"{sys.version_info.major}.{sys.version_info.minor}. On Windows: "
        "winget install Python.Python.3.12, then re-run the bootstrap.")

__version__ = "0.1.0"

# Windows consoles and pipes default to cp1252, and this codebase speaks in
# em dashes and reads window titles that carry whatever glyph an app put
# there. The first live desktop observation (2026-09-02) died in print()
# with UnicodeEncodeError on a '\u25d0' in a window title. Never let a
# character the console cannot draw turn a finished action into a crash:
# it is drawn as '?' instead. The Core under pythonw has no streams at all,
# hence the guards.
for _stream in (sys.stdout, sys.stderr):
    try:
        if _stream is not None and hasattr(_stream, "reconfigure"):
            _stream.reconfigure(errors="replace")
    except (ValueError, OSError):
        pass
del _stream
