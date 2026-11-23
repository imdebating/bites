#!/usr/bin/env bash
# scratch_repo.sh - create or delete a disposable GitHub repository for testing a bites release.
#
# usage: bash tests/scratch_repo.sh [--public] [--empty] [--default-branch NAME] NAME
#        bash tests/scratch_repo.sh --delete NAME
#        bash tests/scratch_repo.sh --seed-only DIR
#
#   NAME                    The repository name. It must start with bites-scratch-, so this script
#                           can never create or delete anything else. The owner is the account that
#                           gh is signed in as.
#   --public                Create a public repository. The default is private.
#   --empty                 Create the repository with no commits at all.
#   --default-branch NAME   Make NAME the default branch (default main). The script reads the
#                           setting back and stops with an error if GitHub did not keep it.
#   --delete NAME           Delete the repository. It asks you to type the name first: either
#                           the bare name or OWNER/NAME is accepted.
#   --seed-only DIR         Write the seed content into the new directory DIR as a git repository,
#                           and touch nothing on GitHub. Use it to inspect what would be pushed.
#
# The seed content is the same every time:
#   main (or the default branch)  README.md, docs/small.md (6,000 characters) and docs/big.md
#                                 (60,000 characters, so 3 parts at the default max_chars)
#   dev                           main plus dev-only.txt
#   feature/x                     main plus feature.txt
# Every line of the two documents is 60 characters, numbered, and unique, so a patch can find it.
# Needs: git, and gh signed in with the repo scope (add delete_repo to use --delete).
set -euo pipefail

die() { echo "error: $*" >&2; exit 1; }

usage() { sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }

lines() {
  local n=$1 i=1
  while [ "$i" -le "$n" ]; do
    printf 'line %04d: the quick brown fox jumps over the lazy dog 0123\n' "$i"
    i=$((i + 1))
  done
}

seed() {
  local dir=$1 default=$2
  mkdir -p "$dir"
  git -C "$dir" init --quiet -b "$default"
  local g=(git -C "$dir" -c user.name="bites scratch" -c user.email="scratch@example.com")
  printf '# bites scratch repository\n\nDisposable. Created by tests/scratch_repo.sh.\n' > "$dir/README.md"
  mkdir -p "$dir/docs"
  lines 100 > "$dir/docs/small.md"
  lines 1000 > "$dir/docs/big.md"
  "${g[@]}" add -A
  "${g[@]}" commit --quiet -m "Seed the scratch repository"
  "${g[@]}" switch --quiet -c dev
  echo "only on dev" > "$dir/dev-only.txt"
  "${g[@]}" add -A
  "${g[@]}" commit --quiet -m "Add a dev-only file"
  "${g[@]}" switch --quiet "$default"
  "${g[@]}" switch --quiet -c feature/x
  echo "only on feature/x" > "$dir/feature.txt"
  "${g[@]}" add -A
  "${g[@]}" commit --quiet -m "Add a feature file"
  "${g[@]}" switch --quiet "$default"
}

vis=--private empty=0 default=main mode=create name="" seed_dir=""
while [ $# -gt 0 ]; do
  case $1 in
    --public) vis=--public; shift ;;
    --empty) empty=1; shift ;;
    --default-branch) [ $# -ge 2 ] || die "--default-branch needs a value"; default=$2; shift 2 ;;
    --delete) mode=delete; shift ;;
    --seed-only) mode=seed; [ $# -ge 2 ] || die "--seed-only needs a directory"; seed_dir=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    -*) die "unknown option: $1" ;;
    *) [ -z "$name" ] || die "give one repository name only"; name=$1; shift ;;
  esac
done

if [ "$mode" = seed ]; then
  [ -z "$name" ] || die "--seed-only takes a directory, not a repository name"
  if [ -e "$seed_dir" ] && [ -n "$(ls -A "$seed_dir" 2>/dev/null)" ]; then die "$seed_dir already has files in it"; fi
  seed "$seed_dir" "$default"
  echo "seeded $seed_dir"
  git -C "$seed_dir" branch --list
  exit 0
fi

[ -n "$name" ] || { usage >&2; exit 2; }
case $name in bites-scratch-*) ;; *) die "the name must start with bites-scratch-: $name" ;; esac
case $name in *[!A-Za-z0-9._-]*) die "the name may use only letters, digits, . _ and -: $name" ;; esac
command -v gh >/dev/null 2>&1 || die "gh is not installed (https://cli.github.com)"
owner=$(gh api user --jq .login) || die "gh is not signed in: run gh auth login"
full=$owner/$name

if [ "$mode" = delete ]; then
  gh repo view "$full" >/dev/null 2>&1 || die "$full does not exist"
  printf 'To delete %s, type its name (%s or %s): ' "$full" "$name" "$full"
  read -r answer
  [ "$answer" = "$name" ] || [ "$answer" = "$full" ] || die "not deleted: you typed '$answer', which is neither $name nor $full"
  gh repo delete "$full" --yes
  echo "deleted $full"
  exit 0
fi

if gh repo view "$full" >/dev/null 2>&1; then die "$full already exists"; fi
if [ "$empty" = 1 ]; then
  gh repo create "$full" "$vis"
  echo "created the empty repository $full"
  exit 0
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
seed "$work/repo" "$default"
gh repo create "$full" "$vis" --source "$work/repo" --remote origin

# Push the default branch alone first, so GitHub has one branch to choose from, then make sure
# GitHub's default branch is the one asked for. Pushing every branch at once left some
# repositories with dev as the default.
git -C "$work/repo" push --quiet origin "$default"
tries=0
while [ "$(gh repo view "$full" --json defaultBranchRef --jq .defaultBranchRef.name 2>/dev/null)" != "$default" ]; do
  tries=$((tries + 1))
  [ "$tries" -le 5 ] || die "the default branch of $full is not $default"
  gh repo edit "$full" --default-branch "$default" >/dev/null 2>&1 || true
  sleep 2
done
git -C "$work/repo" push --quiet origin dev feature/x

echo "created $full with the branches $default, dev and feature/x"
echo "next: scripts/bootstrap.sh -v \"\$(git rev-parse HEAD)\" $full"
