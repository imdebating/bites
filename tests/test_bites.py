"""Tests for the bites_tool package.  Run from the repository root with:

    python -m pytest tests -q

Every test builds a throw-away git repository under pytest's tmp_path, runs the real
command-line entry point (`cli.main`) in-process, and checks the files it produces.
Small max_chars values (100, 200) keep most tests fast and make boundaries easy to hit;
`test_roundtrip_real_limit` uses the real 27,000-character setting.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bites_tool import cli, core  # noqa: E402

# Template for a throw-away bites.toml.  {m} = max_chars, {mm} = manifest_max_chars.
# The include list is wider than the real one so the .env tests can prove the hard-coded
# deny list overrides the globs.
TOML = """
max_chars = {m}
manifest_max_chars = {mm}
read_cap = 28000
wrapper_chars = 82
include = ["**/*.md", "**/*.txt", "**/*.json", "**/*.csv", "**/*.env", "**/.env*"]
exclude = [".bites-patches/**", ".git/**"]
"""


# ------------------------------------------------------------------ helpers
def make_repo(tmp_path, files, m=100, mm=100000):
    """Create a git repo with `files` staged, plus a bites.toml (max_chars=m).

    Returns (src repo path, config path, output dir path); the output dir is not created.
    """
    src = tmp_path / "src"
    src.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=src, check=True)
    for k, v in files.items():
        write(src, k, v)
    git_add(src)
    cfg = tmp_path / "bites.toml"
    cfg.write_text(TOML.format(m=m, mm=mm))
    return src, cfg, tmp_path / "out"


def write(src, rel, content):
    """Write str or bytes to src/rel, creating directories (bytes keep CRLF intact)."""
    p = src / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def git_add(src):
    """Stage everything so `git ls-files` (used by bites) sees new and changed files."""
    subprocess.run(["git", "add", "-A"], cwd=src, check=True)


def run(*args):
    """Call the CLI in-process with stringified arguments; return its exit code."""
    return cli.main([str(a) for a in args])


def build(src, cfg, out, *extra, commit="c1"):
    """Run `build` for branch "main" at the given fake commit id."""
    return run("build", "--config", cfg, "--src", src, "--out", out,
               "--source-branch", "main", "--source-commit", commit, *extra)


def verify(src, cfg, out):
    """Run `verify` and return its exit code (0 = consistent)."""
    return run("verify", "--config", cfg, "--src", src, "--out", out)


def tree(out):
    """Return {path relative to out: file bytes} for every file under out/parts."""
    return {p.relative_to(out).as_posix(): p.read_bytes()
            for p in sorted((out / "parts").rglob("*")) if p.is_file()}


def manifest(out):
    """Load the manifest written under `out`."""
    return json.loads((out / "manifest.json").read_text(encoding="utf-8"))


def mixed(n):
    """Return exactly n characters mixing accents, dashes, emoji, a combining mark, CRLF and LF."""
    unit = "caf\u00e9 \u2014 \U0001F600 e\u0301 line\r\nnext\n"
    return (unit * (n // len(unit) + 1))[:n]


def built(tmp_path):
    """Build a 450-character mixed-text file, confirm it verifies, return (src, cfg, out)."""
    src, cfg, out = make_repo(tmp_path, {"big.md": mixed(450)})
    build(src, cfg, out)
    assert verify(src, cfg, out) == 0
    return src, cfg, out


# ------------------------------------------------------------------ globs
def test_glob_matches_root_and_nested():
    """`**/*.md` matches root-level and nested files, and rejects other extensions."""
    r = core.glob_to_re("**/*.md")
    assert r.match("README.md") and r.match("a/b/c.md")
    assert not r.match("a/b/c.txt") and not r.match("a/b/c.mdx")
    assert core.glob_to_re(".git/**").match(".git/config")


def test_denied_names_never_chunked_even_if_included(tmp_path):
    """Secret-like names (.env*) are never chunked even when an include glob matches them."""
    src, cfg, out = make_repo(tmp_path, {".env": "S" * 500, "a/.env.local": "S" * 500, "ok.md": "x" * 500})
    assert build(src, cfg, out) == 0
    assert list(manifest(out)["files"]) == ["ok.md"]


# ------------------------------------------------------------- round trip
def test_roundtrip_real_limit(tmp_path):
    """At the real 27,000 limit: thresholds, part counts, last-part chars=1, exact reassembly."""
    lengths = [26999, 27000, 27001, 54000, 54001]
    files = {f"f{n}.md": mixed(n) for n in lengths}
    src, cfg, out = make_repo(tmp_path, files, m=27000)
    assert build(src, cfg, out) == 0
    assert verify(src, cfg, out) == 0
    man = manifest(out)["files"]
    # At or below the limit: not chunked, no entry.
    assert "f26999.md" not in man and "f27000.md" not in man
    assert man["f27001.md"]["parts"] == 2
    assert man["f54000.md"]["parts"] == 2  # exact multiple: no empty third part
    assert man["f54001.md"]["parts"] == 3
    for n in (27001, 54001):
        last = out / core.part_rel(f"f{n}.md", man[f"f{n}.md"]["parts"], man[f"f{n}.md"]["parts"])
        meta, _ = core.parse_part(last.read_text(encoding="utf-8"))
        assert meta["chars"] == 1  # the one-character remainder
    for n in (27001, 54000, 54001):
        data = core.join_parts(out, f"f{n}.md", man[f"f{n}.md"]["parts"])
        assert data == (src / f"f{n}.md").read_bytes()


def test_start_lines(tmp_path):
    """Each part's recorded start line matches a direct count of newlines before its offset."""
    text = "".join(f"line {i:03d}\n" for i in range(1, 61))
    src, cfg, out = make_repo(tmp_path, {"a.md": text}, m=100)
    build(src, cfg, out)
    e = manifest(out)["files"]["a.md"]
    for i, start in enumerate(e["start_lines"]):
        assert start == 1 + text.count("\n", 0, i * 100)


