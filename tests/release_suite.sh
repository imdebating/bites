#!/usr/bin/env bash
# release_suite.sh - create, configure and run the GitHub release tests for bites.
#
# usage: bash tests/release_suite.sh [options] [TRACK...]
#
# It builds the scratch repositories described in tests/RELEASE_TESTING.md (seeded content,
# branch protection, a ruleset), runs every scenario in that document against the real
# GitHub, checks the "Pass when" column, and prints the Results table to paste into the
# release pull request. Without TRACK arguments it runs all six tracks:
#
#   a  unprotected repository   S4 S1 S3 S13a S13b S12 S2
#   b  classic protection       S5 S8 S7
#   c  a ruleset                S6
#   d  classic, legacy branch   S9
#   e  default branch trunk     S10
#   f  empty repository         S11
#
# options:
#   --sha SHA        the commit of imdebating/bites under test (default: HEAD of this checkout,
#                    which must be pushed)
#   --public         create public repositories (private repositories may not allow branch
#                    protection on a free plan)
#   --setup-only     create and configure the repositories, run nothing, delete nothing
#   --teardown       delete the repositories of the given tracks, and stop
#   --keep           keep every repository, even after a pass
#   --skip-optional  leave out S4, S8, S10, S11 (tracks e and f, and those steps)
#   --allow-dirty    do not stop for uncommitted changes in the code under test (the suite
#                    then tests whatever is checked out, which the action does not run)
#   --timeout SECS   how long to wait for one Actions run (default 300)
#   --results FILE   where to write the Results table (default release-test-results.md); the
#                    text git printed when it rejected a direct push to a protected branch is
#                    written next to it, in FILE with -rejections.txt in place of .md
#   -h, --help       this text
#
# Needs: git, gh (signed in; the repo and delete_repo scopes), python3, and a gh recent
# enough to have `gh run list --commit`. A repository whose scenarios all pass is deleted;
# one with a failure is kept so you can look at it. Exit status: 0 all passed, 1 a failure.
#
# The checks use exit statuses and what is on GitHub afterwards, not the wording of
# bootstrap's messages, so a change to the strings catalog does not break them.
set -uo pipefail

readonly PREFIX=bites-scratch
ACTION_REPO=${ACTION_REPO:-imdebating/bites}
GIT_BASE=${GIT_BASE:-https://github.com/}
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BOOT=${BITES_BOOTSTRAP_SCRIPT:-$ROOT/scripts/bootstrap.sh}
BASH_BIN=$(command -v bash)

SHA="" VIS="" KEEP=0 SETUP_ONLY=0 TEARDOWN=0 SKIP_OPT=0 TIMEOUT=300 ALLOW_DIRTY=0
RESULTS_FILE=release-test-results.md TRACKS="" REJECT_FILE=""
OWNER="" WORK="" RESULTS="" FAILCOUNT=0 CUR="" FAILS="" NOTES="" RC=0 OUT="" PUSHED="" PROBE_OUT=""

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,/^set -uo/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; }
not() { ! "$@"; }

