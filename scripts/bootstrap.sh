#!/usr/bin/env bash
# bootstrap.sh - install the bites caller workflow into a repository and create the
# bites/<branch> output branches. Works for brand-new and existing repositories, and is
# safe to run again (it only changes what differs).
#
# usage: scripts/bootstrap.sh [options] OWNER/REPO [BRANCH ...]
#
#   BRANCH ...       source branches to mirror (default: the repository's default branch);
#                    names may use only letters, digits and . _ / -
#   --ref REF        version of the action the caller uses: a tag such as v1 (default),
#                    an exact tag, or a full commit SHA
#   --action O/R     repository that holds the action (default: imdebating/bites)
#   --ssh            clone and push over SSH instead of HTTPS
#   --pr             push the workflow to a branch named bites-setup instead of the
#                    default branch (for protected default branches); open a pull request
#                    by hand, or automatically if the gh CLI is installed
#   --dry-run        show what would be done; change nothing on the remote
#   --no-preflight   skip the check that the action repository and --ref can be reached
#   --url URL        clone the target from this URL instead (used by the tests; it also
#                    turns the preflight check off unless --action-url is given)
#   --action-url URL where the preflight check looks for the action (default:
#                    https://github.com/O/R.git for --action O/R; used by the tests)
#   -h, --help       show this text
#
# What it does:
#   0. preflight: checks, anonymously (as a workflow in another repository would see it),
#      that the action repository is reachable and has the tag, branch or commit given by
#      --ref. Problems are warnings, not errors, because a private action repository can
#      be shared with private repositories through its Actions access setting.
#   1. clones OWNER/REPO into a temporary directory
#   2. writes .github/workflows/bites.yml (from templates/bites.yml) on the default branch,
#      commits and pushes it if it differs from what is there
#   3. for each BRANCH, creates an empty bites/BRANCH branch if it does not exist
# It never edits existing source files, and never touches existing bites/* branches.
# Re-running with a different --ref is how a project's pinned version is changed.
#
# Exit status: 0 on success; non-zero with a message on stderr if anything is wrong
# (bad arguments, clone failure, missing source branch, push rejected).
#
# Needs: git, plus credentials that can push to the target repository.
set -euo pipefail

# Print the comment block above (lines 2 up to "set -euo") with the leading "# " removed.
usage() { sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }
die()  { echo "error: $*" >&2; exit 1; }
note() { echo "==> $*"; }
warn() { echo "warning: $*" >&2; }

REF="v1"; ACTION="imdebating/bites"; PROTO="https"; URL=""; ACTION_URL=""; PREFLIGHT=1; PR=0; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --ref)          [ $# -ge 2 ] || die "--ref needs a value"; REF="$2"; shift 2 ;;
    --action)       [ $# -ge 2 ] || die "--action needs a value"; ACTION="$2"; shift 2 ;;
    --url)          [ $# -ge 2 ] || die "--url needs a value"; URL="$2"; shift 2 ;;
    --action-url)   [ $# -ge 2 ] || die "--action-url needs a value"; ACTION_URL="$2"; shift 2 ;;
    --no-preflight) PREFLIGHT=0; shift ;;
    --ssh)          PROTO="ssh"; shift ;;
    --pr)           PR=1; shift ;;
    --dry-run)      DRY=1; shift ;;
    -h|--help)      usage; exit 0 ;;
    --)             shift; break ;;
    -*)             usage >&2; die "unknown option: $1" ;;
    *)              break ;;
  esac
