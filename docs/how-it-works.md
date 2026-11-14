# How it works

1. A push to any branch starts a small workflow in your repository, which runs the `bites` action.
2. The action does nothing unless a branch named `bites/<branch>` exists. That branch is the opt-in switch.
3. If it exists, the action applies any patch files waiting in `.bites-patches/`, splits every text file longer than
   `max_chars` (default 27,000 characters) into parts, checks that each file reassembles byte for byte, and pushes the
   result to `bites/<branch>`.
4. The assistant reads `manifest.json`, `last_build.json` and `parts/...` on `bites/<branch>` instead of the oversized
   file. To edit, it commits a patch file to the source branch; the next build applies it.
5. When a branch is deleted, the `cleanup` action deletes its `bites/<branch>`.

A build usually finishes well under a minute.

## What is on the mirror branch

```
bites/main
├── manifest.json        index of every chunked file
├── last_build.json      result of the latest run
└── parts/
    └── docs/guide.md/
        ├── 0001-of-0003.txt
        ├── 0002-of-0003.txt
        └── 0003-of-0003.txt
```

- A file at or under `max_chars` characters is not chunked and is read directly.
- A longer file is cut at exact multiples of `max_chars` characters (not at line or word boundaries); the last part holds
  the remainder.
- Each part is a header line, the body, and a footer line, so a truncated read is detectable:
  `<<<BITE file=... part=2/3 chars=27000 start_line=412 sha256=... >>>` ... `<<<END BITE 2/3>>>`.
- `manifest.json` lists each chunked file with its git blob SHA, size, SHA-256, part count and the first line of each
  part, and records the `max_chars` in use. `last_build.json` has `status` (`ok` or `error`), the source commit, which
  files changed, and any patch results.
- Builds are incremental: a file is re-split only when its git blob changes.
- If a build fails, the previous parts stay as they were and only `last_build.json` is updated with the error.

Which files are mirrored is set by `include` and `exclude` globs; see [Configuration](configuration.md#which-files-are-mirrored).

## Editing large files with patches

The assistant never rewrites a mirrored file directly. It commits a patch file to `.bites-patches/` on the source branch:

```
@@@ FILE path/to/file.md
@@@ BASE 4d9cd51ffe2d
@@@ FIND
exact existing text
@@@ REPLACE
the new text
@@@ END
```

`BASE` is the start of the file's current git blob SHA, so a patch made against an outdated file is rejected. Each
`FIND` must match exactly once. Patches also support `APPEND` and creating new files. All pending patch files are applied
together or not at all; on success the workflow commits the result to the source branch, deletes the patch files, and
rebuilds the parts. The full grammar is in [BITES_INSTRUCTIONS.md](../BITES_INSTRUCTIONS.md) and the `bites_tool/patches.py`
docstring.

## Cleaning up mirror branches

A mirror holds only derived data, so deleting one is cheap: recreate the branch and the next push rebuilds it.

- **Automatic.** When a branch is deleted, by hand or by the repository's "Automatically delete head branches" setting
  after a pull request merge, the `cleanup` job deletes `bites/<branch>`. It skips tags, the default branch, `bites/*`
  branches, a branch that exists again by the time it runs, and branches that have no mirror.
- **Restoring a branch.** GitHub's "Restore branch" button on a closed pull request recreates the source branch, but not
  the mirror: create `bites/<branch>` again (step 2 of the [quick start](../README.md#quick-start)).
- **Sweeping.** `scripts/prune.sh OWNER/REPO` lists mirrors whose source branch no longer exists; add `--delete` to remove
  them. Use it for mirrors orphaned before the cleanup job existed, or if a delete event was missed.

## Repository layout

| Path | Purpose |
|---|---|
| `action.yml` | composite action: gate, apply patches, build, verify, publish |
| `cleanup/action.yml` | composite action: delete `bites/<branch>` when `<branch>` is deleted |
| `bites_tool/` | the Python package the build runs: standard library only, Python 3.11+ and `git` |
| `bites.toml` | default configuration |
| `templates/bites.yml` | the workflow that `scripts/bootstrap.sh` installs |
| `scripts/` | `bootstrap.sh` (install), `cleanup.sh` (logic behind the cleanup action), `prune.sh` (sweep orphaned mirrors) |
| `BITES_INSTRUCTIONS.md` | what to paste into a chat so the assistant reads and edits correctly |
| `docs/` | the guides linked from the README |
| `tests/` | test suite; the shell scripts run against local git repositories |
| `LICENSE` | the MIT license |

Module docstrings describe the part format, manifest layout, patch grammar and exit codes; start with
`bites_tool/__init__.py`. To run the tests locally (Python 3.11+): create a virtual environment, `python -m pip install
pytest`, then `python -m pytest tests -q`.

## Versions and releases

Use `imdebating/bites@v1` for the latest 1.x release, an exact tag such as `@v1.3.2`, or a full commit SHA. A breaking
change gets a new major tag. Maintainers: change the code through a pull request, bump `__version__` in
`bites_tool/__init__.py`, tag the release (`vX.Y.Z`), and move the major tag (`git tag -f v1 && git push -f origin v1`).
If a release changes `templates/bites.yml`, projects re-run `scripts/bootstrap.sh` to update their workflow.
Update `BITES_INSTRUCTIONS.md` in the same pull request as any change to what the assistant sees.
