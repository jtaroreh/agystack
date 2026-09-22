.PHONY: test lint doctor clean

test:
	pytest -v tests/

lint:
	ruff check .

doctor:
	python3 skills/setup-agystack/scripts/setup_runtime.py --doctor

clean:
	rm -rf .pytest_cache .ruff_cache __pycache__ *.egg-info dist build
