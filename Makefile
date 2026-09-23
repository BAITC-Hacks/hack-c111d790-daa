.PHONY: install dev api build test lint benchmark demo

install:
	python3 -m venv .venv
	.venv/bin/python -m pip install -r requirements.lock
	.venv/bin/python -m pip install -e . --no-deps
	npm ci

dev:
	npm run dev

api:
	.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

build:
	npm run build

test:
	.venv/bin/python -m pytest -q

lint:
	.venv/bin/ruff check backend scripts tests
	npm run format:check

benchmark:
	.venv/bin/python -m scripts.evaluate

demo:
	.venv/bin/python -m scripts.dataset demo --output data/demo.json

partner-benchmark:
	.venv/bin/python -m scripts.evaluate_partners
