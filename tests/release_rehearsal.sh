#!/usr/bin/env bash
# release_rehearsal.sh - publish a release on a scratch repository first, to see that the release
# workflow works on the real GitHub.
#
# usage: bash tests/release_rehearsal.sh [options]
#
# It copies the committed code (HEAD of this checkout) into a new private repository named
# bites-scratch-g, turns on immutable releases there, pushes the code to main, and lets the
# release workflow publish the release for the number in VERSION. Then it checks what GitHub
# holds: the workflow run, the release (published, immutable, titled from the notes, latest),
# its two files, the tags v<VERSION> and v<MAJOR> on the pushed commit, the downloaded
# bootstrap.sh (checksum, version, a dry run from an empty directory), and a second run of the
# workflow, which must change nothing. A repository whose checks all pass is deleted; one with
# a failure is kept so you can look at it. Nothing is ever pushed to, or published in, any
# repository but the scratch one.
#
# If .github/release-notes/v<VERSION>.md is not committed yet, the copy gets a stand-in, so you
# can rehearse before the real notes exist.
#
# options:
#   --public         create a public repository (the default is private)
#   --no-immutable   leave immutable releases off, and skip the checks that need them
#   --keep           keep the repository even after a pass
#   --allow-dirty    do not stop for uncommitted changes (only the committed code is copied)
#   --timeout SECS   how long to wait for the workflow run (default 900)
#   --results FILE   where to write the Results table (default release-rehearsal-results.md)
#   -h, --help       this text
#
# Needs: git, gh (signed in; the repo, workflow and delete_repo scopes; admin on the scratch
# repository), python3 and tar. Exit status: 0 all passed, 1 a failure.
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=release_suite.sh
. "$HERE/release_suite.sh"   # the helper functions only: the suite runs when that file is run itself

usage() { sed -n '2,/^set -uo/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; }

KEEP=0 IMM=1 IMMON=0 ALLOW_DIRTY=0 TIMEOUT=900 VIS="" RESULTS_FILE=release-rehearsal-results.md
REJECT_FILE="" VERSION="" MAJOR="" TAG="" R="" PUSHED="" FAKE_NOTES=0 RUN1="" REL_ID="" WANT_TITLE=""

parse_args() {
  while [ $# -gt 0 ]; do
    case $1 in
      --public) VIS=--public; shift ;;
      --no-immutable) IMM=0; shift ;;
      --keep) KEEP=1; shift ;;
      --allow-dirty) ALLOW_DIRTY=1; shift ;;
      --timeout) [ $# -ge 2 ] || die "--timeout needs a value"; TIMEOUT=$2; shift 2 ;;
      --results) [ $# -ge 2 ] || die "--results needs a file"; RESULTS_FILE=$2; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown option: $1" ;;
    esac
  done
}

rehearsal_preflight() {
  local tool scopes
  for tool in git gh python3 tar; do command -v "$tool" >/dev/null 2>&1 || die "$tool is not installed"; done
  OWNER=$(gh api user --jq .login 2>/dev/null) || die "gh is not signed in: run gh auth login"
  scopes=$(gh api -i user 2>/dev/null | grep -i '^x-oauth-scopes:' || true)
  if [ -n "$scopes" ]; then
    case $scopes in *delete_repo*) ;; *) die "gh lacks the delete_repo scope: gh auth refresh -s delete_repo" ;; esac
    case $scopes in *workflow*) ;; *) die "gh lacks the workflow scope, which pushing .github/workflows needs: gh auth refresh -s workflow" ;; esac
  fi
  SHA=$(git -C "$ROOT" rev-parse HEAD) || die "this is not a git checkout"
  VERSION=$(git -C "$ROOT" show HEAD:VERSION 2>/dev/null | tr -d '[:space:]')
  [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "VERSION at HEAD must be a number such as 1.6.0, not '$VERSION'"
  MAJOR=v${VERSION%%.*}
  TAG=v$VERSION
  if [ "$ALLOW_DIRTY" = 0 ] && [ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]; then
    die "uncommitted changes: only the committed code is rehearsed, so commit them or use --allow-dirty"
  fi
}

