.PHONY: install lint type test check run

install:
	python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

lint:
	.venv/bin/ruff check . && .venv/bin/ruff format --check .

type:
	.venv/bin/mypy

test:
	.venv/bin/pytest -q

check: lint type test

run:
	.venv/bin/uvicorn kept.api.app:create_app --factory --reload
