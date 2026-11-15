# Bootstrap and repository settings

`scripts/bootstrap.sh` sets bites up with one command: it adds the caller workflow to every branch you choose, creates
each branch's `bites/<branch>` mirror, and then checks that all of it is on the remote. It works for new and existing
repositories, and is safe to repeat.

    git clone https://github.com/imdebating/bites && cd bites
    scripts/bootstrap.sh OWNER/REPO main feature
    scripts/bootstrap.sh --all-branches OWNER/REPO

The first command covers `main` and `feature`. The second covers every branch the repository has at that moment, except
`bites/*` and `bites-setup`. With no branch names, only the default branch is covered. You cannot combine
`--all-branches` with branch names.

## What it does

The workflow file lives on each branch that should build, because a push is run by the copy of
`.github/workflows/bites.yml` in the pushed commit. The code that does the work is shared: the file only says
`uses: imdebating/bites@v1`. Bootstrap therefore does this, in order:

1. Clones the repository and works out the selected branches. The default branch is always included for the workflow,
   because deleting a branch runs the copy on the default branch (that is what removes the mirror). It is mirrored only
   if you selected it.
2. Checks every selected branch before it changes anything: the branch exists, and an existing
   `.github/workflows/bites.yml` is a bites workflow whose settings would not be lost. If any check fails, nothing is
   written.
3. Creates each missing `bites/<branch>`, before the workflow, so the first build already finds its mirror.
4. Adds the workflow to each branch as one new commit on top of that branch. Nothing is merged, rebased or
   force-pushed, and no other file changes.
5. Fetches the remote again and checks that each workflow and mirror is really there.
6. Prints one line per branch, and reports success only if every branch is ready.

## What "complete" means

When bootstrap exits with status 0, every branch you asked for has the workflow and its mirror on the remote. The next
ordinary commit and push to any of them starts a build. You do nothing else, apart from the normal `git pull` to bring the
new workflow commit into your local checkouts.

It cannot see everything. It does not check that Actions is enabled, an organization's allowlist, or what the workflow
token may do at run time. The first build in the Actions tab is the real test of those.

## Options

- `--all-branches`: every existing branch except `bites/*` and `bites-setup`. Branches created later are not included;
  run the command again to add them.
- `--ref`: the version the workflow uses.
- `--action OWNER/REPO`: take the action from another repository, such as a fork.
- `--set KEY=VALUE`: put a setting into the workflow; see [Configuration](configuration.md).
- `--ssh`: use SSH remotes.
- `--pr`: for a protected default branch, push the workflow to `bites-setup` and open a pull request (see below).
- `--dry-run`: show what would happen without changing anything. It verifies nothing, so it never reports success.
- `--no-preflight`: skip the check that the action repository and version can be reached.

Run `scripts/bootstrap.sh --help` for the full text.

## Exit status

| Status | Meaning |
|---|---|
| 0 | Complete and verified (or a dry run). |
| 1 | An error, or setup incomplete. The summary names the branches and the reason. |
| 3 | Pending: a pull request must be merged (`--pr`). |

## If it stops part way

A push can be refused after the checks pass, for example by branch protection, a missing permission, or because
someone pushed to the branch meanwhile (bootstrap never overwrites that). The summary lists each branch as added, already
there, PENDING, FAILED or NOT DONE, with the reason from git, and the exit status is 1. Fix the cause and run the same
command again: finished work is recognised and not repeated. A branch whose mirror could not be created is left without
the workflow, so it never builds against a missing mirror.

## Protected default branch and `--pr`

With `--pr`, the workflow goes to a `bites-setup` branch and a pull request is opened with the `gh` CLI if it is
installed (otherwise open it by hand). Setup is then pending, with exit status 3. Merge the pull request, then run the same
command again; it verifies the result and exits 0. `--pr` covers the default branch only, because a pull request cannot add
the workflow to other branches as well, so bootstrap refuses `--pr` with other branches or `--all-branches` and changes
nothing. For other protected branches, allow `github-actions[bot]` and your own account to push, or add the file by hand.

## Branches created later

A new branch builds only when it has the workflow file and a `bites/<branch>` mirror. Creating it from a branch that
already has the file carries the file along; the mirror still has to be created. Running bootstrap for that branch does
both.

## Repository settings

- Actions must be enabled. If your organization limits Actions to an allowlist, add `imdebating/bites@*`.
- Do not protect `bites/**` or restrict deletions on it: the workflow pushes to those branches and deletes them.
- Applied patches are committed straight to the source branch, so if it is protected, allow `github-actions[bot]` to push.
- Optional: turn on Settings > General > Pull Requests > "Automatically delete head branches" if your branches are
  short-lived. Rulesets and branch protection can stop a branch being deleted.
- If you fork this repository privately, set the fork's Settings > Actions > General > Access so your other repositories
  can use it.
