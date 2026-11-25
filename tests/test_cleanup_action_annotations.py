"""Execute the real cleanup YAML shell block without requiring a YAML parser."""
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def block():
    source = (ROOT / "cleanup" / "action.yml").read_text(encoding="utf-8")
    return textwrap.dedent(source.split("      run: |\n", 1)[1])


@pytest.mark.parametrize("enabled", ["", "false", "TRUE", "1", "true"])
def test_missing_script_fallback_is_standalone_and_escaped(tmp_path, enabled):
    action_path = str(tmp_path / "missing %, action\r\nsecond line")
    message = f"cleanup.sh not found at {action_path}/../scripts/cleanup.sh (action path: {action_path})"
    env = dict(os.environ, ACTION_PATH=action_path, GITHUB_ACTIONS=enabled)
    done = subprocess.run(["bash", "-euo", "pipefail", "-c", block()], env=env, capture_output=True, text=True)
    expected = message + "\n"
    if enabled == "true":
        escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        expected += f"::error title=bites cleanup::{escaped}\n"
    assert done.returncode == 1
    assert done.stdout == ""
    assert done.stderr == expected.replace("\r\n", "\n")


def test_existing_script_runs_without_fallback_annotation(tmp_path):
    action = tmp_path / "cleanup"
    action.mkdir()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "cleanup.sh").write_text("printf 'called\\n'\nexit 7\n", encoding="utf-8")
    done = subprocess.run(["bash", "-euo", "pipefail", "-c", block()], env=dict(os.environ, ACTION_PATH=str(action), GITHUB_ACTIONS="true"), capture_output=True, text=True)
    assert done.returncode == 7
    assert done.stdout == "called\n"
    assert done.stderr == ""
