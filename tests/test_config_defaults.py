"""Tests for configuration defaults: partial bites.toml files, and agreement between the
defaults built into core.py and the shipped bites.toml."""
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bites_tool import core  # noqa: E402


def load(tmp_path, text):
    """Write `text` as a bites.toml in tmp_path and load it."""
    p = tmp_path / "bites.toml"
    p.write_text(text, encoding="utf-8")
    return core.load_config(p)


def test_empty_config_uses_every_default(tmp_path):
    cfg = load(tmp_path, "")
    assert (cfg["max_chars"], cfg["read_cap"], cfg["wrapper_chars"]) == (27000, 28000, 82)
    assert cfg["manifest_max_chars"] == 27000
    files = ["a.md", "docs/b.txt", "src/c.py", "pyproject.toml", "img/d.png",
             ".github/e.yml", "bites.toml", "node_modules/x/f.md"]
    assert core.select_files(cfg, files) == ["a.md", "docs/b.txt", "src/c.py", "pyproject.toml"]


def test_partial_config_overrides_only_what_it_names(tmp_path):
    cfg = load(tmp_path, "max_chars = 5000\n")
    assert cfg["max_chars"] == 5000
    assert cfg["read_cap"] == 28000
    assert cfg["manifest_max_chars"] == 5000
    assert core.select_files(cfg, ["a.md", "b.png"]) == ["a.md"]


def test_include_replaces_the_default_list_but_always_excluded_paths_stay_out(tmp_path):
    cfg = load(tmp_path, 'include = ["**/*.rst"]\n')
    assert core.select_files(cfg, ["a.md", "b.rst", ".github/c.rst"]) == ["b.rst"]


def test_exclude_replaces_only_the_default_list(tmp_path):
    cfg = load(tmp_path, 'exclude = ["docs/**"]\n')
    files = ["a.md", "docs/b.md", "node_modules/x/f.md", ".github/c.yml"]
    assert core.select_files(cfg, files) == ["a.md", "node_modules/x/f.md"]


def test_empty_include_is_an_error(tmp_path):
    with pytest.raises(core.BitesError):
        load(tmp_path, "include = []\n")


def test_shipped_bites_toml_matches_the_built_in_defaults(tmp_path):
    raw = tomllib.loads((ROOT / "bites.toml").read_text(encoding="utf-8"))
    assert raw["include"] == core.DEFAULT_INCLUDE
    assert raw["exclude"] == core.DEFAULT_EXCLUDE
    defaults = load(tmp_path, "")
    for key in ("max_chars", "read_cap", "wrapper_chars"):
        assert raw[key] == defaults[key]
