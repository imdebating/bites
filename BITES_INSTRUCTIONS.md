# Large files on this repository ("bites")

The tool names in this document (`get_file_contents`, `list_commits`, `create_or_update_file`,
`push_files`, `delete_file`) are those of the GitHub MCP server connector. With another GitHub
connector, use its equivalents. How a repository is set up for bites is covered in the bites
README, not here.

## 1. Paste this at the start of every chat (fill in OWNER, REPO and BRANCH)

```
Repository: OWNER/REPO. Working branch: BRANCH.

The GitHub connector cuts any single result at about 28,000 characters, so large text files
cannot be read whole. Every .md/.txt/.py/.conf/.csv/.sh/.json/.yml/.yaml file longer than
27,000 characters is mirrored as exact parts on branch bites/BRANCH. Rules:

1. Before reading any such file, read bites/BRANCH: find its head commit H (list_commits,
   perPage 1), then read manifest.json and last_build.json at H (use the sha argument).
   If last_build.json says status "error", tell me the message before doing anything else.
2. A file listed in manifest.json "files" must be read from its parts, never directly:
   parts/<path>/NNNN-of-MMMM.txt at H. Read every part, in order. Each part must start with
   "<<<BITE ..." and end with "<<<END BITE i/n>>>". If any part is missing, cut off, or
   ends with "...[truncated]", stop and tell me. Never say you read a whole file unless you
   read and checked all of its parts; say "read 4/4 parts".
3. Join part bodies (the text between the header line and the footer line) with no
   separator. Ignore the "successfully downloaded text file" line the connector adds.
4. Never edit a manifest-listed file with create_or_update_file, push_files or delete_file.
   Write a patch file (format in BITES_INSTRUCTIONS.md section 4) to
   .bites-patches/ on BRANCH instead, then wait for the build and check last_build.json.
5. Files not listed in manifest.json are read and written normally.
```

## 2. Reading a large file (reference)

1. Head of the bites branch: `list_commits` on `bites/<BRANCH>` with `perPage` 1 gives H.
2. `get_file_contents` for `manifest.json` and `last_build.json` with `sha` = H.
3. Freshness check for file F: list F's parent directory on `<BRANCH>` with
   `fields` = `["name","sha"]`. The entry's `sha` must equal `files[F].blob_sha` in the
   manifest. If it differs, the bites branch is behind: re-check later (up to 3 tries), then
   report it. Do not read stale parts as if they were current.
4. `n = files[F].parts`. Read `parts/F/0001-of-000n.txt` through `.../000n-of-000n.txt`
   with `sha` = H, up to 3 calls in parallel.
5. Check each part: header `part=i/n` matches the file name, footer is `<<<END BITE i/n>>>`,
   nothing follows the footer, and the text does not end with `...[truncated]`.
6. Concatenate the bodies in order with no separator. Part boundaries fall mid-line and
   mid-word on purpose.
7. To read around line L only: `files[F].start_lines` lists the first line of each part.
   Pick the part whose range contains L, and also its neighbour when L is near a boundary.
8. If F is not in `files`: read it directly. If the result ends with `...[truncated]`,
   stop: the file is probably excluded by `bites.toml`, not UTF-8 (see `skipped` in the
   manifest), or the manifest is stale.
9. If `bites/<BRANCH>` does not exist, the branch is not mirrored (or its mirror was deleted
   together with the branch, or the branch was restored afterwards). Read files directly, and if a
   result ends with `...[truncated]`, stop and tell the user the branch needs its mirror created.

`.env`, `*.pem`, `*.key` and `id_rsa*` are never mirrored.

## 3. Small files

Files of 27,000 characters or fewer are not mirrored. Read and write them directly with
`get_file_contents` and `create_or_update_file`. If a file grows past 27,000 characters, the
next build starts mirroring it and from then on it must be read through its parts and
edited with patches.

## 4. Editing a large file: patch files

Create `.bites-patches/<UTC yyyymmddThhmmssZ>-<slug>.patch` on `<BRANCH>` with
`create_or_update_file` (a new file needs no sha). Keep each patch file under about
20,000 characters.

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

## 5. After pushing a patch

1. The workflow applies the patches, commits that to `<BRANCH>`, deletes the applied patch
   files, rebuilds the parts and publishes `bites/<BRANCH>`. Re-fetch the heads of both
   branches on each check. The patch file is gone from `<BRANCH>` afterwards but stays in
   git history (the commit that added it).
2. The build is finished when `last_build.json` at the head of `bites/<BRANCH>` has
   `source_commit` equal to the current head of `<BRANCH>`.
3. `status: "ok"`: compare `patches[].lines_added` and `lines_removed` with what you
   intended, then read the edited region back from the new parts. If `truncated_report` is
   true, only the first 20 patch records are listed.
4. `status: "error"`: `stage` and `message` say what failed (BASE mismatch, FIND matched 0
   or 2 times, a part over the cap, and so on). The patch file is still in
   `.bites-patches/`, and it blocks every later build on that branch until you fix it with
   `create_or_update_file` (supply its sha) or remove it with `delete_file`. Re-read the
   file from fresh parts before rewriting the patch.
5. If nothing changes after several checks, the workflow may not be running for this
   branch. It only runs when `bites/<BRANCH>` exists, and the branch must contain
   `.github/workflows/bites.yml` (a branch created from the default branch after the
   workflow was added has it; merge the default branch into older branches). Tell the
   user; setting this up is the operator's job.
