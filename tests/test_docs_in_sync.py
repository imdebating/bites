"""Tests that keep the documentation and the files it describes in step."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bites_tool import core  # noqa: E402

README = (ROOT / "README.md").read_text(encoding="utf-8")
CONFIG_DOC = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "templates" / "bites.yml").read_text(encoding="utf-8")
LINK = re.compile(r"\]\(([^)\s]+)\)")


def significant(text):
    """Return the non-blank, non-comment lines of `text`, without trailing spaces."""
    return [ln.rstrip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def without_comments_and_code(text):
    """Drop HTML comments and fenced code blocks, which may hold unpublished or sample links."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def test_readme_workflow_matches_the_template():
    """The first YAML block in the README is the template with its placeholders filled in."""
    block = re.search(r"```yaml\n(.*?)```", README, re.DOTALL)
    assert block, "no yaml block in the README"
    rendered = TEMPLATE.replace("__ACTION__", "imdebating/bites").replace("__REF__", "v1")
    expected = [ln for ln in significant(rendered) if ln != "__SETTINGS__"]
    assert significant(block.group(1)) == expected


def test_configuration_guide_lists_every_default_extension():
    """Each extension in the built-in include list is named in docs/configuration.md."""
    for glob in core.DEFAULT_INCLUDE:
        ext = "." + glob.rsplit(".", 1)[1]
        assert f"`{ext}`" in CONFIG_DOC, f"{ext} is in the default include list but not in docs/configuration.md"


def test_readme_links_every_guide():
    """Every file in docs/ is reachable from the README."""
    guides = sorted((ROOT / "docs").glob("*.md"))
    assert guides, "docs/ has no guides"
    for guide in guides:
        assert f"docs/{guide.name}" in README, f"README does not link docs/{guide.name}"


def test_relative_links_point_to_existing_files():
    """No link in the README or the guides points to a file that does not exist."""
    docs = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
    for doc in docs:
        text = without_comments_and_code(doc.read_text(encoding="utf-8"))
        for target in LINK.findall(text):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path = target.split("#", 1)[0]
            assert (doc.parent / path).exists(), f"{doc.relative_to(ROOT)} links to a missing file: {target}"


def test_cleanup_action_looks_for_its_script_one_level_up():
    """github.action_path is the cleanup/ directory, so the script is in ../scripts."""
    text = (ROOT / "cleanup" / "action.yml").read_text(encoding="utf-8")
    assert '"$ACTION_PATH/../scripts/cleanup.sh"' in text
    assert '"$ACTION_PATH/scripts"' not in text
    assert (ROOT / "scripts" / "cleanup.sh").is_file()
