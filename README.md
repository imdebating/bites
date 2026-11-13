# bites

Make large text files readable and editable by AI assistants whose GitHub connector cuts off long results.

Some chat assistants read repository files through a GitHub connector (for example the GitHub MCP server) that
truncates any single result at a fixed size. In the setup this project was built and measured in, that size was about
28,000 characters. A file over the limit arrives cut off, and the assistant cannot tell what is missing. `bites` is a
pair of GitHub Actions that keep an exact, size-capped copy of each large file on a separate branch, split into small
numbered "parts" that can each be read whole. It also lets the assistant edit a large file by committing a small patch
file, so the whole file never has to be retyped.

## Is this for you?

It helps if all of these are true:

- your assistant reaches the repository only through a hosted GitHub connector (no local checkout, no code execution),
- the repository has text files longer than the connector's per-result limit, and
- you want the assistant to read them exactly, and to edit them.

It is probably not for you if the assistant can clone the repository and read files from disk, or if your files all fit
under the limit. Binary and non-UTF-8 files are skipped.

## How it works

1. A push to any branch starts a small workflow in your repository, which runs the `bites` action.
2. The action does nothing unless a branch named `bites/<branch>` exists. That branch is the opt-in switch.
3. If it exists, the action applies any patch files waiting in `.bites-patches/`, splits every text file longer than
   `max_chars` (default 27,000 characters) into parts, checks that each file reassembles byte for byte, and pushes the
   result to `bites/<branch>`.
4. The assistant reads `manifest.json`, `last_build.json` and `parts/...` on `bites/<branch>` instead of the oversized
   file. To edit, it commits a patch file to the source branch; the next build applies it.
5. When a branch is deleted, the `cleanup` action deletes its `bites/<branch>`.

A build usually finishes well under a minute.

## Quick start

Requirements: GitHub Actions enabled for the repository, and GitHub-hosted Linux runners (the workflow uses
`ubuntu-24.04`; other runners are untested). The assistant's token needs read access, and write access if it will push
patch files.

### 1. Add the workflow to the default branch

Create `.github/workflows/bites.yml`:

```yaml
name: bites

on:
  push:
    branches-ignore: ['bites/**']
  delete:
  workflow_dispatch:
    inputs:
      full:
        description: Rebuild and re-split every large file instead of only changed ones
        type: boolean
        default: false

permissions:
  contents: write

jobs:
  bites:
    if: github.event_name != 'delete'
    runs-on: ubuntu-24.04
    concurrency:
      group: bites-${{ github.ref }}
      cancel-in-progress: false
    steps:
      - uses: imdebating/bites@v1
        with:
          full: ${{ inputs.full || false }}

  cleanup:
    if: github.event_name == 'delete' && github.event.ref_type == 'branch' && !startsWith(github.event.ref, 'bites/')
    runs-on: ubuntu-24.04
    concurrency:
      group: bites-cleanup-${{ github.event.ref }}
      cancel-in-progress: false
    steps:
      - uses: imdebating/bites/cleanup@v1
```

A branch needs this file to build on push, so create other branches after it is on the default branch, or merge the
default branch into older ones. The `delete` trigger always uses the copy on the default branch.

### 2. Create the mirror branch for each branch you want mirrored

From a clean working tree:

```
git switch --orphan bites/main
git commit --allow-empty -m "bites: init"
git push -u origin bites/main
git switch main
```

Repeat with `bites/<branch>` for every other branch. Do not protect `bites/**`.

### 3. Push

Push a commit to `main` (or run the `bites` workflow by hand with "full" ticked). When the run finishes, `bites/main`
contains the parts. Then give your assistant the instructions in [BITES_INSTRUCTIONS.md](BITES_INSTRUCTIONS.md).

### Shortcut: the bootstrap script

`scripts/bootstrap.sh` does steps 1 and 2 for you, for new or existing repositories, and is safe to repeat:

    git clone https://github.com/imdebating/bites && cd bites
    scripts/bootstrap.sh OWNER/REPO main feature

