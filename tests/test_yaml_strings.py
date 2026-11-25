"""The YAML files and the message catalog agree.

The files in action.yml, cleanup/action.yml and templates/bites.yml cannot call the catalog, so
every catalog entry that lives in one of them is checked here instead: the entries of the
[action], [cleanup_action] and [template] tables. Plain text matching is enough (no YAML library),
because each value sits on a line of a fixed shape.

If this fails after you edit the catalog, change the YAML file to match (or the other way round).
"""
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = tomllib.loads((ROOT / "locales" / "strings.en.toml").read_text(encoding="utf-8"))
ACTION = (ROOT / "action.yml").read_text(encoding="utf-8")
CLEANUP = (ROOT / "cleanup" / "action.yml").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "templates" / "bites.yml").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")

CHECKED = set()  # (table, key) pairs some test below has compared with its YAML file


def seen(table, key):
    CHECKED.add((table, key))
    return CATALOG[table][key]


def top_level(text, key):
    """The value of a top-level `key: value` line (a plain scalar)."""
    return re.search(rf"^{key}: (.+)$", text, re.MULTILINE).group(1)


def input_description(text, name):
    """The description of the input `name`, which is a double-quoted scalar or a plain one."""
    m = re.search(rf'^  {name}:\n    description: (.+)$', text, re.MULTILINE)
    value = m.group(1)
    return value[1:-1] if value.startswith('"') else value


def step_names(text):
    return re.findall(r"^    - name: (.+)$", text, re.MULTILINE)


def test_action_description_and_inputs():
    assert top_level(ACTION, "description") == seen("action", "description")
    for name, key in [("full", "bite_rebuild"), ("max-chars", "bite_max_chars"), ("read-cap", "bite_read_cap"),
                      ("include", "bite_include"), ("exclude", "bite_exclude")]:
        assert input_description(ACTION, name) == seen("action", key), name


def test_action_step_names_in_order():
    keys = ["step_checkout_source", "step_gate", "step_checkout_bites", "step_python", "step_apply",
            "step_commit_patches", "step_build", "step_verify", "step_record_failure", "step_publish"]
    assert step_names(ACTION) == [seen("action", k) for k in keys]


def test_action_messages_in_the_shell_blocks():
    nothing = seen("action", "no_output_branch").replace("{branch}", "$BRANCH_NAME")
    assert f'echo "{nothing}"' in ACTION
    assert f'git commit -m "{seen("action", "commit_patches")}"' in ACTION
    assert f'git commit -m "{seen("action", "commit_build").replace("{commit}", "${GITHUB_SHA::7}")}"' in ACTION


def test_cleanup_action():
    assert top_level(CLEANUP, "name") == seen("cleanup_action", "name")
    assert top_level(CLEANUP, "description") == seen("cleanup_action", "description")
    assert input_description(CLEANUP, "dry-run") == seen("cleanup_action", "input_dry_run")
    assert step_names(CLEANUP) == [seen("cleanup_action", "step_checkout"), seen("cleanup_action", "step_delete")]
    missing = seen("cleanup_action", "script_not_found").replace("{script}", "$script").replace("{action_path}", "$ACTION_PATH")
    assert f'echo "{missing}" >&2' in CLEANUP


def comment_lines(text):
    """Every comment line of a YAML file with its `# ` removed (`#` alone becomes an empty line)."""
    return [ln[2:] if ln.startswith("# ") else "" for ln in text.splitlines() if ln.startswith("#")]


def test_template_comment_block_is_the_catalog_help_text():
    """The catalog's help text appears, line by line and in order, in the template's comments.

    The last two lines of it sit above `permissions:` rather than at the top, so the lines are
    matched in order but not necessarily next to each other.
    """
    wanted = seen("template", "help").rstrip("\n").split("\n")
    have = iter(comment_lines(TEMPLATE))
    for line in wanted:
        assert any(line == got for got in have), f"template comments lack, in order: {line!r}"


def test_template_input_description_and_the_readme_copy():
    description = seen("template", "input_full")
    assert f"        description: {description}\n" in TEMPLATE
    assert f"        description: {description}\n" in README


def test_every_yaml_entry_in_the_catalog_is_checked():
    # Run the other checks first, so this test also works when it is run on its own.
    for check in (test_action_description_and_inputs, test_action_step_names_in_order, test_action_messages_in_the_shell_blocks,
                  test_cleanup_action, test_template_comment_block_is_the_catalog_help_text,
                  test_template_input_description_and_the_readme_copy):
        check()
    every = {(table, key) for table in ("action", "cleanup_action", "template") for key in CATALOG[table]}
    assert every == CHECKED, f"entries nobody checks: {sorted(every - CHECKED)}"
