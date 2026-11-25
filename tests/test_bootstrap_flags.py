"""Tests for the bootstrap.sh command line: short and long options, the renamed options, and --version."""
import os
import re
import shutil
import sys
from pathlib import Path

import pytest
from gitutil import make_remote, sh

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bites_tool  # noqa: E402

SCRIPT = ROOT / "scripts" / "bootstrap.sh"
WF = ".github/workflows/bites.yml"
VALUE_OPTIONS = {"-v", "--workflow-version", "-f", "--action-from", "-c", "--config"}
pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None, reason="needs git and bash"
)


def raw(*args):
    """Run bootstrap.sh with exactly these arguments."""
    return sh(["bash", str(SCRIPT), *args], env=dict(os.environ), check=False)


def run(bare, env, *args, target="owner/repo"):
    """Run bootstrap.sh against the bare remote; options go before the target, branch names after it."""
    opts, names, it = [], [], iter(args)
    for a in it:
        if a in VALUE_OPTIONS:
            opts += [a, next(it)]
        elif a.startswith("-"):
            opts.append(a)
        else:
            names.append(a)
    return sh(
        ["bash", str(SCRIPT), "--url", str(bare), *opts, target, *names],
        env=env,
        check=False,
    )


def refs(bare, env):
    out = sh(["git", "for-each-ref", "--format=%(refname) %(objectname)"], cwd=bare, env=env).stdout
    return dict(line.split(" ", 1) for line in out.splitlines())


def show(bare, env, ref, path):
    return sh(["git", "show", f"{ref}:{path}"], cwd=bare, env=env).stdout


# ---- the version --------------------------------------------------------------------------------

def test_the_version_file_holds_one_version_and_nothing_else():
    text = (ROOT / "VERSION").read_text(encoding="utf-8")
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+\n", text)


def test_python_and_the_script_report_the_version_in_the_version_file():
    number = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert bites_tool.__version__ == number
    for flag in ("-V", "--version"):
        r = raw(flag)
        assert r.returncode == 0, r.stdout + r.stderr
        assert r.stdout.splitlines()[0] == f"bootstrap.sh {number}"


def test_version_needs_no_target_and_works_among_other_options():
    number = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    r = raw("-a", "-V")
    assert r.returncode == 0 and r.stdout.startswith(f"bootstrap.sh {number}")


# ---- help ---------------------------------------------------------------------------------------

def test_short_and_long_help_are_the_same_and_describe_every_option():
    short, long = raw("-h"), raw("--help")
    assert short.returncode == 0 and long.returncode == 0
    assert short.stdout == long.stdout
    for name in ("--all-branches", "--workflow-version", "--action-from", "--config", "--ssh",
                 "--protected", "--dry-run", "--no-preflight", "--version", "--help"):
        assert name in long.stdout


# ---- renamed and unknown options ----------------------------------------------------------------

@pytest.mark.parametrize(
    "old, args, new",
    [
        ("--ref", ["--ref", "v2"], "--workflow-version"),
        ("--action", ["--action", "x/y"], "--action-from"),
        ("--set", ["--set", "max_chars=5"], "--config"),
        ("--pr", ["--pr"], "--protected"),
    ],
)
def test_an_old_option_name_stops_with_a_pointer_to_the_new_one(tmp_path, old, args, new):
    bare, env = make_remote(tmp_path)
    before = refs(bare, env)
    r = run(bare, env, *args, "main")
    assert r.returncode == 1
    assert old in r.stderr and new in r.stderr
    assert refs(bare, env) == before


def test_an_unknown_option_is_rejected(tmp_path):
    bare, env = make_remote(tmp_path)
    r = run(bare, env, "-x", "main")
    assert r.returncode == 1 and "Unknown option: -x" in r.stderr


# ---- short forms --------------------------------------------------------------------------------

def test_short_and_long_options_make_the_same_workflow(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    bare_a, env = make_remote(tmp_path / "a")
    bare_b, _ = make_remote(tmp_path / "b")
    long = run(bare_a, env, "--workflow-version", "v2", "--config", "max_chars=5",
               "--config", "include=**/*.md", "--no-preflight", "main")
    short = run(bare_b, env, "-v", "v2", "-c", "max_chars=5", "-c", "include=**/*.md", "-n", "main")
    assert long.returncode == 0 and short.returncode == 0, long.stdout + short.stdout + long.stderr + short.stderr
    assert show(bare_a, env, "main", WF) == show(bare_b, env, "main", WF)
    assert "max-chars: 5" in show(bare_a, env, "main", WF)


def test_short_options_can_be_combined(tmp_path):
    bare, env = make_remote(tmp_path, branches=("dev",))
    r = run(bare, env, "-an")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "refs/heads/bites/dev" in refs(bare, env)


def test_an_option_that_takes_a_value_must_come_last_in_a_combination(tmp_path):
    bare, env = make_remote(tmp_path)
    before = refs(bare, env)
    r = sh(["bash", str(SCRIPT), "--url", str(bare), "-va", "v2", "owner/repo"], env=env, check=False)
    assert r.returncode == 1 and "must come last" in r.stderr
    assert refs(bare, env) == before


def test_a_combination_can_end_with_an_option_and_its_value(tmp_path):
    bare, env = make_remote(tmp_path)
    r = sh(["bash", str(SCRIPT), "--url", str(bare), "-nv", "v3", "owner/repo", "main"], env=env, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "uses: imdebating/bites@v3" in show(bare, env, "main", WF)
