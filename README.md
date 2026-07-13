# TG Order Radar

TG Order Radar is a Python service for finding website development orders in public Telegram channels and groups.

This repository is currently at stage 2: repository scaffold, local infrastructure, database models, and Alembic migrations. Telegram collection, Celery tasks, source CRUD, and notification logic are intentionally not implemented yet.

## Requirements

- Python 3.12
- Docker and Docker Compose
- Git

## Local Setup

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Create a local environment file when you need to override defaults:

```bash
cp .env.example .env
```

Do not put real secrets into Git.

## Run Locally

Start PostgreSQL, Redis, and the API:

```bash
docker compose up -d postgres redis api
```

Apply database migrations and seed base dictionaries:

```bash
python -m alembic upgrade head
python -m scripts.seed_keywords
```

Health endpoints:

- `GET http://localhost:8000/health/live`
- `GET http://localhost:8000/health/ready`

Source endpoints:

- `POST http://localhost:8000/api/v1/sources` with body `{"link":"@public_channel"}`
- `GET http://localhost:8000/api/v1/sources?page=1&size=20`
- `GET http://localhost:8000/api/v1/sources/{id}`
- `PATCH http://localhost:8000/api/v1/sources/{id}` with body `{"enabled":false}`
- `DELETE http://localhost:8000/api/v1/sources/{id}` disables collection for the source

Placeholder containers for later stages are available:

```bash
docker compose up -d collector worker bot
```

They use the same application image and run safe no-op commands.

## Development Commands

```bash
python -m ruff format .
python -m ruff check .
python -m mypy app
python -m pytest -q
docker compose config
docker compose build
python -m alembic upgrade head
```

The Makefile exposes the same commands as `make format`, `make lint`, `make typecheck`, `make test`, `make compose-config`, and `make build`.

## Project Layout

```text
app/
  api/        FastAPI routers
  bot/        Notification bot package for later stages
  collector/  Telegram collector package for later stages
  core/       Settings, logging, middleware
  db/         Async database setup for later stages
  models/     SQLAlchemy 2.0 typed models
  schemas/    Pydantic schemas
  services/   Business services
  workers/    Background worker package for later stages
tests/
  unit/
  integration/
migrations/
  versions/   Alembic revisions
scripts/
  seed_keywords.py
```
