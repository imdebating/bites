"""Tests for `bootstrap.sh --set` and the settings placeholder in the workflow template."""
import re
import shutil
from pathlib import Path

import pytest
from gitutil import branches, make_remote, sh

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "bootstrap.sh"
pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None, reason="needs git and bash"
)

# A line that sets one of the options under `with:` (comment lines never match: they start with #).
SETTING_LINE = re.compile(r"^\s+(max-chars|read-cap|include|exclude):", re.MULTILINE)


def run(bare, env, *extra):
    """Run bootstrap.sh against the bare remote for owner/repo, mirroring main."""
    return sh(
        ["bash", str(SCRIPT), "--url", str(bare), "--action", "imdebating/bites", *extra, "owner/repo", "main"],
        env=env,
        check=False,
    )


def workflow(bare, env):
    """Return the text of the installed workflow on main."""
    return sh(["git", "show", "main:.github/workflows/bites.yml"], cwd=bare, env=env).stdout


def head(bare, env):
    """Return the commit id of main in the bare remote."""
    return sh(["git", "rev-parse", "main"], cwd=bare, env=env).stdout.strip()


def test_template_has_exactly_one_settings_placeholder():
    template = (ROOT / "templates" / "bites.yml").read_text(encoding="utf-8")
    assert template.count("\n__SETTINGS__\n") == 1
    assert template.count("__SETTINGS__") == 1


def test_without_settings_no_placeholder_or_option_remains(tmp_path):
    bare, env = make_remote(tmp_path)
    assert run(bare, env).returncode == 0
    wf = workflow(bare, env)
    assert "__SETTINGS__" not in wf
    assert not SETTING_LINE.search(wf)


def test_settings_are_written_under_with(tmp_path):
    bare, env = make_remote(tmp_path)
    r = run(bare, env, "--set", "max_chars=20000", "--set", "read_cap=25000",
            "--set", "include=**/*.md", "--set", "include=**/*.py", "--set", "exclude=docs/**")
    assert r.returncode == 0, r.stderr
    wf = workflow(bare, env)
    assert "__SETTINGS__" not in wf
    assert "          max-chars: 20000\n" in wf
    assert "          read-cap: 25000\n" in wf
    assert "          include: |\n            **/*.md\n            **/*.py\n" in wf
    assert "          exclude: |\n            docs/**\n" in wf
    assert wf.index("full:") < wf.index("          max-chars:") < wf.index("cleanup:")


def test_same_settings_again_change_nothing(tmp_path):
    bare, env = make_remote(tmp_path)
    assert run(bare, env, "--set", "max_chars=20000").returncode == 0
    before = head(bare, env)
    assert run(bare, env, "--set", "max_chars=20000").returncode == 0
    assert head(bare, env) == before


def test_changed_settings_update_the_workflow(tmp_path):
    bare, env = make_remote(tmp_path)
    assert run(bare, env, "--set", "max_chars=20000").returncode == 0
    assert run(bare, env, "--set", "max_chars=15000").returncode == 0
    wf = workflow(bare, env)
    assert "max-chars: 15000" in wf and "max-chars: 20000" not in wf


def test_running_again_without_settings_is_refused(tmp_path):
    bare, env = make_remote(tmp_path)
    assert run(bare, env, "--set", "max_chars=20000").returncode == 0
    before = head(bare, env)
    r = run(bare, env)
    assert r.returncode != 0
    assert "would remove" in r.stderr
    assert head(bare, env) == before
    assert "max-chars: 20000" in workflow(bare, env)


@pytest.mark.parametrize("bad", [
    "max_chars=abc", "max_chars=0", "max_chars=", "read_cap=1.5", "wrapper_chars=82",
    "manifest_max_chars=5", "colour=blue", "nokey", "include=a b", "include=${x}",
])
def test_bad_settings_are_rejected_before_anything_changes(tmp_path, bad):
    bare, env = make_remote(tmp_path)
    r = run(bare, env, "--set", bad)
    assert r.returncode != 0
    assert branches(bare, env) == {"main"}
