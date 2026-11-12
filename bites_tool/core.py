r"""Shared building blocks: configuration, file selection and the part file format.

UNITS
    Every length in this package is a count of Unicode code points (Python `len()` of
    the decoded `str`), never bytes. That is the unit the connector's cap was measured
    in (an emoji counts as 1). Files must be valid UTF-8; others are skipped and listed.

SOURCE FILE SELECTION
    Files come from `git ls-files` (tracked files only), filtered by the `include` and
    `exclude` glob lists in the configuration. These names are NEVER processed, even if
    a glob matches them: `.env*`, `*.pem`, `*.key`, `id_rsa*` (see DENY_BASENAMES).
    Glob syntax: `*` = any characters except `/`, `?` = one character except `/`,
    `**/` = zero or more directories, `**` = anything including `/`. So `**/*.md`
    matches both `README.md` and `a/b/c.md`.

SPLITTING RULE
    A file whose length is <= `max_chars` is NOT chunked and produces no output.
    A longer file is cut at exact multiples of `max_chars` code points (no attempt to
    respect lines, words or syntax); the last part holds the remainder, so a file of
    `max_chars + 1` characters yields parts of `max_chars` and 1.
    Number of parts: n = ceil(length / max_chars).

PART FILE FORMAT (exact)
    <<<BITE file=<url-quoted path> part=<i>/<n> chars=<c> start_line=<l> sha256=<hex> >>>\n
    <body: exactly c code points of the original text>
    \n<<<END BITE <i>/<n>>>>\n
    * `chars`      real length of this part's body in code points (so the last part
                   of a file one character over the limit has chars=1).
    * `start_line` 1-based line number on which the body's first character sits (a part
                   may begin mid-line). Lines are counted by "\n" only.
    * `sha256`     SHA-256 of the body encoded as UTF-8.
    Reassembly = take `chars` code points after the header line, require the footer
    immediately after, and join bodies with no separator. The header deliberately omits
    anything that changes when only another part of the file changes, so editing the
    end of a file rewrites only the last part(s).

OUTPUT LAYOUT (the tree of the `bites/<branch>` branch)
    manifest.json                 index of every chunked file (see build.py)
    last_build.json               result of the latest run (see build.py)
    parts/<source path>/NNNN-of-MMMM.txt
                                  one file per part; NNNN = part number, MMMM = total.
                                  The source path is kept in full (including its
                                  extension) so same-named files in different
                                  directories, or `x.md` and `x.txt`, never collide.

CONFIGURATION (bites.toml, read with the standard-library tomllib)
    max_chars            no-chunk threshold and maximum part body        (default 27000)
    read_cap             measured per-result cap                         (default 28000)
    wrapper_chars        connector wrapper line counted against the cap  (default 82)
    manifest_max_chars   limit for manifest.json / last_build.json       (default max_chars)
    include, exclude     glob lists (include is required)
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import math
import os
import re
import subprocess
import tomllib
from pathlib import Path
from urllib.parse import quote, unquote

# Version of the manifest / last_build.json layout. A manifest with another value is
# ignored and everything is rebuilt.
SCHEMA = 1

# File names (matched against the last path component) that are never chunked, even if
# an include glob matches them. They are the usual homes of secrets.
DENY_BASENAMES = (".env*", "*.pem", "*.key", "id_rsa*")


class BitesError(Exception):
    """A problem the user can act on (bad config, bad patch, failed verification).

    Caught in `cli.main`, printed without a traceback, and turned into exit code 1.
    """


# ---------------------------------------------------------------- helpers
def sha256_hex(data: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of `data`."""
    return hashlib.sha256(data).hexdigest()


