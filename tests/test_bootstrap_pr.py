"""Tests for bootstrap.sh --protected (-p): a direct push first, and a pull request only when needed.

Everything runs against local bare repositories. A protected branch is simulated with an `update`
hook that rejects pushes with the text GitHub uses, and `gh` is replaced by a small script on PATH.
"""
import contextlib
import os
import shutil
from pathlib import Path

import pytest
from gitutil import make_remote, sh

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "bootstrap.sh"
WF = ".github/workflows/bites.yml"
CLI_URL = "https://cli.github.com"
VALUE_OPTIONS = {"-v", "--workflow-version", "-f", "--action-from", "-c", "--config"}
pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None, reason="needs git and bash"
)


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
        ["bash", str(SCRIPT), "--url", str(bare), "--action-from", "imdebating/bites", *opts, target, *names],
        env=env,
        check=False,
    )


def refs(bare, env):
    out = sh(["git", "for-each-ref", "--format=%(refname) %(objectname)"], cwd=bare, env=env).stdout
    return dict(line.split(" ", 1) for line in out.splitlines())


def show(bare, env, ref, path):
    return sh(["git", "show", f"{ref}:{path}"], cwd=bare, env=env).stdout


def has(bare, env, ref, path):
    """True if `path` exists at `ref` in the bare remote."""
    return sh(["git", "cat-file", "-e", f"{ref}:{path}"], cwd=bare, env=env, check=False).returncode == 0


def setup_refs(bare, env):
    return sorted(r for r in refs(bare, env) if "bites-setup" in r)


