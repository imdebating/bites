#!/usr/bin/env bash
# cleanup.sh - delete the bites/<branch> mirror after <branch> itself has been deleted.
#
# Run inside a git clone whose `origin` is the repository (the cleanup action does this).
# Settings come from environment variables:
#   BRANCH          name of the deleted branch, without refs/heads/   (required)
#   REF_TYPE        what was deleted: branch or tag (default branch)
#   DEFAULT_BRANCH  the repository's default branch, which is never cleaned up
#   DRY_RUN         "true" reports what would be deleted and deletes nothing
#
# It does nothing (exit 0) unless ALL of these hold, so a stray event can never remove
# something it should not:
#   * a branch was deleted (not a tag)
#   * the branch is not the default branch and not itself a bites/* branch
#   * the branch does not exist again (deleted and re-created, or restored, in the meantime)
#   * a mirror named bites/<branch> exists
# A mirror holds only derived data, so deleting one is cheap to undo: run
# scripts/bootstrap.sh for the branch again and the next push rebuilds it.
set -euo pipefail

note() { echo "==> $*"; }

BRANCH="${BRANCH:?BRANCH is not set}"
REF_TYPE="${REF_TYPE:-branch}"
DEFAULT_BRANCH="${DEFAULT_BRANCH:-}"
DRY_RUN="${DRY_RUN:-false}"
MIRROR="bites/$BRANCH"

if [ "$REF_TYPE" != "branch" ]; then note "a $REF_TYPE was deleted, not a branch; nothing to do"; exit 0; fi
case "$BRANCH" in bites/*) note "$BRANCH is an output branch; nothing to do"; exit 0 ;; esac
if [ "$BRANCH" = "$DEFAULT_BRANCH" ]; then note "$BRANCH is the default branch; nothing to do"; exit 0; fi
if git ls-remote --exit-code --heads origin "refs/heads/$BRANCH" >/dev/null 2>&1; then
  note "$BRANCH exists again; keeping $MIRROR"; exit 0
fi
if ! git ls-remote --exit-code --heads origin "refs/heads/$MIRROR" >/dev/null 2>&1; then
  note "no $MIRROR branch; nothing to do"; exit 0
fi
if [ "$DRY_RUN" = "true" ]; then note "[dry-run] would delete $MIRROR"; exit 0; fi
git push --quiet origin ":refs/heads/$MIRROR"
note "deleted $MIRROR"
