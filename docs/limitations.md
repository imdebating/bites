# Limitations, Security and Troubleshooting

## Limitations

- UTF-8 text only. 
  Other files are listed under `skipped` in the manifest.
- A branch's `manifest.json` must fit in one read, which limits it to about as many characters as `max_chars` (27,000 by default).
  Each processed file uses roughly 350 characters of space, so with the defaults a branch holds up to approx. 70 to 80 large files, and a smaller `max_chars` lowers that number in proportion.
  Beyond the limit the build fails with an error naming it instead of publishing a cut-off manifest; narrow `include` and `exclude` if you reach it.
- Reading a large file takes several tool calls (one per part), and an assistant must follow the procedure in `BITES_INSTRUCTIONS.md`; there is no enforcement on the assistant's side.
- The bites branch lags the source by the build time, so assistants should check freshness (the instructions explain how).
- Applied patches add a commit to the source branch, pushed with the workflow's token.
  Patches therefore work only on branches that accept direct pushes; see [Patches and protected branches](#patches-and-protected-branches).
- Tested on GitHub-hosted Ubuntu runners and with the GitHub MCP server connector.
  Other runners and connectors are untested.

## Patches and Protected Branches

Patches work on branches that accept the workflow's direct pushes. To change a protected branch, apply the patch on an unprotected working branch, wait for the action to commit the edits and remove the patch file, then merge that branch through the normal pull-request process. Bites does not apply patches directly to branches that require pull requests. Bootstrap's `--protected` option installs the workflow through a setup pull request; it does not change this patching limitation.

The working branch can be any branch that accepts direct pushes, such as `feature/v1.7.0`, and it can be merged into the protected branch afterwards:

1. Create the working branch and run `scripts/bootstrap.sh OWNER/REPO <working-branch>`, so that it has the workflow and its `bites/<working-branch>` output branch.
2. Push the patch file to the working branch.
3. Wait for the action to commit the edits as "bites: apply patches" and delete the patch file in that commit.
4. Fetch the working branch and check that `.bites-patches/` no longer holds the file.
5. Open a pull request from the working branch into the protected branch, and merge it.

Merge the applied edits, not an unapplied patch file. A patch file that reaches a protected branch makes the run fail at "Commit applied patches to the source branch", and every later build on that branch fails until the file is deleted with a pull request. The failed run records `"stage": "commit"` and the reason in `last_build.json`.

One caveat: events caused by the workflow's own `GITHUB_TOKEN` do not start new workflow runs, so the "bites: apply patches" commit does not start push-triggered workflows. Checks that the protected branch requires on that new head may need to be triggered through your normal process before the pull request can merge.

## Security and Cost

- **Permissions.** The workflow needs `contents: write` to push to your branches. It uses only the job's `GITHUB_TOKEN`.
  The bites code itself makes no network calls beyond running git against your repository.
  Patch paths are limited to the working tree: absolute paths, `..` and `.git/` are rejected.
- **Your content is duplicated.** Parts of your files are written to the bites branch.
  Anyone who can read the repository can read them.
  The secret-like file names listed in [Configuration](configuration.md#which-files-are-processed) are never copied, but a secret inside a processed file is.
- **Supply chain.** `@v1` is a moving tag.
  To control exactly what runs, pin a full commit SHA instead (`imdebating/bites@<sha>`), and let Dependabot propose updates.
  The actions this project uses internally are pinned to full SHAs.
- **Cost.** The workflow starts on every push to every branch.
- With no bites branch it exits within seconds; with one, a build takes roughly 10 to 60 seconds of runner time.
  On private repositories that counts against your Actions minutes. 
  Storage grows by the size of the processed files.

## Troubleshooting

| Symptom | Likely cause and fix |
|----|----|
| A push does not start a build | The pushed branch has no `.github/workflows/bites.yml`: run `scripts/bootstrap.sh OWNER/REPO BRANCH` for it (or with `--all-branches`), which adds the file without merging anything. Or Actions is disabled. |
| The run finishes in seconds and changes nothing | There is no `bites/<branch>` branch. Run bootstrap for that branch; it creates the output branch. |
| "Unable to resolve action ... repository not found" | The action repository is private or its Access setting does not allow your repository; or the tag in your workflow does not exist; or an organization allowlist blocks it. |
| `bootstrap.sh` warns "cannot reach" or "no tag or branch named ..." | The action repository is private or misspelled, or it has no such tag, so workflows in your repository would fail with the error above. Correct `--action-from` or `--workflow-version`, make the action repository public (or share it through its Access setting), or pass `--no-preflight` to skip the check. |
| `bootstrap.sh` stops with "would remove" | The installed workflow has `max-chars`, `read-cap`, `include` or `exclude` lines that this run would delete. Run it again with the same `-c` options, or delete those lines first. |
| `bootstrap.sh` stops with "not a bites workflow" | `.github/workflows/bites.yml` on one of the branches was not written by bootstrap. Move it aside, or merge its jobs by hand, then run bootstrap again. Nothing was changed. |
| `bootstrap.sh` exits 1 and says INCOMPLETE | A push was refused (a protected branch when you did not give `--protected`, or a missing permission) or a branch moved while it ran. The summary names the branch and the reason. Fix it and run the same command again. |
| `bootstrap.sh` exits 3 (PENDING) | `--protected` opened a pull request. Merge it, then run the same command again to verify. |
| `bootstrap.sh` says the GitHub CLI (gh) was not found | A branch needed a pull request, and `gh` is not installed. Install it from <https://cli.github.com> (on macOS, `brew install gh`), run `gh auth login`, and run the same command again. Or open the pull request at the link that bootstrap prints. |
| `bootstrap.sh --all-branches` refuses a branch name | A branch has characters other than letters, digits and `. _ / -`. Nothing was changed; list the other branches by name instead. |
| Push rejected, "protected branch" or "permission denied" | The source branch requires pull requests, so the workflow cannot push applied patches to it: GitHub does not let the workflow's token bypass that rule, and `last_build.json` records `"stage": "commit"`. Delete the patch file with a pull request (every build on the branch fails until you do), then apply the patch on an unprotected working branch and merge it; see [Patches and protected branches](#patches-and-protected-branches). For bootstrap itself, use --protected. An organization policy that caps the workflow token to read-only gives the same error. |
| `last_build.json` says `"status": "error"` | `stage` and `message` name the failure (`apply`: a patch was rejected; `build`: for example a manifest over its limit; `verify`: a part did not match its source or is over `read_cap`; `commit`: the applied patches could not be pushed to the source branch). Previous parts are left untouched. A rejected patch file stays in `.bites-patches/` and blocks later builds until it is fixed or deleted. |
| The build log warns that `max_chars` leaves too little room | `max_chars` plus the part header, the footer and the connector's wrapper would exceed `read_cap`. Lower `max_chars` to the value the warning gives, or verification will fail. |
| `source_commit` in `last_build.json` is behind the branch head | The build has not finished yet, or it failed before publishing; check the run in the Actions tab. |
| A deleted branch's bites branch is still there | The workflow on the default branch predates the cleanup job, a rule blocks deleting `bites/**`, or the delete event did not fire. Run `scripts/prune.sh`. |
| A restored branch no longer builds | Its mirror was deleted with it. Run bootstrap for the branch again, or create `bites/<branch>` by hand. |
