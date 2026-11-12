"""Shared helpers for the shell-script tests: a throw-away bare remote and a command runner.

Imported by test_cleanup.py and test_prune.py (pytest puts the tests directory on sys.path).
A private HOME and fixed git identity keep the developer's own git configuration out of
the results.
"""
import os
import subprocess


def sh(args, cwd=None, env=None, check=True):
    """Run a command with `env` added to the environment; raise with its output if it fails."""
    e = dict(os.environ)
    e.update(env or {})
    r = subprocess.run(args, cwd=cwd, env=e, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"{args} failed\nstdout:{r.stdout}\nstderr:{r.stderr}")
    return r


def make_remote(tmp_path, branches=(), mirrors=()):
    """Create a bare remote with `main`, the given source `branches` and bites/ `mirrors`.

    Returns (path of the bare remote, git environment). Mirrors are empty-tree root commits,
    like the ones scripts/bootstrap.sh creates.
    """
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
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
    for b in branches:
        sh(["git", "push", "--quiet", "origin", f"main:refs/heads/{b}"], cwd=seed, env=env)
    empty = sh(["git", "mktree"], cwd=seed, env=env).stdout.strip()
    for m in mirrors:
        c = sh(["git", "commit-tree", empty, "-m", "bites: init"], cwd=seed, env=env).stdout.strip()
        sh(["git", "push", "--quiet", "origin", f"{c}:refs/heads/bites/{m}"], cwd=seed, env=env)
    return bare, env


def branches(bare, env):
    """Return the set of branch names in the bare remote."""
    out = sh(["git", "for-each-ref", "--format=%(refname:short)", "refs/heads"], cwd=bare, env=env).stdout
    return set(out.split())
