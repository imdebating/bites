"""Shell annotation gating, escaping, and retained diagnostics (including bash 3.2)."""
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STRINGS = ROOT / "scripts" / "strings.sh"


def shell(command, enabled):
    env = dict(os.environ, GITHUB_ACTIONS=enabled)
    return subprocess.run(["bash", "-c", command], env=env, text=True, capture_output=True)


@pytest.mark.parametrize("value", ["", "false", "TRUE", "1"])
def test_shell_gate_is_exact(value):
    done = shell(f'. "{STRINGS}"; bites_annotate error title problem; echo survived', value)
    assert done.returncode == 0 and done.stdout == "survived\n" and done.stderr == ""


def test_shell_annotation_escapes_without_polluting_stdout():
    command = f'. "{STRINGS}"; bites_annotate warning "$TITLE" "$BODY"'
    env = dict(os.environ, GITHUB_ACTIONS="true", TITLE="bites: a,b%\r\n", BODY="100%\r\n::error::injected,:")
    done = subprocess.run(["bash", "-c", command], env=env, capture_output=True, text=True)
    assert done.returncode == 0 and done.stdout == ""
    assert done.stderr == "::warning title=bites%3A a%2Cb%25%0D%0A::100%25%0D%0A::error::injected,:\n"


@pytest.mark.parametrize("script,args,extra", [
    ("bootstrap.sh", ["--unknown-annotation-test"], {}),
    ("prune.sh", ["--unknown-annotation-test"], {}),
    ("cleanup.sh", [], {"BRANCH": ""}),
])
def test_shell_errors_add_one_annotation_and_keep_diagnostic(script, args, extra):
    cmd = ["bash", str(ROOT / "scripts" / script), *args]
    off = subprocess.run(cmd, env=dict(os.environ, GITHUB_ACTIONS="false", **extra), capture_output=True, text=True)
    on = subprocess.run(cmd, env=dict(os.environ, GITHUB_ACTIONS="true", **extra), capture_output=True, text=True)
    assert on.returncode == off.returncode == 1
    assert on.stdout == off.stdout
    lines = on.stderr.splitlines(keepends=True)
    assert "".join(line for line in lines if not line.startswith("::error ")) == off.stderr
    assert sum(line.startswith("::error ") for line in lines) == 1


def test_bootstrap_multiline_warning_preserves_every_prefix():
    source = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
    warn = next(line for line in source.splitlines() if line.startswith("warn()"))
    command = f'. "{STRINGS}"; text() {{ local key="$1"; shift; bites_fmt "bootstrap.$key" "$@"; }}; {warn}\nwarn "$BODY"'
    env = dict(os.environ, GITHUB_ACTIONS="true", BODY="first%\nsecond")
    done = subprocess.run(["bash", "-c", command], env=env, capture_output=True, text=True)
    assert done.returncode == 0 and done.stdout == ""
    assert done.stderr == "==> Warning: first%\n==> Warning: second\n::warning title=bites bootstrap::first%25%0Asecond\n"
