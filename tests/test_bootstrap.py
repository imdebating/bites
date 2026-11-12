"""Tests for scripts/bootstrap.sh, run against local bare git repositories (no network).

Each test gets a bare "remote" with two branches (main, dev) and runs the real script
against it through its --url option. A private HOME and fixed git identity keep the
developer's own git configuration out of the results. Run with:

    python -m pytest tests -q
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "bootstrap.sh"
pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None, reason="needs git and bash"
)


def sh(args, cwd=None, env=None, check=True):
    """Run a command with `env` added to the environment; raise with its output if it fails."""
    e = dict(os.environ)
    e.update(env or {})
    r = subprocess.run(args, cwd=cwd, env=e, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"{args} failed\nstdout:{r.stdout}\nstderr:{r.stderr}")
    return r


@pytest.fixture()
def remote(tmp_path):
    """Create a bare remote with branches main and dev; return (its path, the git env)."""
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    bare = tmp_path / "remote.git"
    sh(["git", "init", "--quiet", "--bare", "--initial-branch=main", str(bare)], env=env)
    seed = tmp_path / "seed"
    sh(["git", "clone", "--quiet", str(bare), str(seed)], env=env)
    sh(["git", "checkout", "--quiet", "-b", "main"], cwd=seed, env=env)
    (seed / "README.md").write_text("hello\n")
    sh(["git", "add", "."], cwd=seed, env=env)
    sh(["git", "commit", "--quiet", "-m", "init"], cwd=seed, env=env)
    sh(["git", "push", "--quiet", "origin", "main"], cwd=seed, env=env)
    sh(["git", "checkout", "--quiet", "-b", "dev"], cwd=seed, env=env)
    sh(["git", "push", "--quiet", "origin", "dev"], cwd=seed, env=env)
    return bare, env


def refs(bare, env):
    """Return {branch name: commit id} for every branch in the bare remote."""
    out = sh(["git", "for-each-ref", "--format=%(refname:short) %(objectname)"], cwd=bare, env=env).stdout
    return dict(line.split(" ", 1) for line in out.splitlines())


def run(bare, env, *extra, check=True):
    """Run bootstrap.sh against the bare remote with the given extra arguments."""
    return sh(
        ["bash", str(SCRIPT), "--url", str(bare), "--action", "imdebating/bites", *extra],
        env=env,
        check=check,
    )


def show(bare, env, ref, path):
    """Return the text of `path` at `ref` in the bare remote."""
    return sh(["git", "show", f"{ref}:{path}"], cwd=bare, env=env).stdout


def test_installs_workflow_and_creates_mirror_branches(remote):
    """The caller lands on main with its placeholders filled in; bites/main and bites/dev exist."""
    bare, env = remote
    run(bare, env, "owner/repo", "main", "dev")
    r = refs(bare, env)
    assert "bites/main" in r and "bites/dev" in r
    wf = show(bare, env, "main", ".github/workflows/bites.yml")
    assert "uses: imdebating/bites@v1" in wf
    assert "__ACTION__" not in wf and "__REF__" not in wf
    assert show(bare, env, "main", "README.md") == "hello\n"


def test_default_branch_when_none_given(remote):
    """With no branch arguments only the default branch is mirrored."""
    bare, env = remote
    run(bare, env, "owner/repo")
    r = refs(bare, env)
    assert "bites/main" in r and "bites/dev" not in r


def test_second_run_changes_nothing(remote):
    """Running again is a no-op: no ref moves and nothing new is created."""
    bare, env = remote
    run(bare, env, "owner/repo", "main")
    before = refs(bare, env)
    run(bare, env, "owner/repo", "main")
    assert refs(bare, env) == before


def test_ref_change_updates_the_caller(remote):
    """Re-running with --ref rewrites the version in the installed caller."""
    bare, env = remote
    run(bare, env, "owner/repo", "main")
    run(bare, env, "--ref", "v2", "owner/repo", "main")
    assert "uses: imdebating/bites@v2" in show(bare, env, "main", ".github/workflows/bites.yml")


def test_dry_run_changes_nothing(remote):
    """--dry-run prints what it would push but leaves the remote untouched."""
    bare, env = remote
    before = refs(bare, env)
    r = run(bare, env, "--dry-run", "owner/repo", "main")
    assert "[dry-run]" in r.stdout
    assert refs(bare, env) == before


def test_pr_mode_leaves_default_branch_alone(remote):
    """--pr pushes the workflow to bites-setup and does not move the default branch."""
    bare, env = remote
    before = refs(bare, env)["main"]
    run(bare, env, "--pr", "owner/repo", "main")
    r = refs(bare, env)
    assert r["main"] == before
    assert "bites-setup" in r and "bites/main" in r


def test_warns_when_other_branch_lacks_the_workflow(remote):
    """A listed branch created before the caller existed gets a 'merge main into it' warning."""
    bare, env = remote
    r = run(bare, env, "owner/repo", "main", "dev")
    assert "merge main into it" in r.stderr


def test_rejects_bad_input(remote):
    """A malformed target, a missing source branch and a bites/* source branch all fail."""
    bare, env = remote
    assert run(bare, env, "not-a-repo", check=False).returncode != 0
    assert run(bare, env, "owner/repo", "nope", check=False).returncode != 0
    assert run(bare, env, "owner/repo", "bites/main", check=False).returncode != 0