def test_same_name_files_stay_separate(tmp_path):
    """Same-named files in different directories, and same stem with different extensions, do not collide."""
    files = {"a/notes.md": "A" * 250, "b/notes.md": "B" * 250, "a/notes.txt": "C" * 250}
    src, cfg, out = make_repo(tmp_path, files)
    build(src, cfg, out)
    assert verify(src, cfg, out) == 0
    t = tree(out)
    assert any(k.startswith("parts/a/notes.md/") for k in t)
    assert any(k.startswith("parts/b/notes.md/") for k in t)
    assert any(k.startswith("parts/a/notes.txt/") for k in t)


# --------------------------------------------------- strict part parsing
def part_text(body="hello world", i=1, n=2):
    """Render a small valid part file for the parsing tests."""
    return core.render_part("x.md", i, n, body, 1)


def test_parse_rejects_truncation_and_tampering():
    """parse_part accepts a good part and rejects cut footers, edited bodies, trailing text and bad headers."""
    good = part_text()
    meta, body = core.parse_part(good)
    assert body == "hello world" and meta["chars"] == 11
    with pytest.raises(core.BitesError):
        core.parse_part(good[:-5])  # footer cut off
    with pytest.raises(core.BitesError):
        core.parse_part(good.replace("hello", "jello"))  # body edited, sha256 stale
    with pytest.raises(core.BitesError):
        core.parse_part(good + "extra")  # text after the footer
    with pytest.raises(core.BitesError):
        core.parse_part(good.replace("chars=11", "chars=12"))  # wrong length claimed
    with pytest.raises(core.BitesError):
        core.parse_part(good[:good.index("\n")])  # header only


def test_header_quotes_awkward_paths(tmp_path):
    """Paths with spaces and non-ASCII letters survive the header's URL quoting and verify."""
    rel = "dir with space/\u00e9 file.md"
    src, cfg, out = make_repo(tmp_path, {rel: "z" * 250})
    build(src, cfg, out)
    assert verify(src, cfg, out) == 0


