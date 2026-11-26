"""Tests for bootstrap.sh across several branches: --all-branches, ordering, failures, --protected.

The contract under test: one bootstrap command installs the caller workflow and creates the
output branch for every requested branch, without merging anything, and reports success only when
the remote really holds all of it. Everything runs against local bare repositories.
"""
import shutil
import stat
from pathlib import Path

import pytest
from gitutil import bootstrap_script, make_remote, sh

import tomllib

CATALOG = tomllib.loads(
    (Path(__file__).resolve().parent.parent / "locales" / "strings.en.toml").read_text(encoding="utf-8")
)
SCRIPT = bootstrap_script()
WF = ".github/workflows/bites.yml"
pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None, reason="needs git and bash"
)


def run(bare, env, *args, target="owner/repo"):
    """Run bootstrap.sh against the bare remote; never raises on a non-zero exit.

    Options (--all-branches, --dry-run, --protected, --config X, --workflow-version X) may be mixed with branch names
    in any order here; they are put before the target and the names after it, as the script expects.
    """
    opts, names, it = [], [], iter(args)
    for a in it:
        if a in ("--config", "--workflow-version"):
            opts += [a, next(it)]
        elif a.startswith("--"):
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


def add_commit(bare, env, branch, path, text):
    """Add one commit that creates `path` on `branch` in the bare remote (a divergent branch)."""
    tmp = bare.parent / f"work-{branch.replace('/', '-')}-{path.replace('/', '-')}"
    sh(["git", "clone", "--quiet", "--branch", branch, str(bare), str(tmp)], env=env)
    (tmp / path).parent.mkdir(parents=True, exist_ok=True)
    (tmp / path).write_text(text)
    sh(["git", "add", "."], cwd=tmp, env=env)
    sh(["git", "commit", "--quiet", "-m", f"add {path}"], cwd=tmp, env=env)
    sh(["git", "push", "--quiet", "origin", branch], cwd=tmp, env=env)


def install_hook(bare, name, body):
    hook = bare / "hooks" / name
    hook.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    return hook


# ---- --all-branches ---------------------------------------------------------------------------

def test_all_branches_covers_every_branch_including_slash_names(tmp_path):
    bare, env = make_remote(tmp_path, branches=("dev", "feature/x"))
    r = run(bare, env, "--all-branches")
    assert r.returncode == 0, r.stdout + r.stderr
    got = refs(bare, env)
    for b in ("main", "dev", "feature/x"):
        assert f"refs/heads/bites/{b}" in got
        assert show(bare, env, b, WF) == show(bare, env, "main", WF)
    assert "Setup complete and verified" in r.stdout


def test_all_branches_skips_current_setup_branches(tmp_path):
    bare, env = make_remote(tmp_path, branches=("dev", "bites-setup/dev"))
    before = refs(bare, env)
    r = run(bare, env, "--all-branches")
    assert r.returncode == 0, r.stdout + r.stderr
    got = refs(bare, env)
    assert got["refs/heads/bites-setup/dev"] == before["refs/heads/bites-setup/dev"]
    assert "refs/heads/bites/bites-setup/dev" not in got


def test_all_branches_with_names_is_rejected_before_any_write(tmp_path):
    bare, env = make_remote(tmp_path, branches=("dev",))
    before = refs(bare, env)
    r = run(bare, env, "--all-branches", "main")
    assert r.returncode != 0
    assert "cannot be combined" in r.stderr
    assert refs(bare, env) == before


def test_all_branches_stops_on_an_unsupported_branch_name(tmp_path):
    bare, env = make_remote(tmp_path, branches=("dev", "odd#name"))
    before = refs(bare, env)
    r = run(bare, env, "--all-branches")
    assert r.returncode != 0
    assert "odd#name" in r.stderr
    assert refs(bare, env) == before


# ---- what the workflow commit does and does not touch -------------------------------------------

