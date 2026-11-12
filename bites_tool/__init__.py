"""bites_tool - mirror large text files as exact, size-capped parts, and edit them by patch.

WHY THIS EXISTS
    The GitHub connector used in chat cuts any single tool result at about 28,000
    characters (measured), after adding an 82-character wrapper line in front of the
    content. Larger files arrive truncated. This package mirrors every large file as a
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

# Keep in step with the release tag: tag v1.2.0 means __version__ = "1.2.0" (the moving
# tag v1 follows the latest 1.x release). See the README, "Releasing a change".
__version__ = "1.1.0"