# ---------------------------------------------------- replacement behaviour
def test_rebuild_is_deterministic_and_incremental(tmp_path):
    """Rebuilding unchanged input is byte-identical; editing the tail rewrites only the last part."""
    src, cfg, out = make_repo(tmp_path, {"big.md": "a" * 250, "other.md": "b" * 250})
    build(src, cfg, out)
    first = tree(out)
    build(src, cfg, out)
    assert tree(out) == first
    write(src, "big.md", "a" * 249 + "Z")
    git_add(src)
    build(src, cfg, out, commit="c2")
    second = tree(out)
    k1, k2, k3 = (core.part_rel("big.md", i, 3) for i in (1, 2, 3))
    assert second[k1] == first[k1] and second[k2] == first[k2] and second[k3] != first[k3]
    other = [k for k in first if "other.md" in k]
    assert all(second[k] == first[k] for k in other)
    last = json.loads((out / "last_build.json").read_text(encoding="utf-8"))
    assert list(last["changed"]) == ["big.md"]


def test_growth_shrink_and_threshold_crossing(tmp_path):
    """Parts are replaced wholesale when a file grows, shrinks, drops below the threshold, and grows again."""
    src, cfg, out = make_repo(tmp_path, {"big.md": "a" * 250})
    build(src, cfg, out)
    assert manifest(out)["files"]["big.md"]["parts"] == 3
    write(src, "big.md", "a" * 450)  # grow: 3 -> 5 parts
    git_add(src)
    build(src, cfg, out)
    t = tree(out)
    assert len(t) == 5 and all(k.endswith("-of-0005.txt") for k in t)
    write(src, "big.md", "a" * 150)  # shrink: 5 -> 2, old 5-part names must disappear
    git_add(src)
    build(src, cfg, out)
    t = tree(out)
    assert len(t) == 2 and all(k.endswith("-of-0002.txt") for k in t)
    write(src, "big.md", "a" * 80)  # below threshold: no parts at all
    git_add(src)
    build(src, cfg, out)
    assert tree(out) == {} and "big.md" not in manifest(out)["files"]
    assert not (out / "parts" / "big.md").exists()
    assert verify(src, cfg, out) == 0
    write(src, "big.md", "a" * 250)  # and back above it
    git_add(src)
    build(src, cfg, out)
    assert len(tree(out)) == 3


def test_deleted_source_removes_parts(tmp_path):
    """Deleting a source file removes its parts and leaves the tree verifiable."""
    src, cfg, out = make_repo(tmp_path, {"big.md": "a" * 250, "keep.md": "k" * 250})
    build(src, cfg, out)
    (src / "big.md").unlink()
    git_add(src)
    build(src, cfg, out)
    assert all("big.md" not in k for k in tree(out))
    assert verify(src, cfg, out) == 0


def test_full_flag_and_max_chars_change_rebuild_everything(tmp_path):
    """Changing max_chars invalidates the previous output and re-splits at the new size."""
    src, cfg, out = make_repo(tmp_path, {"big.md": "a" * 250})
    build(src, cfg, out)
    cfg.write_text(TOML.format(m=200, mm=100000))
    build(src, cfg, out)
    assert manifest(out)["files"]["big.md"]["parts"] == 2
    assert verify(src, cfg, out) == 0


def test_non_utf8_is_skipped_not_fatal(tmp_path):
    """A non-UTF-8 file is listed under `skipped` and does not fail the build."""
    src, cfg, out = make_repo(tmp_path, {"bin.txt": b"\xff\xfe" * 300, "ok.md": "x" * 250})
    assert build(src, cfg, out) == 0
    assert manifest(out)["skipped"] == {"bin.txt": "not_utf8"}