def test_divergent_branches_keep_their_own_files_and_history(tmp_path):
    bare, env = make_remote(tmp_path, branches=("dev",))
    add_commit(bare, env, "dev", "notes/dev-only.txt", "only on dev\n")
    add_commit(bare, env, "main", "main-only.txt", "only on main\n")
    old = refs(bare, env)
    r = run(bare, env, "--all-branches")
    assert r.returncode == 0, r.stdout + r.stderr
    assert show(bare, env, "dev", "notes/dev-only.txt") == "only on dev\n"
    assert show(bare, env, "main", "main-only.txt") == "only on main\n"
    assert not has(bare, env, "dev", "main-only.txt")
    for b in ("main", "dev"):
        assert sh(["git", "rev-parse", f"{b}^"], cwd=bare, env=env).stdout.strip() == old[f"refs/heads/{b}"]


def test_unselected_branches_are_untouched_and_default_gets_only_the_caller(tmp_path):
    bare, env = make_remote(tmp_path, branches=("dev", "other"))
    before = refs(bare, env)
    r = run(bare, env, "dev")
    assert r.returncode == 0, r.stdout + r.stderr
    got = refs(bare, env)
    assert got["refs/heads/other"] == before["refs/heads/other"]
    assert "refs/heads/bites/main" not in got and "refs/heads/bites/other" not in got
    assert "refs/heads/bites/dev" in got
    assert show(bare, env, "main", WF) == show(bare, env, "dev", WF)
    assert CATALOG["bootstrap"]["no_output_branch_row"] in r.stdout


def test_output_branches_exist_before_the_workflow_is_pushed(tmp_path):
    bare, env = make_remote(tmp_path, branches=("dev",))
    log = tmp_path / "order.log"
    install_hook(bare, "update", f'echo "$1" >> "{log}"\nexit 0\n')
    r = run(bare, env, "main", "dev")
    assert r.returncode == 0, r.stdout + r.stderr
    order = log.read_text().split()
    for b in ("main", "dev"):
        assert order.index(f"refs/heads/bites/{b}") < order.index(f"refs/heads/{b}")


def test_existing_output_branches_are_left_alone(tmp_path):
    bare, env = make_remote(tmp_path, branches=("dev",), output_branches=("dev",))
    before = refs(bare, env)["refs/heads/bites/dev"]
    assert run(bare, env, "main", "dev").returncode == 0
    assert refs(bare, env)["refs/heads/bites/dev"] == before


def test_rerun_and_duplicate_names_change_nothing_more(tmp_path):
    bare, env = make_remote(tmp_path, branches=("dev",))
    assert run(bare, env, "main", "dev", "dev", "main").returncode == 0
    first = refs(bare, env)
    assert sh(["git", "rev-list", "--count", "dev"], cwd=bare, env=env).stdout.strip() == "2"
    assert run(bare, env, "--all-branches").returncode == 0
    assert refs(bare, env) == first


def test_new_ref_reaches_every_branch(tmp_path):
    bare, env = make_remote(tmp_path, branches=("dev",))
    assert run(bare, env, "--all-branches").returncode == 0
    assert run(bare, env, "--all-branches", "--workflow-version", "v2").returncode == 0
    for b in ("main", "dev"):
        assert "uses: imdebating/bites@v2" in show(bare, env, b, WF)


# ---- nothing is written when the checks fail ------------------------------------------------------

def test_a_custom_workflow_on_any_branch_stops_everything_before_writes(tmp_path):
    bare, env = make_remote(tmp_path, branches=("dev",))
    add_commit(bare, env, "dev", WF, "name: something else\non: push\n")
    before = refs(bare, env)
    r = run(bare, env, "main", "dev")
    assert r.returncode != 0
    assert "not a bites workflow" in r.stderr and "dev" in r.stderr
    assert refs(bare, env) == before


def test_settings_that_would_be_dropped_on_any_branch_stop_everything(tmp_path):
    bare, env = make_remote(tmp_path, branches=("dev",))
    assert run(bare, env, "--config", "max_chars=20000", "main", "dev").returncode == 0
    before = refs(bare, env)
    r = run(bare, env, "main", "dev")
    assert r.returncode != 0 and "would remove" in r.stderr
    assert refs(bare, env) == before


