# Release testing

The automated tests (`python -m pytest tests -q`) run the shell scripts against local git repositories. They cannot
show what only GitHub does: the text of a real push rejection, `gh pr create`, an Actions run of the action, the
workflow token's permissions, or the cleanup job on a delete event. `tests/release_suite.sh` checks those against real
GitHub repositories. Run it before every release that changes `scripts/`, `action.yml`, `cleanup/action.yml`, or
`templates/bites.yml`.

## Run the suite

    bash tests/release_suite.sh

It needs git, python3, and gh signed in with the `repo` and `delete_repo` scopes (`gh auth refresh -s delete_repo`); gh
must be recent enough for `gh run list --commit`. The suite tests the commit at `HEAD` of your checkout, and that commit
must be pushed to GitHub, because the workflows the suite installs run the action at that commit. An uncommitted change
to `scripts/`, `action.yml`, `cleanup/`, `bites_tool/`, `templates/`, `bites.toml` or `VERSION` stops the run, since the
local `bootstrap.sh` would then differ from the action. Changes under `tests/` and `docs/` do not. If `imdebating/bites`
is private, set its Settings > Actions > General > Access so your other repositories can use it.

The suite creates one scratch repository per track, configures its protection, runs the scenarios below, checks each
"Pass when" column, and prints the Results table. It also writes the table to `release-test-results.md`, and what git
printed when it rejected a direct push to a protected branch to `release-test-results-rejections.txt`. A repository
whose scenarios all pass is deleted; one with a failure is kept for you to inspect. The exit status is 0 only if
everything passed. The checks use exit statuses and what is on GitHub afterwards, not the wording of bootstrap's
messages, so a change to the strings catalog does not break them.

| Track | Repository | Setup | Scenarios |
|---|---|---|---|
| a | `bites-scratch-a` | none | S4, S1, S3, S13a, S13b, S12, S2, in that order |
| b | `bites-scratch-b` | classic protection on `main` and `dev` | S5, S8, S7 |
| c | `bites-scratch-c` | a ruleset on `main` | S6 |
| d | `bites-scratch-d` | classic protection on `main`; the 1.4.0 script creates the old setup branch | S9 |
| e | `bites-scratch-e` | default branch `trunk` | S10 (optional) |
| f | `bites-scratch-f` | empty | S11 (optional) |

Name tracks to run only those: `bash tests/release_suite.sh b c`.

| Option | Effect |
|---|---|
| `--sha SHA` | The commit under test: a full 40-character SHA that is on GitHub. The default is `HEAD`. |
| `--public` | Create public repositories. Private ones may not allow branch protection on a free plan. |
| `--setup-only` | Create and configure the repositories, run nothing, delete nothing. |
| `--teardown` | Delete the repositories of the given tracks, and stop. |
| `--keep` | Keep every repository, even after a pass. |
| `--skip-optional` | Leave out S4, S8, S10 and S11, and so tracks e and f. |
| `--allow-dirty` | Do not stop for uncommitted changes in the code under test. The suite then tests code that the action does not run. |
| `--timeout SECS` | How long to wait for one Actions run. The default is 300. |
| `--results FILE` | Where to write the Results table. The default is `release-test-results.md`. |

## Scenarios

Exit statuses are 0 complete, 1 error or incomplete, 3 pending. `$REPO` is `$OWNER/<repository>`, and `$SHA` is the
commit under test.

| # | Track | Steps | Pass when |
|---|---|---|---|
| S4 (optional) | a | `scripts/bootstrap.sh --dry-run -v "$SHA" $REPO main` | Exit 0, and no branch on the remote changed. |
| S1 | a | `scripts/bootstrap.sh -v "$SHA" $REPO`. Then push a change to `docs/big.md`. | Exit 0. The run for bootstrap's own push and the run for your push are green. `bites/main` holds `manifest.json`, `last_build.json` (`"status": "ok"`) and 3 part files for `docs/big.md`. |
| S3 | a | `scripts/bootstrap.sh -v "$SHA" $REPO main dev feature/x`; run it again; run `-a` (`--all-branches`) | First run exit 0, with `bites/dev` and `bites/feature/x` created and the workflow on each. The second and third runs exit 0 and leave the remote's branches unchanged. |
| S13a | a | Push a patch (below) to `main` | The run is green. After `git pull`: line 500 of `docs/big.md` is changed, the patch file is gone, a `bites: apply patches` commit by `github-actions[bot]` exists, and `last_build.json` has status `ok`. |
| S13b | a | Push the same patch with `BASE` set to `000000000000`. Then remove it. | The run fails (conclusion `failure`) at **Apply pending patches**. `last_build.json` on `bites/main` says `"status": "error"` and `"stage": "apply"`, and the parts are unchanged. After the patch file is removed, the next run is green and `last_build.json` is `ok` again. |
| S12 | a | Delete the branch `dev` | `bites/dev` is removed, `bites/main` and `bites/feature/x` remain, and the `cleanup` run (event `delete`) succeeds. |
| S2 | a | `scripts/bootstrap.sh -v "$SHA" -c max_chars=15000 -c read_cap=20000 $REPO main`; push a change. Then run it again without `-c`. | The first run exits 0, the workflow has both values, and the next manifest says `max_chars` 15000 with 4 parts for `docs/big.md`. The run without `-c` exits 1, names the settings it would remove, and leaves the workflow unchanged. |
| S5 | b | `scripts/bootstrap.sh -v "$SHA" $REPO main dev`, then the same with `-p` | A direct push to `main` is rejected. Without `-p`: exit 1; `main` and `dev` are FAILED and the output names `--protected`; `bites/main` and `bites/dev` exist; no workflow was added. With `-p`: exit 3, and two open pull requests from `bites-setup/main` and `bites-setup/dev`, each changing only `.github/workflows/bites.yml`. |
| S8 (optional) | b | At that PENDING state, run `-p` with gh hidden from `PATH`, then with `GH_TOKEN=invalid` | Both runs exit 3 and print the compare link. |
| S7 | b | Merge `main`'s pull request and run `-p main dev` again; merge `dev`'s and run again. | After the first merge: exit 3. After the second: exit 0, and the workflow is on both branches. |
| S6 | c | `scripts/bootstrap.sh -v "$SHA" $REPO`, then with `-p`, then merge and run again. | Without `-p`: exit 1. With `-p`: exit 3 and a pull request that changes only the workflow. After the merge: exit 0. The rejection git printed for a direct push is saved. |
| S9 | d | From a checkout of `v1.4.0` run `scripts/bootstrap.sh --pr $REPO`. Then run the version under test with `-p -v "$SHA" $REPO`. | After the old run: a flat `bites-setup` branch. After the new run: that branch is gone, `bites-setup/main` exists, a pull request is open, exit 3. The old pull request's state is recorded; GitHub closed it. |
| S10 (optional) | e | `scripts/bootstrap.sh -v "$SHA" $REPO` | The default branch is `trunk` before the run. Exit 0; the workflow and `bites/trunk` exist on `trunk`; there is no `bites/main`. |
| S11 (optional) | f | `scripts/bootstrap.sh -v "$SHA" $REPO` | Exit 1, with a message that the repository has no default branch yet; nothing is created. |

