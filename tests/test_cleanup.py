"""Tests for scripts/cleanup.sh: when the mirror of a deleted branch is, and is not, deleted.

Each test builds a bare remote, deletes a source branch in it (as GitHub does), clones it,
and runs the real script inside the clone with the environment the action would provide.
"""
import shutil
from pathlib import Path

import pytest
from gitutil import branches, make_remote, sh

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "cleanup.sh"
pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None, reason="needs git and bash"
)


def cleanup(tmp_path, existing, mirrors, deleted, remove=True, **overrides):
    """Make a remote with `existing` branches and `mirrors`, then run cleanup for `deleted`.

    `deleted` is the branch name passed to the script. With remove=True (the normal case) it
    is first deleted from the remote, as GitHub would have done; remove=False simulates a
    branch that exists again by the time the script runs. Returns (script result, the
    branch names left on the remote).
    """
    bare, env = make_remote(tmp_path, branches=existing, mirrors=mirrors)
    if remove and deleted in existing:
        sh(["git", "update-ref", "-d", f"refs/heads/{deleted}"], cwd=bare, env=env)
    work = tmp_path / "work"
    sh(["git", "clone", "--quiet", str(bare), str(work)], env=env)
    settings = {"BRANCH": deleted, "REF_TYPE": "branch", "DEFAULT_BRANCH": "main", "DRY_RUN": "false"}
    settings.update(overrides)
    r = sh(["bash", str(SCRIPT)], cwd=work, env={**env, **settings}, check=False)
    return r, branches(bare, env)


def test_deletes_mirror_of_deleted_branch(tmp_path):
    """Deleting `feature` removes bites/feature and leaves every other mirror alone."""
    r, left = cleanup(tmp_path, ["feature", "other"], ["feature", "other", "main"], "feature")
    assert r.returncode == 0, r.stderr
    assert "bites/feature" not in left
    assert {"bites/other", "bites/main", "other", "main"} <= left


def test_branch_names_with_slashes(tmp_path):
    """A branch such as feature/login has the mirror bites/feature/login, and it is removed."""
    r, left = cleanup(tmp_path, ["feature/login"], ["feature/login"], "feature/login")
    assert r.returncode == 0, r.stderr
    assert "bites/feature/login" not in left


def test_keeps_mirror_when_source_exists_again(tmp_path):
    """If the source branch exists when the script runs (restored or re-created), keep the mirror."""
    r, left = cleanup(tmp_path, ["feature"], ["feature"], "feature", remove=False)
    assert r.returncode == 0 and "exists again" in r.stdout
    assert "bites/feature" in left


def test_never_touches_default_branch_mirror(tmp_path):
    """bites/main is kept even if an event names the default branch."""
    r, left = cleanup(tmp_path, [], ["main"], "main")
    assert r.returncode == 0 and "bites/main" in left


def test_ignores_output_branches(tmp_path):
    """Deleting a bites/* branch does not cascade into bites/bites/...."""
    r, left = cleanup(tmp_path, [], ["x"], "bites/x")
    assert r.returncode == 0 and "bites/x" in left


def test_ignores_tags(tmp_path):
    """A deleted tag with the same name as a mirrored branch removes nothing."""
    r, left = cleanup(tmp_path, [], ["v1"], "v1", REF_TYPE="tag")
    assert r.returncode == 0 and "bites/v1" in left


def test_nothing_to_do_without_a_mirror(tmp_path):
    """A deleted branch that was never mirrored is a quiet success."""
    r, left = cleanup(tmp_path, ["plain"], [], "plain")
    assert r.returncode == 0 and "no bites/plain branch" in r.stdout


def test_dry_run_deletes_nothing(tmp_path):
    """DRY_RUN=true reports the deletion but leaves the mirror in place."""
    r, left = cleanup(tmp_path, ["feature"], ["feature"], "feature", DRY_RUN="true")
    assert r.returncode == 0 and "[dry-run]" in r.stdout and "bites/feature" in left
