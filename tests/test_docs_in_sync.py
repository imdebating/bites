"""Tests that keep the documentation and the files it describes in step."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bites_tool import core  # noqa: E402

README = (ROOT / "README.md").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "templates" / "bites.yml").read_text(encoding="utf-8")


def significant(text):
    """Return the non-blank, non-comment lines of `text`, without trailing spaces."""
    return [ln.rstrip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def test_readme_workflow_matches_the_template():
    """The first YAML block in the README is the template with its placeholders filled in."""
    block = re.search(r"```yaml\n(.*?)```", README, re.DOTALL)
    assert block, "no yaml block in the README"
    rendered = TEMPLATE.replace("__ACTION__", "imdebating/bites").replace("__REF__", "v1")
    expected = [ln for ln in significant(rendered) if ln != "__SETTINGS__"]
    assert significant(block.group(1)) == expected


def test_readme_lists_every_default_extension():
    """Each extension in the built-in include list is named in the README."""
    for glob in core.DEFAULT_INCLUDE:
        ext = "." + glob.rsplit(".", 1)[1]
        assert f"`{ext}`" in README, f"{ext} is in the default include list but not in the README"


def test_cleanup_action_looks_for_its_script_one_level_up():
    """github.action_path is the cleanup/ directory, so the script is in ../scripts."""
    text = (ROOT / "cleanup" / "action.yml").read_text(encoding="utf-8")
    assert '"$ACTION_PATH/../scripts/cleanup.sh"' in text
    assert '"$ACTION_PATH/scripts"' not in text
    assert (ROOT / "scripts" / "cleanup.sh").is_file()
