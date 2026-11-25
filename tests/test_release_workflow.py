"""Plain-text checks on .github/workflows/release-assets.yml (no YAML library)."""
import re
from pathlib import Path

WORKFLOW = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "release-assets.yml").read_text(encoding="utf-8")


def test_it_runs_when_a_release_is_published_or_by_hand():
    assert "\n  release:\n    types: [published]\n" in WORKFLOW
    assert "\n  workflow_dispatch:\n" in WORKFLOW


def test_every_action_is_pinned_to_a_commit():
    uses = re.findall(r"^\s+uses: (\S+)", WORKFLOW, re.MULTILINE)
    assert uses
    for ref in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), ref


def test_expressions_never_appear_in_a_shell_command():
    """The tag name travels in an environment variable, so it can never be pasted into a command."""
    allowed = re.compile(r"^\s+(?:ref|group|[A-Z_]+): .*\$\{\{ [^}]+ \}\}.*$")
    for line in WORKFLOW.splitlines():
        if "${{" in line and not line.lstrip().startswith("#"):
            assert allowed.match(line), line


def test_it_tests_checks_the_tag_builds_and_attaches_both_files():
    assert "python -m pytest tests -q" in WORKFLOW
    assert 'python scripts/build_bootstrap.py -o dist/bootstrap.sh --check-tag "$TAG"' in WORKFLOW
    assert 'gh release upload "$TAG" dist/bootstrap.sh dist/bootstrap.sh.sha256' in WORKFLOW
    assert "\npermissions:\n  contents: write\n" in WORKFLOW
