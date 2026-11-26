"""bites_tool - output large text files as exact, size-capped parts, and edit them by patch.

WHY THIS EXISTS
    The GitHub connector used in chat cuts any single tool result at about 28,000
    characters (measured), after adding an 82-character wrapper line in front of the
    content. Larger files arrive truncated. This package outputs every large file as a
    series of small "part" files on a separate branch, so each part can be read whole,
    and it applies edits to large files from small patch files, so a whole large file
    never has to be re-typed.

PACKAGE LAYOUT
    core.py      shared helpers, configuration, source-file selection, and the part
                 file format (render, parse, split, join)
    build.py     the build, verify, reassemble and report-failure commands
    patches.py   patch-file grammar and the apply command
    cli.py       argument parsing and the program entry point
    __main__.py  lets the package run as `python -m bites_tool`

RUNNING
    PYTHONPATH=<directory containing bites_tool> python -m bites_tool <command> ...
    Commands: apply, build, verify, reassemble, report-failure (see cli.py).
    In CI the composite action (action.yml in the repository root) does this for you: it
    sets PYTHONPATH to the directory it was fetched into (github.action_path) and runs
    apply, build, verify and, after a failure, report-failure.

Standard library only. Requires Python 3.11+ (tomllib) and `git` on PATH.
"""

import re as _re
from pathlib import Path as _Path

# The version lives in one place: the VERSION file at the repository root, which holds one line
# such as 1.5.0 and nothing else. The release tag is v plus that number (tag v1.5.0 means VERSION
# holds 1.5.0), and the moving tag v1 follows the latest 1.x release. scripts/bootstrap.sh reads
# the same file. See docs/how-it-works.md, "Versions and releases".


def _read_version() -> str:
    """Return the text of the VERSION file, or "unknown" if it is missing or malformed."""
    try:
        text = (_Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    return text if _re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", text) else "unknown"


__version__ = _read_version()
