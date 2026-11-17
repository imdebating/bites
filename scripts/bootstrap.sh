#!/usr/bin/env bash
# bootstrap.sh - Set up bites in a repository with one command. It installs the caller workflow on
# every branch you choose and creates each branch's bites/<branch> output branch. It works for
# brand-new and existing repositories, and it is safe to run again, because it only changes what
# differs.
#
# usage: scripts/bootstrap.sh [options] OWNER/REPO [BRANCH ...]
#        scripts/bootstrap.sh [options] --all-branches OWNER/REPO
#
#   BRANCH ...                 The source branches to mirror. The default is the repository's
#                              default branch. Names may use only letters, digits, and the
#                              characters . _ / -
#   -a, --all-branches         Mirror every branch the repository has now, except bites/*,
#                              bites-setup, and bites-setup/*. It cannot be combined with BRANCH
#                              names. Branches created later are not included, so run the command
#                              again to add them.
#   -v, --workflow-version V   The version of the action that the workflow uses: a tag such as v1
#                              (the default), an exact tag, or a full commit SHA.
#   -f, --action-from O/R      The repository that holds the action. The default is
#                              imdebating/bites. Use this to take the action from a fork.
#   -c, --config KEY=VALUE     Put a bites setting into the generated workflow. Repeat the option
#                              once per setting. The keys are max_chars, read_cap, include, and
#                              exclude, and include and exclude may be repeated once per glob.
#                              These apply to every branch, so settings that differ by branch
#                              belong in a bites.toml. Running the script again without them
#                              would remove them, so it stops instead. Give them again, or delete
#                              them from the workflow first.
#   -s, --ssh                  Clone and push over SSH instead of HTTPS.
#   -p, --protected            Allow pull requests for protected branches. Each branch is tried
#                              with a direct push first. Only if GitHub rejects the push because
#                              the branch is protected does the script push the workflow to a
#                              branch named bites-setup/<branch> and open a pull request into
#                              <branch>. Those branches stay PENDING (exit status 3) until the
#                              pull requests are merged and the command is run again. Without
#                              this option, a protected branch is reported as FAILED.
#   --dry-run                  Show what would be done, and change nothing on the remote.
#   -n, --no-preflight         Skip the check that the action repository and version can be
#                              reached.
#   --url URL                  Clone the target from this URL instead. The tests use it, and it
#                              also turns the preflight check off unless --action-url is given.
#   --action-url URL           Where the preflight check looks for the action. The default is
#                              https://github.com/O/R.git for --action-from O/R. The tests use it.
#   -V, --version              Print the version of this script, and stop.
#   -h, --help                 Show this text, and stop.
#
# Short options that take no value can be combined, so -aps means -a -p -s. Options that take a
# value (-v, -f, and -c) go last in a combination, followed by their value as the next argument.
#
# What it does, in order:
#   0. Preflight: checks, anonymously (as a workflow in another repository would see it), that the
#      action repository is reachable and has the tag, branch, or commit given by
#      --workflow-version. Problems are warnings, not errors, because a private action repository
#      can be shared with private repositories through its Actions access setting.
#   1. Clones OWNER/REPO into a temporary directory and works out the selected branches.
#   2. Checks every selected branch before changing anything: it exists, and its existing
#      .github/workflows/bites.yml (if any) is a bites workflow whose settings would not be lost.
#   3. Creates the missing bites/<branch> output branches, before the workflow, so the first build
#      already finds its mirror.
#   4. Adds .github/workflows/bites.yml (from templates/bites.yml) to each selected branch, and to
#      the default branch, whose copy runs the cleanup job, as one extra commit on top of that
#      branch. Nothing is merged, and no other file changes. A branch that rejects the push
#      because it is protected gets a pull request instead, if --protected was given.
#   5. Fetches the remote again, and checks that every workflow and mirror is really there.
#   6. Prints one line per branch, and reports success only if all of them are ready.
# It never edits existing source files, never force-pushes a source branch, and never touches an
# existing bites/* branch. Only the reserved bites-setup/* branches are ever replaced.
# Running it again with a different --workflow-version is how a project's pinned version changes.
#
# Exit status: 0 means setup is complete and verified (or --dry-run). 1 means an error, or setup is
# incomplete, and the summary says which branches. 3 means pending: a pull request must be merged.
# "Verified" means the files and branches are on the remote. Actions settings, organization
# policies, and the token's permissions at run time cannot be seen from here.
#
# Needs: git, plus credentials that can push to the target repository. The pull request step uses
# the gh CLI when it is installed, and prints a link otherwise.
set -euo pipefail

