"""The release workflow, the rehearsal and the guides describe the same release process."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
REHEARSAL = (ROOT / "tests" / "release_rehearsal.sh").read_text(encoding="utf-8")
HOW = (ROOT / "docs" / "how-it-works.md").read_text(encoding="utf-8")
TESTING = (ROOT / "tests" / "RELEASE_TESTING.md").read_text(encoding="utf-8")


def saved_name():
    names = re.findall(r"^\s+name: (\S+)$", WORKFLOW, re.MULTILINE)
    assert len(names) == 1, names
    return names[0]


def test_the_rehearsal_looks_for_the_artifact_the_workflow_saves():
    assert re.search(r"^ARTIFACT=(\S+)", REHEARSAL, re.MULTILINE).group(1) == saved_name()


def test_the_guides_name_the_artifact_the_workflow_saves():
    assert f"`{saved_name()}`" in HOW and f"`{saved_name()}`" in TESTING


def test_the_rehearsal_does_the_manual_steps_in_order():
    steps = ["gh run download", "gh release create", "--draft", "draft=false", 'git/refs" -f ref="refs/tags/$MAJOR"']
    positions = [REHEARSAL.index(step) for step in steps]
    assert positions == sorted(positions)


def test_the_rehearsal_checks_that_the_workflow_publishes_nothing():
    for check in ("it created no release", "it created no tag $TAG", "it created no major tag $MAJOR"):
        assert f'assert "{check}"' in REHEARSAL


def test_nothing_in_the_release_process_needs_notes_in_the_repository():
    for text in (WORKFLOW, REHEARSAL, HOW, TESTING):
        assert ".github/release-notes" not in text


def test_the_guides_say_the_workflow_creates_no_release_and_the_maintainer_does():
    assert "creates no release and no tag" in HOW and "creates no release and no tag" in TESTING
    for text in (HOW, TESTING):
        assert "Attach the files before you publish" in text or "only after both files are attached" in text
        assert "`main` publishes the release" not in text