# ---------- results ----------
begin() { CUR=$1; FAILS=""; NOTES=""; say ""; say "== $1: $2"; }
assert() {
  local label=$1; shift
  if "$@" >/dev/null 2>&1; then say "  ok    $label"; else say "  FAIL  $label"; FAILS="$FAILS; $label"; fi
}
note() { say "  info  $*"; NOTES="$NOTES; $*"; }
add_result() {
  local note=${3//|/\\|}
  RESULTS="$RESULTS| $1 | $2 | $(date +%F) | ${note#; } |"$'\n'
}
finish() {
  local st=PASS n=${NOTES#; }
  if [ -n "$FAILS" ]; then
    st=FAIL; FAILCOUNT=$((FAILCOUNT + 1))
    n="failed: ${FAILS#; }${n:+; $n}"
  fi
  add_result "$CUR" "$st" "$n"
  say "  => $CUR $st"
}
skip() { add_result "$1" SKIP "$2"; say ""; say "== $1: skipped ($2)"; }

# ---------- GitHub and git helpers ----------
url() { printf '%s%s.git' "$GIT_BASE" "$1"; }
heads() { git ls-remote --heads "$(url "$1")" 2>/dev/null | sort; }
remote_sha() { git ls-remote "$(url "$1")" "refs/heads/$2" 2>/dev/null | cut -f1; }
has_branch() { [ -n "$(remote_sha "$1" "$2")" ]; }
file_exists() { gh api "repos/$1/contents/$3?ref=$2" >/dev/null 2>&1; }
file_sha() { gh api "repos/$1/contents/$3?ref=$2" --jq .sha 2>/dev/null; }
raw() { gh api -H 'Accept: application/vnd.github.raw+json' "repos/$1/contents/$3?ref=$2" 2>/dev/null; }
names_in() { gh api "repos/$1/contents/$3?ref=$2" --jq '.[].name' 2>/dev/null; }
pr_number() { gh pr list -R "$1" --state open --head "$2" --json number --jq '.[0].number // empty' 2>/dev/null; }
pr_files() { gh pr view "$2" -R "$1" --json files --jq '[.files[].path] | join(",")' 2>/dev/null; }
merge_pr() { gh pr merge "$2" -R "$1" --merge >/dev/null 2>&1; }
default_branch() { gh repo view "$1" --json defaultBranchRef --jq .defaultBranchRef.name 2>/dev/null; }
default_is() { [ "$(default_branch "$1")" = "$2" ]; }
parts_hash() {
  local b
  b=$(remote_sha "$1" bites/main)
  gh api "repos/$1/git/trees/$b?recursive=1" \
    --jq '[.tree[] | select(.path | startswith("parts/")) | .sha] | sort | join(",")' 2>/dev/null
}

PYFIND='
import json, sys
key = sys.argv[1]
def find(o):
    if isinstance(o, dict):
        if key in o:
            return o[key]
        for v in o.values():
            r = find(v)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = find(v)
            if r is not None:
                return r
    return None
try:
    r = find(json.load(sys.stdin))
except ValueError:
    r = None
print("" if r is None else r)
'
json_find() { python3 -c "$PYFIND" "$1"; }
last_build() { raw "$1" bites/main last_build.json | json_find "$2"; }
manifest_val() { raw "$1" bites/main manifest.json | json_find "$2"; }

parts_expected() { echo $(( ($1 + $2 - 1) / $2 )); }

# parts_ok REPO FILE MAX: the file on main is split into the right number of part files.
parts_ok() {
  local size n names count want
  size=$(raw "$1" main "$2" | wc -m | tr -d ' ')
  n=$(parts_expected "$size" "$3")
  [ "$n" -ge 2 ] || return 1
  names=$(names_in "$1" bites/main "parts/$2") || return 1
  count=$(printf '%s\n' "$names" | grep -c .)
  [ "$count" -eq "$n" ] || return 1
  want=$(printf -- '-of-%04d.txt' "$n")
  [ "$(printf '%s\n' "$names" | grep -c -- "$want\$")" -eq "$n" ]
}

# wait_run REPO SHA SECS: print the conclusion of the run for that commit, or none.
# An empty SHA never matches a run, so a push that did not happen cannot borrow another run.
wait_run() {
  local t=0 line
  [ -n "$2" ] || { echo none; return 1; }
  while [ "$t" -lt "$3" ]; do
    line=$(gh run list -R "$1" --commit "$2" --limit 5 --json status,conclusion \
      --jq '.[0] | "\(.status) \(.conclusion)"' 2>/dev/null || true)
    case $line in
      "completed "*) echo "${line#completed }"; return 0 ;;
    esac
    sleep 8; t=$((t + 8))
  done
  echo none; return 1
}

# wait_delete_run REPO SECS: print "ID CONCLUSION" of the latest delete-event run once it is
# complete, or "none none". A run that is still going has no conclusion yet.
wait_delete_run() {
  local t=0 line
  while [ "$t" -lt "$2" ]; do
    line=$(gh run list -R "$1" --event delete --limit 1 --json databaseId,status,conclusion \
      --jq '.[0] | "\(.databaseId) \(.status) \(.conclusion)"' 2>/dev/null || true)
    case $line in
      *" completed "*) echo "${line%% *} ${line##* }"; return 0 ;;
    esac
    sleep 6; t=$((t + 6))
  done
  echo "none none"; return 1
}