# ---------- what GitHub holds ----------
rel() { gh api "repos/$R/releases/tags/$TAG" --jq "$1" 2>/dev/null; }
tag_sha() { git ls-remote --tags "$(url "$R")" "refs/tags/$1" 2>/dev/null | cut -f1; }
release_runs() {  # EVENT: the ids of the release workflow runs for that event, newest first
  gh run list -R "$R" --workflow release.yml --event "$1" --limit 10 --json databaseId --jq '.[].databaseId' 2>/dev/null
}
run_state() { gh run view "$1" -R "$R" --json status,conclusion --jq '"\(.status) \(.conclusion)"' 2>/dev/null; }
wait_conclusion() {  # ID SECS: print the conclusion once the run is complete, or none
  local t=0 line
  while [ "$t" -lt "$2" ]; do
    line=$(run_state "$1")
    case $line in "completed "*) echo "${line#completed }"; return 0 ;; esac
    sleep 10; t=$((t + 10))
  done
  echo none; return 1
}
wait_new_run() {  # EVENT KNOWN_ID SECS: print the id of a run of that event newer than KNOWN_ID, or nothing
  local t=0 id
  while [ "$t" -lt "$3" ]; do
    id=$(release_runs "$1" | head -n 1)
    if [ -n "$id" ] && [ "$id" != "$2" ]; then echo "$id"; return 0; fi
    sleep 5; t=$((t + 5))
  done
  return 1
}
checksum_ok() {  # DIR
  ( cd "$1" && if command -v sha256sum >/dev/null 2>&1; then sha256sum -c bootstrap.sh.sha256; else shasum -a 256 -c bootstrap.sh.sha256; fi )
}
assets_are() { [ "$(rel '[.assets[].name] | sort | join(",")')" = "bootstrap.sh,bootstrap.sh.sha256" ]; }

# ---------- the repository ----------
setup_scratch() {
  say ""; say "## setup $R"
  safe_repo "$R" || die "refusing to use $R"
  delete_repo "$R" || return 1
  bash "$ROOT/tests/scratch_repo.sh" $VIS --empty "$PREFIX-g" >/dev/null || { say "  cannot create $R"; return 1; }
  if [ "$IMM" = 1 ]; then
    if gh api -X PUT "repos/$R/immutable-releases" >/dev/null 2>&1 \
        && [ "$(gh api "repos/$R/immutable-releases" --jq .enabled 2>/dev/null)" = true ]; then
      IMMON=1
    else
      say "  could not turn on immutable releases (this needs admin on $R); going on without them"
    fi
  fi
  say "  ready: https://github.com/$R (immutable releases: $([ "$IMMON" = 1 ] && echo on || echo off))"
}

push_copy() {  # copy HEAD into a fresh repository and push it to main of the scratch repository
  local src=$WORK/src notes=.github/release-notes/$TAG.md
  PUSHED=""
  mkdir -p "$src" && git -C "$ROOT" archive HEAD | tar -x -C "$src" || return 1
  rm -f "$src/.github/workflows/bites.yml"   # the installed caller workflow uses the real action
  if [ ! -f "$src/$notes" ]; then
    mkdir -p "$src/.github/release-notes"
    printf '%s - rehearsal\n\nThis release was made by tests/release_rehearsal.sh on a scratch repository.\n' "$TAG" > "$src/$notes"
    FAKE_NOTES=1
  fi
  WANT_TITLE=$(head -n 1 "$src/$notes" | sed 's/^# *//')
  git -C "$src" init --quiet -b main || return 1
  git -C "$src" add -A \
    && git -C "$src" -c user.name="bites rehearsal" -c user.email="rehearsal@example.com" commit --quiet -m "Rehearse the release of $TAG" \
    && git -C "$src" remote add origin "$(url "$R")" || return 1
  [ "$(git -C "$src" remote get-url origin)" = "$(url "$R")" ] || return 1
  git -C "$src" push --quiet origin main || return 1
  PUSHED=$(git -C "$src" rev-parse HEAD)
}

