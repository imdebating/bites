"""Plain-text checks on action.yml: the settings inputs exist and reach the build and verify
steps, and no input is ever pasted into a shell command (no YAML library needed)."""
import re
from pathlib import Path

ACTION = (Path(__file__).resolve().parent.parent / "action.yml").read_text(encoding="utf-8")

SETTINGS = (("BITES_MAX_CHARS", "max-chars"), ("BITES_READ_CAP", "read-cap"),
            ("BITES_INCLUDE", "include"), ("BITES_EXCLUDE", "exclude"))


def test_settings_inputs_are_declared():
    for _, name in SETTINGS:
        assert f"\n  {name}:\n" in ACTION


def test_advanced_settings_are_not_inputs():
    for name in ("wrapper-chars", "manifest-max-chars"):
        assert f"\n  {name}:" not in ACTION


def test_build_and_verify_steps_both_receive_every_setting():
    for var, name in SETTINGS:
        assert ACTION.count(f"{var}: ${{{{ inputs.{name} }}}}") == 2


def test_inputs_only_appear_as_environment_values():
    lines = [ln for ln in ACTION.splitlines() if "${{ inputs." in ln and not ln.lstrip().startswith("#")]
    assert lines
    for ln in lines:
        assert re.match(r"^\s+[A-Z_]+: \$\{\{ inputs\.[a-z-]+ \}\}$", ln), ln
