.PHONY: install web lint type test web-test check run dev

install:
	python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
	cd frontend && npm ci

web:
	cd frontend && npm run build

lint:
	.venv/bin/ruff check . && .venv/bin/ruff format --check .

type:
	.venv/bin/mypy && cd frontend && npm run typecheck

test:
	.venv/bin/pytest -q

web-test:
	cd frontend && npm test

check: lint type test web-test

# Build the UI and serve everything from one process at http://127.0.0.1:8000
run: web
	.venv/bin/uvicorn kept.api.app:create_app --factory --port 8000

# Hot-reloading UI at :5173 (proxies /api to :8000, so run the API alongside)
dev:
	cd frontend && npm run dev
