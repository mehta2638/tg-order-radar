.PHONY: setup up down logs lint format typecheck test compose-config build

setup:
	python -m pip install --upgrade pip
	python -m pip install -e ".[dev]"

up:
	docker compose up -d postgres redis api

down:
	docker compose down

logs:
	docker compose logs -f

lint:
	python -m ruff check .

format:
	python -m ruff format .

typecheck:
	python -m mypy app

test:
	python -m pytest -q

compose-config:
	docker compose config

build:
	docker compose build
