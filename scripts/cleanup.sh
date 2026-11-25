#!/usr/bin/env bash
# cleanup.sh - delete the bites/<branch> output branch after <branch> itself has been deleted.
#
# Run inside a git clone whose `origin` is the repository (the cleanup action does this). The
# settings it reads from the environment, and every message it prints, are described in
# locales/strings.en.toml ([cleanup]); scripts/strings.sh is generated from that file.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=strings.sh
. "$HERE/strings.sh"

text() { local key="$1"; shift; bites_fmt "cleanup.$key" ${1+"$@"}; }
die()  { printf '%s\n' "$(text prefix_error message="$*")" >&2; exit 1; }
note() { printf '%s\n' "$(text prefix_note message="$*")"; }

[ -n "${BRANCH:-}" ] || die "$(text branch_not_set)"
REF_TYPE="${REF_TYPE:-branch}"
DEFAULT_BRANCH="${DEFAULT_BRANCH:-}"
DRY_RUN="${DRY_RUN:-false}"
OUTPUT_BRANCH="bites/$BRANCH"

if [ "$REF_TYPE" != "branch" ]; then note "$(text not_a_branch ref_type="$REF_TYPE")"; exit 0; fi
case "$BRANCH" in bites/*) note "$(text output_branch branch="$BRANCH")"; exit 0 ;; esac
if [ "$BRANCH" = "$DEFAULT_BRANCH" ]; then note "$(text default_branch branch="$BRANCH")"; exit 0; fi
if git ls-remote --exit-code --heads origin "refs/heads/$BRANCH" >/dev/null 2>&1; then
  note "$(text branch_exists_again branch="$BRANCH" output_branch="$OUTPUT_BRANCH")"; exit 0
fi
if ! git ls-remote --exit-code --heads origin "refs/heads/$OUTPUT_BRANCH" >/dev/null 2>&1; then
  note "$(text no_output_branch output_branch="$OUTPUT_BRANCH")"; exit 0
fi
if [ "$DRY_RUN" = "true" ]; then note "$(text dry_run_would_delete output_branch="$OUTPUT_BRANCH")"; exit 0; fi
git push --quiet origin ":refs/heads/$OUTPUT_BRANCH"
note "$(text deleted output_branch="$OUTPUT_BRANCH")"
