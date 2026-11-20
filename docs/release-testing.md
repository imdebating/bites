# Release testing

The automated tests (`python -m pytest tests -q`) run the shell scripts against local git repositories. They cannot
show what only GitHub does: the text of a real push rejection, `gh pr create`, an Actions run of the action, the
workflow token's permissions, or the cleanup job on a delete event. This checklist covers those. Run it before every
release that changes `scripts/`, `action.yml`, `cleanup/action.yml`, or `templates/bites.yml`.

## Before you start

- A clean checkout of the branch under test, pushed to GitHub, with the full test suite passing.
- `gh auth status` shows you signed in with the `repo` scope. Add `delete_repo` (`gh auth refresh -s delete_repo`) to
  delete scratch repositories from the command line.
- If `imdebating/bites` is private, set its Settings > Actions > General > Access so your other repositories can use it.
- Branch protection on a private repository may need a paid plan. If protection will not save, make the scratch
  repository public with `--public`; its contents are dummy.

Set these in the shell you test from, inside the checkout:

    OWNER=$(gh api user --jq .login)
    SHA=$(git rev-parse HEAD)          # the full SHA of the commit under test
    git status --short; git log -1 --oneline origin/$(git branch --show-current)   # clean, and pushed

Always pass `-v "$SHA"`. The tag `v1` points at the previous release, so a run without `-v` tests the old action.

## Scratch repositories

`bash tests/scratch_repo.sh NAME` creates `$OWNER/NAME`; the name must start with `bites-scratch-`. Every repository gets
the same content: `README.md`, `docs/small.md` (6,000 characters) and `docs/big.md` (60,000 characters, so 3 parts at the
default `max_chars`) on `main`, plus a `dev` branch and a `feature/x` branch that each add one file. Every document line
is 60 characters, numbered and unique (`line 0500: the quick brown fox jumps over the lazy dog 0123`), so a patch can
find it. Use `--seed-only DIR` to inspect the content without touching GitHub.

| Repo | Create with | Setup | Scenarios |
|---|---|---|---|
| `bites-scratch-a` | `bash tests/scratch_repo.sh bites-scratch-a` | none | S4, S1, S3, S13, S12, S2, in that order |
| `bites-scratch-b` | same, name `-b` | Classic protection on `main` and on `dev` (below) | S5, S7, S8 |
| `bites-scratch-c` | same, name `-c` | A ruleset on `main` (below) | S6 |
| `bites-scratch-d` | same, name `-d` | Classic protection on `main` | S9 |
| `bites-scratch-e` | `--default-branch trunk` | none | S10 (optional) |
| `bites-scratch-f` | `--empty` | none | S11 (optional) |

Recreate a repository instead of repairing it: bootstrap commits to its branches, so a second pass starts from a dirty
state. Delete with `bash tests/scratch_repo.sh --delete NAME`.

### Protection settings

Classic protection (Settings > Branches > Add branch protection rule): branch name `main` (and again for `dev` in repo
B); turn on **Require a pull request before merging** with 0 required approvals; turn on **Do not allow bypassing the
above settings**. Without the last one, repository admins are exempt, your own push succeeds, and the fallback never
runs.

Ruleset (Settings > Rules > Rulesets > New branch ruleset): enforcement **Active**; target the default branch; turn on
**Require a pull request before merging** with 0 required approvals; leave the bypass list empty.

## Scenarios

`REPO=$OWNER/<name>` in each. Exit statuses are 0 complete, 1 error or incomplete, 3 pending.

