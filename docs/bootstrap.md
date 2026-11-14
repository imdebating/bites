# Bootstrap and repository settings

`scripts/bootstrap.sh` installs the workflow and creates the mirror branches for new or existing repositories, and is safe
to repeat. It does steps 1 and 2 of the [quick start](../README.md#quick-start):

    git clone https://github.com/imdebating/bites && cd bites
    scripts/bootstrap.sh OWNER/REPO main feature

It installs the workflow on the default branch, creates `bites/main` and `bites/feature` if they do not exist, and
warns about a listed branch that lacks the workflow. Before it changes anything, it checks without your credentials that
the action repository and the version you ask for can be reached, and prints a warning (it does not stop) if not.

## Options

- `--ref`: the version the workflow uses.
- `--action OWNER/REPO`: take the action from another repository, such as a fork.
- `--set KEY=VALUE`: put a setting into the workflow; see [Configuration](configuration.md).
- `--ssh`: use SSH remotes.
- `--pr`: push the workflow to a branch for a pull request instead of the default branch.
- `--dry-run`: show what would happen without changing anything.
- `--no-preflight`: skip the reachability check.

Run `scripts/bootstrap.sh --help` for the full text.

## Repository settings

- Actions must be enabled. If your organization limits Actions to an allowlist, add `imdebating/bites@*`.
- Do not protect `bites/**` or restrict deletions on it: the workflow pushes to those branches and deletes them.
- Applied patches are committed straight to the source branch, so if it is protected, allow `github-actions[bot]` to push.
- Optional: turn on Settings > General > Pull Requests > "Automatically delete head branches" if your branches are
  short-lived. Rulesets and branch protection can stop a branch being deleted.
- If you fork this repository privately, set the fork's Settings > Actions > General > Access so your other repositories
  can use it.
