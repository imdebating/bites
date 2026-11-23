"""Tests for the command line of bites_tool: `-c`/`--config KEY=VALUE` and `--toml FILE`."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bites_tool import cli  # noqa: E402

BIG = "manifest_max_chars = 100000\n"


def git(cwd, *args):
    """Run git in `cwd` with a fixed identity; raise if it fails."""
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd, check=True, capture_output=True,
    )


@pytest.fixture()
def source(tmp_path):
    """A git repository holding one 12-character markdown file; returns (src, out)."""
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    git(src, "init", "-q")
    (src / "a.md").write_text("x" * 12, encoding="utf-8")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "one")
    return src, out


def build(source, *extra):
    src, out = source
    return cli.main([
        "build", "--src", str(src), "--out", str(out),
        "--source-branch", "t", "--source-commit", "c", *extra,
    ])


def parts(source):
    return sorted(p.name for p in (source[1] / "parts").rglob("*.txt"))


def write_toml(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_short_and_long_config_options_do_the_same(tmp_path, source):
    empty = write_toml(tmp_path, "empty.toml", "")
    assert build(source, "--toml", empty, "-c", "max_chars=5", "-c", "manifest_max_chars=100000") == 0
    assert len(parts(source)) == 3
    again = (tmp_path / "src2", tmp_path / "out2")
    again[0].mkdir()
    git(again[0], "init", "-q")
    (again[0] / "a.md").write_text("x" * 12, encoding="utf-8")
    git(again[0], "add", "-A")
    git(again[0], "commit", "-q", "-m", "one")
    assert build(again, "--toml", empty, "--config", "max_chars=5", "--config", "manifest_max_chars=100000") == 0
    assert parts(again) == parts(source)


def test_toml_option_names_the_configuration_file(tmp_path, source):
    cfg = write_toml(tmp_path, "five.toml", "max_chars = 5\n" + BIG)
    assert build(source, "--toml", cfg) == 0
    assert len(parts(source)) == 3


def test_toml_file_setting_names_the_configuration_file(tmp_path, source):
    cfg = write_toml(tmp_path, "five.toml", "max_chars = 5\n" + BIG)
    assert build(source, "-c", f"toml_file={cfg}") == 0
    assert len(parts(source)) == 3


def test_toml_file_setting_wins_over_the_toml_option(tmp_path, source):
    empty = write_toml(tmp_path, "empty.toml", "")
    five = write_toml(tmp_path, "five.toml", "max_chars = 5\n" + BIG)
    assert build(source, "--toml", empty, "-c", f"toml_file={five}") == 0
    assert len(parts(source)) == 3


def test_settings_still_override_the_configuration_file(tmp_path, source):
    five = write_toml(tmp_path, "five.toml", "max_chars = 5\n" + BIG)
    assert build(source, "--toml", five, "-c", "max_chars=6") == 0
    assert len(parts(source)) == 2
    assert parts(source)[0].endswith("of-0002.txt")


def test_the_old_set_option_no_longer_exists(tmp_path, source):
    empty = write_toml(tmp_path, "empty.toml", "")
    with pytest.raises(SystemExit) as stopped:
        build(source, "--toml", empty, "--set", "max_chars=5")
    assert stopped.value.code == 2


def test_a_setting_without_an_equals_sign_is_an_error(tmp_path, source, capsys):
    empty = write_toml(tmp_path, "empty.toml", "")
    assert build(source, "--toml", empty, "-c", "max_chars") == 1
    assert "--config expects KEY=VALUE" in capsys.readouterr().err


def test_an_empty_toml_file_setting_is_an_error(source, capsys):
    assert build(source, "-c", "toml_file=") == 1
    assert "toml_file needs a file name" in capsys.readouterr().err