# Print the comment block above (lines 2 up to "set -euo") with the leading "# " removed.
usage() { sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }
die()  { echo "error: $*" >&2; exit 1; }
note() { echo "==> $*"; }
warn() { echo "warning: $*" >&2; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
            [ "$pos" -eq "${#letters}" ] || { echo "error: The option -$ch takes a value, so it must come last in a combination: $(printf '%q' "$arg")" >&2; exit 1; }
            want_value=1 ;;
        esac
      done ;;
    *)   EXPANDED+=("$arg") ;;
  esac
done
set -- ${EXPANDED[@]+"${EXPANDED[@]}"}

SET_MAX=""; SET_CAP=""; SET_INC=(); SET_EXC=()
add_setting() { # add_setting KEY=VALUE - remember one --config option for the generated workflow
  [[ "$1" == *=* ]] || die "--config expects KEY=VALUE: $(printf '%q' "$1")"
  local key="${1%%=*}" val="${1#*=}"
  if [ -z "$val" ] || [[ "$val" =~ [[:space:]] ]] || [[ "$val" == *'${'* ]]; then
    die "--config $(printf '%q' "$key") needs a value without spaces and without \${: $(printf '%q' "$val")"
  fi
  case "$key" in
    max_chars|read_cap)
      [[ "$val" =~ ^[0-9]{1,9}$ ]] && [ "$((10#$val))" -ge 1 ] || die "--config $key needs a whole number of at least 1: $(printf '%q' "$val")"
      if [ "$key" = max_chars ]; then SET_MAX="$((10#$val))"; else SET_CAP="$((10#$val))"; fi ;;
    include) SET_INC+=("$val") ;;
    exclude) SET_EXC+=("$val") ;;
    wrapper_chars|manifest_max_chars) die "$key is an advanced setting: put it in a bites.toml, not in the workflow" ;;
    *) die "unknown setting $(printf '%q' "$key"); --config accepts max_chars, read_cap, include and exclude" ;;
  esac
}
renamed() { # renamed OLD - stop with a pointer to the new name of a renamed option
  case "$1" in
    --ref)    die "The option --ref is now --workflow-version (-v)." ;;
    --action) die "The option --action is now --action-from (-f)." ;;
    --set)    die "The option --set is now --config (-c)." ;;
    --pr)     die "The option --pr is now --protected (-p). It now tries a direct push first, and it opens a pull request only if the branch rejects it." ;;
  esac
}

REF="v1"; ACTION="imdebating/bites"; PROTO="https"; URL=""; ACTION_URL=""; PREFLIGHT=1; PROT=0; DRY=0; ALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    -v|--workflow-version) [ $# -ge 2 ] || die "$1 needs a value"; REF="$2"; shift 2 ;;
    -f|--action-from)      [ $# -ge 2 ] || die "$1 needs a value"; ACTION="$2"; shift 2 ;;
    -c|--config)           [ $# -ge 2 ] || die "$1 needs KEY=VALUE"; add_setting "$2"; shift 2 ;;
    --url)                 [ $# -ge 2 ] || die "--url needs a value"; URL="$2"; shift 2 ;;
    --action-url)          [ $# -ge 2 ] || die "--action-url needs a value"; ACTION_URL="$2"; shift 2 ;;
    -a|--all-branches)     ALL=1; shift ;;
    -n|--no-preflight)     PREFLIGHT=0; shift ;;
    -s|--ssh)              PROTO="ssh"; shift ;;
    -p|--protected)        PROT=1; shift ;;
    --dry-run)             DRY=1; shift ;;
    -V|--version)          echo "bootstrap.sh $VERSION"; echo "Run bootstrap.sh --help to see the options that this version supports."; exit 0 ;;
    -h|--help)             usage; exit 0 ;;
    --ref|--action|--set|--pr) renamed "$1" ;;
    --)                    shift; break ;;
    -*)                    usage >&2; die "unknown option: $1" ;;
    *)                     break ;;
  esac
