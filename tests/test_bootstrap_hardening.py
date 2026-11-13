"""Tests for how bootstrap.sh treats odd input and remote failures."""
import os
import shutil
from pathlib import Path

import pytest
from gitutil import branches, make_remote, sh

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "bootstrap.sh"
pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None, reason="needs git and bash"
)


def test_invisible_character_in_branch_name_is_rejected(tmp_path):
    """A branch name ending in a non-breaking space (as pasted from a web page) fails up front."""
    bare, env = make_remote(tmp_path)
    r = sh(
        ["bash", str(SCRIPT), "--url", str(bare), "owner/repo", b"main\xc2\xa0"],
        env=env,
        check=False,
    )
    assert r.returncode != 0
    assert "other than letters, digits" in r.stderr
    assert branches(bare, env) == {"main"}


def test_missing_source_branch_is_reported_by_name(tmp_path):
    bare, env = make_remote(tmp_path)
    r = sh(["bash", str(SCRIPT), "--url", str(bare), "owner/repo", "nope"], env=env, check=False)
    assert r.returncode != 0
    assert "source branch nope does not exist on the remote" in r.stderr


def test_unreachable_remote_is_not_reported_as_a_missing_branch(tmp_path):
    """If asking the remote about a branch fails outright, the error says so."""
    bare, env = make_remote(tmp_path)
    fake = tmp_path / "fakebin"
    fake.mkdir()
    wrapper = fake / "git"
    wrapper.write_text(
        '#!/bin/sh\n'
        'for a in "$@"; do\n'
        '  if [ "$a" = "--heads" ]; then echo "fatal: unable to access the remote" >&2; exit 128; fi\n'
        'done\n'
        f'exec "{shutil.which("git")}" "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    env2 = dict(env, PATH=f"{fake}:{os.environ['PATH']}")
    r = sh(["bash", str(SCRIPT), "--url", str(bare), "owner/repo", "main"], env=env2, check=False)
    assert r.returncode != 0
    assert "could not ask the remote" in r.stderr
    assert "does not exist" not in r.stderr
