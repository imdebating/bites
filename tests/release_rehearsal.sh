#!/usr/bin/env bash
# release_rehearsal.sh - rehearse a release on a scratch repository first, to see that the release
# workflow and the steps you take by hand work on the real GitHub.
#
# usage: bash tests/release_rehearsal.sh [options]
#
# It copies the committed code (HEAD of this checkout) into a new private repository named
# bites-scratch-release-<uuid>, turns on immutable releases there, pushes the code to main, and lets the
# release workflow build the files for the number in VERSION. The workflow saves bootstrap.sh and
# bootstrap.sh.sha256 as an artifact and creates no release and no tag, and the rehearsal checks that.
# Then it does what a maintainer does by hand: downloads the artifact, creates a draft release with both
# files attached, publishes it, and creates the major tag. It checks what GitHub holds (the release
# published, immutable, titled, latest, with its two files, and the tags v<VERSION> and v<MAJOR> on the
# pushed commit), the downloaded bootstrap.sh (checksum, version, a dry run from an empty directory), and a
# second run of the workflow, which must change nothing. A repository whose checks all pass is deleted;
# one with a failure is kept so you can look at it. Nothing is ever pushed to, or published in, any
# repository but the scratch one.
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
REJECT_FILE="" VERSION="" MAJOR="" TAG="" R="" PUSHED="" RUN1="" REL_ID="" WANT_TITLE=""
ARTIFACT=bootstrap-release-candidate   # the name that .github/workflows/release.yml gives the saved files

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
artifact_names() { gh api "repos/$R/actions/runs/$1/artifacts" --jq '[.artifacts[].name] | sort | join(",")' 2>/dev/null; }  # RUN_ID
release_ids() { gh api --paginate "repos/$R/releases" --jq '.[].id' 2>/dev/null; }  # every release, drafts included
release_id() { gh api --paginate "repos/$R/releases" --jq ".[] | select(.tag_name == \"$TAG\") | .id" 2>/dev/null | head -n 1; }
release_field() { gh api "repos/$R/releases/$1" --jq "$2" 2>/dev/null; }  # ID JQ_FILTER: works for a draft too

# ---------- the repository ----------
# Restrict the sourced suite's deletion helper to this invocation's exact repository.
safe_repo() {
  [ -n "${REHEARSAL_REPO:-}" ] && [ "$1" = "$REHEARSAL_REPO" ] || return 1
  case "$1" in
    "$OWNER"/bites-scratch-release-*) return 0 ;;
    *) return 1 ;;
  esac
}

setup_scratch() {
  local err state attempt=0
  say ""; say "## setup $R"
  safe_repo "$R" || die "refusing to use $R"
  # Refuse a collision rather than deleting a repository to make room.
  bash "$ROOT/tests/scratch_repo.sh" $VIS --empty "${R#*/}" >/dev/null || { say "  cannot create $R"; return 1; }
  IMMON=0
  if [ "$IMM" = 1 ]; then
    if ! err=$(gh api -X PUT "repos/$R/immutable-releases" 2>&1); then
      say "  could not enable immutable releases on $R: $err"
      return 1
    fi
    # A successful PUT can precede a GET that reflects the new setting.
    while [ "$attempt" -lt 13 ]; do
      state=$(gh api "repos/$R/immutable-releases" --jq .enabled 2>&1)
      if [ "$state" = true ]; then IMMON=1; break; fi
      attempt=$((attempt + 1))
      [ "$attempt" -ge 13 ] || sleep 5
    done
    if [ "$IMMON" != 1 ]; then
      say "  immutable releases were not verified after 60 seconds on $R; last GET: $state"
      say "  setup stopped; use --no-immutable only for an explicitly mutable rehearsal"
      return 1
    fi
    note "immutable releases verified on $R"
  fi
  say "  ready: https://github.com/$R (immutable releases: $([ "$IMMON" = 1 ] && echo on || echo off))"
}

push_copy() {  # copy HEAD into a fresh repository and push it to main of the scratch repository
  local src=$WORK/src
  PUSHED=""
  mkdir -p "$src" && git -C "$ROOT" archive HEAD | tar -x -C "$src" || return 1
  rm -f "$src/.github/workflows/bites.yml"   # the installed caller workflow uses the real action
  WANT_TITLE="$TAG - rehearsal"
  git -C "$src" init --quiet -b main || return 1
  git -C "$src" add -A \
    && git -C "$src" -c user.name="bites rehearsal" -c user.email="rehearsal@example.com" commit --quiet -m "Rehearse the release of $TAG" \
    && git -C "$src" remote add origin "$(url "$R")" || return 1
  [ "$(git -C "$src" remote get-url origin)" = "$(url "$R")" ] || return 1
  git -C "$src" push --quiet origin main || return 1
  PUSHED=$(git -C "$src" rev-parse HEAD)
}

