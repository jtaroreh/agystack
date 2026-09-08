.PHONY: test lint doctor build-worker clean

test:
	pytest -v tests/

lint:
	ruff check .

doctor:
	python3 skills/setup-agystack/scripts/setup_runtime.py --doctor

clean:
	rm -rf .pytest_cache __pycache__ *.egg-info dist build
