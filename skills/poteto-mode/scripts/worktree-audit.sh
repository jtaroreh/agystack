#!/usr/bin/env bash
# Read-only worktree prune audit. Classifies every git worktree by size, merge
# state, uncommitted work, remote/PR state, and the most recent chat that
# operated in it. Emits a table sorted by size with a suggested bucket. Never
# deletes anything; deletion stays a human-gated step in the playbook.
#
# Usage: worktree-audit.sh [-b <base-branch>] [repo-path]   (defaults to current repo)
set -u

usage() {
	cat <<'EOF'
Usage: worktree-audit.sh [-b <base-branch>] [repo-path]

Classifies every git worktree by size, merge state, uncommitted work,
remote/PR state, and the most recent chat that operated in it.

Options:
  -b <base-branch>  Specify the base branch for merge checks (e.g. origin/main, release)
  -h, --help        Show this help message and exit
EOF
	exit 0
}

base_branch=""
repo=""

while [ $# -gt 0 ]; do
	case "$1" in
		-h|--help)
			usage
			;;
		-b)
			shift
			if [ $# -eq 0 ]; then
				echo "error: -b requires an argument" >&2
				exit 1
			fi
			base_branch="$1"
			shift
			;;
		-b*)
			base_branch="${1#-b}"
			shift
			;;
		--)
			shift
			break
			;;
		-*)
			echo "error: unknown option: $1" >&2
			exit 1
			;;
		*)
			if [ -z "$repo" ]; then
				repo="$1"
			else
				echo "error: unexpected extra argument: $1" >&2
				exit 1
			fi
			shift
			;;
	esac
done

[ -z "$repo" ] && repo="$(git rev-parse --show-toplevel 2>/dev/null)"
[ -z "$repo" ] && { echo "not in a git repo; pass a repo path" >&2; exit 1; }
cd "$repo" || exit 1

if [ -z "$base_branch" ]; then
	if ref=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null); then
		base_branch="${ref#refs/remotes/}"
	elif git rev-parse --verify --quiet origin/main >/dev/null 2>&1; then
		base_branch="origin/main"
	elif git rev-parse --verify --quiet origin/master >/dev/null 2>&1; then
		base_branch="origin/master"
	else
		base_branch="main"
	fi
fi

# Main worktree is the first entry; everything else is a candidate.
main_wt=$(git worktree list --porcelain | awk '/^worktree /{print substr($0, 10); exit}')

# Best-effort fetch of base branch; stale is fine for a first pass.
case "$base_branch" in
	*/*)
		fetch_remote="${base_branch%%/*}"
		fetch_ref="${base_branch#*/}"
		git fetch "$fetch_remote" "$fetch_ref" --quiet 2>/dev/null || echo "warn: could not fetch $base_branch; merged column may be stale" >&2
		;;
	*)
		git fetch origin "$base_branch" --quiet 2>/dev/null || true
		;;
esac

# PR state by branch, fetched once. Empty if gh is unavailable.
prs=$(mktemp)
trap 'rm -f "$prs"' EXIT INT TERM
gh pr list --author "@me" --state all --limit 1000 \
	--json number,state,headRefName 2>/dev/null > "$prs" || echo "[]" > "$prs"

# Transcripts dir: Antigravity brain directories
agy_ide_transcripts="$HOME/.gemini/antigravity-ide/brain"
agy_cli_transcripts="$HOME/.gemini/antigravity/brain"
now=$(date +%s)
is_darwin=$([ "$(uname -s)" = "Darwin" ] && echo yes || echo no)

printf "# base: %s\n" "$base_branch"
printf "SIZE\tAGE\tMERGED\tDIRTY\tREMOTE\tPR\tLAST_CHAT\tBUCKET\tWORKTREE\n"

