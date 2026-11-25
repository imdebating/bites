r"""Patch files: edit large files without re-typing them, and the `apply` command.

PATCH FILES (.bites-patches/*.patch)
    Marker lines start at column 0 with "@@@ ". Grammar:
        @@@ FILE <path>            start a section for one file
        @@@ BASE <hex>             >= 12 hex chars of the file's current git blob SHA
        @@@ NEW                    (instead of BASE) the file must not exist yet
        @@@ FIND                   exact text that must occur exactly once ...
        @@@ REPLACE                ... and the text that replaces it (may be empty)
        @@@ APPEND                 text added at the end, on its own new line(s)
        @@@ END                    close the section
    Text of a block = the lines between markers joined with "\n"; the newline before
    the next marker is not part of it. To include a blank line, include an empty line.

    All pending patch files are applied together in file-name order, in memory first:
    if any section fails nothing is written and every patch file stays in place. On
    success the files are written and the patch files deleted. A later patch sees the
    result of an earlier one, so its BASE must match that result. CRLF files are patched
    with CRLF line endings automatically. NEW sections accept APPEND blocks only.

    Safety: target paths must be relative, contain no "..", and not point inside .git/.
"""
from __future__ import annotations

import difflib
import re
from itertools import islice
from pathlib import Path, PurePosixPath

from .core import BitesError, blob_sha, dumps
from .strings import message

# A marker line: "@@@ " + keyword (+ optional argument), starting at column 0.
MARKER = re.compile(r"^@@@ (FILE|BASE|NEW|FIND|REPLACE|APPEND|END)(?: (.*))?$")