def test_manifest_overflow_is_an_error(tmp_path):
    """A manifest over manifest_max_chars fails the build and records an error status."""
    files = {f"dir/file_{i:03d}.md": "x" * 250 for i in range(30)}
    src, cfg, out = make_repo(tmp_path, files, m=100, mm=2000)
    st = tmp_path / "status.json"
    assert run("build", "--config", cfg, "--src", src, "--out", out, "--status", st) == 1
    assert json.loads(st.read_text())["status"] == "error"


# ------------------------------------------------------------ verification
def test_verify_catches_tampered_part(tmp_path):
    """Editing one character inside a part is detected by verify."""
    src, cfg, out = built(tmp_path)
    p = out / core.part_rel("big.md", 2, 5)
    p.write_bytes(p.read_bytes().replace(b"caf", b"cab", 1))
    assert verify(src, cfg, out) == 1


def test_verify_catches_missing_part(tmp_path):
    """Deleting a part file is detected by verify."""
    src, cfg, out = built(tmp_path)
    (out / core.part_rel("big.md", 3, 5)).unlink()
    assert verify(src, cfg, out) == 1


def test_verify_catches_orphan_file(tmp_path):
    """An unexpected file under parts/ is detected by verify."""
    src, cfg, out = built(tmp_path)
    (out / "parts" / "big.md" / "0009-of-0009.txt").write_text("junk")
    assert verify(src, cfg, out) == 1


def test_verify_catches_stale_bites(tmp_path):
    """Changing the source without rebuilding is detected by verify."""
    src, cfg, out = built(tmp_path)
    write(src, "big.md", mixed(460))
    git_add(src)
    assert verify(src, cfg, out) == 1


def test_verify_catches_unlisted_large_file(tmp_path):
    """A new large source file missing from the manifest is detected by verify."""
    src, cfg, out = built(tmp_path)
    write(src, "new.md", "n" * 400)
    git_add(src)
    assert verify(src, cfg, out) == 1


def test_part_must_fit_under_read_cap(tmp_path):
    """A part that would exceed read_cap once the wrapper is added fails verify."""
    src, cfg, out = make_repo(tmp_path, {"big.md": "a" * 450})
    build(src, cfg, out)
    cfg.write_text(TOML.format(m=100, mm=100000).replace("read_cap = 28000", "read_cap = 150"))
    assert verify(src, cfg, out) == 1


# ----------------------------------------------------------------- patches
def patch(src, name, text):
    """Write a patch file into the repo's .bites-patches directory."""
    write(src, f".bites-patches/{name}.patch", text)


def base_of(src, rel):
    """Return the 12-character git blob prefix of a source file (the patch BASE)."""
    return core.blob_sha((src / rel).read_bytes())[:12]


def apply(src, report=None):
    """Run `apply`, optionally saving the patch report; return the exit code."""
    args = ["apply", "--src", src]
    if report:
        args += ["--report", report]
    return run(*args)


def test_patch_replace_and_report(tmp_path):
    """A FIND/REPLACE patch edits the file, deletes the patch, and reports lines added and removed."""
    src, cfg, out = make_repo(tmp_path, {"d.md": "one\ntwo\nthree\n"})
    patch(src, "p1", f"@@@ FILE d.md\n@@@ BASE {base_of(src, 'd.md')}\n@@@ FIND\ntwo\n@@@ REPLACE\nTWO\nTWO-B\n@@@ END\n")
    rep = tmp_path / "r.json"
    assert apply(src, rep) == 0
    assert (src / "d.md").read_text() == "one\nTWO\nTWO-B\nthree\n"
    assert not (src / ".bites-patches" / "p1.patch").exists()
    r = json.loads(rep.read_text())
    assert r[0]["lines_added"] == 2 and r[0]["lines_removed"] == 1


def test_patch_multi_line_find_and_delete(tmp_path):
    """A multi-line FIND works and an empty REPLACE deletes the matched text."""
    src, cfg, out = make_repo(tmp_path, {"d.md": "a\nb\nc\nd\n"})
    patch(src, "p", f"@@@ FILE d.md\n@@@ BASE {base_of(src, 'd.md')}\n@@@ FIND\nb\nc\n@@@ REPLACE\n@@@ END\n")
    assert apply(src) == 0
    assert (src / "d.md").read_text() == "a\n\nd\n"