# poll SECS COMMAND...: run the command until it succeeds or the time is up.
poll() {
  local secs=$1 t=0; shift
  while [ "$t" -lt "$secs" ]; do
    if "$@" >/dev/null 2>&1; then return 0; fi
    sleep 6; t=$((t + 6))
  done
  return 1
}

settle() {  # wait for the runs that bootstrap's own pushes started
  local r=$1 b; shift
  for b in "$@"; do wait_run "$r" "$(remote_sha "$r" "$b")" 150 >/dev/null || true; done
}

clone_to() {
  rm -rf "$2"
  git clone --quiet "$(url "$1")" "$2" \
    && git -C "$2" config user.name "bites release test" \
    && git -C "$2" config user.email "release-test@example.com"
}
sync_clone() { git -C "$1" pull --quiet --rebase origin "$2"; }
push_commit() {  # DIR MESSAGE BRANCH; sets PUSHED to the pushed commit, or to nothing on failure
  PUSHED=""
  git -C "$1" add -A && git -C "$1" commit --quiet -m "$2" \
    && git -C "$1" push --quiet origin "HEAD:refs/heads/$3" \
    && PUSHED=$(git -C "$1" rev-parse HEAD)
}

# probe_push REPO LABEL: try an empty direct push to main; it must be rejected. What git
# printed goes to PROBE_OUT and is appended to the rejections file.
probe_push() {
  local d=$WORK/probe-$2 rc
  clone_to "$1" "$d" || return 1
  git -C "$d" commit --quiet --allow-empty -m "probe: a direct push must be rejected"
  PROBE_OUT=$(git -C "$d" push origin HEAD:refs/heads/main 2>&1); rc=$?
  printf '## %s (%s)\n%s\n\n' "$2" "$1" "$PROBE_OUT" >> "$REJECT_FILE"
  [ "$rc" -ne 0 ]
}

show_out() { printf '%s\n' "$OUT" | sed 's/^/    | /'; }
run_raw() { OUT=$("$@" 2>&1); RC=$?; show_out; }
boot() { run_raw "$BASH_BIN" "$BOOT" "$@"; }

# ---------- creating and configuring the repositories ----------
safe_repo() { case $1 in */"$PREFIX"-?) return 0 ;; esac; return 1; }

delete_repo() {
  safe_repo "$1" || die "refusing to delete $1"
  if gh repo view "$1" >/dev/null 2>&1; then
    gh repo delete "$1" --yes >/dev/null 2>&1 || { say "  cannot delete $1 (gh auth refresh -s delete_repo)"; return 1; }
    sleep 3
  fi
}

protect_classic() {  # REPO BRANCH
  gh api -X PUT "repos/$1/branches/$2/protection" --input - >/dev/null <<'JSON' \
    || { say "  cannot protect $2: private repositories may need a paid plan; try --public"; return 1; }
{"required_status_checks":null,"enforce_admins":true,"required_pull_request_reviews":{"required_approving_review_count":0},"restrictions":null}
JSON
  [ "$(gh api "repos/$1/branches/$2/protection" --jq .enforce_admins.enabled 2>/dev/null)" = true ]
}

ruleset_pr() {  # REPO
  gh api -X POST "repos/$1/rulesets" --input - >/dev/null <<'JSON' \
    || { say "  cannot create the ruleset: private repositories may need a paid plan; try --public"; return 1; }
{"name":"bites-scratch-require-pr","target":"branch","enforcement":"active","bypass_actors":[],
 "conditions":{"ref_name":{"include":["~DEFAULT_BRANCH"],"exclude":[]}},
 "rules":[{"type":"pull_request","parameters":{"dismiss_stale_reviews_on_push":false,
   "require_code_owner_review":false,"require_last_push_approval":false,
   "required_approving_review_count":0,"required_review_thread_resolution":false}}]}
JSON
  [ "$(gh api "repos/$1/rules/branches/main" --jq length 2>/dev/null || echo 0)" -ge 1 ]
}

