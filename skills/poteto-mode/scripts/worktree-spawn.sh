#!/usr/bin/env bash
# Ephemeral git worktree manager for Antigravity subagents and swarms.
# Creates, lists, doctors, and prunes subagent worktrees under .agents/worktrees/.
#
# Usage:
#   worktree-spawn.sh create <task-id> [base-branch]
#   worktree-spawn.sh cleanup <task-id> [--force]
#   worktree-spawn.sh list
#   worktree-spawn.sh path <task-id>
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$repo_root" ]; then
	echo "error: not inside a git repository" >&2
	exit 1
fi

worktree_base="$repo_root/.agents/worktrees"

validate_task_id() {
	local tid="$1"
	if [ -z "$tid" ]; then
		echo "error: task-id is required" >&2
		exit 1
	fi
	if ! [[ "$tid" =~ ^[a-zA-Z0-9_-]+$ ]]; then
		echo "error: invalid task-id format: '$tid' (must match ^[a-zA-Z0-9_-]+$)" >&2
		exit 1
	fi
}

cmd="${1:-help}"

case "$cmd" in
	create)
		task_id="${2:-}"
		base_ref="${3:-HEAD}"
		validate_task_id "$task_id"

		target_dir="$worktree_base/$task_id"
		branch_name="agent/$task_id"

		if [ -d "$target_dir" ]; then
			echo "warn: worktree directory already exists at $target_dir" >&2
			echo "$target_dir"
			exit 0
		fi

		mkdir -p "$worktree_base"

		# Clean up any leftover branch with the same name if not in a worktree
		if git show-ref --verify --quiet "refs/heads/$branch_name"; then
			git branch -D "$branch_name" >/dev/null 2>&1 || true
		fi

		git worktree add -b "$branch_name" "$target_dir" "$base_ref" --quiet
		echo "$target_dir"
		;;

	cleanup)
		task_id="${2:-}"
		force="${3:-}"
		validate_task_id "$task_id"

		target_dir="$worktree_base/$task_id"
		branch_name="agent/$task_id"

		if [ -d "$target_dir" ]; then
			if [ "$force" = "--force" ]; then
				git worktree remove --force "$target_dir" --quiet 2>/dev/null || rm -rf "$target_dir"
			else
				git worktree remove "$target_dir" --quiet
			fi
		fi

		git worktree prune --expire now --quiet

		if git show-ref --verify --quiet "refs/heads/$branch_name"; then
			git branch -D "$branch_name" >/dev/null 2>&1 || true
		fi

		echo "cleaned: $task_id"
		;;

	list)
		if [ ! -d "$worktree_base" ]; then
			echo "[]"
			exit 0
		fi
		git worktree list --porcelain | awk '
			function emit_record() {
				if (wt != "" && index(wt, "/.agents/worktrees/") > 0) {
					if (!first) printf ",\n"
					gsub(/\\/, "\\\\", wt); gsub(/"/, "\\\"", wt)
					gsub(/\\/, "\\\\", head); gsub(/"/, "\\\"", head)
					gsub(/\\/, "\\\\", branch); gsub(/"/, "\\\"", branch)
					printf "  {\"path\":\"%s\",\"head\":\"%s\",\"branch\":\"%s\"}", wt, head, branch
					first = 0
				}
				wt = ""; head = ""; branch = "detached"
			}
			BEGIN { printf "[\n"; first = 1; wt = ""; head = ""; branch = "detached" }
			/^worktree / { emit_record(); wt = substr($0, 10) }
			/^HEAD / { head = substr($0, 6) }
			/^branch / { branch = substr($0, 8) }
			/^detached/ { branch = "detached" }
			END { emit_record(); printf "\n]\n" }
		'
		;;

	path)
		task_id="${2:-}"
		validate_task_id "$task_id"
		echo "$worktree_base/$task_id"
		;;

	*)
		echo "Usage: $0 {create <task-id> [base]|cleanup <task-id> [--force]|list|path <task-id>}" >&2
		exit 1
		;;
esac