# ---------- the scenarios ----------
scenario_build() {
  local started=push t=0 id="" c=none
  begin R1 "the release workflow builds and saves the files, and publishes nothing"
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
  assert "it saved the artifact $ARTIFACT" [ "$(artifact_names "$id")" = "$ARTIFACT" ]
  assert "it created no release" [ -z "$(release_ids)" ]
  assert "it created no tag $TAG" [ -z "$(tag_sha "$TAG")" ]
  assert "it created no major tag $MAJOR" [ -z "$(tag_sha "$MAJOR")" ]
  finish
}

scenario_publish() {
  local dl=$WORK/candidate notes=$WORK/notes.md
  begin R2 "a maintainer creates and publishes the release by hand"
  mkdir -p "$dl"
  printf '%s\n\nThis release was made by tests/release_rehearsal.sh on a scratch repository.\n' "$WANT_TITLE" > "$notes"
  assert "downloaded the saved files" gh run download "$RUN1" -R "$R" -n "$ARTIFACT" -D "$dl"
  assert "the checksum matches" checksum_ok "$dl"
  assert "created a draft release with both files" gh release create "$TAG" "$dl/bootstrap.sh" "$dl/bootstrap.sh.sha256" \
    -R "$R" --draft --target "$PUSHED" --title "$WANT_TITLE" --notes-file "$notes"
  REL_ID=$(release_id)
  assert "the release is a draft" [ "$(release_field "$REL_ID" .draft)" = true ]
  assert "the draft has exactly bootstrap.sh and bootstrap.sh.sha256" \
    [ "$(release_field "$REL_ID" '[.assets[].name] | sort | join(",")')" = "bootstrap.sh,bootstrap.sh.sha256" ]
  assert "published the draft" gh api -X PATCH "repos/$R/releases/$REL_ID" -F draft=false -f make_latest=true
  assert "the release is published" [ "$(rel .draft)" = false ]
  assert "the title is $WANT_TITLE" [ "$(rel .name)" = "$WANT_TITLE" ]
  assert "it has exactly bootstrap.sh and bootstrap.sh.sha256" assets_are
  if [ "$IMMON" = 1 ]; then assert "the release is immutable" [ "$(rel .immutable)" = true ]; fi
  assert "the tag $TAG is on the pushed commit" [ "$(tag_sha "$TAG")" = "$PUSHED" ]
  assert "created the major tag $MAJOR" gh api -X POST "repos/$R/git/refs" -f ref="refs/tags/$MAJOR" -f sha="$PUSHED"
  assert "the major tag $MAJOR is on the pushed commit" [ "$(tag_sha "$MAJOR")" = "$PUSHED" ]
  assert "it is the latest release" [ "$(gh api "repos/$R/releases/latest" --jq .tag_name 2>/dev/null)" = "$TAG" ]
  finish
}

scenario_download() {
  local dl=$WORK/download empty=$WORK/empty
  begin R3 "what a user downloads"
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
  local id c
  begin R4 "running the workflow again changes nothing"
  gh workflow run release.yml -R "$R" --ref main >/dev/null 2>&1
  id=$(wait_new_run workflow_dispatch "$RUN1" 90)
  c=none
  [ -n "$id" ] && c=$(wait_conclusion "$id" "$TIMEOUT")
  assert "the second run succeeded ($c)" [ "$c" = success ]
  assert "it saved the artifact again" [ "$(artifact_names "$id")" = "$ARTIFACT" ]
  assert "the release is the same one" [ "$(rel .id)" = "$REL_ID" ]
  assert "there is still only one release" [ "$(release_ids | wc -l | tr -d ' ')" = 1 ]
  assert "it still has exactly the two files" assets_are
  assert "the tag is still on the pushed commit" [ "$(tag_sha "$TAG")" = "$PUSHED" ]
  assert "the major tag is still on the pushed commit" [ "$(tag_sha "$MAJOR")" = "$PUSHED" ]
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
  # Immutable-release reservations can survive deletion of a repository.
  # Keep the version unchanged and give each rehearsal its own repository namespace.
  R="$OWNER/bites-scratch-release-$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
  REHEARSAL_REPO=$R
  before=$FAILCOUNT
  scenario_build
  if [ -n "$RUN1" ] && [ "$(artifact_names "$RUN1")" = "$ARTIFACT" ]; then
    scenario_publish
  else
    skip R2 "the workflow saved no files"
  fi
  if [ "$(rel .draft)" = false ]; then
    scenario_download
    scenario_again
  else
    skip R3 "nothing was published"
    skip R4 "nothing was published"
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
