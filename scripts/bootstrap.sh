#!/usr/bin/env bash
# bootstrap.sh - set up bites in a repository with one command.
#
# usage: scripts/bootstrap.sh [options] OWNER/REPO [BRANCH ...]
#        scripts/bootstrap.sh [options] --all-branches OWNER/REPO
#
# The full help text (every option, what the script does in order, the exit statuses) and every
# message the script prints are in locales/strings.en.toml ([bootstrap]); scripts/strings.sh is
# generated from that file by scripts/gen_strings.py.
set -euo pipefail

# >>> release: files
# A checkout finds its two helper files next to it. The release build (scripts/build_bootstrap.py)
# replaces this block with their contents, so that the released script is one file.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=strings.sh
. "$HERE/strings.sh"
TEMPLATE="$HERE/../templates/bites.yml"
template_text() { cat "$TEMPLATE"; }
# <<< release: files

# text KEY [NAME=VALUE ...] gives the catalog text; say prints it. Every line of a message that
# note, warn or error_lines print carries the catalog prefix; die is error_lines, then exit 1.
text() { local key="$1"; shift; bites_fmt "bootstrap.$key" ${1+"$@"}; }
say() { printf '%s\n' "$(text "$@")"; }
usage() { say help; }
quote() { printf '%q' "$1"; }  # a value shown in a message, with invisible characters made visible
error_lines() { local line; while IFS= read -r line; do printf '%s\n' "$(text prefix_error message="$line")"; done <<< "$*"; }
die()  { error_lines "$*" >&2; exit 1; }
note() { local line; while IFS= read -r line; do printf '%s\n' "$(text prefix_note message="$line")"; done <<< "$*"; }
warn() { local line; while IFS= read -r line; do printf '%s\n' "$(text prefix_warning message="$line")" >&2; done <<< "$*"; }

# >>> release: version
# The one place the version lives is the VERSION file at the repository root. A script that was
# built for a release has the number written in by the build, so it needs no file.
VERSION="@@VERSION@@"
if [ "$VERSION" = "@@VERSION@@" ]; then
  VERSION="unknown"
  if [ -f "$HERE/../VERSION" ]; then
    version_text="$(tr -d '[:space:]' < "$HERE/../VERSION")"
    if [[ "$version_text" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then VERSION="$version_text"; fi
  fi
fi
# <<< release: version

# Split combined short options (-aps) into separate ones (-a -p -s). A value goes through
# untouched, and so does everything after "--".
EXPANDED=(); want_value=0; past_opts=0
for arg in "$@"; do
  if [ "$want_value" = 1 ] || [ "$past_opts" = 1 ]; then EXPANDED+=("$arg"); want_value=0; continue; fi
  case "$arg" in
    --)  past_opts=1; EXPANDED+=("$arg") ;;
    --workflow-version|--action-from|--config|--url|--action-url) want_value=1; EXPANDED+=("$arg") ;;
    --*) EXPANDED+=("$arg") ;;
    -[A-Za-z]*)
      letters="${arg#-}"; pos=0
      while [ "$pos" -lt "${#letters}" ]; do
        ch="${letters:$pos:1}"; pos=$((pos + 1)); EXPANDED+=("-$ch")
        case "$ch" in
          v|f|c)
            [ "$pos" -eq "${#letters}" ] || { qv="$(quote "$arg")"; die "$(text option_value_not_last letter="$ch" combination="$qv")"; }
            want_value=1 ;;
        esac
      done ;;
    *)   EXPANDED+=("$arg") ;;
  esac
done
set -- ${EXPANDED[@]+"${EXPANDED[@]}"}