| # | Repo | Steps | Pass when |
|---|---|---|---|
| S4 (optional) | A | `scripts/bootstrap.sh --dry-run -v "$SHA" $REPO main` | Exit 0; says nothing was changed or verified; `git ls-remote` shows only the seed branches. |
| S1 | A | `scripts/bootstrap.sh -v "$SHA" $REPO`. Then clone it, append a line to `docs/big.md`, push. | Exit 0. The Actions run is green. `bites/main` holds `manifest.json`, `last_build.json` (`"status": "ok"`) and 3 part files for `docs/big.md`. Record whether bootstrap's own push already started a run. |
| S3 | A | `scripts/bootstrap.sh -v "$SHA" $REPO main dev feature/x`; save `git ls-remote $URL`; run it again; run `-a` (`--all-branches`) | First run exit 0, with `bites/dev` and `bites/feature/x` created and the workflow on each. Second and third runs exit 0, report everything "already there", and leave `git ls-remote` unchanged. |
| S13a | A | Add a patch (below), push to `main` | Run green. After `git pull`: line 500 of `docs/big.md` is changed, the patch file is gone, a `bites: apply patches` commit by `github-actions[bot]` exists, and `last_build.json` lists the patch. |
| S13b | A | Same patch with `BASE` set to `000000000000`, push | The run fails at **Apply pending patches**. `last_build.json` on `bites/main` says `"status": "error"` and `"stage": "apply"` and names the `BASE` problem. The parts are unchanged. Remove the patch file, push, and the next run is green again. |
| S12 | A | `git push origin --delete dev` | The `cleanup` job runs and `bites/dev` is gone; `bites/main` and `bites/feature/x` remain. |
| S2 | A | `scripts/bootstrap.sh -v "$SHA" -c max_chars=15000 -c read_cap=20000 $REPO main`; push a change. Then run it again without `-c`. | The first run exit 0, the workflow has a `with:` block with both values, and the next manifest says `max_chars` 15000 with 4 parts for `docs/big.md`. The run without `-c` stops with exit 1, names the settings it would remove, and changes nothing. |
| S5 | B | Protect `main` and `dev`. `scripts/bootstrap.sh -v "$SHA" $REPO main dev`, then the same with `-p`. | Without `-p`: exit 1; `main` and `dev` are FAILED and the reason names `--protected`; `bites/main` and `bites/dev` exist; no workflow was added. With `-p`: exit 3; `gh pr list -R $REPO` shows two open pull requests from `bites-setup/main` and `bites-setup/dev`; `gh pr diff` for each shows only `.github/workflows/bites.yml`. |
| S7 | B | `gh pr merge N -R $REPO --merge` for `main`'s pull request; run `-p main dev` again; merge `dev`'s; run again. | After the first merge: exit 3, `main` "already there", `dev` PENDING. After the second: exit 0, all "already there". |
| S8 (optional) | B | At a PENDING state, hide gh: `mkdir /tmp/nogh && ln -s "$(command -v git)" /tmp/nogh/git`, then `PATH=/tmp/nogh:/usr/bin:/bin scripts/bootstrap.sh -p ...`. Then `GH_TOKEN=invalid scripts/bootstrap.sh -p ...`. | Both runs exit 3 and print the compare link. The first also says where to install gh. |
| S6 | C | Add the ruleset. `scripts/bootstrap.sh -v "$SHA" $REPO`, then with `-p`, then merge and run again. | The same results as S5 and S7 for `main`. Copy the real rejection text from the output into your notes: it is the ruleset message (`GH013`), not the classic one (`GH006`). |
| S9 | D | Protect `main`. From a checkout of `v1.4.0` run `scripts/bootstrap.sh --pr $REPO`. Then run the version under test with `-p -v "$SHA" $REPO`. | After the old run: a flat `bites-setup` branch and an open pull request. After the new run: that branch is gone, `bites-setup/main` exists, a pull request is open, exit 3. Record what happened to the old pull request. |
| S10 (optional) | E | `scripts/bootstrap.sh -v "$SHA" $REPO` | The workflow and `bites/trunk` are created on `trunk`; exit 0; a push to `trunk` builds. |
| S11 (optional) | F | `scripts/bootstrap.sh -v "$SHA" $REPO` | Exit 1, with a message that the repository has no default branch yet; nothing is created. |

A patch for S13 (run from a clone of the scratch repository, on `main`):

    BASE=$(git rev-parse HEAD:docs/big.md | cut -c1-12)    # S13b: BASE=000000000000
    mkdir -p .bites-patches
    cat > .bites-patches/01-test.patch <<EOF
    @@@ FILE docs/big.md
    @@@ BASE $BASE
    @@@ FIND
    line 0500: the quick brown fox jumps over the lazy dog 0123
    @@@ REPLACE
    line 0500: patched by the release test
    @@@ END
    EOF
    git add .bites-patches && git commit -m "Test patch" && git push

Look at a run with `gh run list -R $REPO` and `gh run view RUN_ID -R $REPO --log-failed`. Look at an output branch with
`git fetch && git show origin/bites/main:last_build.json`.

One more check, once, on repo B after S7: push a patch to the protected `main`. The workflow's token is not an admin, so
the push is expected to be rejected unless the bot is allowed to bypass. Record what happens, and make the repository
settings section of `docs/bootstrap.md` match it.

## Results

This table is a blank template, empty on purpose. The file in the repository stays blank. For each release, copy it
into the release pull request description and fill in one row per scenario you ran, as you run it. Reviewers use it as
the record of what was tested, so do not merge with a row marked FAIL.

| Column | What to write |
|---|---|
| # | The scenario number from the table above, for example S5. |
| Result | PASS, FAIL, or SKIP. Write the reason after SKIP, for example "not run: release does not touch this". |
| Date | The date you ran it, as YYYY-MM-DD. |
| Notes | Anything a reviewer would want: the exit status, the Actions run URL, text you copied from a real GitHub message, and answers to the "record" items (for example, whether bootstrap's own push started a run). |

The template to copy:

| # | Result | Date | Notes |
|---|---|---|---|

If a scenario fails, fix the cause, recreate the scratch repository, rerun that scenario, and keep the failed attempt in
the Notes column.

## Release gate

1. The full test suite passes on the branch, locally and in CI.
2. S1 to S3, S5 to S7, S9, S12 and S13 pass. S2, S4, S8, S10 and S11 are run when the release touches what they cover.
3. Open the pull request into `main` and wait for CI.
4. Merge. Tag `vX.Y.Z` and move the major tag: `git tag -f v1 && git push -f origin v1`. `VERSION` already holds the number.
5. Publish release notes. For a release that renames options, say plainly which names are gone.
6. Delete the scratch repositories.