setup_track() {
  local t=$1 r=$OWNER/$PREFIX-$1 want=main
  say ""; say "## setup $r"
  delete_repo "$r" || return 1
  case $t in
    e) bash "$ROOT/tests/scratch_repo.sh" $VIS --default-branch trunk "$PREFIX-$t"; want=trunk ;;
    f) bash "$ROOT/tests/scratch_repo.sh" $VIS --empty "$PREFIX-$t"; want="" ;;
    *) bash "$ROOT/tests/scratch_repo.sh" $VIS "$PREFIX-$t" ;;
  esac >/dev/null || { say "  cannot create $r"; return 1; }
  if [ -n "$want" ] && ! poll 30 default_is "$r" "$want"; then
    say "  setup failed: the default branch of $r is $(default_branch "$r"), not $want"
    return 1
  fi
  case $t in
    b) protect_classic "$r" main && protect_classic "$r" dev ;;
    c) ruleset_pr "$r" ;;
    d) protect_classic "$r" main ;;
  esac || return 1
  say "  ready: https://github.com/$r"
}

# ---------- the scenarios ----------
track_a() {
  local r=$OWNER/$PREFIX-a d=$WORK/a h0 sha c base id concl
  if [ "$SKIP_OPT" = 0 ]; then
    begin S4 "dry run changes nothing"
    h0=$(heads "$r")
    boot --dry-run -v "$SHA" "$r" main
    assert "exit 0" [ "$RC" -eq 0 ]
    assert "no branch changed" [ "$(heads "$r")" = "$h0" ]
    finish
  else skip S4 "optional"; fi

  begin S1 "first install, then a build"
  boot -v "$SHA" "$r"
  assert "exit 0" [ "$RC" -eq 0 ]
  assert "workflow on main" file_exists "$r" main .github/workflows/bites.yml
  assert "bites/main exists" has_branch "$r" bites/main
  sha=$(remote_sha "$r" main)
  c=$(wait_run "$r" "$sha" 90) || true
  note "bootstrap's own push started a run: $c"
  if clone_to "$r" "$d"; then
    printf 'line 9999: appended by the release test\n' >> "$d/docs/big.md"
    assert "pushed the appended line" push_commit "$d" "Append a line" main
    c=$(wait_run "$r" "$PUSHED" "$TIMEOUT") || true
    assert "run succeeded ($c)" [ "$c" = success ]
  else assert "clone" false; fi
  assert "manifest.json on bites/main" file_exists "$r" bites/main manifest.json
  assert "last_build status ok" [ "$(last_build "$r" status)" = ok ]
  assert "big.md in the right number of parts" parts_ok "$r" docs/big.md 27000
  finish

  begin S3 "several branches, then again, then --all-branches"
  boot -v "$SHA" "$r" main dev feature/x
  assert "exit 0" [ "$RC" -eq 0 ]
  assert "bites/dev exists" has_branch "$r" bites/dev
  assert "bites/feature/x exists" has_branch "$r" bites/feature/x
  assert "workflow on dev" file_exists "$r" dev .github/workflows/bites.yml
  assert "workflow on feature/x" file_exists "$r" feature/x .github/workflows/bites.yml
  settle "$r" main dev feature/x
  h0=$(heads "$r")
  boot -v "$SHA" "$r" main dev feature/x
  assert "second run exit 0" [ "$RC" -eq 0 ]
  assert "second run changed nothing" [ "$(heads "$r")" = "$h0" ]
  boot -a -v "$SHA" "$r"
  assert "--all-branches exit 0" [ "$RC" -eq 0 ]
  assert "--all-branches changed nothing" [ "$(heads "$r")" = "$h0" ]
  finish

  begin S13a "a valid patch is applied"
  sync_clone "$d" main
  base=$(git -C "$d" rev-parse HEAD:docs/big.md | cut -c1-12)
  mkdir -p "$d/.bites-patches"
  printf '@@@ FILE docs/big.md\n@@@ BASE %s\n@@@ FIND\nline 0500: the quick brown fox jumps over the lazy dog 0123\n@@@ REPLACE\nline 0500: patched by the release test\n@@@ END\n' \
    "$base" > "$d/.bites-patches/01-test.patch"
  assert "pushed the patch" push_commit "$d" "Test patch" main
  c=$(wait_run "$r" "$PUSHED" "$TIMEOUT") || true
  assert "run succeeded ($c)" [ "$c" = success ]
  sync_clone "$d" main
  assert "line 500 changed" grep -q 'line 0500: patched by the release test' "$d/docs/big.md"
  assert "patch file removed" [ ! -e "$d/.bites-patches/01-test.patch" ]
  OUT=$(git -C "$d" log --format='%an|%s' -n 6)
  assert "bites: apply patches by github-actions[bot]" grep -qxF 'github-actions[bot]|bites: apply patches' <<<"$OUT"
  assert "last_build status ok" [ "$(last_build "$r" status)" = ok ]
  finish

  begin S13b "a patch with a wrong BASE fails safely"
  h0=$(parts_hash "$r")
  mkdir -p "$d/.bites-patches"
  printf '@@@ FILE docs/big.md\n@@@ BASE 000000000000\n@@@ FIND\nline 0501: the quick brown fox jumps over the lazy dog 0123\n@@@ REPLACE\nline 0501: never applied\n@@@ END\n' \
    > "$d/.bites-patches/02-bad.patch"
  assert "pushed the bad patch" push_commit "$d" "Bad patch" main
  c=$(wait_run "$r" "$PUSHED" "$TIMEOUT") || true
  assert "run failed ($c)" [ "$c" = failure ]
  assert "last_build status error" [ "$(last_build "$r" status)" = error ]
  assert "last_build stage apply" [ "$(last_build "$r" stage)" = apply ]
  assert "parts unchanged" [ "$(parts_hash "$r")" = "$h0" ]
  git -C "$d" rm --quiet -f .bites-patches/02-bad.patch
  assert "pushed the removal of the bad patch" push_commit "$d" "Remove the bad patch" main
  c=$(wait_run "$r" "$PUSHED" "$TIMEOUT") || true
  assert "next run succeeded ($c)" [ "$c" = success ]
  assert "last_build status ok again" [ "$(last_build "$r" status)" = ok ]
  finish

  begin S12 "deleting a branch deletes its output branch"
  gh api -X DELETE "repos/$r/git/refs/heads/dev" >/dev/null 2>&1
  assert "bites/dev removed" poll 240 not has_branch "$r" bites/dev
  assert "bites/main remains" has_branch "$r" bites/main
  assert "bites/feature/x remains" has_branch "$r" bites/feature/x
  read -r id concl <<<"$(wait_delete_run "$r" 120)"
  note "delete run: $id ($concl)"
  assert "the cleanup run succeeded" [ "$concl" = success ]
  finish

  begin S2 "settings in the workflow, and not losing them"
  settle "$r" main
  boot -v "$SHA" -c max_chars=15000 -c read_cap=20000 "$r" main
  assert "exit 0" [ "$RC" -eq 0 ]
  assert "workflow has 15000" grep -q 15000 <<<"$(raw "$r" main .github/workflows/bites.yml)"
  assert "workflow has 20000" grep -q 20000 <<<"$(raw "$r" main .github/workflows/bites.yml)"
  sync_clone "$d" main
  printf 'line 9998: appended for S2\n' >> "$d/docs/big.md"
  assert "pushed the appended line" push_commit "$d" "Append a line for S2" main
  c=$(wait_run "$r" "$PUSHED" "$TIMEOUT") || true
  assert "run succeeded ($c)" [ "$c" = success ]
  assert "manifest max_chars is 15000" [ "$(manifest_val "$r" max_chars)" = 15000 ]
  assert "big.md in the right number of parts" parts_ok "$r" docs/big.md 15000
  h0=$(file_sha "$r" main .github/workflows/bites.yml)
  boot -v "$SHA" "$r" main
  assert "without -c: exit 1" [ "$RC" -eq 1 ]
  assert "without -c: workflow unchanged" [ "$(file_sha "$r" main .github/workflows/bites.yml)" = "$h0" ]
  finish
}

