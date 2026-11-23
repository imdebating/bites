"""Tests that bootstrap.sh recognises the push rejections GitHub sends for a protected branch.

The two texts below are what git printed for a direct push to a protected branch, captured from
real GitHub repositories by tests/release_suite.sh (scenarios S5 and S6) on 2026-11-21: one with
classic branch protection, one with a ruleset that requires a pull request. They include the
final status lines, which a local `update` hook cannot produce, so the detection pattern is
checked against them directly, with the same grep the script uses. The last test then runs
bootstrap.sh against a remote whose hook prints the ruleset message.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from gitutil import make_remote
from test_bootstrap_pr import fake_gh, protect, refs, run, setup_refs

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "bootstrap.sh"
pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None or shutil.which("grep") is None,
    reason="needs git, bash and grep",
)

CLASSIC = """\
remote: error: GH006: Protected branch update failed for refs/heads/main.
remote:
remote: - Changes must be made through a pull request.
To https://github.com/OWNER/REPO.git
 ! [remote rejected] HEAD -> main (protected branch hook declined)
error: failed to push some refs to 'https://github.com/OWNER/REPO.git'
"""

RULESET = """\
remote: error: GH013: Repository rule violations found for refs/heads/main.
remote: Review all repository rules at https://github.com/OWNER/REPO/rules?ref=refs%2Fheads%2Fmain
remote:
remote: - Changes must be made through a pull request.
remote:
To https://github.com/OWNER/REPO.git
 ! [remote rejected] HEAD -> main (push declined due to repository rule violations)
error: failed to push some refs to 'https://github.com/OWNER/REPO.git'
"""

NOT_PROTECTION = {
    "permission": "remote: Permission to OWNER/REPO.git denied to someone.\n"
    "fatal: unable to access 'https://github.com/OWNER/REPO.git/': The requested URL returned error: 403\n",
    "private email": "remote: error: GH007: Your push would publish a private email address.\n"
    " ! [remote rejected] HEAD -> main (push declined due to email privacy restrictions)\n",
    "moved on": " ! [rejected]        HEAD -> main (fetch first)\n"
    "error: failed to push some refs to 'https://github.com/OWNER/REPO.git'\n",
}


def detection_pattern():
    """Return the pattern push_needs_pull_request() passes to `grep -Eqi` in bootstrap.sh."""
    m = re.search(r"push_needs_pull_request\(\)\s*\{\s*grep -Eqi '([^']+)'", SCRIPT.read_text(encoding="utf-8"))
    assert m, "push_needs_pull_request() was not found in bootstrap.sh"
    return m.group(1)


def detects(text, tmp_path):
    """True if the script's own grep call treats `text` as a rejection that needs a pull request."""
    f = tmp_path / "push.err"
    f.write_text(text, encoding="utf-8")
    return subprocess.run(["grep", "-Eqi", detection_pattern(), str(f)]).returncode == 0


@pytest.mark.parametrize("text", [CLASSIC, RULESET], ids=["classic", "ruleset"])
def test_a_real_protection_rejection_is_detected(tmp_path, text):
    assert detects(text, tmp_path)


@pytest.mark.parametrize("text", [CLASSIC, RULESET], ids=["classic", "ruleset"])
def test_each_line_that_identifies_the_rejection_is_enough_alone(tmp_path, text):
    key = [ln for ln in text.splitlines() if "GH0" in ln or "declined" in ln]
    assert len(key) == 2
    for line in key:
        assert detects(line + "\n", tmp_path), line


@pytest.mark.parametrize("name", sorted(NOT_PROTECTION))
def test_other_rejections_are_not_taken_for_protection(tmp_path, name):
    assert not detects(NOT_PROTECTION[name], tmp_path)


def test_a_ruleset_rejection_gets_a_setup_branch_and_a_pull_request(tmp_path):
    bare, env = make_remote(tmp_path)
    reason = (
        "error: GH013: Repository rule violations found for refs/heads/main.\n"
        "Review all repository rules at https://github.com/owner/repo/rules?ref=refs%2Fheads%2Fmain\n"
        "\n"
        "- Changes must be made through a pull request."
    )
    protect(bare, "main", reason=reason)
    env0, _ = fake_gh(tmp_path, env, "echo 0", "gh0")
    r = run(bare, env0, "-p", "main")
    assert r.returncode == 3, r.stdout + r.stderr
    assert setup_refs(bare, env) == ["refs/heads/bites-setup/main"]
    assert "refs/heads/main" in refs(bare, env)
