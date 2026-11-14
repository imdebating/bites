# Configuration

Four settings are meant to be changed:

| Setting | Workflow input | Default | Meaning |
|---|---|---|---|
| `max_chars` | `max-chars` | 27000 | No-chunk threshold and maximum part body, in characters (Unicode code points, not bytes) |
| `read_cap` | `read-cap` | 28000 | The connector's per-result limit; the build fails if a part plus the connector's wrapper would exceed it |
| `include` | `include` | the extensions listed below | Globs of the files to mirror (`*` within a directory, `**/` across directories) |
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

The [bootstrap script](bootstrap.md) writes the same lines for you and keeps them when you run it again: `scripts/bootstrap.sh --set
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

## Which files are mirrored

By default: `.md`, `.txt`, `.rst`, `.py`, `.js`, `.ts`,
`.go`, `.rs`, `.java`, `.c`, `.h`, `.sh`, `.sql`, `.html`, `.css`, `.xml`, `.json`, `.yml`, `.yaml`, `.toml`, `.ini`,
`.cfg`, `.conf` and `.csv`, excluding `node_modules/`. Git internals, `.github/`, `.bites-patches/` and `bites.toml` are
never mirrored, and neither are `.env*`, `*.pem`, `*.key` and `id_rsa*`, whatever the configuration says.

## Inputs and permissions

| Action | Input | Default | Meaning |
|---|---|---|---|
| `imdebating/bites` | `full` | `false` | `true` rebuilds and re-splits every large file |
| `imdebating/bites` | `max-chars`, `read-cap`, `include`, `exclude` | empty | Override the settings above; empty keeps the value from `bites.toml` or the default |
| `imdebating/bites/cleanup` | `dry-run` | `false` | `true` only logs what it would delete |

Both need the calling job to grant `permissions: contents: write`. Set it in the workflow, as in the [quick start](../README.md#quick-start).
