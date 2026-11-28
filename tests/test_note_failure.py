"""A failure outside the bites tool (the patch commit and push) is recorded with its stage and reason."""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from gitutil import make_remote, sh

ROOT = Path(__file__).resolve().parent.parent
ACTION = (ROOT / "action.yml").read_text(encoding="utf-8")
GH006 = (
    "remote: error: GH006: Protected branch update failed for refs/heads/main.\n"
    "remote: error: Changes must be made through a pull request.\n"
    " ! [remote rejected] HEAD -> main (protected branch hook declined)\n"
)
GH013 = (
    "remote: error: GH013: Repository rule violations found for refs/heads/main.\n"
    "remote: - Changes must be made through a pull request.\n"
)


def python_on_path(tmp_path):
    """A directory with a `python` command, because the action calls `python` and some systems only have python3."""
    folder = tmp_path / "bin"
    folder.mkdir()
    shim = folder / "python"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    shim.chmod(0o755)
    return f"{folder}{os.pathsep}{os.environ['PATH']}"


def note(tmp_path, printed, github_actions="false", stage="commit", branch="main"):
    status = tmp_path / "status.json"
    args = [sys.executable, "-m", "bites_tool", "note-failure", "--status", str(status), "--stage", stage,
            "--source-branch", branch]
    if printed is not None:
        detail = tmp_path / "detail.txt"
        detail.write_text(printed, encoding="utf-8")
        args += ["--detail-file", str(detail)]
    done = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                          env={**os.environ, "PYTHONPATH": str(ROOT), "GITHUB_ACTIONS": github_actions})
    return done, status


@pytest.mark.parametrize("printed", [GH006, GH013])
def test_a_branch_that_requires_pull_requests_is_named_as_the_reason(tmp_path, printed):
    done, status = note(tmp_path, printed)
    assert done.returncode == 0, done.stderr
    record = json.loads(status.read_text(encoding="utf-8"))
    assert record["schema"] == 1 and record["status"] == "error" and record["stage"] == "commit"
    assert "pushed to main, because it requires pull requests" in record["message"]
    assert "merge that branch into main" in record["message"]
    assert printed.splitlines()[0].strip() in record["message"]


def test_any_other_failure_keeps_what_git_said(tmp_path):
    done, status = note(tmp_path, "fatal: unable to access 'https://example.invalid/': Could not resolve host\n")
    record = json.loads(status.read_text(encoding="utf-8"))
    assert record["stage"] == "commit"
    assert "could not be committed to main" in record["message"]
    assert "Could not resolve host" in record["message"] and "requires pull requests" not in record["message"]
    assert ".bites-patches/" in record["message"]


def test_without_a_detail_file_the_message_points_to_the_run_log(tmp_path):
    for printed in (None, ""):
        done, status = note(tmp_path, printed)
        assert json.loads(status.read_text(encoding="utf-8"))["message"].count("See the workflow run log") == 1


def test_the_detail_is_the_first_three_lines(tmp_path):
    done, status = note(tmp_path, "".join(f"line {n}\n" for n in range(1, 11)))
    message = json.loads(status.read_text(encoding="utf-8"))["message"]
    assert "line 1 line 2 line 3)" in message and "line 4" not in message


def test_the_detail_is_cut_to_a_readable_length(tmp_path):
    done, status = note(tmp_path, "x" * 5000 + "\n")
    message = json.loads(status.read_text(encoding="utf-8"))["message"]
    assert "x" * 500 in message and "x" * 501 not in message


@pytest.mark.parametrize("enabled", ["true", "false", "TRUE", ""])
def test_the_failure_is_printed_and_annotated_only_when_the_runner_asks(tmp_path, enabled):
    done, status = note(tmp_path, GH006, github_actions=enabled)
    assert done.stderr.startswith("bites commit: Error: The applied patches could not be pushed to main")
    annotations = [line for line in done.stdout.splitlines() if line.startswith("::error ")]
    assert len(annotations) == (1 if enabled == "true" else 0)
    if annotations:
        assert annotations[0].startswith("::error title=bites commit::")


