"""Tests for the preflight check in scripts/bootstrap.sh and for the rendered workflow header.

The check looks for the action repository and the requested version without the user's
git credentials. Here the "action repository" is a local bare repository passed with
--action-url, so no network is needed.
"""
import shutil
from pathlib import Path

import pytest
from gitutil import make_remote, sh

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "bootstrap.sh"
pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None, reason="needs git and bash"
)

FAKE_SHA = "0123456789abcdef0123456789abcdef01234567"


def make_action_repo(tmp_path, env, tag="v1"):
    """Create a local bare repository standing in for the action, with one tag; return its path."""
    bare = tmp_path / "action.git"
    sh(["git", "init", "--quiet", "--bare", "--initial-branch=main", str(bare)], env=env)
    seed = tmp_path / "action-seed"
    sh(["git", "clone", "--quiet", str(bare), str(seed)], env=env)
    sh(["git", "checkout", "--quiet", "-b", "main"], cwd=seed, env=env)
    (seed / "action.yml").write_text("name: x\n")
    sh(["git", "add", "."], cwd=seed, env=env)
    sh(["git", "commit", "--quiet", "-m", "action"], cwd=seed, env=env)
    sh(["git", "tag", tag], cwd=seed, env=env)
    sh(["git", "push", "--quiet", "origin", "main", tag], cwd=seed, env=env)
    return bare


def run(bare, env, *extra):
    """Run bootstrap.sh against the bare target remote; never fails the test on exit status."""
    return sh(
        ["bash", str(SCRIPT), "--url", str(bare), "--action", "imdebating/bites", *extra, "owner/repo", "main"],
        env=env,
        check=False,
    )


def test_silent_when_action_and_tag_exist(tmp_path):
    """No warning when the action repository is reachable and has the tag."""
    bare, env = make_remote(tmp_path)
    action = make_action_repo(tmp_path, env)
    r = run(bare, env, "--action-url", str(action))
    assert r.returncode == 0, r.stderr
    assert "cannot reach" not in r.stderr and "no tag or branch" not in r.stderr


def test_warns_but_continues_when_tag_is_missing(tmp_path):
    """A missing tag is a warning; the workflow is still installed."""
    bare, env = make_remote(tmp_path)
    action = make_action_repo(tmp_path, env)
    r = run(bare, env, "--action-url", str(action), "--ref", "v9")
    assert r.returncode == 0, r.stderr
    assert "no tag or branch named 'v9'" in r.stderr
    wf = sh(["git", "show", "main:.github/workflows/bites.yml"], cwd=bare, env=env).stdout
    assert "imdebating/bites@v9" in wf


def test_warns_when_action_repository_is_unreachable(tmp_path):
    """An action repository that cannot be reached anonymously gives the 'repository not found' warning."""
    bare, env = make_remote(tmp_path)
    r = run(bare, env, "--action-url", str(tmp_path / "does-not-exist.git"))
    assert r.returncode == 0, r.stderr
    assert "cannot reach" in r.stderr and "repository not found" in r.stderr


def test_commit_sha_ref_only_checks_reachability(tmp_path):
    """A full commit SHA cannot be looked up by name, so it passes whenever the repository is reachable."""
    bare, env = make_remote(tmp_path)
    action = make_action_repo(tmp_path, env)
    r = run(bare, env, "--action-url", str(action), "--ref", FAKE_SHA)
    assert r.returncode == 0, r.stderr
    assert "no tag or branch" not in r.stderr and "cannot reach" not in r.stderr


def test_no_preflight_flag_skips_the_check(tmp_path):
    """--no-preflight suppresses all preflight output."""
    bare, env = make_remote(tmp_path)
    r = run(bare, env, "--action-url", str(tmp_path / "does-not-exist.git"), "--no-preflight")
    assert r.returncode == 0, r.stderr
    assert "cannot reach" not in r.stderr


def test_url_alone_skips_the_check(tmp_path):
    """With --url and no --action-url the check is off, so the tests never touch github.com."""
    bare, env = make_remote(tmp_path)
    r = sh(
        ["bash", str(SCRIPT), "--url", str(bare), "--action", "no-such-owner/no-such-repo", "owner/repo", "main"],
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert "cannot reach" not in r.stderr


def test_rendered_workflow_header_has_no_leftover_text(tmp_path):
    """The installed workflow keeps a sensible header: the placeholders appear only on the uses: lines."""
    bare, env = make_remote(tmp_path)
    r = run(bare, env, "--no-preflight")
    assert r.returncode == 0, r.stderr
    wf = sh(["git", "show", "main:.github/workflows/bites.yml"], cwd=bare, env=env).stdout
    assert "__ACTION__" not in wf and "__REF__" not in wf
    assert "replacing imdebating/bites" not in wf
    assert wf.count("uses: imdebating/bites@v1") == 1
    assert wf.count("uses: imdebating/bites/cleanup@v1") == 1


def test_template_has_exactly_two_placeholder_pairs():
    """The template mentions each placeholder only on its two uses: lines, not in comments."""
    template = (Path(__file__).resolve().parent.parent / "templates" / "bites.yml").read_text(encoding="utf-8")
    assert template.count("__ACTION__") == 2 and template.count("__REF__") == 2