def test_patch_anchor_must_match_exactly_once(tmp_path):
    """A FIND matching twice or zero times is rejected and the file is left unchanged."""
    src, cfg, out = make_repo(tmp_path, {"d.md": "x\nx\ny\n"})
    b = base_of(src, "d.md")
    patch(src, "dup", f"@@@ FILE d.md\n@@@ BASE {b}\n@@@ FIND\nx\n@@@ REPLACE\nz\n@@@ END\n")
    assert apply(src) == 1
    (src / ".bites-patches" / "dup.patch").unlink()
    patch(src, "miss", f"@@@ FILE d.md\n@@@ BASE {b}\n@@@ FIND\nnope\n@@@ REPLACE\nz\n@@@ END\n")
    assert apply(src) == 1
    assert (src / "d.md").read_text() == "x\nx\ny\n"


def test_patch_base_mismatch_rejected(tmp_path):
    """A BASE that does not match the file's current blob SHA is rejected."""
    src, cfg, out = make_repo(tmp_path, {"d.md": "x\n"})
    patch(src, "p", "@@@ FILE d.md\n@@@ BASE 000000000000\n@@@ FIND\nx\n@@@ REPLACE\ny\n@@@ END\n")
    assert apply(src) == 1
    assert (src / "d.md").read_text() == "x\n"


def test_patch_failure_is_atomic(tmp_path):
    """If one patch fails, no earlier patch is applied and all patch files remain."""
    src, cfg, out = make_repo(tmp_path, {"a.md": "a\n", "b.md": "b\n"})
    good = f"@@@ FILE a.md\n@@@ BASE {base_of(src, 'a.md')}\n@@@ FIND\na\n@@@ REPLACE\nA\n@@@ END\n"
    bad = f"@@@ FILE b.md\n@@@ BASE {base_of(src, 'b.md')}\n@@@ FIND\nzzz\n@@@ REPLACE\nB\n@@@ END\n"
    patch(src, "1", good)
    patch(src, "2", bad)
    assert apply(src) == 1
    assert (src / "a.md").read_text() == "a\n"
    assert (src / ".bites-patches" / "1.patch").exists()


def test_patch_preserves_crlf(tmp_path):
    """Patch text is converted to CRLF when the target file uses CRLF."""
    src, cfg, out = make_repo(tmp_path, {"d.md": b"one\r\ntwo\r\nthree\r\n"})
    patch(src, "p", f"@@@ FILE d.md\n@@@ BASE {base_of(src, 'd.md')}\n@@@ FIND\ntwo\n@@@ REPLACE\nTWO\nMORE\n@@@ END\n")
    assert apply(src) == 0
    assert (src / "d.md").read_bytes() == b"one\r\nTWO\r\nMORE\r\nthree\r\n"


def test_patch_new_file_and_append(tmp_path):
    """NEW creates a file from APPEND blocks; APPEND to an existing file starts on a new line."""
    src, cfg, out = make_repo(tmp_path, {"d.md": "one\ntwo"})
    patch(src, "a", "@@@ FILE new.md\n@@@ NEW\n@@@ APPEND\nfirst\nsecond\n@@@ APPEND\nthird\n@@@ END\n")
    assert apply(src) == 0
    assert (src / "new.md").read_text() == "first\nsecond\nthird\n"
    patch(src, "b", f"@@@ FILE d.md\n@@@ BASE {base_of(src, 'd.md')}\n@@@ APPEND\nthree\n@@@ END\n")
    assert apply(src) == 0
    assert (src / "d.md").read_text() == "one\ntwo\nthree\n"


def test_patch_new_fails_if_file_exists(tmp_path):
    """A NEW section for an existing file is rejected."""
    src, cfg, out = make_repo(tmp_path, {"d.md": "x\n"})
    patch(src, "p", "@@@ FILE d.md\n@@@ NEW\n@@@ APPEND\nq\n@@@ END\n")
    assert apply(src) == 1


