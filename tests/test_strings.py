"""The message catalog (locales/strings.en.toml) and the Python code that uses it agree.

Every user-facing sentence in bites_tool comes from the catalog through `message()`. These tests
keep the two in step: each key a call names exists, each call passes exactly the placeholders the
catalog text has, no catalog key for the Python tables is left unused, and the header comment
above every entry lists the placeholders its text really contains.
"""
import ast
import re
import string
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "locales" / "strings.en.toml"
PACKAGE = ROOT / "bites_tool"

# The catalog tables whose entries are used by the Python package. The other tables belong to
# the shell scripts and the YAML files.
PYTHON_TABLES = {"build", "cli", "core", "patches"}

# Entries that are in the catalog before the code that uses them exists. Remove an entry from
# this set when its code lands; the test then insists that it is used.
NOT_USED_YET = set()

ENTRY = re.compile(r"^# (?P<header>[^\n]*)\n(?P<key>[a-z][a-z0-9_]*) = ", re.MULTILINE)
PLACEHOLDERS = re.compile(r"placeholders:\s*(?P<names>[a-z0-9_, ]+?)\s*$")


def catalog():
    return tomllib.loads(CATALOG.read_text(encoding="utf-8"))


def fields(text):
    """The placeholder names in `text`; {{ and }} are literal braces and are not counted."""
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def documented_placeholders():
    """Map (table, key) -> the placeholder names its header comment lists."""
    text = CATALOG.read_text(encoding="utf-8")
    table, found = None, {}
    # Walk the file in order so each entry is filed under the table it sits in.
    for m in re.finditer(r"^\[([a-z_]+)\]$|" + ENTRY.pattern, text, re.MULTILINE):
        if m.group(1):
            table = m.group(1)
            continue
        names = PLACEHOLDERS.search(m.group("header"))
        found[(table, m.group("key"))] = (
            {n.strip() for n in names.group("names").split(",") if n.strip()} if names else set()
        )
    return found


def message_calls():
    """Yield (file name, table, key, keyword names) for every message(...) call in the package."""
    for path in sorted(PACKAGE.glob("*.py")):
        if path.name == "strings.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "message":
                args = [a.value for a in node.args if isinstance(a, ast.Constant)]
                assert len(args) == 2 == len(node.args), f"{path.name}:{node.lineno}: message() needs a literal table and key"
                yield path.name, args[0], args[1], {k.arg for k in node.keywords}


def test_catalog_is_valid_toml_with_a_format_version():
    assert catalog()["meta"] == {"language": "en", "format_version": 1}


def test_every_call_names_an_entry_and_passes_exactly_its_placeholders():
    data = catalog()
    for name, table, key, given in message_calls():
        assert key in data.get(table, {}), f"{name}: no catalog entry [{table}] {key}"
        wanted = fields(data[table][key])
        assert given == wanted, f"{name}: [{table}] {key} takes {sorted(wanted)}, the call passes {sorted(given)}"


def test_every_python_entry_is_used():
    data = catalog()
    used = {(table, key) for _, table, key, _ in message_calls()}
    defined = {(t, k) for t in PYTHON_TABLES for k in data[t]}
    assert defined - used - NOT_USED_YET == set(), "catalog entries no code uses"
    assert used - defined == set(), "calls to entries that are not in a Python table"
    assert NOT_USED_YET & used == set(), "entry is used now: remove it from NOT_USED_YET"


def test_header_comments_list_the_placeholders_each_text_contains():
    data, documented = catalog(), documented_placeholders()
    for table, entries in data.items():
        for key, value in entries.items():
            if table == "meta" or not isinstance(value, str):
                continue
            assert (table, key) in documented, f"[{table}] {key} has no header comment"
            assert documented[(table, key)] == fields(value), (
                f"[{table}] {key}: header lists {sorted(documented[(table, key)])}, "
                f"text contains {sorted(fields(value))}"
            )


def test_no_raw_message_strings_in_the_package():
    """Errors are raised and lines are printed only with catalog text, never with a literal."""
    for path in sorted(PACKAGE.glob("*.py")):
        if path.name == "strings.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = getattr(node.func, "id", None)
            if func in ("BitesError", "print"):
                first = node.args[0]
                ok = isinstance(first, ast.Call) and getattr(first.func, "id", None) == "message"
                assert ok, f"{path.name}:{node.lineno}: {func}() must use message()"
