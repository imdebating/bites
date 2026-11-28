"""GitHub Actions annotations, in addition to the ordinary stderr diagnostics.

Only the exact GITHUB_ACTIONS=true value enables runner commands. Message data and
property values use the same escaping rules as actions/toolkit's command writer.
"""
import os
import sys


def escape_data(value):
    return str(value).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_property(value):
    return escape_data(value).replace(":", "%3A").replace(",", "%2C")


def annotate(level, text, *, title):
    """Write one runner command on stdout, never changing the ordinary stderr output."""
    if level not in ("error", "warning"):
        raise ValueError("annotation level must be error or warning")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        sys.stdout.write(f"::{level} title={escape_property(title)}::{escape_data(text)}\n")
