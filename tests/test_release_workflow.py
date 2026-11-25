"""Plain-text checks on .github/workflows/release.yml (no YAML library)."""
import re
from pathlib import Path

WORKFLOW = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")


def test_it_runs_when_version_changes_on_main_or_by_hand_and_only_on_main():
    assert "\n  push:\n    branches: [main]\n    paths: [VERSION]\n" in WORKFLOW
    assert "\n  workflow_dispatch:\n" in WORKFLOW
    assert "\n    if: github.ref == 'refs/heads/main'\n" in WORKFLOW


def test_every_action_is_pinned_to_a_commit():
    uses = re.findall(r"^\s+(?:- )?uses: (\S+)", WORKFLOW, re.MULTILINE)
    assert len(uses) == 3
    for ref in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), ref


def test_expressions_never_appear_in_a_shell_command():
    """Values travel in environment variables, so none is ever pasted into a command."""
    allowed = re.compile(r"^\s+[A-Z_]+: \$\{\{ [^}]+ \}\}$")
    for line in WORKFLOW.splitlines():
        if "${{" in line and not line.lstrip().startswith("#"):
            assert allowed.match(line), line


def test_the_steps_run_in_this_order_and_the_artifact_is_saved_last():
    order = ["python -m pytest tests -q", "python scripts/build_bootstrap.py -o dist/bootstrap.sh",
             'BITES_BOOTSTRAP_SCRIPT="$RUNNER_TEMP/download/bootstrap.sh" python -m pytest tests/test_bootstrap*.py tests/test_preflight.py -q',
             "sha256sum -c bootstrap.sh.sha256", "uses: actions/upload-artifact@"]
    positions = [WORKFLOW.index(step) for step in order]
    assert positions == sorted(positions)


def test_the_built_file_is_tested_alone_in_an_empty_directory():
    assert 'mkdir "$RUNNER_TEMP/download"' in WORKFLOW
    assert 'cp dist/bootstrap.sh "$RUNNER_TEMP/download/"' in WORKFLOW


def test_the_workflow_cannot_publish_releases_or_move_tags():
    assert "\npermissions:\n  contents: read\n" in WORKFLOW
    assert WORKFLOW.count("permissions:") == 1
    commands = "\n".join(line for line in WORKFLOW.splitlines() if not line.lstrip().startswith("#"))
    for forbidden in ("publish_release.py", "GH_TOKEN", "contents: write", "gh release", "git tag", "git push"):
        assert forbidden not in commands


def test_both_release_files_are_saved_and_missing_files_fail():
    assert "name: bootstrap-release-candidate" in WORKFLOW
    assert "path: |\n            dist/bootstrap.sh\n            dist/bootstrap.sh.sha256\n" in WORKFLOW
    assert "if-no-files-found: error" in WORKFLOW
