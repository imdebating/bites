# Large files on this repository ("bites")

The tool names in this document (`get_file_contents`, `list_commits`, `create_or_update_file`,
`push_files`, `delete_file`) are those of the GitHub MCP server connector. With another GitHub
connector, use its equivalents. How a repository is set up for bites is covered in the bites
README, not here.

## 1. Paste this at the start of every chat (fill in OWNER, REPO and BRANCH)

```
Repository: OWNER/REPO. Working branch: BRANCH.

The GitHub connector cuts any single result at a fixed size (about 28,000 characters by
default), so large text files cannot be read whole. Text files longer than max_chars (27,000
by default; manifest.json records the value in use), except anything under .github/ or
excluded by the project's configuration, are mirrored as exact parts on branch bites/BRANCH,
and manifest.json on that branch lists exactly which ones. Rules:

1. Before reading any such file, read bites/BRANCH: find its head commit H (list_commits,
   perPage 1), then read manifest.json and last_build.json at H (use the sha argument).
   If last_build.json says status "error", tell me the message before doing anything else.
   If bites/BRANCH or its manifest.json does not exist, tell me; do not guess.
2. A file listed in manifest.json "files" must be read from its parts, never directly:
   parts/<path>/NNNN-of-MMMM.txt at H. Read every part, in order. Each part must start with
   "<<<BITE ..." and end with "<<<END BITE i/n>>>". If any part is missing, cut off, or
   ends with "...[truncated]", stop and tell me. Never say you read a whole file unless you
   read and checked all of its parts; say "read 4/4 parts".
3. A part body starts on the line after the header and has exactly the number of characters
   in the header's chars=. The single line break before the footer is not part of the body.
   Join the bodies with no separator. Ignore the "successfully downloaded text file" line
   the connector adds.
4. Never edit a manifest-listed file with create_or_update_file, push_files or delete_file.
   Write a patch file (format in BITES_INSTRUCTIONS.md section 4) to
   .bites-patches/ on BRANCH instead, then wait for the build and check last_build.json.
5. Files not listed in manifest.json are read and written normally.
```

## 2. Reading a large file (reference)

1. Head of the bites branch: `list_commits` on `bites/<BRANCH>` with `perPage` 1 gives H.
2. `get_file_contents` for `manifest.json` and `last_build.json` with `sha` = H.
3. Freshness check for file F: list F's parent directory on `<BRANCH>` (use path `/` for a
   file in the root) with `fields` = `["name","sha"]`. The entry's `sha` must equal
   `files[F].blob_sha` in the manifest. If it differs, the bites branch is behind: wait and
   re-check (see section 5, step 2, for timing), then report it. Do not read stale parts as
   if they were current.
4. `n = files[F].parts`. The part paths are `parts/F/0001-of-NNNN.txt` up to
   `parts/F/NNNN-of-NNNN.txt`, where both numbers are zero-padded to 4 digits (for n = 4:
   `0001-of-0004.txt` ... `0004-of-0004.txt`). Read them with `sha` = H, up to 3 calls in
   parallel.
5. Check each part: header `part=i/n` matches the file name (the header's `file=` is
   URL-quoted, so compare after decoding; the directory under `parts/` uses the plain path),
   footer is `<<<END BITE i/n>>>`, nothing follows the footer, and the text does not end with
   `...[truncated]`. Every part except the last has `chars` equal to the manifest's
   `max_chars` (27000 by default); a shorter one in the middle means something is wrong.
6. Each body is the `chars` characters that follow the header line. The line break before the
   footer is not part of it: a body that ends with a line break is followed by an empty line
   and then the footer, and one that ends mid-word is followed by that single line break. Join
   the bodies in order with no separator. Part boundaries fall mid-line and mid-word on
   purpose.
7. To read around line L only: `files[F].start_lines` lists the first line of each part.
   Pick the part whose range contains L, and also its neighbour when L is near a boundary.
8. If F is not in `files`: read it directly. If the result ends with `...[truncated]`,
   stop: the file is probably excluded by the configuration (a `bites.toml` or the workflow's
   include and exclude settings), not UTF-8 (see `skipped` in the manifest), or the manifest
   is stale.
9. If `bites/<BRANCH>` does not exist, the branch is not mirrored. That also happens when its
   mirror was deleted together with the branch, or the branch was restored afterwards. Read
   files directly, and if a result ends with `...[truncated]`, stop and tell the user the
   branch needs its mirror created.
10. If `bites/<BRANCH>` exists but has no `manifest.json`, its first build has not run (it
    starts with a single empty "bites: init" commit). Tell the user to push to `<BRANCH>` or
    run the bites workflow; do not treat it as an error in the repository.