def test_a_missing_branch_among_several_writes_nothing(tmp_path):
    bare, env = make_remote(tmp_path, branches=("dev",))
    before = refs(bare, env)
    r = run(bare, env, "main", "dev", "nope")
    assert r.returncode != 0 and "nope" in r.stderr
    assert refs(bare, env) == before


# ---- failures part way, and verification ------------------------------------------------------------

def test_a_rejected_branch_is_reported_and_the_rest_is_finished(tmp_path):
    bare, env = make_remote(tmp_path, branches=("dev",))
    hook = install_hook(
        bare, "update", 'if [ "$1" = refs/heads/dev ]; then echo "protected branch" >&2; exit 1; fi\nexit 0\n'
    )
    r = run(bare, env, "main", "dev")
    assert r.returncode == 1
    assert "Incomplete" in r.stderr and "Failed" in r.stdout
    assert "refs/heads/bites/main" in refs(bare, env)
    assert has(bare, env, "main", WF)
    assert not has(bare, env, "dev", WF)
    hook.unlink()
    r = run(bare, env, "main", "dev")
    assert r.returncode == 0, r.stdout + r.stderr
    assert show(bare, env, "dev", WF) == show(bare, env, "main", WF)


def test_a_mirror_that_cannot_be_created_keeps_its_workflow_back(tmp_path):
    bare, env = make_remote(tmp_path, branches=("dev",))
    install_hook(bare, "update", 'if [ "$1" = refs/heads/bites/dev ]; then exit 1; fi\nexit 0\n')
    r = run(bare, env, "main", "dev")
    assert r.returncode == 1
    assert "Not Complete" in r.stdout
    assert not has(bare, env, "dev", WF)
    assert "refs/heads/bites/main" in refs(bare, env)


def test_a_source_branch_that_moves_meanwhile_is_not_overwritten(tmp_path):
    bare, env = make_remote(tmp_path, branches=("dev",))
    real = shutil.which("git")
    fake = tmp_path / "fakebin"
    fake.mkdir()
    marker = tmp_path / "moved"
    wrapper = fake / "git"
    wrapper.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = push ] && [ ! -e "{marker}" ]; then\n'
        f'  touch "{marker}"\n'
        f'  tree=$("{real}" --git-dir="{bare}" rev-parse dev^{{tree}})\n'
        f'  c=$("{real}" --git-dir="{bare}" commit-tree "$tree" -p dev -m "someone else")\n'
        f'  "{real}" --git-dir="{bare}" update-ref refs/heads/dev "$c"\n'
        "fi\n"
        f'exec "{real}" "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    env2 = dict(env, PATH=f"{fake}:{env.get('PATH', '')}:/usr/bin:/bin")
    r = run(bare, env2, "main", "dev")
    assert r.returncode == 1, r.stdout + r.stderr
    msg = sh(["git", "log", "-1", "--format=%s", "dev"], cwd=bare, env=env).stdout.strip()
    assert msg == "someone else"
    r = run(bare, env, "main", "dev")
    assert r.returncode == 0, r.stdout + r.stderr
    assert show(bare, env, "dev", WF) == show(bare, env, "main", WF)
    assert sh(["git", "log", "-2", "--format=%s", "dev"], cwd=bare, env=env).stdout.split("\n")[1] == "someone else"


def test_success_is_not_claimed_when_the_remote_does_not_hold_the_result(tmp_path):
    bare, env = make_remote(tmp_path, branches=("dev",))
    install_hook(bare, "post-receive", 'git update-ref -d refs/heads/bites/dev 2>/dev/null\nexit 0\n')
    r = run(bare, env, "main", "dev")
    assert r.returncode == 1
    assert "Failed" in r.stdout and "on the remote after the push" in r.stdout
    assert "complete and verified" not in r.stdout


def test_dry_run_with_all_branches_writes_nothing(tmp_path):
    bare, env = make_remote(tmp_path, branches=("dev",))
    before = refs(bare, env)
    r = run(bare, env, "--dry-run", "--all-branches")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("[dry-run]") >= 4
    assert "Planned" in r.stdout and "complete and verified" not in r.stdout
    assert refs(bare, env) == before