track_b() {
  local r=$OWNER/$PREFIX-b nm nd hide
  begin S5 "protected branches: failure without -p, pull requests with -p"
  assert "a direct push to main is rejected" probe_push "$r" classic
  if grep -q GH006 <<<"$PROBE_OUT"; then note "git's own output has GH006 (saved in $REJECT_FILE)"
  else note "GH006 not in git's own output (saved in $REJECT_FILE)"; fi
  boot -v "$SHA" "$r" main dev
  assert "without -p: exit 1" [ "$RC" -eq 1 ]
  assert "without -p: the output names --protected" grep -q -- '--protected' <<<"$OUT"
  assert "bites/main created" has_branch "$r" bites/main
  assert "bites/dev created" has_branch "$r" bites/dev
  assert "no workflow on main" not file_exists "$r" main .github/workflows/bites.yml
  assert "no workflow on dev" not file_exists "$r" dev .github/workflows/bites.yml
  boot -p -v "$SHA" "$r" main dev
  assert "with -p: exit 3" [ "$RC" -eq 3 ]
  nm=$(pr_number "$r" bites-setup/main); nd=$(pr_number "$r" bites-setup/dev)
  assert "pull request for main" [ -n "$nm" ]
  assert "pull request for dev" [ -n "$nd" ]
  assert "main's pull request changes only the workflow" [ "$(pr_files "$r" "$nm")" = .github/workflows/bites.yml ]
  assert "dev's pull request changes only the workflow" [ "$(pr_files "$r" "$nd")" = .github/workflows/bites.yml ]
  finish

  if [ "$SKIP_OPT" = 0 ]; then
    begin S8 "no usable gh: the link is printed and the status is pending"
    mkdir -p "$WORK/nogh" && ln -sf "$(command -v git)" "$WORK/nogh/git"
    hide="$WORK/nogh:/usr/bin:/bin"
    if PATH=$hide command -v gh >/dev/null 2>&1; then
      note "gh is in /usr/bin on this machine, so it cannot be hidden"
      assert "gh could be hidden" false
    else
      run_raw env PATH="$hide" "$BASH_BIN" "$BOOT" -p -v "$SHA" "$r" main dev
      assert "gh missing: exit 3" [ "$RC" -eq 3 ]
      assert "gh missing: a github.com link is printed" grep -q 'https://github.com/' <<<"$OUT"
    fi
    run_raw env GH_TOKEN=invalid "$BASH_BIN" "$BOOT" -p -v "$SHA" "$r" main dev
    assert "gh failing: exit 3" [ "$RC" -eq 3 ]
    finish
  else skip S8 "optional"; fi

  begin S7 "merging the pull requests, one at a time"
  nm=$(pr_number "$r" bites-setup/main); nd=$(pr_number "$r" bites-setup/dev)
  assert "merge main's pull request" merge_pr "$r" "$nm"
  sleep 3
  boot -p -v "$SHA" "$r" main dev
  assert "after one merge: exit 3" [ "$RC" -eq 3 ]
  assert "workflow now on main" file_exists "$r" main .github/workflows/bites.yml
  assert "merge dev's pull request" merge_pr "$r" "$nd"
  sleep 3
  boot -p -v "$SHA" "$r" main dev
  assert "after both merges: exit 0" [ "$RC" -eq 0 ]
  assert "workflow now on dev" file_exists "$r" dev .github/workflows/bites.yml
  finish
}

