# bites

<!-- Banner: uncomment once assets/banner.png is committed.
![bites: big files in, small parts out](assets/banner.png)
-->

[![CI](https://github.com/imdebating/bites/actions/workflows/ci.yml/badge.svg)](https://github.com/imdebating/bites/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/tag/imdebating/bites?sort=semver&label=version)](https://github.com/imdebating/bites/tags)
[![License: MIT](https://img.shields.io/github/license/imdebating/bites)](LICENSE)
<!-- Marketplace badge: uncomment after the action is published, and check the URL slug.
[![Marketplace](https://img.shields.io/badge/Marketplace-bites-2ea44f?logo=github)](https://github.com/marketplace/actions/bites)
-->

## Does your AI assistant choke on big files?

Chat assistants often read a repository through a GitHub connector that cuts every long result off at a fixed size. In the setup this project was measured on, that size was about 28,000 characters. The assistant gets half a file, cannot tell what is missing, and answers anyway.

**bites** fixes that. On every push, it mirrors your large text files onto a separate branch as small, numbered parts that each fit under the limit, plus a manifest the assistant uses to check that it read everything. It can also edit a large file from a small patch, so the file never has to be retyped.

## Stop pasting files into chat. Let your assistant read the whole repo.

No more copying a file, hitting the size limit, splitting it in two, and explaining which half came first. Point the assistant at your repository, paste the [short instructions](BITES_INSTRUCTIONS.md) once, and it reads each large file part by part and confirms that nothing is missing. Setup is one workflow file, which `scripts/bootstrap.sh` can write for you.

## Is this for you?

It helps if all of these are true:

- your assistant reaches the repository only through a hosted GitHub connector (no local checkout, no code execution),
- the repository has text files longer than the connector's per-result limit, and
- you want the assistant to read them exactly, and to edit them.

It is probably not for you if the assistant can clone the repository and read files from disk, or if your files all fit
under the limit. Binary and non-UTF-8 files are skipped.

## Quick start

Requirements: GitHub Actions enabled for the repository, and GitHub-hosted Linux runners (the workflow uses
`ubuntu-24.04`; other runners are untested). The assistant's token needs read access, and write access if it will push
patch files.

**Shortcut:** `scripts/bootstrap.sh` does steps 1 and 2 for you, for new or existing repositories, and is safe to repeat:

    git clone https://github.com/imdebating/bites && cd bites
    scripts/bootstrap.sh OWNER/REPO main feature

See [Bootstrap and repository settings](docs/bootstrap.md) for its options. To do it by hand:

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

## Documentation

| Guide | What it covers |
|---|---|
| [How it works](docs/how-it-works.md) | The mirror branch, parts and manifest, editing with patches, cleanup, repository layout, releases |
| [Configuration](docs/configuration.md) | `max_chars`, `read_cap`, `include`, `exclude`, workflow inputs, `bites.toml`, precedence |
| [Bootstrap and repository settings](docs/bootstrap.md) | `scripts/bootstrap.sh` options and the repository settings the action needs |
| [Limitations, security and troubleshooting](docs/limitations.md) | Known limits, permissions and cost, and fixes for common errors |
| [BITES_INSTRUCTIONS.md](BITES_INSTRUCTIONS.md) | What to paste into a chat so the assistant reads and edits correctly |

Use `imdebating/bites@v1` for the latest 1.x release, an exact tag such as `@v1.3.2`, or a full commit SHA.

## License

MIT. See [LICENSE](LICENSE).
