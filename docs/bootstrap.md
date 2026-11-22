# Bootstrap and repository settings

`scripts/bootstrap.sh` sets bites up with one command: it adds the caller workflow to every branch you choose, creates each branch's `bites/<branch>` mirror, and then checks that all of it is on the remote.
It works for new and existing repositories, and is safe to repeat.

    git clone https://github.com/imdebating/bites && cd bites
    scripts/bootstrap.sh OWNER/REPO main feature
    scripts/bootstrap.sh --all-branches OWNER/REPO

The first command covers `main` and `feature`. The second covers every branch the repository has at that moment, except `bites/*`, `bites-setup`, and `bites-setup/*`. With no branch names, only the default branch is covered, whatever its name. 
You cannot combine `--all-branches` with branch names.
Options go before `OWNER/REPO`, and branch names go after it.

## What it does

The workflow file lives on each branch that should build, because a push is run by the copy of `.github/workflows/bites.yml` in the pushed commit.
The code that does the work is shared: the file only says `uses: imdebating/bites@v1`. Bootstrap therefore does this, in order:

1. Clones the repository and works out the selected branches. The default branch is always included for the workflow, because deleting a branch runs the copy on the default branch (that is what removes the mirror).
   It is mirrored only if you selected it.
2. Checks every selected branch before it changes anything: the branch exists, and an existing `.github/workflows/bites.yml` is a bites workflow whose settings would not be lost.
   If any check fails, nothing is written.
3. Creates each missing `bites/<branch>`, before the workflow, so the first build already finds its mirror.
4. Adds the workflow to each branch as one new commit on top of that branch. Nothing is merged or rebased, no source branch is force-pushed, and no other file changes.
   A branch that rejects the push because it is protected gets a pull request instead, if you gave `--protected` (see below).
5. Fetches the remote again and checks that each workflow and mirror is really there.
6. Prints one line per branch, and reports success only if every branch is ready.

## What "complete" means

When bootstrap exits with status 0, every branch you asked for has the workflow and its mirror on the remote.
The push that adds the workflow also starts a first build on that branch, and the next ordinary commit and push to any of them starts another.
You do nothing else, apart from the normal `git pull` to bring the new workflow commit into your local checkouts.

It cannot see everything.
It does not check that Actions is enabled, an organization's allowlist, or what the workflow token may do at run time.
The first build in the Actions tab is the real test of those.

## Options

- `-a`, `--all-branches`: every existing branch except `bites/*`, `bites-setup`, and `bites-setup/*`.
  Branches created later are not included; run the command again to add them.
- `-v`, `--workflow-version VERSION`: the version of the action that the workflow uses. The default is `v1`.
   It can be a moving tag such as `v1`, an exact tag such as `v1.5.0`, or a full commit SHA.
- `-f`, `--action-from OWNER/REPO`: take the action from another repository, such as a fork.
- `-c`, `--config KEY=VALUE`: put a setting into the workflow, and repeat the option for more; see [Configuration](configuration.md).
- `-s`, `--ssh`: use SSH remotes.
- `-p`, `--protected`: allow pull requests for protected branches (see below).
- `--dry-run`: show what would happen without changing anything.
   It verifies nothing, so it never reports success.
- `-n`, `--no-preflight`: skip the check that the action repository and version can be reached.
- `-V`, `--version`: print the version of the script and stop.
- `-h`, `--help`: print the full help text and stop.

Short options that take no value can be combined, so `-aps` means `-a -p -s`. An option that takes a value (`-v`, `-f`, or `-c`) goes last in a combination, followed by its value as the next argument.

Version 1.5.0 renamed four options, and the old names are gone.
Each one stops with a message that names its replacement.

| Old        | New                                                       |
|------------|-----------------------------------------------------------|
| `--ref`    | `--workflow-version` (`-v`)                               |
| `--action` | `--action-from` (`-f`)                                    |
| `--set`    | `--config` (`-c`)                                         |
| `--pr`     | `--protected` (`-p`), which now tries a direct push first |

## Exit status

| Status | Meaning |
|----|----|
| 0 | Complete and verified (or a dry run, or `--version`, or `--help`). |
| 1 | An error, or setup incomplete. The summary names the branches and the reason. |
| 3 | Pending: a pull request must be merged (`--protected`). |

## If it stops part way

A push can be refused after the checks pass, for example by branch protection, a missing permission, or because someone pushed to the branch meanwhile (bootstrap never overwrites that).
The summary lists each branch as added, already there, PENDING, FAILED or NOT DONE, with the reason from git, and the exit status is 1.
Fix the cause and run the same command again: finished work is recognised and not repeated.
A branch whose mirror could not be created is left without the workflow, so it never builds against a missing mirror.

## Protected branches and `--protected`

Bootstrap always tries a direct push first.
The option `--protected` does not force a pull request.
It only says what to do if GitHub rejects the push because the branch is protected, or because a rule requires a pull request.
Any other rejection, such as a missing permission, stays a failure.

When that happens and you gave `--protected`, the workflow goes to a branch named `bites-setup/<branch>` that holds one commit adding only `.github/workflows/bites.yml`.
Bootstrap then makes sure a pull request from `bites-setup/<branch>` into `<branch>` is open.
With the `gh` CLI installed and signed in, it opens one if none is open. Without a usable `gh` it prints the link to open one by hand, and says where to install `gh` (<https://cli.github.com>, or `brew install gh` on macOS).
Setup is then pending, with exit status 3.
Merge the pull request (its diff should show that one file), then run the same command again; it verifies the result and exits 0.

The option works for any branch, not only the default branch.
In one run, branches that accept the push are finished directly, and only the protected ones get a pull request, for example `scripts/bootstrap.sh -p OWNER/REPO main dev`.
Without `--protected`, a protected branch is reported as FAILED, and the message names the option.

Bootstrap accepts an existing `bites-setup/<branch>` only if merging it would change nothing but that one file, with the expected content.
If the branch holds anything else (extra files, a changed file mode, or another version), bootstrap replaces it, because the branch is reserved for this.
If you closed the pull request, running the command again opens a new one.
Version 1.4.0 used a single branch named `bites-setup`.
Git cannot hold that name and `bites-setup/<branch>` at once, so bootstrap deletes the old branch when it needs the new one.
GitHub closes the pull request that was open from the old branch when the branch is deleted.

A dry run cannot tell whether a branch is protected. With `--dry-run --protected`, bootstrap only reports whether `gh` was found.

## Branches created later

A new branch builds only when it has the workflow file and a `bites/<branch>` mirror.
Creating it from a branch that already has the file carries the file along; the mirror still has to be created.
Running bootstrap for that branch does both.

## Repository settings

- Actions must be enabled. 
  If your organization limits Actions to an allowlist, add `imdebating/bites@*`.
- Do not protect `bites/**` or restrict deletions on it: the workflow pushes to those branches and deletes them.
- Applied patches are committed straight to the source branch with the workflow's GITHUB_TOKEN, and GitHub does not letthat token bypass a rule that requires a pull request.
  On such a branch the push is rejected, the run fails at "Commit applied patches to the source branch", and the patch file stays on the branch and fails every later build until you delete it with a pull request.
  Use patches only on branches that accept direct pushes; ordinary builds on a protected branch are unaffected.
- Optional: turn on Settings \> General \> Pull Requests \> "Automatically delete head branches" if your branches are short-lived.
  Rulesets and branch protection can stop a branch being deleted.
- If you fork this repository privately, set the fork's Settings \> Actions \> General \> Access so your other repositories can use it.