def test_only_known_stages_are_accepted(tmp_path):
    done, status = note(tmp_path, GH006, stage="build")
    assert done.returncode == 2 and "invalid choice" in done.stderr and not status.exists()


def test_report_failure_publishes_the_stage_and_reason(tmp_path):
    done, status = note(tmp_path, GH006)
    out = tmp_path / "out"
    out.mkdir()
    published = subprocess.run(
        [sys.executable, "-m", "bites_tool", "report-failure", "--status", str(status), "--out", str(out),
         "--source-branch", "main", "--source-commit", "abc123"],
        cwd=ROOT, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert published.returncode == 0, published.stderr
    record = json.loads((out / "last_build.json").read_text(encoding="utf-8"))
    assert (record["status"], record["stage"], record["source_branch"], record["source_commit"]) == ("error", "commit", "main", "abc123")
    assert "requires pull requests" in record["message"]


def commit_step():
    """The shell block of the 'Commit applied patches to the source branch' step, as the runner runs it."""
    block = ACTION.split("    - name: Commit applied patches to the source branch\n", 1)[1].split("      run: |\n", 1)[1]
    lines = []
    for line in block.splitlines():
        if line.strip() and not line.startswith("        "):
            break
        lines.append(line[8:] if line.startswith("        ") else "")
    return "\n".join(lines) + "\n"


def run_step(tmp_path, hook=None):
    """Run the real step in a clone whose remote may refuse pushes; return (result, status file, remote, env)."""
    bare, env = make_remote(tmp_path)
    if hook is not None:
        path = bare / "hooks" / "pre-receive"
        path.write_text("#!/bin/sh\n" + hook, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    clone = tmp_path / "clone"
    sh(["git", "clone", "--quiet", str(bare), str(clone)], env=env)
    (clone / "docs").mkdir()
    (clone / "docs" / "edited.md").write_text("patched\n", encoding="utf-8")
    runner = tmp_path / "runner"
    runner.mkdir()
    # The step sets its own git identity, so the fixed identity that make_remote exports must not override it.
    kept = {k: v for k, v in {**os.environ, **env}.items() if not k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))}
    step_env = {**kept, "PATH": python_on_path(tmp_path), "PYTHONPATH": str(ROOT),
                "RUNNER_TEMP": str(runner), "BRANCH": "main", "GITHUB_ACTIONS": "false"}
    done = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", commit_step()],
                          cwd=clone, env=step_env, capture_output=True, text=True)
    return done, runner / "status.json", bare, env


def test_the_step_commits_and_pushes_when_the_branch_accepts_it(tmp_path):
    done, status, bare, env = run_step(tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    assert not status.exists()
    shown = sh(["git", "log", "-1", "--format=%an: %s", "main"], cwd=bare, env=env).stdout.strip()
    assert shown == "github-actions[bot]: bites: apply patches"


def test_the_step_records_a_branch_that_requires_pull_requests(tmp_path):
    hook = ("echo 'remote: error: GH006: Protected branch update failed for refs/heads/main.' >&2\n"
            "echo 'remote: error: Changes must be made through a pull request.' >&2\nexit 1\n")
    done, status, bare, env = run_step(tmp_path, hook)
    assert done.returncode == 1
    assert "GH006" in done.stderr and "bites commit: Error:" in done.stderr
    record = json.loads(status.read_text(encoding="utf-8"))
    assert record["stage"] == "commit" and "requires pull requests" in record["message"]
    assert sh(["git", "log", "-1", "--format=%s", "main"], cwd=bare, env=env).stdout.strip() == "init"


def test_the_step_records_any_other_refusal_with_its_reason(tmp_path):
    done, status, bare, env = run_step(tmp_path, "echo 'remote: error: quota exceeded' >&2\nexit 1\n")
    assert done.returncode == 1
    record = json.loads(status.read_text(encoding="utf-8"))
    assert record["stage"] == "commit" and "quota exceeded" in record["message"]
    assert "requires pull requests" not in record["message"]
