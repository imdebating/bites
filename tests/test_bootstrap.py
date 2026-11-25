"""Tests for scripts/bootstrap.sh, run against local bare git repositories (no network).

Each test gets a bare "remote" with two branches (main, dev) and runs the real script
against it through its --url option. A private HOME and fixed git identity keep the
developer's own git configuration out of the results. Run with:

    python -m pytest tests -q

The multi-branch behaviour (--all-branches, partial failures, verification, --protected) is in
test_bootstrap_branches.py.
"""
import shutil
from pathlib import Path

import pytest
from gitutil import make_remote, sh

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "bootstrap.sh"
WF = ".github/workflows/bites.yml"
pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None, reason="needs git and bash"
)


@pytest.fixture()
def remote(tmp_path):
    """Create a bare remote with branches main and dev; return (its path, the git env)."""
    return make_remote(tmp_path, branches=("dev",))


def refs(bare, env):
    """Return {branch name: commit id} for every branch in the bare remote."""
    out = sh(["git", "for-each-ref", "--format=%(refname:short) %(objectname)"], cwd=bare, env=env).stdout
    return dict(line.split(" ", 1) for line in out.splitlines())


def run(bare, env, *extra, check=True):
    """Run bootstrap.sh against the bare remote with the given extra arguments."""
    return sh(
        ["bash", str(SCRIPT), "--url", str(bare), "--action-from", "imdebating/bites", *extra],
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
    wf = show(bare, env, "main", WF)
    assert "uses: imdebating/bites@v1" in wf
    assert "__ACTION__" not in wf and "__REF__" not in wf
    assert show(bare, env, "main", "README.md") == "hello\n"


def test_default_branch_when_none_given(remote):
    """With no branch arguments only the default branch is mirrored."""
    bare, env = remote
    run(bare, env, "owner/repo")
    r = refs(bare, env)
    assert "bites/main" in r and "bites/dev" not in r


def test_every_selected_branch_gets_the_workflow_without_a_merge(remote):
    """dev gets its own caller as one new commit on top of its old tip; nothing is merged."""
    bare, env = remote
    old_dev = refs(bare, env)["dev"]
    run(bare, env, "owner/repo", "main", "dev")
    assert show(bare, env, "dev", WF) == show(bare, env, "main", WF)
    assert sh(["git", "rev-parse", "dev^"], cwd=bare, env=env).stdout.strip() == old_dev
    parents = sh(["git", "rev-list", "--parents", "-n", "1", "dev"], cwd=bare, env=env).stdout.split()
    assert len(parents) == 2


def test_second_run_changes_nothing(remote):
    """Running again is a no-op: no ref moves and nothing new is created."""
    bare, env = remote
    run(bare, env, "owner/repo", "main")
    before = refs(bare, env)
    run(bare, env, "owner/repo", "main")
    assert refs(bare, env) == before


def test_ref_change_updates_the_caller(remote):
    """Re-running with --workflow-version rewrites the version in the installed caller."""
    bare, env = remote
    run(bare, env, "owner/repo", "main")
    run(bare, env, "--workflow-version", "v2", "owner/repo", "main")
    assert "uses: imdebating/bites@v2" in show(bare, env, "main", WF)


def test_dry_run_changes_nothing(remote):
    """--dry-run prints what it would push but leaves the remote untouched, and says it verified nothing."""
    bare, env = remote
    before = refs(bare, env)
    r = run(bare, env, "--dry-run", "owner/repo", "main")
    assert "[dry-run]" in r.stdout
    assert "have not verified anything" in r.stdout
    assert refs(bare, env) == before


def test_rejects_bad_input(remote):
    """A malformed target, a missing source branch and a bites/* source branch all fail."""
    bare, env = remote
    assert run(bare, env, "not-a-repo", check=False).returncode != 0
    assert run(bare, env, "owner/repo", "nope", check=False).returncode != 0
    assert run(bare, env, "owner/repo", "bites/main", check=False).returncode != 0
