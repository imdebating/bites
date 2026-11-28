"""The bootstrap tests can run against the built one-file copy, as the release workflow does."""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
BOOTSTRAP_TESTS = sorted(p.name for p in TESTS.glob("test_bootstrap*.py")) + ["test_preflight.py"]
BOOTSTRAP_TESTS = [name for name in BOOTSTRAP_TESTS if name != "test_build_bootstrap.py"]


def run_tests(script, *names):
    env = {**os.environ, "BITES_BOOTSTRAP_SCRIPT": str(script)}
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *[str(TESTS / n) for n in names]],
                          capture_output=True, text=True, env=env, cwd=ROOT)


def test_every_test_that_runs_bootstrap_takes_its_path_from_gitutil():
    for name in BOOTSTRAP_TESTS:
        text = (TESTS / name).read_text(encoding="utf-8")
        assert "SCRIPT = bootstrap_script()" in text, name
        assert not re.search(r'"scripts"\s*/\s*"bootstrap\.sh"', text), name


def test_the_tests_pass_against_the_built_copy_alone_in_an_empty_directory(tmp_path):
    folder = tmp_path / "download"
    folder.mkdir()
    built = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_bootstrap.py"), "-o", str(folder / "bootstrap.sh")],
                           capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    done = run_tests(folder / "bootstrap.sh", "test_bootstrap_flags.py", "test_bootstrap_settings.py", "test_preflight.py")
    assert done.returncode == 0, done.stdout[-2000:]


def test_the_variable_really_selects_the_script_that_runs(tmp_path):
    """A script that is not bootstrap.sh makes those tests fail, so a passing run proves the file was used."""
    impostor = tmp_path / "bootstrap.sh"
    impostor.write_text("#!/usr/bin/env bash\necho 'bootstrap.sh 0.0.0'\n", encoding="utf-8")
    done = run_tests(impostor, "test_bootstrap_flags.py")
    assert done.returncode != 0
