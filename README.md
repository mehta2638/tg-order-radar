# TG Order Radar

TG Order Radar is a Python service for finding website development orders in public Telegram channels and groups.

This repository is currently at stage 1: repository scaffold and local infrastructure. Domain models, Telegram collection, Celery tasks, and notification logic are intentionally not implemented yet.

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

Health endpoints:

- `GET http://localhost:8000/health/live`
- `GET http://localhost:8000/health/ready`

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
  models/     SQLAlchemy models for later stages
  schemas/    Pydantic schemas
  services/   Business services
  workers/    Background worker package for later stages
tests/
  unit/
  integration/
```
