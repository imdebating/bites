"""Tests for settings overrides (--set, BITES_* variables), the paths that can never be
included, and the part-size warning."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bites_tool import cli, core  # noqa: E402


def load(tmp_path, text, overrides=None):
    """Write `text` as a bites.toml in tmp_path and load it with `overrides` on top."""
    p = tmp_path / "bites.toml"
    p.write_text(text, encoding="utf-8")
    return core.load_config(p, overrides)


def git(cwd, *args):
    """Run git in `cwd` with a fixed identity; raise if it fails."""
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd, check=True, capture_output=True,
    )


def test_override_wins_over_the_file(tmp_path):
    cfg = load(tmp_path, "max_chars = 5000\nread_cap = 9000\n", {"max_chars": 6000})
    assert cfg["max_chars"] == 6000
    assert cfg["read_cap"] == 9000


def test_parse_setting_numbers_and_lists():
    assert core.parse_setting("max_chars", " 123 ") == 123
    text = "**/*.md\n\n# a comment\n  **/*.py  \n"
    assert core.parse_setting("include", text) == ["**/*.md", "**/*.py"]
    with pytest.raises(core.BitesError):
        core.parse_setting("max_chars", "lots")


def test_settings_from_env_ignores_blank_values():
    env = {"BITES_MAX_CHARS": "20000", "BITES_READ_CAP": "", "BITES_INCLUDE": "**/*.md\n", "OTHER": "x"}
    assert core.settings_from_env(env) == {"max_chars": 20000, "include": ["**/*.md"]}


def test_set_beats_env_and_repeated_lists_accumulate():
    env = {"BITES_MAX_CHARS": "20000", "BITES_INCLUDE": "**/*.txt"}
    got = core.collect_overrides(["max_chars=15000", "include=**/*.md", "include=**/*.py"], env)
    assert got == {"max_chars": 15000, "include": ["**/*.md", "**/*.py"]}


@pytest.mark.parametrize("bad", ["nokey", "colour=blue", "=5"])
def test_bad_set_items_are_rejected(bad):
    with pytest.raises(core.BitesError):
        core.collect_overrides([bad], {})


def test_always_excluded_paths_cannot_be_included_back(tmp_path):
    cfg = load(tmp_path, "include = ['**/*']\nexclude = []\n")
    files = [".git/x", ".github/w.yml", ".bites-patches/p.patch", "bites.toml", "a.md", ".env"]
    assert core.select_files(cfg, files) == ["a.md"]


def test_warning_when_a_part_cannot_fit_under_read_cap(tmp_path):
    assert core.config_warnings(load(tmp_path, "")) == []
    assert core.config_warnings(load(tmp_path, "max_chars = 27900\n"))


def test_build_reads_the_environment_and_the_set_option(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    git(src, "init", "-q")
    (src / "f.md").write_text("x" * 25, encoding="utf-8")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "one")
    cfg = tmp_path / "bites.toml"
    cfg.write_text("", encoding="utf-8")
    base = ["build", "--config", str(cfg), "--src", str(src), "--source-branch", "t", "--source-commit", "c"]

    # The manifest limit defaults to max_chars, which is far too small for tiny parts, so
    # the test gives it room.
    monkeypatch.setenv("BITES_MANIFEST_MAX_CHARS", "100000")
    monkeypatch.setenv("BITES_MAX_CHARS", "10")
    out1 = tmp_path / "out1"
    assert cli.main([*base, "--out", str(out1)]) == 0
    man = json.loads((out1 / "manifest.json").read_text(encoding="utf-8"))
    assert man["max_chars"] == 10 and man["files"]["f.md"]["parts"] == 3

    out2 = tmp_path / "out2"
    assert cli.main([*base, "--out", str(out2), "--set", "max_chars=5"]) == 0
    man = json.loads((out2 / "manifest.json").read_text(encoding="utf-8"))
    assert man["max_chars"] == 5 and man["files"]["f.md"]["parts"] == 5
