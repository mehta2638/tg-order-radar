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
- `POST http://localhost:8000/api/v1/sources/{id}/validate` checks public read access through Telethon

## Telegram Authorization

Only public channels and groups are supported. The userbot account is used for read-only validation and later collection; the application does not send messages through it.

Set Telegram credentials in `.env`:

```bash
TG_API_ID=123456
TG_API_HASH=...
TG_PHONE=+10000000000
TG_SESSION_DIR=.telegram-sessions
TG_SESSION_NAME=collector
```

Run the interactive authorization once:

```bash
python -m scripts.auth_telegram
```

Session files are ignored by Git. In Docker Compose they are stored in the dedicated `telegram_sessions` volume.

Placeholder containers for later stages are available:
Start Celery worker and beat for background orchestration:

```bash
docker compose up -d worker collector beat
```

The worker listens to `source_validation`, `telegram_collection`, `message_processing`, `classification`, `duplicate_detection`, `notifications`, and `maintenance`. Stages after source validation currently return explicit `skipped` results until their roadmap stages are implemented.

The `collector` service runs a Celery worker dedicated to `telegram_collection`. Celery beat periodically enqueues public enabled sources with `access_status=ok`; each source is protected by a Redis lease so parallel collector processes do not collect the same source at the same time. First collection backfills the last 7 days plus a 1-day buffer, then later runs collect messages after `last_seen_message_id`.

Message processing is rules-only in the MVP: it normalizes raw text, detects language, applies positive and negative dictionaries, extracts project type, budget, deadline and contacts, stores `message_entities`, and writes `messages.passed_prefilter`. Downstream classification, duplicate detection and notifications stay as later-stage placeholders.

Rules classification assigns `order`, `vacancy`, `service_ad`, `resume`, `partnership`, `spam`, `discussion`, or `irrelevant`, stores `classifications.method=rules`, and calculates `relevance_score` with the section 9 weighted formula. Orders are created only for fresh `order` messages above the configured relevance and confidence thresholds; ML and LLM stages are not used in the MVP.

Basic MVP deduplication links repeated orders within the 7-day freshness window by exact Telegram identity, normalized `content_hash`, and a deterministic fingerprint from normalized text, contacts, budget, and project type. Duplicate groups choose a canonical order by earliest publication time, then completeness, relevance, and order id; only canonical orders are enqueued for notifications.

MVP REST API under `/api/v1` uses simple API-key auth via `X-API-Key` with `admin`, `operator`, and `viewer` roles. It includes order list/detail/status/export endpoints, favorites, keyword and negative keyword CRUD with dictionary cache invalidation, and `/api/v1/stats/summary`.

Telegram bot MVP runs as a separate polling process with aiogram 3 (`python -m app.bot.main` or the `bot` compose service). Configure `BOT_TOKEN` and `BOT_ALLOWED_USER_IDS` for local recipients; delivery is deduplicated through `notification_deliveries`, and callbacks can add favorites or mark orders as contacted/irrelevant.

Check worker dependencies:

```bash
python -m app.workers.health
```

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
