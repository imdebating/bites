"""Guard: the shell scripts must be committed as executable (git mode 100755).

A file written through the GitHub API, or through a connector, is committed as 100644
unless its mode is set, and then `scripts/bootstrap.sh` fails with "permission denied" for
anyone who clones the repository. Fix a failure with
`git update-index --chmod=+x <file>`, then commit and push.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def tracked_script_modes():
    """Return {path: git mode} for the tracked .sh files under scripts/, or None outside git."""
    r = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-s", "--", "scripts"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None
    rows = [line.split(None, 3) for line in r.stdout.splitlines()]  # mode, sha, stage, path
    return {row[3]: row[0] for row in rows if len(row) == 4 and row[3].endswith(".sh")}


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_shell_scripts_are_committed_executable():
    modes = tracked_script_modes()
    if modes is None:
        pytest.skip("not a git checkout")
    assert modes, "no scripts found under scripts/"
    bad = sorted(path for path, mode in modes.items() if mode != "100755")
    assert not bad, f"committed without the executable bit: {bad} (git update-index --chmod=+x ...)"
