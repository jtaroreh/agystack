.PHONY: test test-statechart lint typecheck doctor package-check ci clean

test:
	uv run pytest -v --timeout=60 tests/
	cd skills/poteto-mode/scripts && bun test

test-statechart:
	node --test skills/statechart/scripts/test/pipeline.test.ts skills/statechart/scripts/test/messages.test.ts skills/statechart/scripts/test/chart.test.ts skills/statechart/scripts/test/cli.test.ts

lint:
	uv run ruff check .
	bash -n scripts/package-plugin.sh skills/poteto-mode/scripts/worktree-audit.sh skills/show-me-your-work/scripts/log.sh
	@if command -v shellcheck >/dev/null 2>&1; then \
		shellcheck -S warning scripts/package-plugin.sh skills/poteto-mode/scripts/worktree-audit.sh skills/show-me-your-work/scripts/log.sh; \
	else \
		echo "WARNING: shellcheck not found on PATH; skipping shellcheck."; \
	fi

typecheck:
	cd skills/poteto-mode/scripts && bun run typecheck

doctor:
	uv run python skills/setup-agystack/scripts/setup_runtime.py --doctor

package-check:
	bash scripts/package-plugin.sh --test

ci: lint typecheck doctor test package-check

clean:
	rm -rf .pytest_cache .ruff_cache __pycache__ *.egg-info dist build
