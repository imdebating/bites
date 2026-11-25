"""bites - split large text files into exact, reversible, size-capped parts.

COMMANDS
    apply            apply pending patch files (.bites-patches/*.patch) to the source tree
    build            write parts, manifest.json and last_build.json into --out
    verify           check the whole output tree against the source tree
    reassemble       write one original file, rebuilt from its parts, to stdout
    report-failure   convert a failure status file into <out>/last_build.json

SETTINGS
    build and verify read the configuration file given by --toml FILE (default bites.toml).
    `-c KEY=VALUE` / `--config KEY=VALUE` (repeatable) and BITES_<KEY> environment variables
    override it. `-c toml_file=FILE` names the configuration file too, and wins over --toml.
    See bites_tool/core.py.

EXIT CODES
    0 success; 1 any error (message on stderr; if --status was given, a JSON error
    record is written there so the workflow can publish it).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .build import cmd_build, cmd_reassemble, cmd_report_failure, cmd_verify
from .core import SCHEMA, BitesError, dumps
from .patches import cmd_apply
from .strings import message
from .annotations import annotate


def make_parser():
    """Build the argparse parser with one sub-command per `cmd_*` function."""
    ap = argparse.ArgumentParser(prog="python -m bites_tool", description=message("cli", "description"))
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        """Add the option every command shares: where to record a JSON error."""
        p.add_argument("--status", help=message("cli", "help_status"))

    def toml(p):
        """Add the option that names the configuration file (stored as `a.config`, the path)."""
        p.add_argument(
            "--toml", dest="config", default="bites.toml", metavar="FILE",
            help=message("cli", "help_toml"),
        )

    def settings(p):
        """Add the option that overrides settings (stored as `a.set`, a list of KEY=VALUE items)."""
        p.add_argument(
            "-c", "--config", dest="set", action="append", default=[], metavar="KEY=VALUE",
            help=message("cli", "help_config"),
        )

    p = sub.add_parser("apply", help=message("cli", "help_apply"))
    p.add_argument("--src", default=".", help=message("cli", "help_src"))
    p.add_argument("--patches", default=".bites-patches", help=message("cli", "help_patches"))
    p.add_argument("--report", help=message("cli", "help_report"))
    common(p)
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("build", help=message("cli", "help_build"))
    toml(p)
    p.add_argument("--src", default=".", help=message("cli", "help_src"))
    p.add_argument("--out", required=True, help=message("cli", "help_out"))
    p.add_argument("--source-branch", default="", help=message("cli", "help_recorded"))
    p.add_argument("--source-commit", default="", help=message("cli", "help_recorded"))
    p.add_argument("--patch-report", help=message("cli", "help_patch_report"))
    p.add_argument("--full", action="store_true", help=message("cli", "help_full"))
    settings(p)
    common(p)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("verify", help=message("cli", "help_verify"))
    toml(p)
    p.add_argument("--src", default=".")
    p.add_argument("--out", required=True)
    settings(p)
    common(p)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("reassemble", help=message("cli", "help_reassemble"))
    p.add_argument("--out", required=True)
    p.add_argument("--file", required=True, help=message("cli", "help_file"))
    common(p)
    p.set_defaults(func=cmd_reassemble)

    p = sub.add_parser("report-failure", help=message("cli", "help_report_failure"))
    p.add_argument("--status", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--source-branch", default="")
    p.add_argument("--source-commit", default="")
    p.set_defaults(func=cmd_report_failure)
    return ap


def take_toml_file(a):
    """Move a `-c toml_file=FILE` item out of the settings list and into the configuration path.

    The item wins over --toml. Raises BitesError if the file name is empty.
    """
    items = getattr(a, "set", None)
    if not items:
        return
    kept = []
    for item in items:
        key, sep, value = item.partition("=")
        if sep and key.strip() == "toml_file":
            if not value.strip():
                raise BitesError(message("cli", "toml_file_needs_name"))
            a.config = value.strip()
        else:
            kept.append(item)
    a.set = kept


def main(argv=None) -> int:
    """Entry point. Runs the chosen command and converts any failure to exit code 1.

    BitesError is an expected, explained failure; any other exception is reported with
    its type. In both cases the message goes to stderr and, if --status was given, a JSON
    error record is written there for the workflow to publish.
    """
    a = make_parser().parse_args(argv)
    try:
        take_toml_file(a)
        return a.func(a) or 0
    except BitesError as exc:
        msg = str(exc)
    except Exception as exc:  # noqa: BLE001 - report anything as a failed stage
        msg = message("cli", "unexpected_error", type=type(exc).__name__, message=exc)
    print(message("cli", "error_line", command=a.cmd, message=msg), file=sys.stderr)
    annotate("error", msg, title=message("cli", "annotation_title", command=a.cmd))
    if getattr(a, "status", None):
        Path(a.status).write_text(
            dumps({"schema": SCHEMA, "status": "error", "stage": a.cmd, "message": msg[:2000]}),
            encoding="utf-8",
        )
    return 1
