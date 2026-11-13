"""The build, verify, reassemble and report-failure commands.

manifest.json (sorted keys, 2-space indent, no timestamps)
    schema           1
    source_branch    branch the parts were built from
    source_commit    commit of that branch the parts were built from
    max_chars        the setting used (a change forces a full rebuild)
    files            {source path: {blob_sha, bytes, chars, sha256, parts,
                                    start_lines[]}} for CHUNKED files only
    skipped          {source path: "not_utf8"} for matched files that could not be read

last_build.json
    status "ok":     source_branch, source_commit, changed{path: chars/parts before and
                     after}, removed[], unchanged_chunked, patches[] (per patch section:
                     patch, file, lines_added, lines_removed, operations)
                     truncated_report: true is added when the report would not fit in
                     one read: patches are cut to the first 20 and, if that is not
                     enough, changed and removed are cut to their first entries
                     (changed_total and removed_total then give the full counts).
    status "error":  stage ("apply" | "build" | "verify" | ...), message, plus
                     source_branch / source_commit. Parts are left untouched on error.

INCREMENTAL BUILDS
    A file is rebuilt only when its git blob SHA differs from the manifest, its part
    count changed, or a part file is missing. `--full`, a missing/foreign manifest, or a
    changed `max_chars` rebuilds everything. After each build any file under `parts/`
    that is not an expected part is deleted, so growing, shrinking, renaming or deleting
    a source file replaces its parts cleanly. Part names and headers embed the total
    count, so a change in the number of parts rewrites all parts of that file.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from .core import (
    SCHEMA, BitesError, blob_sha, dumps, join_parts, list_source_files, load_config,
    load_manifest, parse_part, part_rel, read_source, select_files, sha256_hex,
    split_parts, write_if_changed,
)


def cmd_build(a):
    """`build`: (re)generate parts, manifest.json and last_build.json under --out.

    Steps: choose the files to chunk; for each, rebuild its parts if it is new or
    changed (or a full rebuild was requested), otherwise reuse the existing parts;
    delete every file under parts/ that is no longer expected; write the manifest
    (failing if it exceeds `manifest_max_chars`); write last_build.json including the
    patch report from `apply` when one is given.
    """
    cfg = load_config(a.config)
    M = cfg["max_chars"]
    src, out = Path(a.src), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    prev = load_manifest(out)
    # Anything that makes the previous output untrustworthy forces a full rebuild.
    full = bool(a.full) or prev is None or prev.get("schema") != SCHEMA or prev.get("max_chars") != M
    prev_files = {} if prev is None else prev.get("files", {})

    files, skipped, expected, changed, unchanged = {}, {}, set(), {}, 0
    for rel in select_files(cfg, list_source_files(src)):
        got = read_source(src, rel)
        if got is None:
            continue
        data, text = got
        if text is None:
            skipped[rel] = "not_utf8"
            continue
        if len(text) <= M:
            continue  # small enough to read directly; nothing is written for it
        blob = blob_sha(data)
        n = math.ceil(len(text) / M)
        names = [part_rel(rel, i, n) for i in range(1, n + 1)]
        expected.update(names)
        old = prev_files.get(rel)
        # Reuse requires: same content, same part count, and every part file present.
        reuse = (
            not full and old is not None and old.get("blob_sha") == blob and old.get("parts") == n
            and all((out / nm).is_file() for nm in names)
        )
        if reuse:
            starts = old["start_lines"]
            unchanged += 1
        else:
            rendered, starts = split_parts(rel, text, M)
            for nm, content in rendered:
                write_if_changed(out / nm, content.encode("utf-8"))
            if old is None or old.get("blob_sha") != blob:
                changed[rel] = {
                    "chars_before": old.get("chars", 0) if old else 0,
                    "chars_after": len(text),
                    "parts_before": old.get("parts", 0) if old else 0,
                    "parts_after": n,
                }
            else:
                unchanged += 1  # full rebuild of a file whose content did not change
        files[rel] = {
            "blob_sha": blob, "bytes": len(data), "chars": len(text),
            "sha256": sha256_hex(data), "parts": n, "start_lines": starts,
        }

    # Files that were chunked before but are not now (deleted, shrunk, excluded).
    removed = sorted(set(prev_files) - set(files))
    # Delete stale part files (old numbering, removed sources), then empty directories.
    parts_root = out / "parts"
    if parts_root.is_dir():
        for f in sorted(parts_root.rglob("*")):
            if f.is_file() and f.relative_to(out).as_posix() not in expected:
                f.unlink()
        dirs = [d for d in parts_root.rglob("*") if d.is_dir()]
        for d in sorted(dirs, key=lambda x: len(x.parts), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass  # not empty

    manifest = {
        "schema": SCHEMA, "source_branch": a.source_branch, "source_commit": a.source_commit,
        "max_chars": M, "files": files, "skipped": skipped,
    }
    mtext = dumps(manifest)
    MM = cfg["manifest_max_chars"]
    if len(mtext) > MM:
        raise BitesError(
            f"manifest.json is {len(mtext)} chars, over manifest_max_chars={MM}; "
            "too many large files for one manifest"
        )
    write_if_changed(out / "manifest.json", mtext.encode("utf-8"))

    patches = []
    if a.patch_report and Path(a.patch_report).is_file():
        patches = json.loads(Path(a.patch_report).read_text(encoding="utf-8"))
    report = {
        "schema": SCHEMA, "status": "ok", "source_branch": a.source_branch,
        "source_commit": a.source_commit, "changed": changed, "removed": removed,
        "unchanged_chunked": unchanged, "patches": patches,
    }
    rtext = dumps(report)
    if len(rtext) > MM:  # keep last_build.json readable in one call
        report["patches"] = report["patches"][:20]
        report["truncated_report"] = True
        rtext = dumps(report)
    if len(rtext) > MM:
        # Still too long: keep only the first entries of `changed` and `removed`, halving
        # the number kept (50, 25, 12, ... 0) until the report fits.
        report["changed_total"] = len(changed)
        report["removed_total"] = len(removed)
        keep = 50
        while True:
            report["changed"] = dict(sorted(changed.items())[:keep])
            report["removed"] = removed[:keep]
            rtext = dumps(report)
            if len(rtext) <= MM or keep == 0:
                break
            keep //= 2
    write_if_changed(out / "last_build.json", rtext.encode("utf-8"))
    print(f"bites build: {len(files)} chunked file(s), {len(changed)} rebuilt, {len(removed)} removed")
    return 0


def cmd_verify(a):
    """`verify`: prove the output tree under --out is complete, consistent and current.

    Collects every problem (not just the first) and raises one BitesError listing up to
    20. Checks: manifest and last_build.json fit in one read; every listed file's parts
    parse, are in order, fit under `read_cap` with the wrapper, and have the right
    `chars` and start lines; the reassembled bytes match the manifest hashes AND the
    current source file (so stale parts are caught); every large source file is in the
    manifest; and no unexpected files exist under parts/.
    """
    cfg = load_config(a.config)
    M, cap, wrap = cfg["max_chars"], cfg["read_cap"], cfg["wrapper_chars"]
    src, out = Path(a.src), Path(a.out)
    man = load_manifest(out)
    if man is None:
        raise BitesError("manifest.json missing or unreadable")
    errs, expected = [], set()
    for name in ("manifest.json", "last_build.json"):
        fp = out / name
        if fp.is_file() and len(fp.read_bytes().decode("utf-8")) > cfg["manifest_max_chars"]:
            errs.append(f"{name} exceeds manifest_max_chars")

    total_parts = 0
    for rel, e in sorted(man.get("files", {}).items()):
        n = e["parts"]
        total_parts += n
        for i in range(1, n + 1):
            expected.add(part_rel(rel, i, n))
        try:
            data = join_parts(out, rel, n)
        except BitesError as exc:
            errs.append(str(exc))
            continue
        for i in range(1, n + 1):
            ptext = (out / part_rel(rel, i, n)).read_bytes().decode("utf-8")
            meta, _ = parse_part(ptext)
            if len(ptext) + wrap > cap:
                errs.append(f"{rel} part {i}: {len(ptext)}+{wrap} chars exceeds read_cap {cap}")
            if meta["chars"] > M:
                errs.append(f"{rel} part {i}: chars {meta['chars']} > max_chars {M}")
            if meta["start_line"] != e["start_lines"][i - 1]:
                errs.append(f"{rel} part {i}: start_line differs from manifest")
        if sha256_hex(data) != e["sha256"] or len(data) != e["bytes"]:
            errs.append(f"{rel}: reassembled bytes do not match manifest")
        if len(data.decode("utf-8")) != e["chars"]:
            errs.append(f"{rel}: reassembled char count differs from manifest")
        got = read_source(src, rel)
        if got is None:
            errs.append(f"{rel}: listed in manifest but missing from source")
        elif got[0] != data:
            errs.append(f"{rel}: reassembled parts differ from the source file (stale bites?)")

    # Completeness: a large, readable, selected source file must be in the manifest.
    for rel in select_files(cfg, list_source_files(src)):
        got = read_source(src, rel)
        if got is None or got[1] is None:
            continue
        if len(got[1]) > M and rel not in man.get("files", {}):
            errs.append(f"{rel}: over {M} chars but not in manifest")

    # Orphans: nothing under parts/ may exist that the manifest does not account for.
    parts_root = out / "parts"
    if parts_root.is_dir():
        for f in parts_root.rglob("*"):
            if f.is_file() and f.relative_to(out).as_posix() not in expected:
                errs.append(f"orphan part file: {f.relative_to(out).as_posix()}")

    if errs:
        more = f" (+{len(errs) - 20} more)" if len(errs) > 20 else ""
        raise BitesError("verification failed: " + "; ".join(errs[:20]) + more)
    print(f"bites verify: ok, {len(man.get('files', {}))} file(s), {total_parts} part(s)")
    return 0


def cmd_reassemble(a):
    """`reassemble`: write the original bytes of --file, rebuilt from its parts, to stdout."""
    out = Path(a.out)
    man = load_manifest(out)
    if man is None:
        raise BitesError("manifest.json missing or unreadable")
    e = man.get("files", {}).get(a.file)
    if e is None:
        raise BitesError(f"{a.file} is not chunked in this manifest")
    sys.stdout.buffer.write(join_parts(out, a.file, e["parts"]))
    return 0


def cmd_report_failure(a):
    """`report-failure`: write `<out>/last_build.json` describing a failed run.

    Reads the JSON error record that a failing command wrote to --status (if any),
    sets status "error", fills in defaults, and stamps the source branch and commit.
    The action calls this after resetting the bites tree so that only this file is
    published and the previous parts stay intact.
    """
    st = {}
    p = Path(a.status)
    if p.is_file():
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            st = {}
    st.setdefault("schema", SCHEMA)
    st["status"] = "error"
    st.setdefault("stage", "unknown")
    st.setdefault("message", "see the workflow run log")
    st["source_branch"] = a.source_branch
    st["source_commit"] = a.source_commit
    write_if_changed(Path(a.out) / "last_build.json", dumps(st).encode("utf-8"))
    return 0