done
[ $# -ge 1 ] || { usage >&2; exit 2; }
TARGET="$1"; shift
BRANCHES=("$@")
if [ "$ALL" = 1 ] && [ ${#BRANCHES[@]} -gt 0 ]; then
  die "--all-branches cannot be combined with branch names (give one or the other)"
fi

# Validate everything that ends up in a URL, a sed expression, or a ref name. printf %q shows
# an invisible character (for example a non-breaking space pasted from a web page) as an
# escape sequence instead of letting it hide in the message.
re_repo='^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'
re_branch='^[A-Za-z0-9._/-]+$'
[[ "$TARGET" =~ $re_repo ]] || die "target must look like OWNER/REPO: $(printf '%q' "$TARGET")"
[[ "$ACTION" =~ $re_repo ]] || die "--action-from must look like OWNER/REPO: $(printf '%q' "$ACTION")"
[[ "$REF" =~ ^[A-Za-z0-9._/-]+$ ]] || die "--workflow-version contains unexpected characters: $(printf '%q' "$REF")"
check_source_name() { # check_source_name NAME - stop unless NAME can be a source branch
  [[ "$1" =~ $re_branch ]] || die "branch name has characters other than letters, digits and . _ / - : $(printf '%q' "$1")"
  git check-ref-format --branch "$1" >/dev/null 2>&1 || die "not a valid branch name: $(printf '%q' "$1")"
  # The output branches and the setup branches are never source branches.
  case "$1" in bites/*|bites-setup|bites-setup/*) die "refusing to mirror $1" ;; esac
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

TEMPLATE="$HERE/../templates/bites.yml"
[ -f "$TEMPLATE" ] || die "template not found: $TEMPLATE"

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
    2) warn "$ACTION has no tag or branch named '$REF'."
       warn "Workflows that use $ACTION@$REF will fail with 'Unable to resolve action' until it exists." ;;
    *) warn "cannot reach $url without credentials."
       warn "If $ACTION is private or misspelled, workflows in $TARGET will fail with 'repository not found'."
       warn "A public project needs a public action repository. A private project can use a private one only if"
       warn "its Settings > Actions > General > Access allows it. Use --no-preflight to skip this check." ;;
  esac
}
if [ "$PREFLIGHT" = 1 ]; then preflight; fi

# ---- 1. clone and choose the branches ---------------------------------------------------
# Work in a throw-away clone so the caller's own checkouts are never touched.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
note "cloning $TARGET"
git clone --quiet "$URL" "$TMP/repo" || die "could not clone $URL"
cd "$TMP/repo"

# The default branch is whatever the remote's HEAD points to; an empty repository has none.
DEFAULT="$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null || true)"
DEFAULT="${DEFAULT#origin/}"
[ -n "$DEFAULT" ] || die "repository has no default branch yet (is it empty? make a first commit)"
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
  if [ "$DRY" = 1 ]; then echo "[dry-run] git push origin $1:$2"; return 0; fi
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
  local rc=0
  git ls-remote --exit-code --heads origin "refs/heads/$1" >/dev/null 2>"$TMP/lsr.err" || rc=$?
  case "$rc" in
    0) return 0 ;;
    2) return 1 ;;
    *) die "could not ask the remote about branch $(printf '%q' "$1") (git exit status $rc): $(head -n 1 "$TMP/lsr.err")" ;;
  esac
}

SEL=()
in_sel() { local x; for x in ${SEL[@]+"${SEL[@]}"}; do if [ "$x" = "$1" ]; then return 0; fi; done; return 1; }
add_sel() { if ! in_sel "$1"; then SEL+=("$1"); fi; }

if [ "$ALL" = 1 ]; then
  rc=0
  heads="$(git ls-remote --heads origin 2>"$TMP/lsr.err")" || rc=$?
  [ "$rc" = 0 ] || die "could not list the branches on the remote (git exit status $rc): $(head -n 1 "$TMP/lsr.err")"
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
  [ -z "$bad" ] || die "--all-branches cannot cover branch names with characters other than letters, digits and . _ / - :$bad (nothing was changed; list the other branches by name instead)"
elif [ ${#BRANCHES[@]} -eq 0 ]; then
  add_sel "$DEFAULT"
else
  for b in "${BRANCHES[@]}"; do add_sel "$b"; done
fi

# Branches that get the caller workflow: the selected ones, and the default branch, because
# a delete event always runs the copy on the default branch (that is what runs the cleanup).
INSTALL=("${SEL[@]}")
if ! in_sel "$DEFAULT"; then INSTALL+=("$DEFAULT"); fi
note "branches to mirror: ${SEL[*]}"
if ! in_sel "$DEFAULT"; then note "the default branch ($DEFAULT) also gets the workflow, for the cleanup job, but no mirror"; fi

# ---- 2. check everything before changing anything -----------------------------------------
# Fill the settings placeholder line (it disappears if there are no settings), then the
# action and version placeholders.
BLOCK="$SETTINGS_BLOCK" awk '/^__SETTINGS__$/ { if (ENVIRON["BLOCK"] != "") print ENVIRON["BLOCK"]; next } { print }' "$TEMPLATE" \
  | sed -e "s#__ACTION__#$ACTION#g" -e "s#__REF__#$REF#g" > "$TMP/bites.yml"
WF=".github/workflows/bites.yml"
SETTING_LINE='^[[:space:]]+(max-chars|read-cap|include|exclude):'

for b in "${SEL[@]}"; do
  remote_has_branch "$b" || die "source branch $(printf '%q' "$b") does not exist on the remote"
done

: > "$TMP/problems"
for b in "${INSTALL[@]}"; do
  if git cat-file -e "origin/$b:$WF" 2>/dev/null; then
    git show "origin/$b:$WF" > "$TMP/current.yml"
    if ! cmp -s "$TMP/bites.yml" "$TMP/current.yml"; then
      if ! grep -Eq '^name:[[:space:]]*bites[[:space:]]*$' "$TMP/current.yml"; then
        echo "  - $b: $WF exists but is not a bites workflow; move it aside, or merge its jobs by hand" >> "$TMP/problems"
      elif grep -Eq "$SETTING_LINE" "$TMP/current.yml" && ! grep -Eq "$SETTING_LINE" "$TMP/bites.yml"; then
        echo "  - $b: the existing $WF sets bites options (max-chars, read-cap, include or exclude) that this run would remove; give them again with --config, or delete them from the workflow first" >> "$TMP/problems"
      fi
    fi
  fi
done
if [ -s "$TMP/problems" ]; then
  { echo "error: setup stopped before changing anything:"; cat "$TMP/problems"; } >&2
  exit 1
fi

# ---- 3. the bites/<branch> output branches ------------------------------------------------
# `git mktree` with no input writes and prints the empty tree; a commit on it is an
# "orphan" root with no files, which is what the first build expects to find. They are made
# before the workflow, so the first run that the workflow's own push starts finds its mirror.
EMPTY="$(git mktree </dev/null)"
for b in "${SEL[@]}"; do
  if remote_has_branch "bites/$b"; then
    note "bites/$b already exists"
    set_state "mirror:$b" present ""
  else
    c="$(git "${ID[@]}" commit-tree "$EMPTY" -m "bites: init")"
    note "creating bites/$b"
    if push "$c" "refs/heads/bites/$b"; then
      if [ "$DRY" = 1 ]; then set_state "mirror:$b" planned ""; else set_state "mirror:$b" created ""; fi
    elif remote_has_branch "bites/$b"; then
      set_state "mirror:$b" present "created by someone else meanwhile"
    else
      set_state "mirror:$b" failed "$(push_error)"
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
      0)      note "No pull request is open from $setup into $b, so one is being opened."
              gh pr create --repo "$TARGET" --base "$b" --head "$setup" \
                --title "Add bites caller workflow to $b" \
                --body "Installed by bites bootstrap ($ACTION@$REF). The diff should show one added file, $WF." \
                || warn "The command gh pr create failed. Open the pull request by hand: $url" ;;
      [1-9]*) note "A pull request from $setup into $b is already open. Merge it." ;;
      *)      warn "Could not ask gh about pull requests. If you have not signed in, run gh auth login, and then run this command again."
              warn "Or find or open the pull request by hand: $url" ;;
    esac
  else
    note "The GitHub CLI (gh) was not found. With gh installed, bootstrap opens these pull requests for you."
    note "To install it, see https://cli.github.com (on macOS, run: brew install gh), run gh auth login once, and then run this command again."
    note "For now, open the pull request by hand if none is open yet: $url"
  fi
  note "Before merging, check that the diff of the pull request into $b shows only $WF."
}

# pull_request_route BRANCH COMMIT - the branch rejected a direct push, so put COMMIT on
# bites-setup/BRANCH and make sure a pull request is open.
pull_request_route() {
  local b="$1" commit="$2" setup="bites-setup/$1" old="" legacy=""
  # A branch named bites-setup, from an earlier version, would block every name under bites-setup/.
  if git rev-parse --verify -q "origin/bites-setup^{commit}" >/dev/null; then
    legacy="$(git rev-parse "origin/bites-setup")"
    note "Removing the old branch bites-setup, because it blocks branch names under bites-setup/."
    if git push --quiet --force-with-lease="refs/heads/bites-setup:$legacy" origin ":refs/heads/bites-setup" 2>"$TMP/push.err"; then
      git update-ref -d "refs/remotes/origin/bites-setup"
    else
      set_state "workflow:$b" failed "Could not remove the old bites-setup branch: $(push_error)"
      return 0
    fi
  fi
  if git rev-parse --verify -q "origin/$setup^{commit}" >/dev/null; then
    if setup_branch_is_exact "$b" "$setup"; then
      note "$setup already holds exactly the workflow."
      ensure_pull_request "$b" "$setup"
      set_state "workflow:$b" pending "Merge the pull request from $setup into $b."
      return 0
    fi
    old="$(git rev-parse "origin/$setup")"
    note "$setup holds something other than the expected workflow, so it is being replaced."
  fi
  note "Pushing $setup, so that a pull request can be opened into $b."
  if push "$commit" "refs/heads/$setup" "$old"; then
    ensure_pull_request "$b" "$setup"
    set_state "workflow:$b" pending "Merge the pull request from $setup into $b."
  else
    set_state "workflow:$b" failed "$(push_error)"
  fi
}

install_workflow() { # install_workflow BRANCH - one new commit on top of origin/BRANCH
  local b="$1" parent idx blob tree commit
  parent="$(git rev-parse "origin/$b^{commit}")"
  if git cat-file -e "origin/$b:$WF" 2>/dev/null && git show "origin/$b:$WF" | cmp -s - "$TMP/bites.yml"; then
    note "$WF already up to date on $b"
    set_state "workflow:$b" present ""
    return 0
  fi
  idx="$TMP/index"; rm -f "$idx"
  GIT_INDEX_FILE="$idx" git read-tree "$parent"
  blob="$(git hash-object -w "$TMP/bites.yml")"
  GIT_INDEX_FILE="$idx" git update-index --add --cacheinfo "100644,$blob,$WF"
  tree="$(GIT_INDEX_FILE="$idx" git write-tree)"
  commit="$(git "${ID[@]}" commit-tree "$tree" -p "$parent" -m "Add bites caller workflow ($ACTION@$REF)")"
  note "adding the workflow to $b"
  if push "$commit" "refs/heads/$b"; then
    if [ "$DRY" = 1 ]; then set_state "workflow:$b" planned ""; else set_state "workflow:$b" installed ""; fi
  elif push_needs_pull_request; then
    if [ "$PROT" = 1 ]; then
      note "$b rejected the push because it is protected, so a pull request is needed."
      pull_request_route "$b" "$commit"
    else
      set_state "workflow:$b" failed "Adding the workflow failed, because $b is protected and a pull request is required. Run the same command again with --protected (-p) to open one."
    fi
  else
    set_state "workflow:$b" failed "$(push_error)"
  fi
}
for b in "${INSTALL[@]}"; do
  if in_sel "$b" && [ "$(state_of "mirror:$b")" = failed ]; then
    set_state "workflow:$b" skipped "bites/$b could not be created, so the workflow was not added"
  else
    install_workflow "$b"
  fi
done

# ---- 5. look at the remote again ---------------------------------------------------------------
if [ "$DRY" = 0 ]; then
  git fetch --quiet --prune origin 2>"$TMP/fetch.err" \
    || die "could not read the remote again to verify the setup ($(head -n 1 "$TMP/fetch.err")); it may be complete: run the same command again to check"
  for b in "${INSTALL[@]}"; do
    case "$(state_of "workflow:$b")" in
      installed|present)
        if ! git show "origin/$b:$WF" 2>/dev/null | cmp -s - "$TMP/bites.yml"; then
          set_state "workflow:$b" failed "the remote does not hold the expected workflow after the push (changed meanwhile?)"
        fi ;;
    esac
  done
  for b in "${SEL[@]}"; do
    case "$(state_of "mirror:$b")" in
      created|present)
        if ! git rev-parse --verify -q "origin/bites/$b^{commit}" >/dev/null; then
          set_state "mirror:$b" failed "bites/$b is not on the remote after the push"
        fi ;;
    esac
  done
fi

# ---- 6. report -----------------------------------------------------------------------------------
# One line per branch. A branch is ready only when its workflow and (if selected) its mirror are.
describe() { # describe KEY - a short word for the state of one piece of work
  case "$(state_of "$1")" in
    installed|created) echo "added" ;;
    present)           echo "already there" ;;
    planned)           echo "planned" ;;
    pending)           echo "PENDING" ;;
    failed)            echo "FAILED" ;;
    skipped)           echo "NOT DONE" ;;
    *)                 echo "-" ;;
  esac
}
echo
note "summary"
printf '    %-32s %-16s %s\n' "branch" "workflow" "mirror"
for b in "${INSTALL[@]}"; do
  w="$(describe "workflow:$b")"
  if in_sel "$b"; then m="$(describe "mirror:$b")"; else m="not mirrored"; fi
  printf '    %-32s %-16s %s\n' "$b" "$w" "$m"
done
for b in "${INSTALL[@]}"; do
  for k in "workflow:$b" "mirror:$b"; do
    case "$(state_of "$k")" in failed|skipped|pending) echo "    $k: $(detail_of "$k")" ;; esac
  done
done
BAD=0; PENDING=0
for b in "${INSTALL[@]}"; do
  for k in "workflow:$b" "mirror:$b"; do
    case "$(state_of "$k")" in failed|skipped) BAD=$((BAD + 1)) ;; pending) PENDING=$((PENDING + 1)) ;; esac
  done
done

echo
if [ "$DRY" = 1 ]; then
  if [ "$PROT" = 1 ]; then
    note "A dry run cannot tell whether a branch is protected. With --protected, a push that GitHub rejects for that reason becomes a pull request."
    if command -v gh >/dev/null 2>&1; then
      note "The GitHub CLI (gh) was found, so bootstrap would open any pull request that is needed."
    else
      note "The GitHub CLI (gh) was not found, so you would open any needed pull request by hand. To install it, see https://cli.github.com (on macOS, run: brew install gh)."
    fi
  fi
  note "dry run: nothing was changed on the remote, and nothing was verified"
  exit 0
fi
if [ "$BAD" -gt 0 ]; then
  echo "error: setup is INCOMPLETE. Fix the cause shown above and run the same command again; work that is done is not repeated." >&2
  exit 1
fi
if [ "$PENDING" -gt 0 ]; then
  note "Setup is PENDING. Merge the pull request for each branch marked PENDING (its diff should show only $WF), then run the same command again to verify it (exit status 3)."
  exit 3
fi
note "setup complete and verified on the remote: each branch above builds on its next push"
note "update your local checkouts with a normal git pull or git fetch (the workflow is a new commit on each branch)"
note "reminder: if a mirrored branch is protected, allow github-actions[bot] to push to it; keep bites/* unprotected"