track_c() {
  local r=$OWNER/$PREFIX-c n
  begin S6 "a ruleset instead of classic protection"
  assert "a direct push to main is rejected" probe_push "$r" ruleset
  if grep -q GH013 <<<"$PROBE_OUT"; then note "git's own output has GH013 (saved in $REJECT_FILE)"
  else note "GH013 not in git's own output (saved in $REJECT_FILE)"; fi
  boot -v "$SHA" "$r"
  assert "without -p: exit 1" [ "$RC" -eq 1 ]
  boot -p -v "$SHA" "$r"
  assert "with -p: exit 3" [ "$RC" -eq 3 ]
  n=$(pr_number "$r" bites-setup/main)
  assert "pull request opened" [ -n "$n" ]
  assert "pull request changes only the workflow" [ "$(pr_files "$r" "$n")" = .github/workflows/bites.yml ]
  assert "merge it" merge_pr "$r" "$n"
  sleep 3
  boot -p -v "$SHA" "$r"
  assert "after the merge: exit 0" [ "$RC" -eq 0 ]
  finish
}

track_d() {
  local r=$OWNER/$PREFIX-d wt=$WORK/v140 n
  begin S9 "moving from the 1.4.0 single setup branch"
  git -C "$ROOT" fetch --quiet --tags origin >/dev/null 2>&1 || true
  if ! git -C "$ROOT" worktree add --detach --quiet "$wt" v1.4.0 >/dev/null 2>&1; then
    FAILS=""; NOTES=""; skip S9 "tag v1.4.0 not available"; return 0
  fi
  run_raw "$BASH_BIN" "$wt/scripts/bootstrap.sh" --pr "$r"
  assert "1.4.0 left the flat bites-setup branch" has_branch "$r" bites-setup
  boot -p -v "$SHA" "$r"
  assert "exit 3" [ "$RC" -eq 3 ]
  assert "old branch bites-setup is gone" not has_branch "$r" bites-setup
  assert "bites-setup/main exists" has_branch "$r" bites-setup/main
  n=$(pr_number "$r" bites-setup/main)
  assert "a pull request is open from bites-setup/main" [ -n "$n" ]
  note "the old pull request is now: $(gh pr list -R "$r" --state all --head bites-setup --json state --jq '.[0].state' 2>/dev/null)"
  git -C "$ROOT" worktree remove --force "$wt" >/dev/null 2>&1; git -C "$ROOT" worktree prune
  finish
}