SET_MAX=""; SET_CAP=""; SET_INC=(); SET_EXC=()
add_setting() { # add_setting KEY=VALUE - remember one --config option for the generated workflow
  local qv
  qv="$(quote "$1")"
  [[ "$1" == *=* ]] || die "$(text config_needs_key_value item="$qv")"
  local key="${1%%=*}" val="${1#*=}" qkey qval
  qkey="$(quote "$key")"; qval="$(quote "$val")"
  if [ -z "$val" ] || [[ "$val" =~ [[:space:]] ]] || [[ "$val" == *'${'* ]]; then
    die "$(text config_value_invalid key="$qkey" value="$qval")"
  fi
  case "$key" in
    max_chars|read_cap)
      [[ "$val" =~ ^[0-9]{1,9}$ ]] && [ "$((10#$val))" -ge 1 ] || die "$(text config_number_invalid key="$key" value="$qval")"
      if [ "$key" = max_chars ]; then SET_MAX="$((10#$val))"; else SET_CAP="$((10#$val))"; fi ;;
    include) SET_INC+=("$val") ;;
    exclude) SET_EXC+=("$val") ;;
    wrapper_chars|manifest_max_chars) die "$(text config_advanced_setting key="$key")" ;;
    *) die "$(text config_unknown_setting key="$qkey")" ;;
  esac
}
renamed() { # renamed OLD - stop with a pointer to the new name of a renamed option
  case "$1" in
    --ref)    die "$(text renamed_ref)" ;;
    --action) die "$(text renamed_action)" ;;
    --set)    die "$(text renamed_set)" ;;
    --pr)     die "$(text renamed_pr)" ;;
  esac
}

REF="v1"; ACTION="imdebating/bites"; PROTO="https"; URL=""; ACTION_URL=""; PREFLIGHT=1; PROT=0; DRY=0; ALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    -v|--workflow-version) [ $# -ge 2 ] || die "$(text option_needs_value option="$1")"; REF="$2"; shift 2 ;;
    -f|--action-from)      [ $# -ge 2 ] || die "$(text option_needs_value option="$1")"; ACTION="$2"; shift 2 ;;
    -c|--config)           [ $# -ge 2 ] || die "$(text config_option_needs_value option="$1")"; add_setting "$2"; shift 2 ;;
    --url)                 [ $# -ge 2 ] || die "$(text url_option_needs_value)"; URL="$2"; shift 2 ;;
    --action-url)          [ $# -ge 2 ] || die "$(text action_url_option_needs_value)"; ACTION_URL="$2"; shift 2 ;;
    -a|--all-branches)     ALL=1; shift ;;
    -n|--no-preflight)     PREFLIGHT=0; shift ;;
    -s|--ssh)              PROTO="ssh"; shift ;;
    -p|--protected)        PROT=1; shift ;;
    --dry-run)             DRY=1; shift ;;
    -V|--version)          say version_line version="$VERSION"; say version_hint; exit 0 ;;
    -h|--help)             usage; exit 0 ;;
    --ref|--action|--set|--pr) renamed "$1" ;;
    --)                    shift; break ;;
    -*)                    usage >&2; die "$(text unknown_option option="$1")" ;;
    *)                     break ;;
  esac
