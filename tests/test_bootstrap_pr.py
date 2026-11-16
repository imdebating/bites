"""Tests for bootstrap.sh --pr: what bites-setup may hold, and when a pull request is opened.

Everything runs against local bare repositories; `gh` is replaced by a small script on PATH.
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


def run(bare, env, *args, target="owner/repo"):
    """Run bootstrap.sh against the bare remote; options go before the target, branch names after it."""
    opts = [a for a in args if a.startswith("--")]
    names = [a for a in args if not a.startswith("--")]
    return sh(
        ["bash", str(SCRIPT), "--url", str(bare), "--action", "imdebating/bites", *opts, target, *names],
        env=env,
        check=False,
    )


def refs(bare, env):
    out = sh(["git", "for-each-ref", "--format=%(refname) %(objectname)"], cwd=bare, env=env).stdout
    return dict(line.split(" ", 1) for line in out.splitlines())


def has(bare, env, ref, path):
    """True if `path` exists at `ref` in the bare remote."""
    return sh(["git", "cat-file", "-e", f"{ref}:{path}"], cwd=bare, env=env, check=False).returncode == 0


def add_commit(bare, env, branch, path, text):
    """Add one commit that creates `path` on `branch` in the bare remote."""
    tmp = bare.parent / f"work-{branch.replace('/', '-')}-{path.replace('/', '-')}"
    sh(["git", "clone", "--quiet", "--branch", branch, str(bare), str(tmp)], env=env)
    (tmp / path).parent.mkdir(parents=True, exist_ok=True)
    (tmp / path).write_text(text)
    sh(["git", "add", "."], cwd=tmp, env=env)
    sh(["git", "commit", "--quiet", "-m", f"add {path}"], cwd=tmp, env=env)
    sh(["git", "push", "--quiet", "origin", branch], cwd=tmp, env=env)


def fake_gh(tmp_path, env, listing, name):
    """Return (env, log): `gh` on PATH logs its arguments; `listing` is the shell run for `gh pr list`."""
    d = tmp_path / name
    d.mkdir()
    log = tmp_path / f"{name}.log"
    gh = d / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        'if [ "$1 $2" = "pr list" ]; then\n'
        f"  {listing}\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    return dict(env, PATH=f"{d}:{env.get('PATH', '')}:/usr/bin:/bin"), log


def test_pr_replaces_a_setup_branch_that_holds_more_than_the_workflow(tmp_path):
    bare, env = make_remote(tmp_path)
    quiet, _ = fake_gh(tmp_path, env, "exit 1", "gh-quiet")
    assert run(bare, quiet, "--pr", "main").returncode == 3
    add_commit(bare, env, "bites-setup", "extra.sh", "echo hi\n")
    dirty = refs(bare, env)["refs/heads/bites-setup"]
    r = run(bare, quiet, "--pr", "main")
    assert r.returncode == 3, r.stdout + r.stderr
    assert refs(bare, env)["refs/heads/bites-setup"] != dirty
    assert not has(bare, env, "bites-setup", "extra.sh")
    assert has(bare, env, "bites-setup", WF)


def test_pr_replaces_a_setup_branch_whose_workflow_mode_changed(tmp_path):
    bare, env = make_remote(tmp_path)
    quiet, _ = fake_gh(tmp_path, env, "exit 1", "gh-quiet")
    assert run(bare, quiet, "--pr", "main").returncode == 3
    work = tmp_path / "work-mode"
    sh(["git", "clone", "--quiet", "--branch", "bites-setup", str(bare), str(work)], env=env)
    sh(["git", "update-index", "--chmod=+x", WF], cwd=work, env=env)
    sh(["git", "commit", "--quiet", "-m", "mode"], cwd=work, env=env)
    sh(["git", "push", "--quiet", "origin", "bites-setup"], cwd=work, env=env)
    changed = refs(bare, env)["refs/heads/bites-setup"]
    assert run(bare, quiet, "--pr", "main").returncode == 3
    assert refs(bare, env)["refs/heads/bites-setup"] != changed
    assert sh(["git", "ls-tree", "bites-setup", WF], cwd=bare, env=env).stdout.startswith("100644")


def test_pr_keeps_a_setup_branch_when_the_default_branch_moved_on(tmp_path):
    bare, env = make_remote(tmp_path)
    quiet, _ = fake_gh(tmp_path, env, "exit 1", "gh-quiet")
    assert run(bare, quiet, "--pr", "main").returncode == 3
    setup = refs(bare, env)["refs/heads/bites-setup"]
    add_commit(bare, env, "main", "later.txt", "x\n")
    assert run(bare, quiet, "--pr", "main").returncode == 3
    assert refs(bare, env)["refs/heads/bites-setup"] == setup


def test_pr_opens_a_pull_request_only_when_none_is_open(tmp_path):
    bare, env = make_remote(tmp_path)
    env0, log0 = fake_gh(tmp_path, env, "echo 0", "gh0")
    assert run(bare, env0, "--pr", "main").returncode == 3
    assert run(bare, env0, "--pr", "main").returncode == 3  # the PR was closed; the branch is left behind
    lines = log0.read_text().splitlines()
    assert sum(1 for x in lines if x.startswith("pr create")) == 2
    assert any("--head bites-setup" in x and "--base main" in x and "--state open" in x for x in lines)
    env1, log1 = fake_gh(tmp_path, env, "echo 1", "gh1")
    assert run(bare, env1, "--pr", "main").returncode == 3
    assert not any(x.startswith("pr create") for x in log1.read_text().splitlines())


def test_pr_says_how_to_open_the_pull_request_when_gh_cannot_be_used(tmp_path):
    bare, env = make_remote(tmp_path)
    broken, log = fake_gh(tmp_path, env, "exit 1", "gh-broken")
    r = run(bare, broken, "--pr", "main")
    assert r.returncode == 3
    assert "/compare/main...bites-setup" in r.stdout + r.stderr
    assert not any(x.startswith("pr create") for x in log.read_text().splitlines())


def test_pr_dry_run_prints_the_link_and_writes_nothing(tmp_path):
    bare, env = make_remote(tmp_path)
    before = refs(bare, env)
    r = run(bare, env, "--dry-run", "--pr", "main")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "/compare/main...bites-setup" in r.stdout + r.stderr
    assert refs(bare, env) == before