def parse_patch(text: str, name: str) -> list[dict]:
    """Parse the text of one patch file into a list of sections.

    Each section is `{"path", "base", "new", "ops"}` where `ops` is a list of
    `("replace", find, replacement)` and `("append", text)` tuples in file order.
    `name` is only used in error messages. Raises BitesError (with file and line number)
    for any grammar violation: text outside a block, FIND without REPLACE, an empty FIND,
    a section without operations, a missing BASE, NEW combined with FIND, a missing END.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # the newline that ends the last line is not a blank line
    sections, cur, mode, buf, find_text = [], None, None, [], None

    def close(ln):
        """Finish the block being collected (if any) and record it in `cur`."""
        nonlocal mode, buf, find_text
        if mode is None:
            return
        body = "\n".join(buf)
        if mode == "find":
            if body == "":
                raise BitesError(message("patches", "empty_find", name=name, line=ln))
            find_text = body  # completed by the REPLACE block that must follow
        elif mode == "replace":
            cur["ops"].append(("replace", find_text, body))
            find_text = None
        else:
            cur["ops"].append(("append", body))
        mode, buf = None, []

    for ln, line in enumerate(lines, 1):
        m = MARKER.match(line)
        if m is None:
            if mode is None:
                if line.strip() == "":
                    continue  # blank lines between markers are ignored
                raise BitesError(message("patches", "text_outside_block", name=name, line=ln))
            buf.append(line)
            continue
        kind, arg = m.group(1), (m.group(2) or "").strip()
        close(ln)
        if kind == "FILE":
            if cur is not None:
                raise BitesError(message("patches", "file_before_end", name=name, line=ln))
            if not arg:
                raise BitesError(message("patches", "file_needs_path", name=name, line=ln))
            cur = {"path": arg, "base": None, "new": False, "ops": []}
        elif cur is None:
            raise BitesError(message("patches", "kind_outside_file", name=name, line=ln, kind=kind))
        elif kind == "BASE":
            cur["base"] = arg.lower()
        elif kind == "NEW":
            cur["new"] = True
        elif kind in ("FIND", "APPEND"):
            if find_text is not None:
                raise BitesError(message("patches", "kind_without_replace", name=name, line=ln, kind=kind))
            mode = kind.lower()
        elif kind == "REPLACE":
            if find_text is None:
                raise BitesError(message("patches", "replace_without_find", name=name, line=ln))
            mode = "replace"
        elif kind == "END":
            if find_text is not None:
                raise BitesError(message("patches", "find_without_replace", name=name, line=ln))
            if not cur["ops"]:
                raise BitesError(message("patches", "section_no_operations", name=name, line=ln, path=cur["path"]))
            if cur["new"] and any(op[0] == "replace" for op in cur["ops"]):
                raise BitesError(message("patches", "new_files_append_only", name=name, line=ln))
            if not cur["new"] and not cur["base"]:
                raise BitesError(message("patches", "needs_base", name=name, line=ln, path=cur["path"]))
            sections.append(cur)
            cur = None
    if cur is not None or mode is not None:
        raise BitesError(message("patches", "missing_end", name=name))
    if not sections:
        raise BitesError(message("patches", "no_sections", name=name))
    return sections


def safe_rel(path: str) -> str:
    """Validate a patch target path and return it normalised.

    Rejects absolute paths, any `..` component, and anything inside `.git/`, so a patch
    can only touch files inside the working tree.
    """
    pp = PurePosixPath(path)
    if pp.is_absolute() or not pp.parts or ".." in pp.parts or pp.parts[0] == ".git":
        raise BitesError(message("patches", "unsafe_path", path=path))
    return pp.as_posix()


def line_stats(before: str, after: str) -> dict:
    """Count lines added and removed between two texts (for last_build.json)."""
    added = removed = 0
    diff = difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
    for line in islice(diff, 2, None):  # skip the "---" / "+++" header lines
        if line.startswith("@@"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return {"lines_added": added, "lines_removed": removed}


def apply_section(pname: str, rel: str, sec: dict, cur):
    """Apply one parsed patch section to the file `rel`.

    `pname` names the patch file (for messages); `cur` is the file's current bytes, or
    None if it does not exist. Checks BASE against the current git blob SHA (or that the
    file is absent for NEW), then runs the operations in order on the decoded text:
    every FIND must match exactly once. Returns `(new_bytes, stats)`; raises BitesError
    on any mismatch. Nothing is written here.
    """
    if sec["new"]:
        if cur is not None:
            raise BitesError(message("patches", "already_exists", patch=pname, file=rel))
        text = ""
    else:
        if cur is None:
            raise BitesError(message("patches", "does_not_exist", patch=pname, file=rel))
        base = sec["base"] or ""
        if len(base) < 12 or not re.fullmatch(r"[0-9a-f]+", base):
            raise BitesError(message("patches", "base_too_short", patch=pname, file=rel))
        actual = blob_sha(cur)
        if not actual.startswith(base):
            raise BitesError(
                message("patches", "base_mismatch", patch=pname, file=rel, base=base, actual=actual[:12])
            )
        try:
            text = cur.decode("utf-8")
        except UnicodeDecodeError:
            raise BitesError(message("patches", "not_utf8", patch=pname, file=rel))
    before = text
    crlf = "\r\n" in text
    eol = "\r\n" if crlf else "\n"

    def nl(s):
        """Convert patch text (LF) to the file's own line ending."""
        return s.replace("\n", "\r\n") if crlf else s

    for k, op in enumerate(sec["ops"], 1):
        if op[0] == "replace":
            find, repl = nl(op[1]), nl(op[2])
            count = text.count(find)
            if count != 1:
                raise BitesError(
                    message("patches", "find_count", patch=pname, file=rel, operation=k, count=count, text=repr(op[1][:60]))
                )
            text = text.replace(find, repl, 1)
        else:
            # APPEND always starts on a fresh line and ends with a line break.
            if text and not text.endswith("\n"):
                text += eol
            text += nl(op[1]) + eol
    stats = line_stats(before, text)
    stats["operations"] = len(sec["ops"])
    return text.encode("utf-8"), stats


def cmd_apply(a):
    """`apply`: apply every `<--patches>/*.patch` under --src, all or nothing.

    Patch files are parsed first, then applied in file-name order against an in-memory
    copy of the tree (so a later patch sees the result of an earlier one and its BASE
    must match that result). Only if everything succeeds are the files written and the
    patch files deleted. With --report, a JSON list with one record per section
    (patch, file, lines_added, lines_removed, operations) is saved for `build`.
    """
    src = Path(a.src)
    pdir = src / a.patches
    pfiles = sorted(pdir.glob("*.patch")) if pdir.is_dir() else []
    if not pfiles:
        print(message("patches", "apply_none"))
        return 0
    state, report = {}, []
    for pf in pfiles:
        sections = parse_patch(pf.read_bytes().decode("utf-8"), pf.name)
        for sec in sections:
            rel = safe_rel(sec["path"])
            if rel in state:
                cur = state[rel]  # changed by an earlier section in this run
            elif (src / rel).is_file():
                cur = (src / rel).read_bytes()
            else:
                cur = None
            new_bytes, stats = apply_section(pf.name, rel, sec, cur)
            state[rel] = new_bytes
            report.append({"patch": pf.name, "file": rel, **stats})
    for rel, data in state.items():  # commit point: nothing failed, now write
        fp = src / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_bytes(data)
    for pf in pfiles:
        pf.unlink()
    if a.report:
        Path(a.report).write_text(dumps(report), encoding="utf-8")
    print(message("patches", "apply_done", patches=len(pfiles), files=len(state)))
    return 0
