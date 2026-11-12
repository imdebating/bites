# bites

Mirrors large text files as exact, size-capped parts on a `bites/<branch>` branch, and applies
patch files to them, so a chat assistant whose GitHub connector cuts any single result at about
28,000 characters can still read and edit them. One public repository serves every project:
a project adds a small caller workflow that uses this repository's action, and nothing else is
copied into it.

## Documentation map

| Where | What it covers |
|---|---|
| This README | layout, onboarding a repository, releasing, troubleshooting |
| `BITES_INSTRUCTIONS.md` | what to paste into a chat, and the read and patch procedures the assistant follows |
| `action.yml` (header comments) | what one workflow run does, step by step |
| `templates/bites.yml` (header comments) | the caller workflow and its placeholders |
| `scripts/bootstrap.sh` (header comments, or `--help`) | every option of the bootstrap script |
| `bites.toml` (comments) | every setting, with the measurements behind the numbers |
| `bites_tool/` module docstrings | the part file format, manifest and `last_build.json` layout, patch grammar, glob syntax, exit codes. Start with `__init__.py` |
| `tests/` | executable examples of every rule above |

## How it works

1. A push to any branch starts the caller workflow in the project, which runs this action.
2. The action does nothing unless a branch `bites/<branch>` exists (the opt-in switch). If one
   exists it applies any patch files waiting in `.bites-patches/`, rebuilds the parts of files
   longer than 27,000 characters, checks that every part reassembles to its source, and pushes
   the result to `bites/<branch>`.
3. The assistant reads `manifest.json`, `last_build.json` and `parts/...` on `bites/<branch>`
   instead of the oversized files, and edits large files by committing small patch files.

## Layout

| Path | Purpose |
|---|---|
| `action.yml` | composite action: gate, apply patches, build, verify, publish |
| `bites_tool/` | the Python package the action runs; standard library only, Python 3.11+ and `git` |
| `bites.toml` | default configuration; a project's own `bites.toml` in its root overrides it |
| `templates/bites.yml` | the caller workflow installed into projects |
| `scripts/bootstrap.sh` | installs the caller and creates `bites/<branch>` branches in any repository |
| `tests/` | test suite, including the bootstrap script run against local git repositories |
| `BITES_INSTRUCTIONS.md` | what to paste into a chat so the assistant reads and edits correctly |
| `.github/workflows/ci.yml` | runs the tests on every push to `main` and on pull requests |
| `.github/dependabot.yml` | weekly updates of the pinned action SHAs in `action.yml` and `ci.yml` |

## Adding bites to a repository (new or existing)

Run from a clone of this repository, with git credentials that can push to the target:

    scripts/bootstrap.sh imdebating/some-project main feature

- Installs `.github/workflows/bites.yml` on the default branch (committed directly; use `--pr`
  for a protected default branch).
- Creates an empty `bites/main` and `bites/feature` if they do not exist.
- Warns about any listed branch that does not contain the workflow yet; merge the default branch
  into it. Branches created after the workflow is on the default branch inherit it.
- Safe to repeat; `--dry-run` shows what it would do. Works the same for repositories in your
  organizations, as long as you can push to them and their Actions policy allows this action.

Then push to a mirrored branch (or run the `bites` workflow by hand with "full" ticked) to
build the first set of parts. To stop mirroring a branch, delete its `bites/<branch>` branch.
Chat setup (what to paste, which repository and branch) is in `BITES_INSTRUCTIONS.md`.

## How a project refers to this action

The caller uses `imdebating/bites@v1`: a moving major tag, so every project and branch picks up
a new release without being edited. The alternatives are an exact tag (`@v1.2.3`) or a full commit
SHA, which an organization may require in its Actions policy. Re-run the bootstrap script with
`--ref` to change it on the default branch.

## Releasing a change

1. Change the code on a branch, open a pull request, and let CI pass.
2. Update `__version__` in `bites_tool/__init__.py` to the new version number.
3. Merge to `main`, then tag it:

       git tag v1.2.0 && git push origin v1.2.0
       git tag -f v1 && git push -f origin v1

   `v1` moves to the new release; every project using `@v1` uses it from its next run.
4. Make a breaking change (for example a new manifest schema) a new major tag, `v2`, and move
   projects over deliberately.

The action and the package are fetched together at the same ref, so they cannot drift apart.
When a change alters what the assistant sees (file layout, manifest fields, patch grammar), update
`BITES_INSTRUCTIONS.md` in the same pull request.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| A push does not start a build | The pushed branch has no `.github/workflows/bites.yml` (merge the default branch into it), or Actions is disabled for the repository. |
| The run finishes in seconds and changes nothing | There is no `bites/<branch>` branch. Create it with the bootstrap script. |
| "Unable to resolve action" | The tag in the caller does not exist (push `v1`), or an organization's Actions policy blocks this repository (add `imdebating/bites@*` to its allowlist). |
| Push rejected, "protected branch" or "permission denied" | The source branch is protected (let `github-actions[bot]` push to it), or the organization caps the workflow token to read-only. |
| `last_build.json` says `"status": "error"` | `stage` and `message` name the failure (`apply`: a patch was rejected; `build`: for example a manifest over its limit; `verify`: a part did not match its source). The previous parts are left untouched. A rejected patch file stays in `.bites-patches/` and blocks later builds until it is fixed or deleted. |
| `last_build.json` `source_commit` is behind the branch head | The build has not finished, or it failed before publishing; check the run in the Actions tab. |

## Notes

- The calling job needs `permissions: contents: write` (the template sets it). This is set in the
  workflow itself, so the repository's default token permission should not matter; an organization
  or enterprise policy that caps the token would.
- Patch commits are pushed straight to the source branch, so a protected branch needs a rule that
  lets `github-actions[bot]` push. Keep `bites/*` unprotected.
- Dependabot in this repository updates the SHAs pinned inside `action.yml`. Projects need no
  Dependabot entry for this action while they use a moving tag.
