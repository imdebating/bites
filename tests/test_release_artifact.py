"""Release-candidate checks against the actual standalone bootstrap artifact."""
import hashlib
import os
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from gitutil import make_remote, sh

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "scripts" / "bootstrap.sh"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
CATALOG = tomllib.loads((ROOT / "locales" / "strings.en.toml").read_text(encoding="utf-8"))
WF = ".github/workflows/bites.yml"


@pytest.fixture
def artifact(tmp_path):
    folder = tmp_path / "download with spaces"
    folder.mkdir()
    script = folder / "bootstrap.sh"
    done = sh([sys.executable, str(ROOT / "scripts" / "build_bootstrap.py"),
               "--check-tag", f"v{VERSION}", "-o", str(script)])
    assert done.returncode == 0
    # Deliberately leave only the script: no adjacent checksum or checkout helpers.
    script.with_name("bootstrap.sh.sha256").unlink()
    return script


def run(script, *args, env=None):
    return sh(["bash", str(script), *args], cwd=script.parent,
              env={"GITHUB_ACTIONS": "false", **(env or {})}, check=False)


def refs(bare, env):
    return sh(["git", "for-each-ref", "--format=%(refname) %(objectname)"], cwd=bare, env=env).stdout


@pytest.mark.parametrize("enabled", ["", "false", "TRUE", "1", "true"])
def test_artifact_errors_match_checkout_and_gate_annotations(artifact, enabled):
    args = ("--unknown-artifact-test",)
    env = {"GITHUB_ACTIONS": enabled}
    source = run(SOURCE, *args, env=env)
    built = run(artifact, *args, env=env)
    assert (built.returncode, built.stdout, built.stderr) == (source.returncode, source.stdout, source.stderr)
    assert built.returncode == 1
    annotations = [line for line in built.stderr.splitlines() if line.startswith("::error ")]
    assert len(annotations) == (1 if enabled == "true" else 0)
    assert "=> Fatal Error: " in built.stderr


@pytest.mark.parametrize("enabled", ["false", "true"])
def test_artifact_multiline_warnings_and_dry_run_match_checkout(artifact, tmp_path, enabled):
    bare, env = make_remote(tmp_path)
    # A dry run prints the id of each commit it would push, and an id depends on the commit time,
    # so both runs get the same time. Without it the two outputs differ when a second passes between them.
    moment = "@1767225600 +0000"
    env = {**env, "GITHUB_ACTIONS": enabled, "GIT_AUTHOR_DATE": moment, "GIT_COMMITTER_DATE": moment}
    before = refs(bare, env)
    args = ("--url", str(bare), "--action-url", str(bare), "--workflow-version", "missing-ref",
            "--dry-run", "owner/repo", "main")
    source = run(SOURCE, *args, env=env)
    built = run(artifact, *args, env=env)
    assert (built.returncode, built.stdout, built.stderr) == (source.returncode, source.stdout, source.stderr)
    assert built.returncode == 0, built.stdout + built.stderr
    warning = CATALOG["bootstrap"]["preflight_ref_missing"].format(action="imdebating/bites", version="missing-ref")
    human = "".join(f"==> Warning: {line}\n" for line in warning.splitlines())
    expected = human
    if enabled == "true":
        escaped = warning.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        expected += f"::warning title=bites bootstrap::{escaped}\n"
    assert built.stderr == expected
    assert refs(bare, env) == before


def test_artifact_embeds_the_exact_generated_helpers_and_template(artifact):
    text = artifact.read_text(encoding="utf-8")
    assert (ROOT / "scripts" / "strings.sh").read_text(encoding="utf-8").rstrip("\n") in text
    template = (ROOT / "templates" / "bites.yml").read_text(encoding="utf-8")
    assert f"cat <<'BITES_TEMPLATE_END'\n{template}BITES_TEMPLATE_END\n" in text
    assert 'bites_annotate()' in text
    assert 'while ((q = index(v, "\\001")) > 0)' in text
    assert '@@VERSION@@' not in text and 'BASH_SOURCE' not in text
    assert stat.S_IMODE(artifact.stat().st_mode) == 0o755
    done = run(artifact, "--version")
    assert done.returncode == 0 and done.stdout.splitlines()[0] == f"bootstrap.sh {VERSION}"


def test_artifact_installs_exact_workflow_and_is_idempotent(artifact, tmp_path):
    bare, env = make_remote(tmp_path, branches=("dev",))
    args = ("--url", str(bare), "--all-branches", "--workflow-version", f"v{VERSION}", "owner/repo")
    first = run(artifact, *args, env=env)
    assert first.returncode == 0, first.stdout + first.stderr
    before = refs(bare, env)
    template = (ROOT / "templates" / "bites.yml").read_text(encoding="utf-8")
    expected = template.replace("__SETTINGS__\n", "").replace("__ACTION__", "imdebating/bites").replace("__REF__", f"v{VERSION}")
    for branch in ("main", "dev"):
        actual = sh(["git", "show", f"{branch}:{WF}"], cwd=bare, env=env).stdout
        assert actual == expected
        assert sh(["git", "ls-tree", f"bites/{branch}"], cwd=bare, env=env).stdout == ""
    second = run(artifact, *args, env=env)
    assert second.returncode == 0, second.stdout + second.stderr
    assert refs(bare, env) == before


def test_artifact_reprocessing_and_checksum_match(artifact, tmp_path):
    rebuilt = tmp_path / "rebuilt" / "bootstrap.sh"
    sh([sys.executable, str(ROOT / "scripts" / "build_bootstrap.py"), "-o", str(rebuilt), "--check-tag", f"v{VERSION}"])
    assert rebuilt.read_bytes() == artifact.read_bytes()
    expected = hashlib.sha256(rebuilt.read_bytes()).hexdigest()
    assert rebuilt.with_name("bootstrap.sh.sha256").read_text(encoding="utf-8") == f"{expected}  bootstrap.sh\n"
