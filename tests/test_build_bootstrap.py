"""Tests for scripts/build_bootstrap.py: the release copy of bootstrap.sh is one file that works alone."""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

from gitutil import make_remote, sh

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "scripts" / "build_bootstrap.py"
SOURCE = ROOT / "scripts" / "bootstrap.sh"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
WF = ".github/workflows/bites.yml"


def build(out, *extra):
    return subprocess.run([sys.executable, str(BUILD), "-o", str(out), *extra], capture_output=True, text=True)


def alone(tmp_path):
    """Build the release script into an empty directory, with nothing next to it."""
    folder = tmp_path / "download"
    folder.mkdir()
    result = build(folder / "bootstrap.sh")
    assert result.returncode == 0, result.stderr
    return folder / "bootstrap.sh"


def run_script(script, bare, env, *args):
    return sh(["bash", str(script), "--url", str(bare), *args], cwd=script.parent, env=env, check=False)


def test_the_build_is_reproducible_and_comes_with_a_checksum(tmp_path):
    first, second = tmp_path / "a" / "bootstrap.sh", tmp_path / "b" / "bootstrap.sh"
    assert build(first).returncode == 0 and build(second).returncode == 0
    assert first.read_bytes() == second.read_bytes()
    digest, name = first.with_name("bootstrap.sh.sha256").read_text(encoding="utf-8").split()
    assert name == "bootstrap.sh" and digest == hashlib.sha256(first.read_bytes()).hexdigest()
    assert first.stat().st_mode & 0o111


def test_the_release_script_needs_nothing_from_a_checkout(tmp_path):
    text = alone(tmp_path).read_text(encoding="utf-8")
    assert "@@VERSION@@" not in text and "BASH_SOURCE" not in text and "$HERE" not in text
    assert "release:" not in text and '. "$HERE/strings.sh"' not in text
    assert f'VERSION="{VERSION}"' in text
    assert text.rstrip().endswith('main "$@"; exit $?')


def test_it_prints_its_version_and_help_from_an_empty_directory(tmp_path):
    script = alone(tmp_path)
    version = sh(["bash", str(script), "--version"], cwd=script.parent)
    assert version.stdout.splitlines()[0] == f"bootstrap.sh {VERSION}"
    checkout = sh(["bash", str(SOURCE), "--help"])
    assert sh(["bash", str(script), "--help"], cwd=script.parent).stdout == checkout.stdout


def test_it_does_exactly_what_the_checkout_does(tmp_path):
    """Same output, same exit status, same workflow file on the remote."""
    (tmp_path / "x").mkdir()
    (tmp_path / "y").mkdir()
    bare_a, env_a = make_remote(tmp_path / "x", branches=("dev",))
    bare_b, env_b = make_remote(tmp_path / "y", branches=("dev",))
    args = ("-c", "max_chars=15000", "owner/repo", "main", "dev")
    from_checkout = run_script(SOURCE, bare_a, env_a, *args)
    from_download = run_script(alone(tmp_path), bare_b, env_b, *args)
    assert from_checkout.returncode == 0, from_checkout.stdout + from_checkout.stderr
    assert (from_download.returncode, from_download.stdout, from_download.stderr) == \
        (from_checkout.returncode, from_checkout.stdout, from_checkout.stderr)
    for branch in ("main", "dev"):
        shown_a = sh(["git", "show", f"{branch}:{WF}"], cwd=bare_a, env=env_a).stdout
        shown_b = sh(["git", "show", f"{branch}:{WF}"], cwd=bare_b, env=env_b).stdout
        assert shown_a == shown_b and "max-chars: 15000" in shown_b


def test_it_works_when_piped_into_bash_even_if_a_command_reads_standard_input(tmp_path):
    """`curl ... | bash -s -- ARGS`: git here reads standard input, as ssh can, and must not eat the script."""
    script = alone(tmp_path)
    bare, env = make_remote(tmp_path)
    fake = tmp_path / "fake"
    fake.mkdir()
    real_git = shutil.which("git")
    shim = fake / "git"
    shim.write_text(f'#!/bin/sh\nif [ "$1" = clone ]; then cat > /dev/null; fi\nexec "{real_git}" "$@"\n', encoding="utf-8")
    shim.chmod(0o755)
    environment = {**env, "PATH": f"{fake}:" + sh(["bash", "-c", "echo $PATH"]).stdout.strip()}
    done = subprocess.run(["bash", "-s", "--", "--url", str(bare), "owner/repo", "main"], input=script.read_bytes(),
                          cwd=tmp_path, env={**os.environ, **environment}, capture_output=True)
    assert done.returncode == 0, done.stdout.decode() + done.stderr.decode()
    assert b"Setup complete and verified" in done.stdout
    assert "uses: imdebating/bites@" in sh(["git", "show", f"main:{WF}"], cwd=bare, env=env).stdout


def test_the_tag_must_match_the_version_file(tmp_path):
    out = tmp_path / "bootstrap.sh"
    wrong = build(out, "--check-tag", "v0.0.0")
    assert wrong.returncode == 1 and "does not match the VERSION file" in wrong.stderr and not out.exists()
    assert build(out, "--check-tag", f"v{VERSION}").returncode == 0 and out.exists()