track_e() {
  local r=$OWNER/$PREFIX-e
  begin S10 "a default branch that is not main"
  assert "the default branch is trunk" default_is "$r" trunk
  boot -v "$SHA" "$r"
  assert "exit 0" [ "$RC" -eq 0 ]
  assert "workflow on trunk" file_exists "$r" trunk .github/workflows/bites.yml
  assert "bites/trunk exists" has_branch "$r" bites/trunk
  assert "no bites/main" not has_branch "$r" bites/main
  finish
}

track_f() {
  local r=$OWNER/$PREFIX-f
  begin S11 "an empty repository"
  boot -v "$SHA" "$r"
  assert "exit 1" [ "$RC" -eq 1 ]
  assert "nothing was created" [ -z "$(heads "$r")" ]
  finish
}

# ---------- driver ----------
preflight() {
  command -v git >/dev/null 2>&1 || die "git is not installed"
  command -v python3 >/dev/null 2>&1 || die "python3 is not installed"
  command -v gh >/dev/null 2>&1 || die "gh is not installed (https://cli.github.com)"
  OWNER=$(gh api user --jq .login 2>/dev/null) || die "gh is not signed in: run gh auth login"
  local scopes
  scopes=$(gh api -i user 2>/dev/null | grep -i '^x-oauth-scopes:' || true)
  if [ -n "$scopes" ]; then
    case $scopes in *delete_repo*) ;; *) die "gh lacks the delete_repo scope: gh auth refresh -s delete_repo" ;; esac
  fi
  [ "$TEARDOWN" = 1 ] && return 0
  [ "$SETUP_ONLY" = 1 ] && return 0
  [ -n "$SHA" ] || SHA=$(git -C "$ROOT" rev-parse HEAD)
  case $SHA in [0-9a-f]*) ;; *) die "--sha must be a full commit SHA" ;; esac
  [ "${#SHA}" -eq 40 ] || die "--sha must be a full 40-character commit SHA"
  gh api "repos/$ACTION_REPO/commits/$SHA" --jq .sha >/dev/null 2>&1 \
    || die "$SHA is not on GitHub in $ACTION_REPO: push the branch first"
  if [ "$(gh api "repos/$ACTION_REPO" --jq .private 2>/dev/null)" = true ]; then
    say "note: $ACTION_REPO is private; its Settings > Actions > General > Access must allow your other repositories"
  fi
  if [ "$ALLOW_DIRTY" = 0 ]; then
    [ -z "$(git -C "$ROOT" status --porcelain --untracked-files=no -- \
      scripts action.yml cleanup bites_tool templates bites.toml VERSION)" ] \
      || die "uncommitted changes in the code under test (scripts, action.yml, cleanup, bites_tool, templates, bites.toml, VERSION): commit and push them, or use --allow-dirty"
  fi
}

