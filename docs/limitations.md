# Limitations, security and troubleshooting

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

## Security and cost

- **Permissions.** The workflow needs `contents: write` to push to your branches. It uses only the job's `GITHUB_TOKEN`.
  The bites code itself makes no network calls beyond running git against your repository. Patch paths are limited to the working tree: absolute
  paths, `..` and `.git/` are rejected.
- **Your content is duplicated.** Parts of your files are copied to the mirror branch. Anyone who can read the
  repository can read them. The secret-like file names listed in [Configuration](configuration.md#which-files-are-mirrored) are never copied, but a secret inside a mirrored file is.
- **Supply chain.** `@v1` is a moving tag. To control exactly what runs, pin a full commit SHA instead
  (`imdebating/bites@<sha>`), and let Dependabot propose updates. The actions this project uses internally are pinned to
  full SHAs.
- **Cost.** The workflow starts on every push to every branch. With no mirror it exits within seconds; with one, a build
  takes roughly 10 to 60 seconds of runner time. On private repositories that counts against your Actions minutes. Storage
  grows by the size of the mirrored files.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| A push does not start a build | The pushed branch has no `.github/workflows/bites.yml` (merge the default branch into it), or Actions is disabled. |
| The run finishes in seconds and changes nothing | There is no `bites/<branch>` branch. Create it (step 2 of the [quick start](../README.md#quick-start)). |
| "Unable to resolve action ... repository not found" | The action repository is private or its Access setting does not allow your repository; or the tag in your workflow does not exist; or an organization allowlist blocks it. |
| `bootstrap.sh` warns "cannot reach" or "no tag or branch named ..." | The action repository is private or misspelled, or it has no such tag, so workflows in your repository would fail with the error above. Correct `--action` or `--ref`, make the action repository public (or share it through its Access setting), or pass `--no-preflight` to skip the check. |
| `bootstrap.sh` stops with "would remove" | The installed workflow has `max-chars`, `read-cap`, `include` or `exclude` lines that this run would delete. Run it again with the same `--set` options, or delete those lines first. |
| Push rejected, "protected branch" or "permission denied" | The source branch is protected (allow `github-actions[bot]`), or an organization policy caps the workflow token to read-only. |
| `last_build.json` says `"status": "error"` | `stage` and `message` name the failure (`apply`: a patch was rejected; `build`: for example a manifest over its limit; `verify`: a part did not match its source or is over `read_cap`). Previous parts are left untouched. A rejected patch file stays in `.bites-patches/` and blocks later builds until it is fixed or deleted. |
| The build log warns that `max_chars` leaves too little room | `max_chars` plus the part header, the footer and the connector's wrapper would exceed `read_cap`. Lower `max_chars` to the value the warning gives, or verification will fail. |
| `source_commit` in `last_build.json` is behind the branch head | The build has not finished yet, or it failed before publishing; check the run in the Actions tab. |
| A deleted branch's mirror is still there | The workflow on the default branch predates the cleanup job, a rule blocks deleting `bites/**`, or the delete event did not fire. Run `scripts/prune.sh`. |
| A restored branch no longer builds | Its mirror was deleted with it. Create `bites/<branch>` again. |