def protect(bare, *branches, reason=None):
    """Reject every push to `branches` the way GitHub does, unless the `unprotected` block is active."""
    cond = " || ".join(f'[ "$1" = refs/heads/{b} ]' for b in branches)
    if reason is None:
        lines = (
            '  echo "error: GH006: Protected branch update failed for $1." >&2\n'
            '  echo "error: Changes must be made through a pull request." >&2\n'
        )
    else:
        lines = f'  echo "{reason}" >&2\n'
    hook = bare / "hooks" / "update"
    hook.write_text(
        "#!/bin/sh\n"
        f'if [ -e "{bare}/allow-pushes" ]; then exit 0; fi\n'
        f"if {cond}; then\n{lines}  exit 1\nfi\nexit 0\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)


@contextlib.contextmanager
def unprotected(bare):
    """Let the test's own helper pushes through a protect() hook."""
    flag = bare / "allow-pushes"
    flag.write_text("", encoding="utf-8")
    try:
        yield
    finally:
        flag.unlink()


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


def env_without_gh(tmp_path, env):
    """An environment whose PATH holds the tools the script needs, and no gh."""
    d = tmp_path / "no-gh-bin"
    d.mkdir()
    tools = ("git", "bash", "sh", "sed", "awk", "grep", "tr", "head", "tail", "cat", "cmp", "mktemp",
             "rm", "dirname", "basename", "mkdir", "cp", "ls", "sort", "wc", "env", "uname", "id", "date")
    for t in tools:
        found = shutil.which(t)
        if found:
            (d / t).symlink_to(found)
    return dict(env, PATH=str(d))


def test_a_protected_default_branch_gets_a_setup_branch_and_a_pull_request(tmp_path):
    bare, env = make_remote(tmp_path)
    protect(bare, "main")
    env0, log = fake_gh(tmp_path, env, "echo 0", "gh0")
    r = run(bare, env0, "-p", "main")
    assert r.returncode == 3, r.stdout + r.stderr
    assert not has(bare, env, "main", WF)
    assert has(bare, env, "bites-setup/main", WF)
    assert "PENDING" in r.stdout
    lines = log.read_text().splitlines()
    assert any(x.startswith("pr create") and "--head bites-setup/main" in x and "--base main" in x for x in lines)


def test_a_protected_branch_without_the_option_fails_and_names_the_option(tmp_path):
    bare, env = make_remote(tmp_path)
    protect(bare, "main")
    r = run(bare, env, "main")
    assert r.returncode == 1
    assert "FAILED" in r.stdout and "--protected" in r.stdout
    assert setup_refs(bare, env) == []


def test_the_option_does_nothing_when_the_branch_is_not_protected(tmp_path):
    bare, env = make_remote(tmp_path)
    r = run(bare, env, "-p", "main")
    assert r.returncode == 0, r.stdout + r.stderr
    assert has(bare, env, "main", WF)
    assert setup_refs(bare, env) == []


def test_the_default_branch_is_used_when_no_branch_is_named(tmp_path):
    bare, env = make_remote(tmp_path)
    protect(bare, "main")
    env0, _ = fake_gh(tmp_path, env, "echo 0", "gh0")
    assert run(bare, env0, "-p").returncode == 3
    assert setup_refs(bare, env) == ["refs/heads/bites-setup/main"]


def test_only_the_protected_branch_gets_a_pull_request(tmp_path):
    bare, env = make_remote(tmp_path, branches=("dev", "rel"))
    protect(bare, "dev")
    env0, _ = fake_gh(tmp_path, env, "echo 0", "gh0")
    r = run(bare, env0, "-p", "main", "dev", "rel")
    assert r.returncode == 3, r.stdout + r.stderr
    assert has(bare, env, "main", WF) and has(bare, env, "rel", WF)
    assert not has(bare, env, "dev", WF)
    assert setup_refs(bare, env) == ["refs/heads/bites-setup/dev"]


def test_other_rejections_are_failures_and_never_become_pull_requests(tmp_path):
    bare, env = make_remote(tmp_path)
    protect(bare, "main", reason="permission denied")
    r = run(bare, env, "-p", "main")
    assert r.returncode == 1
    assert "FAILED" in r.stdout
    assert setup_refs(bare, env) == []


def test_a_pull_request_is_pending_until_merged_and_then_verified(tmp_path):
    bare, env = make_remote(tmp_path)
    protect(bare, "main")
    env0, _ = fake_gh(tmp_path, env, "echo 0", "gh0")
    assert run(bare, env0, "-p", "main").returncode == 3
    setup = refs(bare, env)["refs/heads/bites-setup/main"]
    assert run(bare, env0, "-p", "main").returncode == 3
    assert refs(bare, env)["refs/heads/bites-setup/main"] == setup
    sh(["git", "update-ref", "refs/heads/main", setup], cwd=bare, env=env)
    r = run(bare, env0, "-p", "main")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "complete and verified" in r.stdout


def test_a_setup_branch_that_holds_more_than_the_workflow_is_replaced(tmp_path):
    bare, env = make_remote(tmp_path)
    protect(bare, "main")
    quiet, _ = fake_gh(tmp_path, env, "exit 1", "gh-quiet")
    assert run(bare, quiet, "-p", "main").returncode == 3
    add_commit(bare, env, "bites-setup/main", "extra.sh", "echo hi\n")
    dirty = refs(bare, env)["refs/heads/bites-setup/main"]
    r = run(bare, quiet, "-p", "main")
    assert r.returncode == 3, r.stdout + r.stderr
    assert refs(bare, env)["refs/heads/bites-setup/main"] != dirty
    assert not has(bare, env, "bites-setup/main", "extra.sh")
    assert has(bare, env, "bites-setup/main", WF)


def test_a_setup_branch_whose_workflow_mode_changed_is_replaced(tmp_path):
    bare, env = make_remote(tmp_path)
    protect(bare, "main")
    quiet, _ = fake_gh(tmp_path, env, "exit 1", "gh-quiet")
    assert run(bare, quiet, "-p", "main").returncode == 3
    work = tmp_path / "work-mode"
    sh(["git", "clone", "--quiet", "--branch", "bites-setup/main", str(bare), str(work)], env=env)
    sh(["git", "update-index", "--chmod=+x", WF], cwd=work, env=env)
    sh(["git", "commit", "--quiet", "-m", "mode"], cwd=work, env=env)
    sh(["git", "push", "--quiet", "origin", "bites-setup/main"], cwd=work, env=env)
    changed = refs(bare, env)["refs/heads/bites-setup/main"]
    assert run(bare, quiet, "-p", "main").returncode == 3
    assert refs(bare, env)["refs/heads/bites-setup/main"] != changed
    assert sh(["git", "ls-tree", "bites-setup/main", WF], cwd=bare, env=env).stdout.startswith("100644")


def test_a_setup_branch_is_kept_when_the_branch_moved_on(tmp_path):
    bare, env = make_remote(tmp_path)
    protect(bare, "main")
    quiet, _ = fake_gh(tmp_path, env, "exit 1", "gh-quiet")
    assert run(bare, quiet, "-p", "main").returncode == 3
    setup = refs(bare, env)["refs/heads/bites-setup/main"]
    with unprotected(bare):
        add_commit(bare, env, "main", "later.txt", "x\n")
    assert run(bare, quiet, "-p", "main").returncode == 3
    assert refs(bare, env)["refs/heads/bites-setup/main"] == setup


def test_a_new_workflow_version_replaces_the_setup_branch(tmp_path):
    bare, env = make_remote(tmp_path)
    protect(bare, "main")
    quiet, _ = fake_gh(tmp_path, env, "exit 1", "gh-quiet")
    assert run(bare, quiet, "-p", "main").returncode == 3
    assert run(bare, quiet, "-p", "-v", "v2", "main").returncode == 3
    assert "uses: imdebating/bites@v2" in show(bare, env, "bites-setup/main", WF)
    assert not has(bare, env, "main", WF)


def test_the_old_flat_setup_branch_is_removed_and_replaced(tmp_path):
    bare, env = make_remote(tmp_path)
    sh(["git", "branch", "bites-setup", "main"], cwd=bare, env=env)
    protect(bare, "main")
    env0, _ = fake_gh(tmp_path, env, "echo 0", "gh0")
    r = run(bare, env0, "-p", "main")
    assert r.returncode == 3, r.stdout + r.stderr
    assert setup_refs(bare, env) == ["refs/heads/bites-setup/main"]


def test_all_branches_skips_the_setup_branches(tmp_path):
    bare, env = make_remote(tmp_path, branches=("dev", "bites-setup/dev"))
    r = run(bare, env, "-a")
    assert r.returncode == 0, r.stdout + r.stderr
    got = refs(bare, env)
    assert "refs/heads/bites/dev" in got
    assert "refs/heads/bites/bites-setup/dev" not in got
    assert not has(bare, env, "bites-setup/dev", WF)


def test_a_pull_request_is_opened_only_when_none_is_open(tmp_path):
    bare, env = make_remote(tmp_path)
    protect(bare, "main")
    env0, log0 = fake_gh(tmp_path, env, "echo 0", "gh0")
    assert run(bare, env0, "-p", "main").returncode == 3
    assert run(bare, env0, "-p", "main").returncode == 3  # the pull request was closed; the branch was left behind
    lines = log0.read_text().splitlines()
    assert sum(1 for x in lines if x.startswith("pr create")) == 2
    assert any("--head bites-setup/main" in x and "--base main" in x and "--state open" in x for x in lines)
    env1, log1 = fake_gh(tmp_path, env, "echo 1", "gh1")
    assert run(bare, env1, "-p", "main").returncode == 3
    assert not any(x.startswith("pr create") for x in log1.read_text().splitlines())


def test_the_link_is_given_when_gh_cannot_be_used(tmp_path):
    bare, env = make_remote(tmp_path)
    protect(bare, "main")
    broken, log = fake_gh(tmp_path, env, "exit 1", "gh-broken")
    r = run(bare, broken, "-p", "main")
    assert r.returncode == 3
    assert "gh auth login" in r.stderr
    assert "/compare/main...bites-setup/main" in r.stdout + r.stderr
    assert not any(x.startswith("pr create") for x in log.read_text().splitlines())


def test_a_missing_gh_is_explained_with_install_instructions(tmp_path):
    bare, env = make_remote(tmp_path)
    protect(bare, "main")
    r = run(bare, env_without_gh(tmp_path, env), "-p", "main")
    assert r.returncode == 3, r.stdout + r.stderr
    assert "GitHub CLI (gh) was not found" in r.stdout
    assert CLI_URL in r.stdout and "brew install gh" in r.stdout
    assert "/compare/main...bites-setup/main" in r.stdout


def test_a_dry_run_writes_nothing_and_reports_whether_gh_is_installed(tmp_path):
    bare, env = make_remote(tmp_path)
    before = refs(bare, env)
    with_gh, _ = fake_gh(tmp_path, env, "echo 0", "gh0")
    r = run(bare, with_gh, "--dry-run", "-p", "main")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "cannot tell whether a branch is protected" in r.stdout
    assert "was found" in r.stdout
    r = run(bare, env_without_gh(tmp_path, env), "--dry-run", "-p", "main")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "was not found" in r.stdout and CLI_URL in r.stdout
    assert refs(bare, env) == before


def test_a_dry_run_without_the_option_says_nothing_about_gh(tmp_path):
    bare, env = make_remote(tmp_path)
    r = run(bare, env, "--dry-run", "main")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "GitHub CLI" not in r.stdout
