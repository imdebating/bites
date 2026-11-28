"""Tests for tests/release_rehearsal.sh that need no GitHub: what it refuses, and that it can only touch the scratch repository."""
import re
import shutil
import subprocess
from pathlib import Path

from gitutil import sh

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tests" / "release_rehearsal.sh"
HELPERS = ("say", "die", "begin", "assert", "note", "finish", "skip", "url", "poll", "delete_repo", "safe_repo", "report", "not", "show_out")


def test_the_script_parses_and_prints_its_usage():
    assert sh(["bash", "-n", str(SCRIPT)], check=False).returncode == 0
    done = sh(["bash", str(SCRIPT), "--help"], check=False)
    assert done.returncode == 0 and "usage: bash tests/release_rehearsal.sh" in done.stdout
    wrong = sh(["bash", str(SCRIPT), "--bogus"], check=False)
    assert wrong.returncode == 1 and "unknown option: --bogus" in wrong.stderr


def test_the_suite_still_provides_every_helper_the_rehearsal_uses():
    """The rehearsal sources release_suite.sh for its helpers, and sourcing must not run the suite."""
    names = " ".join(HELPERS)
    done = sh(["bash", "-c", f'source "{ROOT}/tests/release_suite.sh"; for n in {names}; do type -t "$n" >/dev/null || echo "missing $n"; done'],
              check=False)
    assert done.returncode == 0 and done.stdout == "" and done.stderr == "", done.stdout + done.stderr


def test_it_names_no_repository_but_the_scratch_one():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "imdebating" not in text
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        for match in re.finditer(r'(?:-R|--repo)\s+(\S+)', line):
            assert match.group(1).strip('"') == "$R", line
        if "git -C" in line and " push" in line:
            assert '"$src"' in line, line
    assert 'safe_repo "$R"' in text and "gh repo delete" not in text


def fake_checkout(tmp_path, version="1.6.0", dirty=False):
    """A git checkout holding the two scripts, and a fake gh that only knows who is signed in."""
    work = tmp_path / "checkout"
    (work / "tests").mkdir(parents=True)
    for name in ("release_rehearsal.sh", "release_suite.sh"):
        shutil.copy(ROOT / "tests" / name, work / "tests" / name)
    (work / "VERSION").write_text(version + "\n", encoding="utf-8")
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "gh").write_text('#!/bin/sh\ncase "$1 $2" in\n  "api user") echo tester ;;\n  "api -i") echo "x-oauth-scopes: repo, workflow, delete_repo" ;;\n  *) echo "unexpected gh call: $*" >&2; exit 9 ;;\nesac\n', encoding="utf-8")
    (fake / "gh").chmod(0o755)
    env = {"HOME": str(tmp_path), "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e.com",
           "PATH": f"{fake}:" + sh(["bash", "-c", "echo $PATH"]).stdout.strip()}
    sh(["git", "init", "--quiet", "-b", "main", str(work)], env=env)
    sh(["git", "-C", str(work), "add", "-A"], env=env)
    sh(["git", "-C", str(work), "commit", "--quiet", "-m", "c"], env=env)
    if dirty:
        (work / "VERSION").write_text(version + "\n\n", encoding="utf-8")
    return work, env


def test_it_stops_before_touching_github_when_the_tree_is_dirty(tmp_path):
    work, env = fake_checkout(tmp_path, dirty=True)
    done = sh(["bash", str(work / "tests" / "release_rehearsal.sh")], cwd=work, env=env, check=False)
    assert done.returncode == 1 and "uncommitted changes" in done.stderr
    assert "unexpected gh call" not in done.stderr


def test_it_stops_when_version_is_not_a_plain_number(tmp_path):
    work, env = fake_checkout(tmp_path, version="1.6.0-rc1")
    done = sh(["bash", str(work / "tests" / "release_rehearsal.sh")], cwd=work, env=env, check=False)
    assert done.returncode == 1 and "VERSION at HEAD must be a number" in done.stderr
    assert "unexpected gh call" not in done.stderr