# ---------- the scenarios ----------
scenario_publish() {
  local started=push t=0 id="" c=none
  begin R1 "the release workflow publishes the release"
  if ! setup_scratch || ! push_copy; then
    assert "the scratch repository is set up and the code is pushed" false
    finish
    return 0
  fi
  while [ "$t" -lt 90 ]; do   # the push itself starts the workflow when VERSION is in it
    id=$(release_runs push | head -n 1); [ -n "$id" ] && break
    sleep 5; t=$((t + 5))
  done
  if [ -z "$id" ]; then
    started=dispatch
    gh workflow run release.yml -R "$R" --ref main >/dev/null 2>&1
    id=$(wait_new_run workflow_dispatch "" 90)
  fi
  note "the run was started by the $started event: ${id:-none}"
  RUN1=$id
  [ -n "$id" ] && c=$(wait_conclusion "$id" "$TIMEOUT")
  assert "the workflow run succeeded ($c)" [ "$c" = success ]
  assert "the release exists and is published" [ "$(rel .draft)" = false ]
  REL_ID=$(rel .id)
  assert "the title is the first line of the notes" [ "$(rel .name)" = "$WANT_TITLE" ]
  [ "$FAKE_NOTES" = 1 ] && note "the notes were a stand-in: v$VERSION.md is not committed yet"
  assert "it has exactly bootstrap.sh and bootstrap.sh.sha256" assets_are
  if [ "$IMMON" = 1 ]; then assert "the release is immutable" [ "$(rel .immutable)" = true ]; fi
  assert "the tag $TAG is on the pushed commit" [ "$(tag_sha "$TAG")" = "$PUSHED" ]
  assert "the major tag $MAJOR is on the pushed commit" [ "$(tag_sha "$MAJOR")" = "$PUSHED" ]
  assert "it is the latest release" [ "$(gh api "repos/$R/releases/latest" --jq .tag_name 2>/dev/null)" = "$TAG" ]
  finish
}

scenario_download() {
  local dl=$WORK/download empty=$WORK/empty
  begin R2 "what a user downloads"
  mkdir -p "$dl" "$empty"
  assert "downloaded both files" gh release download "$TAG" -R "$R" -D "$dl"
  assert "the checksum matches" checksum_ok "$dl"
  assert "--version prints $VERSION" [ "$(bash "$dl/bootstrap.sh" --version 2>/dev/null | head -n 1)" = "bootstrap.sh $VERSION" ]
  cp "$dl/bootstrap.sh" "$empty/"
  OUT=$(cd "$empty" && "$BASH_BIN" bootstrap.sh -n --dry-run "$R" main 2>&1); RC=$?
  show_out
  assert "a dry run from an empty directory exits 0" [ "$RC" -eq 0 ]
  finish
}

scenario_again() {
  local id c log
  begin R3 "running the workflow again changes nothing"
  gh workflow run release.yml -R "$R" --ref main >/dev/null 2>&1
  id=$(wait_new_run workflow_dispatch "$RUN1" 90)
  c=none
  [ -n "$id" ] && c=$(wait_conclusion "$id" "$TIMEOUT")
  assert "the second run succeeded ($c)" [ "$c" = success ]
  log=$(gh run view "$id" -R "$R" --log 2>/dev/null)
  assert "it said the release was already published" grep -q 'already published' <<<"$log"
  assert "the release is the same one" [ "$(rel .id)" = "$REL_ID" ]
  assert "it still has exactly the two files" assets_are
  assert "the tag is still on the pushed commit" [ "$(tag_sha "$TAG")" = "$PUSHED" ]
  if [ "$IMMON" = 1 ]; then
    assert "a file cannot be replaced after publishing" not gh release upload "$TAG" -R "$R" "$WORK/download/bootstrap.sh.sha256" --clobber
  fi
  finish
}

main() {
  local before
  parse_args "$@"
  rehearsal_preflight
  WORK=$(mktemp -d)
  trap 'rm -rf "$WORK"' EXIT
  R=$OWNER/$PREFIX-g
  before=$FAILCOUNT
  scenario_publish
  if [ "$(rel .draft)" = false ]; then
    scenario_download
    scenario_again
  else
    skip R2 "nothing was published"
    skip R3 "nothing was published"
  fi
  if [ "$FAILCOUNT" -eq "$before" ] && [ "$KEEP" = 0 ]; then
    delete_repo "$R" && say "  deleted $R"
  else
    say "  kept $R: https://github.com/$R"
  fi
  report
  [ "$FAILCOUNT" -eq 0 ]
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then main "$@"; fi