done
[ $# -ge 1 ] || { usage >&2; exit 2; }
TARGET="$1"; shift
BRANCHES=("$@")
if [ "$ALL" = 1 ] && [ ${#BRANCHES[@]} -gt 0 ]; then
  die "$(text all_branches_with_names)"
fi

# Validate everything that ends up in a URL, a sed expression, or a ref name. printf %q shows
# an invisible character (for example a non-breaking space pasted from a web page) as an
# escape sequence instead of letting it hide in the message.
re_repo='^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'
re_branch='^[A-Za-z0-9._/-]+$'
qv="$(quote "$TARGET")"; [[ "$TARGET" =~ $re_repo ]] || die "$(text target_invalid target="$qv")"
qv="$(quote "$ACTION")"; [[ "$ACTION" =~ $re_repo ]] || die "$(text action_from_invalid action="$qv")"
qv="$(quote "$REF")"; [[ "$REF" =~ ^[A-Za-z0-9._/-]+$ ]] || die "$(text workflow_version_invalid version="$qv")"
check_source_name() { # check_source_name NAME - stop unless NAME can be a source branch
  local qv
  qv="$(quote "$1")"
  [[ "$1" =~ $re_branch ]] || die "$(text branch_characters branch="$qv")"
  git check-ref-format --branch "$1" >/dev/null 2>&1 || die "$(text branch_invalid branch="$qv")"
  # The output branches and the setup branches are never source branches.
  case "$1" in bites/*|bites-setup|bites-setup/*) die "$(text branch_reserved branch="$qv")" ;; esac
}
for b in ${BRANCHES[@]+"${BRANCHES[@]}"}; do check_source_name "$b"; done

# The lines that --config adds under `with:` in the generated workflow (empty if none).
SETTINGS_BLOCK=""
if [ -n "$SET_MAX" ]; then SETTINGS_BLOCK+="          max-chars: $SET_MAX"$'\n'; fi
if [ -n "$SET_CAP" ]; then SETTINGS_BLOCK+="          read-cap: $SET_CAP"$'\n'; fi
if [ ${#SET_INC[@]} -gt 0 ]; then
  SETTINGS_BLOCK+="          include: |"$'\n'
  for g in "${SET_INC[@]}"; do SETTINGS_BLOCK+="            $g"$'\n'; done
fi
if [ ${#SET_EXC[@]} -gt 0 ]; then
  SETTINGS_BLOCK+="          exclude: |"$'\n'
  for g in "${SET_EXC[@]}"; do SETTINGS_BLOCK+="            $g"$'\n'; done
fi
SETTINGS_BLOCK="${SETTINGS_BLOCK%$'\n'}"

# >>> release: template check
TEMPLATE="$HERE/../templates/bites.yml"
[ -f "$TEMPLATE" ] || die "$(text template_missing template="$TEMPLATE")"
# <<< release: template check

# --url replaces the normal GitHub flow (the tests use it), so the preflight check, which
# talks to github.com, is skipped unless --action-url says where to look instead.
if [ -n "$URL" ] && [ -z "$ACTION_URL" ]; then PREFLIGHT=0; fi

if [ -z "$URL" ]; then
  if [ "$PROTO" = "ssh" ]; then URL="git@github.com:$TARGET.git"; else URL="https://github.com/$TARGET.git"; fi
fi

# ---- 0. preflight: can a workflow in another repository use the action? ---------------
# Warnings only. The check ignores the user's git configuration (credential helpers, URL
# rewrites, SSH keys), so it sees what an anonymous client sees: a private action
# repository fails it, which is exactly what makes workflows fail with "repository not
# found". `git ls-remote --exit-code` exits 2 when the repository is reachable but nothing
# matches, and 128 when it cannot be reached. A full commit SHA cannot be looked up by
# name, so for a SHA only reachability is checked.
preflight() {
  local url="${ACTION_URL:-https://github.com/$ACTION.git}" rc=0
  local -a patterns=()
  if [[ ! "$REF" =~ ^[0-9a-f]{40}$ ]]; then patterns=("refs/tags/$REF" "refs/heads/$REF"); fi
  HOME=/nonexistent XDG_CONFIG_HOME=/nonexistent GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
    GIT_TERMINAL_PROMPT=0 \
    git ls-remote --exit-code "$url" ${patterns[@]+"${patterns[@]}"} >/dev/null 2>&1 || rc=$?
  case "$rc" in
    0) ;;
    2) warn "$(text preflight_ref_missing action="$ACTION" version="$REF")" ;;
    *) warn "$(text preflight_unreachable action="$ACTION" target="$TARGET" url="$url")" ;;
  esac
}
if [ "$PREFLIGHT" = 1 ]; then preflight; fi

# ---- 1. clone and choose the branches ---------------------------------------------------
# Work in a throw-away clone so the caller's own checkouts are never touched.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
note "$(text cloning target="$TARGET")"
git clone --quiet "$URL" "$TMP/repo" || die "$(text clone_failed url="$URL")"
cd "$TMP/repo"

# The default branch is whatever the remote's HEAD points to; an empty repository has none.
DEFAULT="$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null || true)"
DEFAULT="${DEFAULT#origin/}"
[ -n "$DEFAULT" ] || die "$(text no_default_branch)"
check_source_name "$DEFAULT"

# Commits are made with the user's git identity if set, else a neutral one.
NAME="$(git config user.name || true)"; NAME="${NAME:-bites bootstrap}"
EMAIL="$(git config user.email || true)"; EMAIL="${EMAIL:-bites-bootstrap@users.noreply.github.com}"
ID=(-c "user.name=$NAME" -c "user.email=$EMAIL")

STATE="$TMP/state"; : > "$STATE"
# Progress of each piece of work, as KEY|STATE|DETAIL lines; the last line for a key wins.
set_state() { printf '%s|%s|%s\n' "$1" "$2" "$(printf '%s' "${3:-}" | tr '|\n' '/ ')" >> "$STATE"; }
state_of()  { awk -F'|' -v k="$1" '$1 == k { s = $2 } END { print s }' "$STATE"; }
detail_of() { awk -F'|' -v k="$1" '$1 == k { d = $3 } END { print d }' "$STATE"; }

push() { # push SRC DEST [OLD] - every write to the remote goes through here, so --dry-run is safe
  # OLD is only for the reserved bites-setup/* branches: replace one if it still points there.
  if [ "$DRY" = 1 ]; then say dry_run_push source="$1" destination="$2"; return 0; fi
  if [ -n "${3:-}" ]; then
    git push --quiet --force-with-lease="$2:$3" origin "$1:$2" 2>"$TMP/push.err"
  else
    git push --quiet origin "$1:$2" 2>"$TMP/push.err"
  fi
}
push_error() { grep -v '^[[:space:]]*$' "$TMP/push.err" 2>/dev/null | head -n 3 | tr '\n' ' ' || true; }
# True if the last push was refused because the branch is protected (GitHub reports branch
# protection as GH006 and repository rules as GH013, and both say a pull request is needed).
push_needs_pull_request() {
  grep -Eqi 'GH006|GH013|protected branch|through a pull request|repository rule' "$TMP/push.err" 2>/dev/null
}

# remote_has_branch BRANCH - exit status 0 if the remote has the branch, 1 if it does not.
# If the remote cannot be asked at all (network, credentials), say so and stop, instead of
# reporting the branch as missing. `git ls-remote --exit-code` exits 2 for "no match".
remote_has_branch() {
  local rc=0 qv detail
  git ls-remote --exit-code --heads origin "refs/heads/$1" >/dev/null 2>"$TMP/lsr.err" || rc=$?
  case "$rc" in
    0) return 0 ;;
    2) return 1 ;;
    *) qv="$(quote "$1")"; detail="$(head -n 1 "$TMP/lsr.err")"; die "$(text remote_branch_query_failed branch="$qv" status="$rc" detail="$detail")" ;;
  esac
}

SEL=()
in_sel() { local x; for x in ${SEL[@]+"${SEL[@]}"}; do if [ "$x" = "$1" ]; then return 0; fi; done; return 1; }
add_sel() { if ! in_sel "$1"; then SEL+=("$1"); fi; }

if [ "$ALL" = 1 ]; then
  rc=0
  heads="$(git ls-remote --heads origin 2>"$TMP/lsr.err")" || rc=$?
  [ "$rc" = 0 ] || { detail="$(head -n 1 "$TMP/lsr.err")"; die "$(text remote_branch_list_failed status="$rc" detail="$detail")"; }
  bad=""
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    case "$name" in bites/*|bites-setup|bites-setup/*) continue ;; esac
    if [[ "$name" =~ $re_branch ]] && git check-ref-format --branch "$name" >/dev/null 2>&1; then
      add_sel "$name"
    else
      bad+=" $(printf '%q' "$name")"
    fi
  done < <(printf '%s\n' "$heads" | sed -n 's#^[0-9a-f]\{40,64\}[[:space:]]\{1,\}refs/heads/##p')
  [ -z "$bad" ] || die "$(text all_branches_bad_names names="$bad")"
elif [ ${#BRANCHES[@]} -eq 0 ]; then
  add_sel "$DEFAULT"
else
  for b in "${BRANCHES[@]}"; do add_sel "$b"; done
fi

# Branches that get the caller workflow: the selected ones, and the default branch, because
# a delete event always runs the copy on the default branch (that is what runs the cleanup).
INSTALL=("${SEL[@]}")
if ! in_sel "$DEFAULT"; then INSTALL+=("$DEFAULT"); fi
note "$(text branches_to_set_up branches="${SEL[*]}")"
if ! in_sel "$DEFAULT"; then note "$(text default_branch_workflow_only default_branch="$DEFAULT")"; fi

# ---- 2. check everything before changing anything -----------------------------------------
# Fill the settings placeholder line (it disappears if there are no settings), then the
# action and version placeholders.
template_text | BLOCK="$SETTINGS_BLOCK" awk '/^__SETTINGS__$/ { if (ENVIRON["BLOCK"] != "") print ENVIRON["BLOCK"]; next } { print }' \
  | sed -e "s#__ACTION__#$ACTION#g" -e "s#__REF__#$REF#g" > "$TMP/bites.yml"
WF=".github/workflows/bites.yml"
SETTING_LINE='^[[:space:]]+(max-chars|read-cap|include|exclude):'

for b in "${SEL[@]}"; do
  remote_has_branch "$b" || { qv="$(quote "$b")"; die "$(text source_branch_missing branch="$qv")"; }
done

: > "$TMP/problems"
for b in "${INSTALL[@]}"; do
  if git cat-file -e "origin/$b:$WF" 2>/dev/null; then
    git show "origin/$b:$WF" > "$TMP/current.yml"
    if ! cmp -s "$TMP/bites.yml" "$TMP/current.yml"; then
      if ! grep -Eq '^name:[[:space:]]*bites[[:space:]]*$' "$TMP/current.yml"; then
        say problem_not_bites_workflow branch="$b" workflow_file="$WF" >> "$TMP/problems"
      elif grep -Eq "$SETTING_LINE" "$TMP/current.yml" && ! grep -Eq "$SETTING_LINE" "$TMP/bites.yml"; then
        say problem_settings_removed branch="$b" workflow_file="$WF" >> "$TMP/problems"
      fi
    fi
  fi
done
if [ -s "$TMP/problems" ]; then
  { error_lines "$(text setup_stopped)"; cat "$TMP/problems"; } >&2
  exit 1
fi

# ---- 3. the bites/<branch> output branches ------------------------------------------------
# `git mktree` with no input writes and prints the empty tree; a commit on it is an
# "orphan" root with no files, which is what the first build expects to find. They are made
# before the workflow, so the first run that the workflow's own push starts finds its mirror.
EMPTY="$(git mktree </dev/null)"
for b in "${SEL[@]}"; do
  if remote_has_branch "bites/$b"; then
    note "$(text output_branch_exists branch="bites/$b")"
    set_state "output:$b" present ""
  else
    c="$(git "${ID[@]}" commit-tree "$EMPTY" -m "$(text output_branch_init_commit)")"
    note "$(text output_branch_creating branch="bites/$b")"
    if push "$c" "refs/heads/bites/$b"; then
      if [ "$DRY" = 1 ]; then set_state "output:$b" planned ""; else set_state "output:$b" created ""; fi
    elif remote_has_branch "bites/$b"; then
      set_state "output:$b" present "$(text output_branch_created_elsewhere branch="bites/$b")"
    else
      set_state "output:$b" failed "$(text output_branch_create_failed branch="bites/$b") $(push_error)"
    fi
  fi
done

# ---- 4. the caller workflow on each branch ---------------------------------------------------
# setup_branch_is_exact BRANCH SETUP - true if merging origin/SETUP into origin/BRANCH would change
# exactly one file, the generated workflow (mode 100644, expected content), and nothing else. The
# three-dot diff compares against the merge base, so it still works after BRANCH has moved on, and
# it looks at the net result, so a file that was added and removed again does not count.
setup_branch_is_exact() {
  local b="$1" setup="$2" changes
  changes="$(git diff --raw --no-renames "origin/$b...origin/$setup" 2>/dev/null)" || return 1
  [ -n "$changes" ] || return 1
  printf '%s\n' "$changes" | awk -F'\t' -v wf="$WF" '
    { split($1, a, " "); ok = (a[2] == "100644" && $2 == wf) }
    END { exit !(NR == 1 && ok) }' || return 1
  git show "origin/$setup:$WF" 2>/dev/null | cmp -s - "$TMP/bites.yml"
}

# ensure_pull_request BRANCH SETUP - make sure a pull request from SETUP into BRANCH is open, or
# say how to open one.
ensure_pull_request() {
  local b="$1" setup="$2" n="" url=""
  url="https://github.com/$TARGET/compare/$b...$setup?expand=1"
  if command -v gh >/dev/null 2>&1; then
    n="$(gh pr list --repo "$TARGET" --head "$setup" --base "$b" --state open --json number --jq length 2>/dev/null)" || n=""
    case "$n" in
      0)      note "$(text pr_none_open branch="$b" setup_branch="$setup")"
              gh pr create --repo "$TARGET" --base "$b" --head "$setup" \
                --title "$(text pr_title branch="$b")" \
                --body "$(text pr_body action="$ACTION" version="$REF" workflow_file="$WF")" \
                || warn "$(text pr_create_failed url="$url")" ;;
      [1-9]*) note "$(text pr_already_open branch="$b" setup_branch="$setup")" ;;
      *)      warn "$(text gh_unusable url="$url")" ;;
    esac
  else
    note "$(text gh_missing url="$url")"
  fi
  note "$(text pr_check_diff branch="$b" workflow_file="$WF")"
}

# pull_request_route BRANCH COMMIT - the branch rejected a direct push, so put COMMIT on
# bites-setup/BRANCH and make sure a pull request is open.
pull_request_route() {
  local b="$1" commit="$2" setup="bites-setup/$1" old="" legacy=""
  # A branch named bites-setup, from an earlier version, would block every name under bites-setup/.
  if git rev-parse --verify -q "origin/bites-setup^{commit}" >/dev/null; then
    legacy="$(git rev-parse "origin/bites-setup")"
    note "$(text legacy_branch_removing)"
    if git push --quiet --force-with-lease="refs/heads/bites-setup:$legacy" origin ":refs/heads/bites-setup" 2>"$TMP/push.err"; then
      git update-ref -d "refs/remotes/origin/bites-setup"
    else
      detail="$(push_error)"; set_state "workflow:$b" failed "$(text legacy_branch_removal_failed detail="$detail")"
      return 0
    fi
  fi
  if git rev-parse --verify -q "origin/$setup^{commit}" >/dev/null; then
    if setup_branch_is_exact "$b" "$setup"; then
      note "$(text setup_branch_exact setup_branch="$setup")"
      ensure_pull_request "$b" "$setup"
      set_state "workflow:$b" pending "$(text pending_merge branch="$b" setup_branch="$setup")"
      return 0
    fi
    old="$(git rev-parse "origin/$setup")"
    note "$(text setup_branch_replacing setup_branch="$setup")"
  fi
  note "$(text setup_branch_pushing branch="$b" setup_branch="$setup")"
  if push "$commit" "refs/heads/$setup" "$old"; then
    ensure_pull_request "$b" "$setup"
    set_state "workflow:$b" pending "$(text pending_merge branch="$b" setup_branch="$setup")"
  else
    set_state "workflow:$b" failed "$(push_error)"
  fi
}

install_workflow() { # install_workflow BRANCH - one new commit on top of origin/BRANCH
  local b="$1" parent idx blob tree commit
  parent="$(git rev-parse "origin/$b^{commit}")"
  if git cat-file -e "origin/$b:$WF" 2>/dev/null && git show "origin/$b:$WF" | cmp -s - "$TMP/bites.yml"; then
    note "$(text workflow_up_to_date branch="$b" workflow_file="$WF")"
    set_state "workflow:$b" present ""
    return 0
  fi
  idx="$TMP/index"; rm -f "$idx"
  GIT_INDEX_FILE="$idx" git read-tree "$parent"
  blob="$(git hash-object -w "$TMP/bites.yml")"
  GIT_INDEX_FILE="$idx" git update-index --add --cacheinfo "100644,$blob,$WF"
  tree="$(GIT_INDEX_FILE="$idx" git write-tree)"
  commit="$(git "${ID[@]}" commit-tree "$tree" -p "$parent" -m "$(text workflow_commit_message action="$ACTION" version="$REF")")"
  note "$(text workflow_adding branch="$b")"
  if push "$commit" "refs/heads/$b"; then
    if [ "$DRY" = 1 ]; then set_state "workflow:$b" planned ""; else set_state "workflow:$b" installed ""; fi
  elif push_needs_pull_request; then
    if [ "$PROT" = 1 ]; then
      note "$(text push_rejected_protected branch="$b")"
      pull_request_route "$b" "$commit"
    else
      set_state "workflow:$b" failed "$(text protected_needs_option branch="$b")"
    fi
  else
    set_state "workflow:$b" failed "$(push_error)"
  fi
}
for b in "${INSTALL[@]}"; do
  if in_sel "$b" && [ "$(state_of "output:$b")" = failed ]; then
    set_state "workflow:$b" skipped "$(text workflow_skipped_no_output_branch branch="bites/$b")"
  else
    install_workflow "$b"
  fi
done

# ---- 5. look at the remote again ---------------------------------------------------------------
if [ "$DRY" = 0 ]; then
  git fetch --quiet --prune origin 2>"$TMP/fetch.err" \
    || { detail="$(head -n 1 "$TMP/fetch.err")"; die "$(text verify_fetch_failed detail="$detail")"; }
  for b in "${INSTALL[@]}"; do
    case "$(state_of "workflow:$b")" in
      installed|present)
        if ! git show "origin/$b:$WF" 2>/dev/null | cmp -s - "$TMP/bites.yml"; then
          set_state "workflow:$b" failed "$(text verify_workflow_mismatch)"
        fi ;;
    esac
  done
  for b in "${SEL[@]}"; do
    case "$(state_of "output:$b")" in
      created|present)
        if ! git rev-parse --verify -q "origin/bites/$b^{commit}" >/dev/null; then
          set_state "output:$b" failed "$(text verify_output_branch_missing branch="bites/$b")"
        fi ;;
    esac
  done
fi

# ---- 6. report -----------------------------------------------------------------------------------
# One line per branch. A branch is ready only when its workflow and (if selected) its mirror are.
describe() { # describe KEY - a short word for the state of one piece of work
  case "$(state_of "$1")" in
    installed|created) say status_installed ;;
    present)           say status_present ;;
    planned)           say status_planned ;;
    pending)           say status_pending ;;
    failed)            say status_failed ;;
    skipped)           say status_skipped ;;
    *)                 say status_default ;;
  esac
}
echo
note "$(text summary_title)"
printf '    %-32s %-16s %s\n' "$(text heading_branch)" "$(text heading_workflow)" "$(text heading_output_branch)"
for b in "${INSTALL[@]}"; do
  w="$(describe "workflow:$b")"
  if in_sel "$b"; then m="$(describe "output:$b")"; else m="$(text no_output_branch_row)"; fi
  printf '    %-32s %-16s %s\n' "$b" "$w" "$m"
done
for b in "${INSTALL[@]}"; do
  for k in "workflow:$b" "output:$b"; do
    case "$(state_of "$k")" in
      failed|skipped|pending)
        case "$k" in
          workflow:*) say detail_workflow branch="${k#*:}" detail="$(detail_of "$k")" ;;
          *)          say detail_output_branch branch="${k#*:}" detail="$(detail_of "$k")" ;;
        esac ;;
    esac
  done
done
BAD=0; PENDING=0
for b in "${INSTALL[@]}"; do
  for k in "workflow:$b" "output:$b"; do
    case "$(state_of "$k")" in failed|skipped) BAD=$((BAD + 1)) ;; pending) PENDING=$((PENDING + 1)) ;; esac
  done
done

echo
if [ "$DRY" = 1 ]; then
  if [ "$PROT" = 1 ]; then
    note "$(text dry_run_protected_unknown)"
    if command -v gh >/dev/null 2>&1; then
      note "$(text dry_run_gh_found)"
    else
      note "$(text dry_run_gh_missing)"
    fi
  fi
  note "$(text dry_run_done)"
  exit 0
fi
if [ "$BAD" -gt 0 ]; then
  error_lines "$(text setup_incomplete)" >&2
  exit 1
fi
if [ "$PENDING" -gt 0 ]; then
  note "$(text setup_pending workflow_file="$WF")"
  exit 3
fi
note "$(text setup_complete)"
note "$(text setup_complete_pull)"
note "$(text setup_complete_reminder)"
