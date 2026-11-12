"""Tests for scripts/prune.sh: finding and deleting mirrors whose source branch is gone."""
import shutil
from pathlib import Path

import pytest
from gitutil import branches, make_remote, sh

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "prune.sh"
pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None, reason="needs git and bash"
)


def prune(bare, env, *extra, check=True):
    """Run prune.sh against the bare remote with extra arguments."""
    return sh(["bash", str(SCRIPT), "--url", str(bare), *extra, "owner/repo"], env=env, check=check)


def test_lists_orphans_without_deleting(tmp_path):
    """Only mirrors with no matching source branch are listed, and nothing is deleted."""
    bare, env = make_remote(tmp_path, branches=["alive"], mirrors=["alive", "gone", "main"])
    r = prune(bare, env)
    assert "orphan:  bites/gone" in r.stdout
    assert "bites/alive" not in r.stdout and "bites/main" not in r.stdout
    assert {"bites/alive", "bites/gone", "bites/main"} <= branches(bare, env)


def test_delete_removes_only_orphans(tmp_path):
    """--delete removes the orphans and keeps mirrors whose source still exists."""
    bare, env = make_remote(tmp_path, branches=["alive"], mirrors=["alive", "gone", "main"])
    prune(bare, env, "--delete")
    left = branches(bare, env)
    assert "bites/gone" not in left
    assert {"bites/alive", "bites/main"} <= left


def test_nested_branch_names(tmp_path):
    """bites/feature/x is an orphan only when feature/x is gone, not when merely feature exists."""
    bare, env = make_remote(tmp_path, branches=["feature-a"], mirrors=["feature/x"])
    assert "orphan:  bites/feature/x" in prune(bare, env).stdout


def test_reports_when_clean(tmp_path):
    """With no orphans the script says so."""
    bare, env = make_remote(tmp_path, branches=["alive"], mirrors=["alive"])
    assert "no orphaned" in prune(bare, env).stdout


def test_rejects_bad_target(tmp_path):
    """A target that is not OWNER/REPO fails."""
    bare, env = make_remote(tmp_path)
    r = sh(["bash", str(SCRIPT), "--url", str(bare), "nonsense"], env=env, check=False)
    assert r.returncode != 0
