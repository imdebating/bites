"""The message catalog: every sentence bites prints lives in locales/strings.en.toml.

`message(table, name, **values)` returns the text of one catalog entry with its placeholders
filled in. Placeholders are written {like_this}; the catalog writes {{ and }} for literal
braces, which is exactly what `str.format` does, so the catalog is formatted with it.

The catalog is found next to this package (the action's checkout, which is also what
PYTHONPATH points at), so the package cannot be copied somewhere else without it.
"""
from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

CATALOG = Path(__file__).resolve().parent.parent / "locales" / "strings.en.toml"


@lru_cache(maxsize=1)
def _catalog() -> dict:
    """Read and parse the catalog once per process."""
    with open(CATALOG, "rb") as fh:
        return tomllib.load(fh)


def message(table: str, name: str, /, **values) -> str:
    """Return the catalog text `[table] name` with `values` filled in.

    `table` and `name` are positional-only so a placeholder may itself be called `name`.
    A missing key raises KeyError and an unfilled placeholder raises KeyError too, which
    is deliberate: tests/test_strings.py checks every call, so neither can ship.
    """
    return _catalog()[table][name].format(**values)