def blob_sha(data: bytes) -> str:
    r"""Return the git blob object id (SHA-1 of "blob <len>\0" + data) for `data`.

    This is the same value `git hash-object` prints and the GitHub API reports as a
    file's `sha`, so it can be compared with directory listings without calling git.
    """
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def dumps(obj) -> str:
    """Serialise `obj` as deterministic JSON text (sorted keys, 2 spaces, final newline)."""
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_if_changed(path: Path, data: bytes) -> bool:
    """Write `data` to `path` unless it already holds exactly those bytes.

    Creates parent directories. Returns True if the file was written. Skipping
    identical writes keeps file modification times (and git diffs) stable.
    """
    if path.is_file() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def glob_to_re(pat: str) -> re.Pattern:
    """Translate a bites glob (see module docstring) into an anchored regex.

    `**/` becomes an optional directory prefix so that `**/*.md` also matches a file
    in the repository root; plain `fnmatch` cannot do that.
    """
    out, i, n = [], 0, len(pat)
    while i < n:
        c = pat[i]
        if c == "*":
            if pat.startswith("**/", i):
                out.append("(?:.*/)?")
                i += 3
                continue
            if pat.startswith("**", i):
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("^" + "".join(out) + "$")


def load_config(path) -> dict:
    """Read and validate the configuration file.

    Returns a dict with the integer settings (`max_chars`, `read_cap`,
    `wrapper_chars`, `manifest_max_chars`) and the compiled regex lists
    `include_re` / `exclude_re`. Raises BitesError for an unreadable file or an
    unusable value.
    """
    try:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BitesError(f"cannot read config {path}: {exc}")
    cfg = {
        "max_chars": int(raw.get("max_chars", 27000)),
        "read_cap": int(raw.get("read_cap", 28000)),
        "wrapper_chars": int(raw.get("wrapper_chars", 82)),
    }
    # manifest.json and last_build.json must also be readable in one call.
    cfg["manifest_max_chars"] = int(raw.get("manifest_max_chars", cfg["max_chars"]))
    if cfg["max_chars"] < 1:
        raise BitesError("max_chars must be positive")
    include = list(raw.get("include", []))
    if not include:
        raise BitesError("config needs a non-empty include list")
    cfg["include_re"] = [glob_to_re(p) for p in include]
    cfg["exclude_re"] = [glob_to_re(p) for p in raw.get("exclude", [])]
    return cfg


def list_source_files(src: Path) -> list[str]:
    """Return the sorted paths (relative, "/"-separated) of files tracked by git in `src`.

    Uses `git ls-files -z`, so untracked and ignored files are not seen. Raises
    BitesError if `src` is not a git repository.
    """
    r = subprocess.run(["git", "-C", str(src), "ls-files", "-z"], capture_output=True)
    if r.returncode != 0:
        raise BitesError("git ls-files failed: " + r.stderr.decode("utf-8", "replace").strip())
    return sorted(os.fsdecode(p) for p in r.stdout.split(b"\0") if p)


def is_denied(rel: str) -> bool:
    """True if the file name matches DENY_BASENAMES (secret-like files)."""
    base = rel.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatchcase(base, p) for p in DENY_BASENAMES)


def select_files(cfg: dict, files: list[str]) -> list[str]:
    """Filter `files` to those matching include, not matching exclude, and not denied."""
    return [
        f
        for f in files
        if any(r.match(f) for r in cfg["include_re"])
        and not any(r.match(f) for r in cfg["exclude_re"])
        and not is_denied(f)
    ]


def read_source(src: Path, rel: str):
    """Read one source file.

    Returns None if it is missing, a symlink, or not a regular file (for example a
    submodule entry). Otherwise returns `(raw_bytes, text)` where `text` is the strict
    UTF-8 decoding with no newline translation, or None if the bytes are not valid
    UTF-8.
    """
    p = src / rel
    if p.is_symlink() or not p.is_file():
        return None
    data = p.read_bytes()
    try:
        return data, data.decode("utf-8")
    except UnicodeDecodeError:
        return data, None