The patch for S13 is run from a clone of the scratch repository, on `main`:

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

Create the directory with `mkdir -p` every time: after a patch is applied, git no longer has the directory.

## What GitHub prints for a protected branch

A direct push to a branch that needs a pull request is rejected with one of two messages. Classic branch protection
gives `GH006: Protected branch update failed` and ends with `(protected branch hook declined)`. A ruleset gives
`GH013: Repository rule violations found` and ends with `(push declined due to repository rule violations)`. Both say
"Changes must be made through a pull request." Bootstrap treats either as "a pull request is needed" by matching
`push_needs_pull_request` in `scripts/bootstrap.sh`, and `tests/test_bootstrap_rejections.py` checks that match against
the text GitHub sent on 2026-11-21. If a suite run saves different text in the rejections file, update that test.

## Running a scenario by hand

`bash tests/scratch_repo.sh NAME` creates `$OWNER/NAME`; the name must start with `bites-scratch-`. Options are
`--public`, `--empty` (no commits), `--default-branch NAME`, `--delete NAME` (asks you to type `NAME` or `OWNER/NAME`),
and `--seed-only DIR` (writes the seed content to a directory and touches nothing on GitHub). Every repository gets the
same content: `README.md`, `docs/small.md` (6,000 characters) and `docs/big.md` (60,000 characters, so 3 parts at the
default `max_chars`) on `main`, plus a `dev` branch and a `feature/x` branch that each add one file. Every document line
is 60 characters, numbered and unique (`line 0500: the quick brown fox jumps over the lazy dog 0123`), so a patch can
find it. The script checks that GitHub kept the default branch you asked for.

Set these in the shell you test from, inside the checkout, and always pass `-v "$SHA"`. The tag `v1` points at the
previous release, so a run without `-v` tests the old action.

    OWNER=$(gh api user --jq .login)
    SHA=$(git rev-parse HEAD)

Protection for tracks b and d is classic protection (Settings > Branches > Add branch protection rule): turn on
**Require a pull request before merging** with 0 required approvals, and turn on **Do not allow bypassing the above
settings**. Without the last one, repository admins are exempt, your own push succeeds, and the fallback never runs. For
track c, use a ruleset (Settings > Rules > Rulesets > New branch ruleset): enforcement **Active**, target the default
branch, turn on **Require a pull request before merging** with 0 required approvals, and leave the bypass list empty.
The suite sets both up through the API.

## One check by hand

The suite does not cover patches on a protected branch. The workflow's token is not an admin, so the bot's push of an
applied patch to a protected `main` is expected to be rejected. Once per release, run
`bash tests/release_suite.sh --setup-only b`, set the repository up with `-p` and merge the pull requests as in S5 and
S7, then merge a pull request that adds a patch file to `main`, and watch the run. Record what happens, and make the
repository settings section of `docs/bootstrap.md` match it.

## Results

The suite writes the table to `release-test-results.md`, with the tested commit, the account and the gh version above it.
Paste it into the release pull request description, and do not merge with a FAIL row. If you run scenarios by hand,
keep one row per scenario:

| Column | What to write |
|---|---|
| # | The scenario number, for example S5. |
| Result | PASS, FAIL, or SKIP. A FAIL row lists the checks that failed. |
| Date | The date you ran it, as YYYY-MM-DD. |
| Notes | What a reviewer would want: the exit status, an Actions run, or an answer to something a scenario asks you to record. |

If a scenario fails, fix the cause, run it again from a fresh scratch repository, and keep the failed attempt in the
Notes column. A track that fails during setup shows as `track X`, FAIL, `setup failed`.

## Release gate

1. The full test suite passes on the branch, locally and in CI.
2. `bash tests/release_suite.sh` passes, and its table is in the pull request. Rerun it if a later commit changes
   `scripts/`, `action.yml`, `cleanup/`, `bites_tool/` or `templates/`; commits to `tests/` and `docs/` do not need one.
3. The check by hand above is done.
4. Open the pull request into `main` and wait for CI.
5. Merge. Tag `vX.Y.Z` and move the major tag: `git tag -f v1 && git push -f origin v1`. `VERSION` already holds the number.
6. Publish release notes. For a release that renames options, say plainly which names are gone.
