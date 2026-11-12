#!/usr/bin/env bash
# prune.sh - find (and optionally delete) bites/<branch> mirrors whose source branch no
# longer exists. Use it for mirrors orphaned before the cleanup job existed, or when a
# delete event was missed. Without --delete it only lists them.
#
# usage: scripts/prune.sh [--delete] [--ssh] [--url URL] OWNER/REPO
#
#   --delete   delete the orphaned mirrors instead of only listing them
#   --ssh      talk to GitHub over SSH instead of HTTPS
#   --url URL  use this repository URL instead (used by the tests)
#   -h, --help show this text
#
# A mirror is an orphan when no branch named exactly like the part after "bites/" exists.
# Exit status: 0 on success (orphans found or not); non-zero on bad arguments or git errors.
set -euo pipefail

usage() { sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }
die()  { echo "error: $*" >&2; exit 1; }

DELETE=0; PROTO="https"; URL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --delete) DELETE=1; shift ;;
    --ssh)    PROTO="ssh"; shift ;;
    --url)    [ $# -ge 2 ] || die "--url needs a value"; URL="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    -*)       usage >&2; die "unknown option: $1" ;;
    *)        break ;;
  esac
done
[ $# -eq 1 ] || { usage >&2; exit 2; }
TARGET="$1"
[[ "$TARGET" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || die "target must look like OWNER/REPO: $TARGET"
if [ -z "$URL" ]; then
  if [ "$PROTO" = "ssh" ]; then URL="git@github.com:$TARGET.git"; else URL="https://github.com/$TARGET.git"; fi
fi

# Every branch name on the remote, one per line ("<sha><TAB>refs/heads/<name>" -> "<name>").
HEADS="$(git ls-remote --heads "$URL" | awk '{print substr($2, 12)}')" || die "could not read $URL"

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
    echo "deleted: $name"
  else
    echo "orphan:  $name"
  fi
done <<< "$HEADS"

if [ "$found" = 0 ]; then echo "no orphaned bites/* branches"
elif [ "$DELETE" = 0 ]; then echo "$found orphaned; run again with --delete to remove them"; fi