def load_manifest(out: Path):
    """Return the parsed manifest.json under `out`, or None if missing or invalid."""
    try:
        man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        return man if isinstance(man, dict) else None
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------- part format
# Matches the header line of a part file (see "PART FILE FORMAT" above). The path is
# URL-quoted, so it never contains whitespace.
HEADER_RE = re.compile(
    r"<<<BITE file=(\S+) part=(\d+)/(\d+) chars=(\d+) start_line=(\d+) sha256=([0-9a-f]{64}) >>>\n"
)


def part_rel(rel: str, i: int, n: int) -> str:
    """Return the output path (relative to the bites tree) of part `i` of `n` of `rel`."""
    return f"parts/{rel}/{i:04d}-of-{n:04d}.txt"


def render_part(rel: str, i: int, n: int, body: str, start_line: int) -> str:
    """Return the full text of one part file: header line, body, footer line."""
    header = "<<<BITE file=%s part=%d/%d chars=%d start_line=%d sha256=%s >>>\n" % (
        quote(rel, safe="/._-~"), i, n, len(body), start_line, sha256_hex(body.encode("utf-8")),
    )
    return header + body + "\n<<<END BITE %d/%d>>>\n" % (i, n)


def parse_part(text: str):
    """Strictly parse the text of one part file.

    Checks, in order: the header is present and well formed, the body really has
    `chars` code points, the footer follows the body exactly with the right numbers and
    nothing after it, and the body matches the header's sha256. Returns
    `(meta, body)` where `meta` has file, part, of, chars and start_line.
    Raises BitesError describing the first problem found, so a cut-off read is reported
    as truncation rather than silently accepted.
    """
    m = HEADER_RE.match(text)
    if not m:
        raise BitesError("bad or missing BITE header")
    path, i, n, chars, start = unquote(m[1]), int(m[2]), int(m[3]), int(m[4]), int(m[5])
    body = text[m.end(): m.end() + chars]
    if len(body) != chars:
        raise BitesError(f"{path} part {i}/{n}: body shorter than chars={chars} (truncated?)")
    tail = text[m.end() + chars:]
    if tail != "\n<<<END BITE %d/%d>>>\n" % (i, n):
        raise BitesError(f"{path} part {i}/{n}: footer missing or wrong (truncated?)")
    if sha256_hex(body.encode("utf-8")) != m[6]:
        raise BitesError(f"{path} part {i}/{n}: body does not match header sha256")
    return {"file": path, "part": i, "of": n, "chars": chars, "start_line": start}, body


def split_parts(rel: str, text: str, max_chars: int):
    """Cut `text` into parts of exactly `max_chars` code points (last part: remainder).

    Returns `(rendered, starts)`: `rendered` is a list of `(output path, part file
    text)` and `starts` the 1-based start line of every part.
    """
    n = math.ceil(len(text) / max_chars)
    rendered, starts = [], []
    for i in range(1, n + 1):
        off = (i - 1) * max_chars
        body = text[off: off + max_chars]
        start = 1 + text.count("\n", 0, off)
        starts.append(start)
        rendered.append((part_rel(rel, i, n), render_part(rel, i, n, body, start)))
    return rendered, starts


def join_parts(out: Path, rel: str, n: int) -> bytes:
    """Read and strictly parse all `n` parts of `rel` under `out`; return the original bytes.

    Raises BitesError if a part is unreadable, malformed, truncated, or its header names
    a different file or position than its path.
    """
    bodies = []
    for i in range(1, n + 1):
        p = out / part_rel(rel, i, n)
        try:
            text = p.read_bytes().decode("utf-8")
        except OSError as exc:
            raise BitesError(f"cannot read {p}: {exc}")
        meta, body = parse_part(text)
        if (meta["file"], meta["part"], meta["of"]) != (rel, i, n):
            raise BitesError(f"{p}: header says {meta['file']} {meta['part']}/{meta['of']}")
        bodies.append(body)
    return "".join(bodies).encode("utf-8")