11. If the working branch was merged by a pull request and deleted, its mirror is deleted
    with it. Continue on the base branch (usually `main`) and its mirror.

`.env`, `*.pem`, `*.key` and `id_rsa*` are never mirrored.

## 3. Small files and new files

Files of `max_chars` characters or fewer (27,000 by default; the manifest records the value)
are not mirrored. Read and write them directly with `get_file_contents` and
`create_or_update_file`. If a file grows past `max_chars`, the next build starts mirroring it
and from then on it must be read through its parts and edited with patches.

A brand-new large file is not in the manifest yet, so it may be created in one
`create_or_update_file` call if the whole content fits in one call. Once the next build has
listed it, it is a manifest-listed file: change it only with patches. A very large new file is
better built with the `NEW` and `APPEND` patch operations in pieces (section 4).

## 4. Editing a large file: patch files

Create `.bites-patches/<UTC yyyymmddThhmmssZ>-<slug>.patch` on `<BRANCH>` with
`create_or_update_file` (a new file needs no sha). Keep each patch file under about
20,000 characters, or under `max_chars` if that is smaller.

```
@@@ FILE path/to/file.md
@@@ BASE 4d9cd51ffe2d
@@@ FIND
exact existing text, one or more whole lines
@@@ REPLACE
the new text
@@@ FIND
a second, different anchor in the same file
@@@ REPLACE
@@@ APPEND
text added at the end of the file
@@@ END
```

Rules:

- Marker lines start at column 0 with `@@@ `. Never put such a line inside FIND, REPLACE or
  APPEND text.
- `BASE` is at least 12 hex characters of `files[F].blob_sha` (or the directory-listing
  `sha`) that you read. If the file changed since, the patch is rejected.
- Each FIND must match exactly once in the file. Include enough neighbouring lines to make
  it unique. An empty REPLACE deletes the FIND text.
- Text for FIND, REPLACE and APPEND is the lines between markers; the newline before the
  next marker is not part of it. To include a blank line, include an empty line.
- APPEND always starts on a new line and ends with a newline.
- A new file: `@@@ FILE path`, `@@@ NEW`, then one or more `@@@ APPEND` blocks, `@@@ END`.
  Build a new large file in several patches of about 20,000 characters, each using the
  `BASE` of the file as it stands after the previous patch (read it from the directory
  listing once the previous patch has been applied).
- One section per file per patch file. Operations run in order on the evolving text.
- CRLF files are handled automatically.
- All patch files waiting in `.bites-patches/` are applied together, in file-name order,
  and one failure rejects the whole set.

## 5. After pushing a patch (or any commit to a mirrored branch)

1. The workflow applies the patches, commits that to `<BRANCH>` as "bites: apply patches",
   deletes the applied patch files, rebuilds the parts and publishes `bites/<BRANCH>`. The
   patch file is gone from `<BRANCH>` afterwards but stays in git history (the commit that
   added it).
2. A build normally finishes within about 10 to 60 seconds of the push. Wait about 30
   seconds between checks and make up to 5 checks (builds on one branch queue, so several
   quick pushes take longer). On each check, re-fetch the heads of both branches.
3. The build is finished when `last_build.json` at the head of `bites/<BRANCH>` has
   `source_commit` equal to the current head of `<BRANCH>`. After a patch that head is the
   bot's "bites: apply patches" commit, not your patch commit, so compare against the new
   head.
4. `status: "ok"`: compare `patches[].lines_added` and `lines_removed` with what you
   intended, check `changed[F].chars_before` and `chars_after` for the file (the difference
   should match the size of your edit), then read the edited region back from the new parts.
   If `truncated_report` is true, only the first 20 patch records are listed, and `changed`
   and `removed` may be cut short too (`changed_total` and `removed_total` give the full
   counts); if F is missing from `changed`, rely on the manifest instead: its `blob_sha`
   for F must match the directory listing, and the edited region must read back correctly.
5. `status: "error"`: `stage` and `message` say what failed (BASE mismatch, FIND matched 0
   or 2 times, a part over the cap, and so on). The patch file is still in
   `.bites-patches/`, and it blocks every later build on that branch. List `.bites-patches/`
   on `<BRANCH>` to get its sha, then fix it with `create_or_update_file` (supply that sha)
   or remove it with `delete_file`. Re-read the file from fresh parts before rewriting the
   patch.
6. If nothing changes after the checks in step 2, the workflow may not be running for this
   branch. It only runs when `bites/<BRANCH>` exists, and the branch must contain
   `.github/workflows/bites.yml` (a branch created from the default branch after the
   workflow was added has it; merge the default branch into older branches). Tell the
   user; setting this up is the operator's job.
