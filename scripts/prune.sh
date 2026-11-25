#!/usr/bin/env bash
# prune.sh - find (and optionally delete) bites/<branch> output branches whose source branch no
# longer exists.
#
# usage: scripts/prune.sh [--delete] [--ssh] [--url URL] OWNER/REPO
#
# The full help text, and every message this script prints, is in locales/strings.en.toml
# ([prune]); scripts/strings.sh is generated from that file.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=strings.sh
. "$HERE/strings.sh"

text()  { local key="$1"; shift; bites_fmt "prune.$key" ${1+"$@"}; }
say()   { printf '%s\n' "$(text "$@")"; }
usage() { say help; }
die()   { printf '%s\n' "$(text prefix_error message="$*")" >&2; bites_annotate error "bites prune" "$*"; exit 1; }

DELETE=0; PROTO="https"; URL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --delete) DELETE=1; shift ;;
    --ssh)    PROTO="ssh"; shift ;;
    --url)    [ $# -ge 2 ] || die "$(text url_option_needs_value)"; URL="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    -*)       usage >&2; die "$(text unknown_option option="$1")" ;;
    *)        break ;;
  esac
done
[ $# -eq 1 ] || { usage >&2; exit 2; }
TARGET="$1"
[[ "$TARGET" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || die "$(text target_invalid target="$TARGET")"
if [ -z "$URL" ]; then
  if [ "$PROTO" = "ssh" ]; then URL="git@github.com:$TARGET.git"; else URL="https://github.com/$TARGET.git"; fi
fi

# Every branch name on the remote, one per line ("<sha><TAB>refs/heads/<name>" -> "<name>").
HEADS="$(git ls-remote --heads "$URL" | awk '{print substr($2, 12)}')" || die "$(text could_not_read url="$URL")"

# `git push` needs a repository to run in, even for a deletion by URL.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git init --quiet "$TMP"

found=0
while IFS= read -r name; do
  case "$name" in bites/*) ;; *) continue ;; esac
  src="${name#bites/}"
  if printf '%s\n' "$HEADS" | grep -Fxq -- "$src"; then continue; fi
  found=$((found + 1))
  if [ "$DELETE" = 1 ]; then
    git -C "$TMP" push --quiet "$URL" ":refs/heads/$name"
    say deleted name="$name"
  else
    say orphan name="$name"
  fi
done <<< "$HEADS"

if [ "$found" = 0 ]; then say none_found
elif [ "$DELETE" = 0 ]; then say found_summary count="$found"; fi
