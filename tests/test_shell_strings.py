"""The shell half of the message catalog: scripts/strings.sh and the scripts that use it.

scripts/strings.sh is generated from locales/strings.en.toml by scripts/gen_strings.py. These
tests keep three things in step: the generated file is current, the `bites_fmt` function that
fills in placeholders behaves exactly like the Python side (`str.format`), and every call in a
script names a catalog entry and passes exactly the placeholders the text has.
"""
import re
import shlex
import shutil
import string
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "locales" / "strings.en.toml"
STRINGS = ROOT / "scripts" / "strings.sh"
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

# Script -> catalog table, for the scripts that already take their messages from the catalog.
WIRED = {"bootstrap.sh": "bootstrap", "cleanup.sh": "cleanup", "prune.sh": "prune"}

# Catalog entries that are not printed by a script: documentation that lives with the messages.
# cleanup.sh has no --help; the text describes the settings it reads.
NOT_PRINTED = {("cleanup", "help")}

CALL = re.compile(r"(?:\$\(text|(?<![\w$(])say)\s+(?P<key>[a-z][a-z0-9_]*)\b")


def catalog():
    return tomllib.loads(CATALOG.read_text(encoding="utf-8"))


def fields(text):
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def bash(code):
    return subprocess.run(["bash", "-c", f'. "{STRINGS}"; {code}'], capture_output=True, text=True)


def calls(script):
    """Yield (line number, key, argument names) for each `text KEY ...` / `say KEY ...` call."""
    for number, line in enumerate(script.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        for m in CALL.finditer(line):
            lexer = shlex.shlex(line[m.end():], posix=True, punctuation_chars=True)
            lexer.whitespace_split = True
            names = set()
            while True:
                try:
                    token = lexer.get_token()
                except ValueError:
                    break
                if token is None or set(token) <= set(lexer.punctuation_chars):
                    break
                if "=" in token:
                    names.add(token.split("=", 1)[0])
            yield number, m.group("key"), names


def test_generated_file_is_current():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_strings.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_generated_file_has_valid_bash_syntax():
    assert subprocess.run(["bash", "-n", str(STRINGS)], capture_output=True).returncode == 0


@pytest.mark.parametrize(
    "key, args",
    [
        ("bootstrap.config_value_invalid", ["key=max_chars", "value=a&b"]),   # {{ in the text, & in a value
        ("cleanup.deleted", ["output_branch=bites/a\\nb"]),                   # a backslash in a value
        ("cleanup.deleted", ["output_branch={x}{{y}}"]),                      # braces in a value
        ("cleanup.prefix_error", ["message=two\nlines"]),                     # a newline in a value
        ("cleanup.branch_exists_again", ["branch=a\nb", "output_branch=c\n\nd"]),  # line breaks in two values
        ("cleanup.prefix_note", ["message="]),                                # an empty value
        ("prune.found_summary", ["count=3"]),
        ("prune.help", []),                                                   # a long text with no placeholders
    ],
)
def test_bites_fmt_matches_python_format(key, args):
    table, name = key.split(".")
    values = dict(a.split("=", 1) for a in args)
    expected = catalog()[table][name].format(**values)
    r = bash("bites_fmt " + " ".join(shlex.quote(x) for x in [key, *args]))
    assert r.returncode == 0, r.stderr
    assert r.stdout == expected


def test_bites_fmt_refuses_an_unknown_entry_or_a_missing_value():
    assert bash("bites_fmt cleanup.no_such_entry").returncode == 1
    r = bash("bites_fmt cleanup.deleted")
    assert r.returncode == 2 and "no value for {output_branch}" in r.stderr


def test_prefixes_are_the_same_in_every_table():
    data = catalog()
    for name in ("prefix_error", "prefix_note"):
        values = {table: entries[name] for table, entries in data.items() if name in entries}
        assert len(set(values.values())) == 1, f"{name} differs between tables: {values}"


@pytest.mark.parametrize("script, table", sorted(WIRED.items()))
def test_every_call_names_an_entry_and_passes_exactly_its_placeholders(script, table):
    entries = catalog()[table]
    seen = set()
    for number, key, given in calls(ROOT / "scripts" / script):
        assert key in entries, f"{script}:{number}: no catalog entry [{table}] {key}"
        assert given == fields(entries[key]), (
            f"{script}:{number}: [{table}] {key} takes {sorted(fields(entries[key]))}, the call passes {sorted(given)}"
        )
        seen.add(key)
    unused = {k for k in entries if k not in seen and (table, k) not in NOT_PRINTED}
    assert not unused, f"{script}: catalog entries the script never uses: {sorted(unused)}"


@pytest.mark.parametrize("script", sorted(WIRED))
def test_wired_scripts_print_nothing_that_is_not_in_the_catalog(script):
    source = (ROOT / "scripts" / script).read_text(encoding="utf-8")
    assert not re.search(r"^[ \t]*echo[ \t]+\S", source, re.MULTILINE), f"{script}: use say/note/die, not echo"
