PORT ?= 8000

.PHONY: install web lint type test web-test check run dev demo sample-mbox rehearse

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

# Build the UI and serve everything from one process at http://127.0.0.1:8000 (PORT=8002 make run)
run: web
	.venv/bin/uvicorn kept.api.app:create_app --factory --port $(PORT)

# A fresh local copy for recording the demo video: an empty ledger in its own database file.
demo: web
	rm -f data/video.db data/video.db-*
	KEPT_DB_PATH=data/video.db .venv/bin/uvicorn kept.api.app:create_app --factory --port $(PORT)

# The synthetic sample inbox as a real .mbox file (data/sample-inbox.mbox), dated for today.
sample-mbox:
	.venv/bin/python scripts/make_sample_mbox.py

# Run the demo video's flow against the real models, with timings. Add SMTP=1 to test the mail login.
rehearse:
	.venv/bin/python scripts/rehearse_demo.py $(if $(SMTP),--smtp)

# Hot-reloading UI at :5173 (proxies /api to :8000, so run the API alongside)
dev:
	cd frontend && npm run dev