done
[ $# -ge 1 ] || { usage >&2; exit 2; }
TARGET="$1"; shift
BRANCHES=("$@")

# Validate everything that ends up in a URL, a sed expression or a ref name. printf %q shows
# an invisible character (for example a non-breaking space pasted from a web page) as an
# escape sequence instead of letting it hide in the message.
re_repo='^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'
[[ "$TARGET" =~ $re_repo ]] || die "target must look like OWNER/REPO: $(printf '%q' "$TARGET")"
[[ "$ACTION" =~ $re_repo ]] || die "--action must look like OWNER/REPO: $(printf '%q' "$ACTION")"
[[ "$REF" =~ ^[A-Za-z0-9._/-]+$ ]] || die "--ref contains unexpected characters: $(printf '%q' "$REF")"
for b in ${BRANCHES[@]+"${BRANCHES[@]}"}; do
  [[ "$b" =~ ^[A-Za-z0-9._/-]+$ ]] || die "branch name has characters other than letters, digits and . _ / - : $(printf '%q' "$b")"
  git check-ref-format --branch "$b" >/dev/null 2>&1 || die "not a valid branch name: $(printf '%q' "$b")"
  # The output branches and the setup branch are never source branches.
  case "$b" in bites/*|bites-setup) die "refusing to mirror $b" ;; esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
if [ ${#BRANCHES[@]} -eq 0 ]; then BRANCHES=("$DEFAULT"); fi

# Commits are made with the user's git identity if set, else a neutral one.
NAME="$(git config user.name || true)"; NAME="${NAME:-bites bootstrap}"
EMAIL="$(git config user.email || true)"; EMAIL="${EMAIL:-bites-bootstrap@users.noreply.github.com}"
ID=(-c "user.name=$NAME" -c "user.email=$EMAIL")

push() { # push SRC DEST - every write to the remote goes through here, so --dry-run is safe
  if [ "$DRY" = 1 ]; then echo "[dry-run] git push origin $1:$2"; else git push --quiet origin "$1:$2"; fi
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

# ---- 1. the caller workflow on the default branch -------------------------------------
sed -e "s#__ACTION__#$ACTION#g" -e "s#__REF__#$REF#g" "$TEMPLATE" > "$TMP/bites.yml"
WF=".github/workflows/bites.yml"
git checkout --quiet "$DEFAULT"
if [ -f "$WF" ] && cmp -s "$TMP/bites.yml" "$WF"; then
  note "$WF already up to date on $DEFAULT"
  WF_PUSHED=0
else
  mkdir -p .github/workflows
  cp "$TMP/bites.yml" "$WF"
  git add "$WF"
  git "${ID[@]}" commit --quiet -m "Add bites caller workflow ($ACTION@$REF)"
  if [ "$PR" = 1 ]; then
    # Rename the local branch so the commit is pushed as bites-setup, not as the default.
    git branch -m bites-setup
    note "pushing bites-setup (open a pull request into $DEFAULT)"
    push bites-setup bites-setup
    if [ "$DRY" = 0 ] && command -v gh >/dev/null 2>&1; then
      gh pr create --repo "$TARGET" --base "$DEFAULT" --head bites-setup \
        --title "Add bites caller workflow" --body "Installed by bites bootstrap ($ACTION@$REF)." || warn "gh pr create failed; open the pull request by hand"
    fi
  else
    note "pushing the workflow to $DEFAULT"
    push HEAD "refs/heads/$DEFAULT"
  fi
  WF_PUSHED=1
fi

# ---- 2. the bites/<branch> output branches --------------------------------------------
# `git mktree` with no input writes and prints the empty tree; a commit on it is an
# "orphan" root with no files, which is what the first build expects to find.
EMPTY="$(git mktree </dev/null)"
for b in "${BRANCHES[@]}"; do
  remote_has_branch "$b" || die "source branch $(printf '%q' "$b") does not exist on the remote"
  if remote_has_branch "bites/$b"; then
    note "bites/$b already exists"
  else
    c="$(git "${ID[@]}" commit-tree "$EMPTY" -m "bites: init")"
    note "creating bites/$b"
    push "$c" "refs/heads/bites/$b"
  fi
  # A push-triggered run uses the workflow file from the pushed commit, so another branch
  # only builds once it contains the caller.
  if [ "$b" != "$DEFAULT" ] && ! git cat-file -e "origin/$b:$WF" 2>/dev/null; then
    warn "branch $b has no $WF yet; merge $DEFAULT into it (git switch $b && git merge $DEFAULT) so pushes to it build"
  fi
done

if [ "$PR" = 1 ] && [ "${WF_PUSHED:-0}" = 1 ]; then
  note "merge the bites-setup pull request, then push to a mirrored branch to start the first build"
else
  note "done. Push to a mirrored branch (or run the 'bites' workflow with 'full' ticked) to start the first build"
fi
note "reminder: if a mirrored branch is protected, allow github-actions[bot] to push to it; keep bites/* unprotected"