parse_args() {
  while [ $# -gt 0 ]; do
    case $1 in
      --sha) [ $# -ge 2 ] || die "--sha needs a value"; SHA=$2; shift 2 ;;
      --public) VIS=--public; shift ;;
      --setup-only) SETUP_ONLY=1; shift ;;
      --teardown) TEARDOWN=1; shift ;;
      --keep) KEEP=1; shift ;;
      --allow-dirty) ALLOW_DIRTY=1; shift ;;
      --skip-optional) SKIP_OPT=1; shift ;;
      --timeout) [ $# -ge 2 ] || die "--timeout needs a value"; TIMEOUT=$2; shift 2 ;;
      --results) [ $# -ge 2 ] || die "--results needs a file"; RESULTS_FILE=$2; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      -*) die "unknown option: $1" ;;
      [a-f]) TRACKS="$TRACKS $1"; shift ;;
      *) die "unknown track: $1 (use a, b, c, d, e or f)" ;;
    esac
  done
  if [ -z "$TRACKS" ]; then
    if [ "$SKIP_OPT" = 1 ]; then TRACKS="a b c d"; else TRACKS="a b c d e f"; fi
  fi
}

report() {
  local head table
  head=$(printf 'Tested commit: %s\nGitHub account: %s\ngh: %s\n' "$SHA" "$OWNER" "$(gh --version | head -n1)")
  table=$(printf '| # | Result | Date | Notes |\n|---|---|---|---|\n%s' "$RESULTS")
  say ""; say "$head"; say ""; say "$table"
  printf '%s\n\n%s\n' "$head" "$table" > "$RESULTS_FILE"
  say ""; say "Results written to $RESULTS_FILE"
  if [ -s "$REJECT_FILE" ]; then say "What git printed for rejected pushes is in $REJECT_FILE"; fi
}

main() {
  local t before r
  parse_args "$@"
  preflight
  WORK=$(mktemp -d)
  trap 'rm -rf "$WORK"' EXIT
  if [ "$TEARDOWN" = 1 ]; then
    for t in $TRACKS; do delete_repo "$OWNER/$PREFIX-$t" && say "deleted $OWNER/$PREFIX-$t"; done
    exit 0
  fi
  REJECT_FILE=${RESULTS_FILE%.md}-rejections.txt
  [ "$SETUP_ONLY" = 1 ] || : > "$REJECT_FILE"
  for t in $TRACKS; do
    r=$OWNER/$PREFIX-$t
    if ! setup_track "$t"; then
      add_result "track $t" FAIL "setup failed"; FAILCOUNT=$((FAILCOUNT + 1)); continue
    fi
    [ "$SETUP_ONLY" = 1 ] && continue
    before=$FAILCOUNT
    "track_$t"
    if [ "$FAILCOUNT" -eq "$before" ] && [ "$KEEP" = 0 ]; then
      delete_repo "$r" && say "  deleted $r"
    else
      say "  kept $r: https://github.com/$r"
    fi
  done
  [ "$SETUP_ONLY" = 1 ] && exit 0
  report
  [ "$FAILCOUNT" -eq 0 ]
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then main "$@"; fi
