PYTHON ?= .venv/bin/python

.PHONY: dev build build-ui run run-http format lint typecheck test verify

dev:
	cd ui && npm run dev

build: build-ui

build-ui:
	cd ui && npm run build

run:
	$(PYTHON) -m synapse_showcase.server --stdio --data-file workspace/showcase/progress.json

run-http:
	$(PYTHON) -m synapse_showcase.server --http --port 27249 --data-file workspace/showcase/progress.json

format:
	$(PYTHON) -m ruff format --check src/ tests/

lint:
	$(PYTHON) -m ruff check src/ tests/

typecheck:
	$(PYTHON) -m ty check src/
	cd ui && npm run typecheck

test:
	$(PYTHON) -m pytest tests/

verify: format lint typecheck test build-ui