It installs the workflow on the default branch, creates `bites/main` and `bites/feature` if they do not exist, and
warns about a listed branch that lacks the workflow. Before it changes anything, it checks without your credentials that
the action repository and the version you ask for can be reached, and prints a warning (it does not stop) if not.
Options: `--ref` (version the workflow uses), `--action OWNER/REPO` (take the action from another repository, such as a
fork), `--set KEY=VALUE` (put a setting into the workflow, see [Configuration](#configuration)), `--ssh`, `--pr` (push
the workflow to a branch for a pull request instead of the default branch), `--dry-run`, and `--no-preflight` (skip the
reachability check). See `--help`.

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

Which files are mirrored is set by `include` and `exclude` globs. By default: `.md`, `.txt`, `.rst`, `.py`, `.js`, `.ts`,
`.go`, `.rs`, `.java`, `.c`, `.h`, `.sh`, `.sql`, `.html`, `.css`, `.xml`, `.json`, `.yml`, `.yaml`, `.toml`, `.ini`,
`.cfg`, `.conf` and `.csv`, excluding `node_modules/`. Git internals, `.github/`, `.bites-patches/` and `bites.toml` are
never mirrored, and neither are `.env*`, `*.pem`, `*.key` and `id_rsa*`, whatever the configuration says.

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
rebuilds the parts. The full grammar is in [BITES_INSTRUCTIONS.md](BITES_INSTRUCTIONS.md) and the `bites_tool/patches.py`
docstring.

## Configuration

Four settings are meant to be changed:

| Setting | Workflow input | Default | Meaning |
|---|---|---|---|
| `max_chars` | `max-chars` | 27000 | No-chunk threshold and maximum part body, in characters (Unicode code points, not bytes) |
| `read_cap` | `read-cap` | 28000 | The connector's per-result limit; the build fails if a part plus the connector's wrapper would exceed it |
| `include` | `include` | the extensions listed above | Globs of the files to mirror (`*` within a directory, `**/` across directories) |
| `exclude` | `exclude` | `**/node_modules/**` | Globs of files to leave out |

There are two places to set them. A workflow input wins over a `bites.toml`, which wins over the defaults.

**In the workflow.** Add the inputs under `with:` in `.github/workflows/bites.yml`. They apply to every branch. Lists take
one glob per line; blank lines and lines starting with `#` are ignored:

```yaml
      - uses: imdebating/bites@v1
        with:
          full: ${{ inputs.full || false }}
          max-chars: 20000
          include: |
            **/*.md
            **/*.py
```

The bootstrap script writes the same lines for you and keeps them when you run it again: `scripts/bootstrap.sh --set
max_chars=20000 --set include='**/*.md' --set include='**/*.py' OWNER/REPO main`. Repeat `--set include=` and `--set
exclude=` once per glob. If the installed workflow already has such settings and you run the script without `--set`, it
stops instead of removing them.

**In a `bites.toml`.** Commit one to the root of a branch when that branch needs different settings. It needs only the
keys you want to change; anything it leaves out keeps the default from this repository's `bites.toml`. The action reads
the copy on the branch being built. For example, a `bites.toml` containing only `max_chars = 15000` is complete.

A given `include` or `exclude` list replaces the default list rather than adding to it. `.git/`, `.github/`,
`.bites-patches/` and `bites.toml` itself are always left out, so there is no need to list them. Changing `max_chars`
makes the next build re-split every large file.

The defaults were measured for one chat client. Yours will differ, so measure before relying on them: commit a text file
with numbered lines, ask the assistant to read it, and note where it is cut. Set `read_cap` to that size and `max_chars`
about 1,000 characters lower (the defaults leave roughly 700 characters of headroom for the part header, the footer and
the connector's own wrapper line). A client that limits by tokens rather than characters needs a conservative character
estimate. A build warns if `max_chars` leaves too little room under `read_cap`, and verification fails the build if a
part really is too big.

## Inputs and permissions

| Action | Input | Default | Meaning |
|---|---|---|---|
| `imdebating/bites` | `full` | `false` | `true` rebuilds and re-splits every large file |
| `imdebating/bites` | `max-chars`, `read-cap`, `include`, `exclude` | empty | Override the settings above; empty keeps the value from `bites.toml` or the default |
| `imdebating/bites/cleanup` | `dry-run` | `false` | `true` only logs what it would delete |

Both need the calling job to grant `permissions: contents: write`. Set it in the workflow, as above.

## Cleaning up mirror branches

A mirror holds only derived data, so deleting one is cheap: recreate the branch and the next push rebuilds it.

- **Automatic.** When a branch is deleted, by hand or by the repository's "Automatically delete head branches" setting
  after a pull request merge, the `cleanup` job deletes `bites/<branch>`. It skips tags, the default branch, `bites/*`
  branches, a branch that exists again by the time it runs, and branches that have no mirror.
- **Restoring a branch.** GitHub's "Restore branch" button on a closed pull request recreates the source branch, but not
  the mirror: create `bites/<branch>` again (step 2 above).
- **Sweeping.** `scripts/prune.sh OWNER/REPO` lists mirrors whose source branch no longer exists; add `--delete` to remove
  them. Use it for mirrors orphaned before the cleanup job existed, or if a delete event was missed.

## Repository settings

- Actions must be enabled. If your organization limits Actions to an allowlist, add `imdebating/bites@*`.
- Do not protect `bites/**` or restrict deletions on it: the workflow pushes to those branches and deletes them.
- Applied patches are committed straight to the source branch, so if it is protected, allow `github-actions[bot]` to push.
- Optional: turn on Settings > General > Pull Requests > "Automatically delete head branches" if your branches are
  short-lived. Rulesets and branch protection can stop a branch being deleted.
- If you fork this repository privately, set the fork's Settings > Actions > General > Access so your other repositories
  can use it.

## Security and cost

- **Permissions.** The workflow needs `contents: write` to push to your branches. It uses only the job's `GITHUB_TOKEN`.
  The bites code itself makes no network calls beyond running git against your repository. Patch paths are limited to the working tree: absolute
  paths, `..` and `.git/` are rejected.
- **Your content is duplicated.** Parts of your files are copied to the mirror branch. Anyone who can read the
  repository can read them. The secret-like file names above are never copied, but a secret inside a mirrored file is.
- **Supply chain.** `@v1` is a moving tag. To control exactly what runs, pin a full commit SHA instead
  (`imdebating/bites@<sha>`), and let Dependabot propose updates. The actions this project uses internally are pinned to
  full SHAs.
- **Cost.** The workflow starts on every push to every branch. With no mirror it exits within seconds; with one, a build
  takes roughly 10 to 60 seconds of runner time. On private repositories that counts against your Actions minutes. Storage
  grows by the size of the mirrored files.

## Limitations

- UTF-8 text only. Other files are listed under `skipped` in the manifest.
- A branch's `manifest.json` must fit in one read, which limits it to about as many characters as `max_chars` (27,000 by
  default). Each mirrored file takes roughly 350 characters of it, so with the defaults a branch holds about 70 to 80
  large files, and a smaller `max_chars` lowers that number in proportion. Beyond the limit the build fails with an error
  naming it instead of publishing a cut-off manifest; narrow `include` and `exclude` if you reach it.
- Reading a large file takes several tool calls (one per part), and an assistant must follow the procedure in
  `BITES_INSTRUCTIONS.md`; there is no enforcement on the assistant's side.
- The mirror lags the source by the build time, so assistants should check freshness (the instructions explain how).
- Applied patches add a commit to the source branch.
- Tested on GitHub-hosted Ubuntu runners and with the GitHub MCP server connector. Other runners and connectors are untested.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| A push does not start a build | The pushed branch has no `.github/workflows/bites.yml` (merge the default branch into it), or Actions is disabled. |
| The run finishes in seconds and changes nothing | There is no `bites/<branch>` branch. Create it (step 2). |
| "Unable to resolve action ... repository not found" | The action repository is private or its Access setting does not allow your repository; or the tag in your workflow does not exist; or an organization allowlist blocks it. |
| `bootstrap.sh` warns "cannot reach" or "no tag or branch named ..." | The action repository is private or misspelled, or it has no such tag, so workflows in your repository would fail with the error above. Correct `--action` or `--ref`, make the action repository public (or share it through its Access setting), or pass `--no-preflight` to skip the check. |
| `bootstrap.sh` stops with "would remove" | The installed workflow has `max-chars`, `read-cap`, `include` or `exclude` lines that this run would delete. Run it again with the same `--set` options, or delete those lines first. |
| Push rejected, "protected branch" or "permission denied" | The source branch is protected (allow `github-actions[bot]`), or an organization policy caps the workflow token to read-only. |
| `last_build.json` says `"status": "error"` | `stage` and `message` name the failure (`apply`: a patch was rejected; `build`: for example a manifest over its limit; `verify`: a part did not match its source or is over `read_cap`). Previous parts are left untouched. A rejected patch file stays in `.bites-patches/` and blocks later builds until it is fixed or deleted. |
| The build log warns that `max_chars` leaves too little room | `max_chars` plus the part header, the footer and the connector's wrapper would exceed `read_cap`. Lower `max_chars` to the value the warning gives, or verification will fail. |
| `source_commit` in `last_build.json` is behind the branch head | The build has not finished yet, or it failed before publishing; check the run in the Actions tab. |
| A deleted branch's mirror is still there | The workflow on the default branch predates the cleanup job, a rule blocks deleting `bites/**`, or the delete event did not fire. Run `scripts/prune.sh`. |
| A restored branch no longer builds | Its mirror was deleted with it. Create `bites/<branch>` again. |

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
| `tests/` | test suite; the shell scripts run against local git repositories |
| `LICENSE` | the MIT license |

Module docstrings describe the part format, manifest layout, patch grammar and exit codes; start with
`bites_tool/__init__.py`. To run the tests locally (Python 3.11+): create a virtual environment, `python -m pip install
pytest`, then `python -m pytest tests -q`.

## Versions and releases

Use `imdebating/bites@v1` for the latest 1.x release, an exact tag such as `@v1.3.1`, or a full commit SHA. A breaking
change gets a new major tag. Maintainers: change the code through a pull request, bump `__version__` in
`bites_tool/__init__.py`, tag the release (`vX.Y.Z`), and move the major tag (`git tag -f v1 && git push -f origin v1`).
If a release changes `templates/bites.yml`, projects re-run `scripts/bootstrap.sh` to update their workflow.
Update `BITES_INSTRUCTIONS.md` in the same pull request as any change to what the assistant sees.

## License

MIT. See [LICENSE](LICENSE).
