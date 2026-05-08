.PHONY: bootstrap up down migrate seed run test lint typecheck proto clean

PYTHON ?= python3.12
PIP ?= $(PYTHON) -m pip

bootstrap:
	$(PIP) install -e ".[dev]"

up:
	docker compose up -d postgres

down:
	docker compose down

migrate:
	alembic upgrade head

seed:
	$(PYTHON) scripts/seed_local.py

run:
	uvicorn tigeri.api.app:create_app --factory --host 0.0.0.0 --port 8000 --reload

test:
	pytest -v

lint:
	ruff check src tests

typecheck:
	mypy src

proto:
	cd src/tigeri/a2a && python -m grpc_tools.protoc -I. --python_out=. envelope.proto

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info
