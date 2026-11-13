"""bites - split large text files into exact, reversible, size-capped parts.

COMMANDS
    apply            apply pending patch files (.bites-patches/*.patch) to the source tree
    build            write parts, manifest.json and last_build.json into --out
    verify           check the whole output tree against the source tree
    reassemble       write one original file, rebuilt from its parts, to stdout
    report-failure   convert a failure status file into <out>/last_build.json

SETTINGS
    build and verify read the configuration file given by --config; `--set KEY=VALUE`
    (repeatable) and BITES_<KEY> environment variables override it. See bites_tool/core.py.

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


def make_parser():
    """Build the argparse parser with one sub-command per `cmd_*` function."""
    ap = argparse.ArgumentParser(prog="python -m bites_tool", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        """Add the option every command shares: where to record a JSON error."""
        p.add_argument("--status", help="on failure, write a JSON error record to this path")

    def settings(p):
        """Add the option that overrides configuration settings."""
        p.add_argument(
            "--set", action="append", default=[], metavar="KEY=VALUE",
            help="override a setting (max_chars, read_cap, include, exclude); repeat for more, "
                 "repeated include/exclude options add to one list",
        )

    p = sub.add_parser("apply", help="apply pending patch files")
    p.add_argument("--src", default=".", help="source repository root")
    p.add_argument("--patches", default=".bites-patches", help="patch directory, relative to --src")
    p.add_argument("--report", help="write the per-section patch report (JSON) here")
    common(p)
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("build", help="write parts, manifest.json and last_build.json")
    p.add_argument("--config", default="bites.toml")
    p.add_argument("--src", default=".", help="source repository root")
    p.add_argument("--out", required=True, help="checkout of the bites/<branch> tree")
    p.add_argument("--source-branch", default="", help="recorded in the manifest")
    p.add_argument("--source-commit", default="", help="recorded in the manifest")
    p.add_argument("--patch-report", help="report written by `apply`, copied into last_build.json")
    p.add_argument("--full", action="store_true", help="rebuild every large file")
    settings(p)
    common(p)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("verify", help="check the output tree against the source tree")
    p.add_argument("--config", default="bites.toml")
    p.add_argument("--src", default=".")
    p.add_argument("--out", required=True)
    settings(p)
    common(p)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("reassemble", help="write one original file to stdout")
    p.add_argument("--out", required=True)
    p.add_argument("--file", required=True, help="source path as listed in the manifest")
    common(p)
    p.set_defaults(func=cmd_reassemble)

    p = sub.add_parser("report-failure", help="turn a failure status into last_build.json")
    p.add_argument("--status", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--source-branch", default="")
    p.add_argument("--source-commit", default="")
    p.set_defaults(func=cmd_report_failure)
    return ap


def main(argv=None) -> int:
    """Entry point. Runs the chosen command and converts any failure to exit code 1.

    BitesError is an expected, explained failure; any other exception is reported with
    its type. In both cases the message goes to stderr and, if --status was given, a JSON
    error record is written there for the workflow to publish.
    """
    a = make_parser().parse_args(argv)
    try:
        return a.func(a) or 0
    except BitesError as exc:
        msg = str(exc)
    except Exception as exc:  # noqa: BLE001 - report anything as a failed stage
        msg = f"{type(exc).__name__}: {exc}"
    print(f"bites {a.cmd}: ERROR: {msg}", file=sys.stderr)
    if getattr(a, "status", None):
        Path(a.status).write_text(
            dumps({"schema": SCHEMA, "status": "error", "stage": a.cmd, "message": msg[:2000]}),
            encoding="utf-8",
        )
    return 1