git worktree list --porcelain | awk '/^worktree /{print substr($0, 10)}' | while IFS= read -r wt; do
	[ "$wt" = "$main_wt" ] && continue

	size=$(du -sh "$wt" 2>/dev/null | awk '{print $1}')
	head=$(git -C "$wt" rev-parse HEAD 2>/dev/null)
	head_ts=$(git -C "$wt" log -1 --format='%ct' HEAD 2>/dev/null || echo 0)
	age=$([ "$head_ts" -gt 0 ] 2>/dev/null && echo "$(( (now - head_ts) / 86400 ))d" || echo "?")

	# Squash-merged branches are not ancestors of main, so PR state is the
	# real signal; merge-base only catches fast-forward/rebase merges.
	git merge-base --is-ancestor "$head" "$base_branch" 2>/dev/null && merged=YES || merged=no

	# Distinguish real WIP (tracked edits) from disposable untracked scratch.
	porcelain=$(git -C "$wt" status --porcelain 2>/dev/null)
	if [ -z "$porcelain" ]; then dirty=clean
	elif printf '%s\n' "$porcelain" | grep -qv '^??'; then
		dirty="wip:$(printf '%s\n' "$porcelain" | grep -cv '^??')"
	else dirty="scratch:$(printf '%s\n' "$porcelain" | grep -c '^??')"; fi

	branch=$(git -C "$wt" symbolic-ref --quiet --short HEAD 2>/dev/null || echo "")
	if [ -z "$branch" ]; then remote=detached
	elif git -C "$wt" show-ref --verify --quiet "refs/remotes/origin/$branch"; then
		[ "$(git -C "$wt" rev-parse "origin/$branch" 2>/dev/null)" = "$head" ] \
			&& remote=pushed \
			|| remote="ahead$(git -C "$wt" rev-list --count "origin/$branch..HEAD" 2>/dev/null)"
	else remote=no-remote; fi

	pr=$([ -n "$branch" ] && jq -r --arg b "$branch" \
		'.[] | select(.headRefName==$b) | "#\(.number)/\(.state)"' "$prs" 2>/dev/null | head -1)
	[ -z "$pr" ] && pr="-"

	# Most recent chat whose transcript operated in this worktree. Match path
	# followed by "/" or a quote so glint-482 does not match glint-482-r37.
	last="-"; last_ts=0
	search_dirs=()
	[ -d "$agy_ide_transcripts" ] && search_dirs+=("$agy_ide_transcripts")
	[ -d "$agy_cli_transcripts" ] && search_dirs+=("$agy_cli_transcripts")

	if [ ${#search_dirs[@]} -gt 0 ]; then
		matched_files=$(rg -l -e "${wt}/" -e "${wt}\"" "${search_dirs[@]}" 2>/dev/null || true)
		if [ -n "$matched_files" ]; then
			if [ "$is_darwin" = yes ]; then
				f=$(printf '%s\n' "$matched_files" | xargs stat -f '%m %N' 2>/dev/null | sort -rn | head -1)
				if [ -n "$f" ]; then
					last_ts=$(echo "$f" | awk '{print $1}')
					last=$(date -r "$last_ts" '+%Y-%m-%d' 2>/dev/null || echo "-")
				fi
			else
				f=$(printf '%s\n' "$matched_files" | xargs stat -c '%Y %n' 2>/dev/null | sort -rn | head -1)
				if [ -n "$f" ]; then
					last_ts=$(echo "$f" | awk '{print $1}')
					last=$(date -d "@$last_ts" '+%Y-%m-%d' 2>/dev/null || echo "-")
				fi
			fi
		fi
	fi
	recent=$([ "$last_ts" -gt 0 ] 2>/dev/null && [ $(( (now - last_ts) / 86400 )) -le 4 ] && echo yes || echo no)

	case "$dirty" in wip:*) bucket=hold-wip ;; *)
		case "$pr" in *OPEN*) bucket=hold-open-pr ;; *)
			if [ "$recent" = yes ]; then bucket=verify-recent-chat
			elif [ "$merged" = YES ] || [ "$pr" != "-" ]; then bucket=safe
			else bucket=review; fi ;;
		esac ;;
	esac

	printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
		"$size" "$age" "$merged" "$dirty" "$remote" "$pr" "$last" "$bucket" "$wt"
done | sort -t$'\t' -k1,1 -rh