@pytest.mark.parametrize("path", ["../evil.md", "/abs.md", ".git/config"])
def test_patch_rejects_unsafe_paths(tmp_path, path):
    """Parent-directory, absolute and .git paths are rejected."""
    src, cfg, out = make_repo(tmp_path, {"d.md": "x\n"})
    patch(src, "p", f"@@@ FILE {path}\n@@@ NEW\n@@@ APPEND\nq\n@@@ END\n")
    assert apply(src) == 1


@pytest.mark.parametrize("text", [
    "garbage\n",                                                                    # text outside a block
    "@@@ FILE a.md\n@@@ BASE 000000000000\n@@@ FIND\nx\n@@@ END\n",                 # FIND without REPLACE
    "@@@ FILE a.md\n@@@ BASE 000000000000\n@@@ REPLACE\ny\n@@@ END\n",              # REPLACE without FIND
    "@@@ FILE a.md\n@@@ BASE 000000000000\n@@@ FIND\nx\n@@@ REPLACE\ny\n",          # missing END
    "@@@ FILE a.md\n@@@ FIND\nx\n@@@ REPLACE\ny\n@@@ END\n",                        # missing BASE
])
def test_malformed_patches_rejected(tmp_path, text):
    """Grammar violations are rejected without touching the tree."""
    src, cfg, out = make_repo(tmp_path, {"a.md": "x\n"})
    patch(src, "p", text)
    assert apply(src) == 1


def test_patch_then_build_end_to_end(tmp_path):
    """apply, then build with the patch report, then verify; last_build.json carries the line counts."""
    src, cfg, out = make_repo(tmp_path, {"big.md": "".join(f"row {i:04d}\n" for i in range(60))})
    build(src, cfg, out)
    patch(src, "p", f"@@@ FILE big.md\n@@@ BASE {base_of(src, 'big.md')}\n@@@ FIND\nrow 0030\n@@@ REPLACE\nrow 0030 EDITED\n@@@ END\n")
    rep = tmp_path / "r.json"
    assert apply(src, rep) == 0
    git_add(src)
    assert build(src, cfg, out, "--patch-report", rep, commit="c2") == 0
    assert verify(src, cfg, out) == 0
    last = json.loads((out / "last_build.json").read_text(encoding="utf-8"))
    assert last["status"] == "ok" and last["patches"][0]["lines_added"] == 1
    assert b"EDITED" in core.join_parts(out, "big.md", manifest(out)["files"]["big.md"]["parts"])


def test_status_and_report_failure(tmp_path):
    """A failing command writes a status file, and report-failure turns it into last_build.json."""
    src, cfg, out = make_repo(tmp_path, {"a.md": "x\n"})
    st = tmp_path / "st.json"
    patch(src, "p", "garbage\n")
    assert run("apply", "--src", src, "--status", st) == 1
    out.mkdir()
    assert run("report-failure", "--status", st, "--out", out, "--source-branch", "main", "--source-commit", "abc") == 0
    last = json.loads((out / "last_build.json").read_text())
    assert last["status"] == "error" and last["stage"] == "apply" and last["source_commit"] == "abc"


def test_reassemble_command_writes_exact_bytes(tmp_path, capsysbinary):
    """The reassemble command writes the original bytes to stdout."""
    src, cfg, out = make_repo(tmp_path, {"big.md": mixed(450)})
    build(src, cfg, out)
    capsysbinary.readouterr()  # discard the build's progress line
    assert run("reassemble", "--out", out, "--file", "big.md") == 0
    assert capsysbinary.readouterr().out == (src / "big.md").read_bytes()


def test_module_entry_point_runs():
    """`python -m bites_tool --help` works, proving the package is runnable as shipped."""
    root = Path(__file__).resolve().parent.parent
    r = subprocess.run([sys.executable, "-m", "bites_tool", "--help"], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0 and "build" in r.stdout
