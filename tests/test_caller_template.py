"""Checks on templates/bites.yml that guard the cleanup wiring (plain text checks, no YAML library)."""
from pathlib import Path

TEMPLATE = (Path(__file__).resolve().parent.parent / "templates" / "bites.yml").read_text(encoding="utf-8")


def test_placeholders_present_for_both_actions():
    """Both jobs name the action through the placeholders the bootstrap script fills in."""
    assert "uses: __ACTION__@__REF__" in TEMPLATE
    assert "uses: __ACTION__/cleanup@__REF__" in TEMPLATE


def test_delete_trigger_and_guards():
    """The delete event is a trigger, and the cleanup job only runs for branches outside bites/*."""
    assert "\n  delete:\n" in TEMPLATE
    assert "github.event.ref_type == 'branch'" in TEMPLATE
    assert "!startsWith(github.event.ref, 'bites/')" in TEMPLATE


def test_build_job_skips_delete_events():
    """The build job must not run on delete events."""
    assert "if: github.event_name != 'delete'" in TEMPLATE


def test_cleanup_has_its_own_concurrency_group():
    """A delete event's ref is the default branch, so cleanup must not share the build group."""
    assert "group: bites-cleanup-${{ github.event.ref }}" in TEMPLATE
    assert "group: bites-${{ github.ref }}" in TEMPLATE
