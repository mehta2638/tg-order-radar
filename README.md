# TG Order Radar

TG Order Radar is a Python service for finding website development orders in public Telegram channels and groups. The current MVP can validate public sources, collect recent messages, process and classify them with rules, deduplicate orders, expose a REST API, and send Telegram bot notifications.

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

Start infrastructure and application processes:

```bash
docker compose up -d postgres redis
```

Apply database migrations and seed base dictionaries:

```bash
python -m alembic upgrade head
python -m scripts.seed_keywords
```

Authorize the read-only Telegram userbot once if you plan to validate or collect real public sources:

```bash
python -m scripts.auth_telegram
```

Start API, Celery workers, scheduler, collector queue worker, and bot polling:

```bash
docker compose up -d api worker collector beat bot
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

Start Celery worker and beat for background orchestration:

```bash
docker compose up -d worker collector beat
```

The worker listens to `source_validation`, `telegram_collection`, `message_processing`, `classification`, `duplicate_detection`, `notifications`, and `maintenance`.

The `collector` service runs a Celery worker dedicated to `telegram_collection`. Celery beat periodically enqueues public enabled sources with `access_status=ok`; each source is protected by a Redis lease so parallel collector processes do not collect the same source at the same time. First collection backfills the last 7 days plus a 1-day buffer, then later runs collect messages after `last_seen_message_id`.

Message processing normalizes raw text, detects language, applies positive and negative dictionaries, extracts project type, budget, deadline and contacts, stores `message_entities`, and writes `messages.passed_prefilter`. Classification, duplicate detection, and notifications are handled by downstream Celery queues.

Rules classification assigns `order`, `vacancy`, `service_ad`, `resume`, `partnership`, `spam`, `discussion`, or `irrelevant`, stores `classifications.method=rules`, and calculates `relevance_score` with the section 9 weighted formula. Orders are created only for fresh `order` messages above the configured relevance and confidence thresholds.

The optional ML classifier uses scikit-learn TF-IDF word/char n-grams with Logistic Regression and safe rules fallback. It is disabled by default and is never trained automatically on API, worker, or test startup. Configure it with:

```text
ML_CLASSIFICATION_ENABLED=false
ML_MODEL_ARTIFACT_PATH=artifacts/ml/classifier.joblib
ML_MIN_CONFIDENCE=0.7
ML_MODEL_VERSION=
```

The local training dataset is `tests/fixtures/rules_regression_dataset.json`. Train and evaluate a local artifact manually:

```bash
python -m scripts.ml_classifier baseline --dataset tests/fixtures/rules_regression_dataset.json
python -m scripts.ml_classifier train --dataset tests/fixtures/rules_regression_dataset.json --artifact artifacts/ml/classifier.joblib --model-version local-v1
python -m scripts.ml_classifier evaluate --dataset tests/fixtures/rules_regression_dataset.json --artifact artifacts/ml/classifier.joblib
```

Artifacts under `artifacts/` are ignored by Git. Each artifact contains `model_version`, `trained_at`, class list, feature schema version, holdout metrics, confusion matrix, and dataset checksum.

Semantic dedup is an optional expensive layer after exact `content_hash` and deterministic fingerprint dedup. It uses pgvector plus the compact multilingual `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` model (384 dimensions), and is disabled by default:

```text
SEMANTIC_DEDUP_ENABLED=false
SEMANTIC_MODEL_NAME=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
SEMANTIC_MODEL_VERSION=paraphrase-multilingual-MiniLM-L12-v2
SEMANTIC_EMBEDDING_DIMENSION=384
SEMANTIC_SIMILARITY_THRESHOLD=0.9
SEMANTIC_REVIEW_THRESHOLD=0.82
SEMANTIC_DEDUP_WINDOW_DAYS=7
SEMANTIC_BATCH_SIZE=32
SEMANTIC_DEVICE=
```

The compose PostgreSQL image is `pgvector/pgvector:pg16`. Existing volumes are not removed automatically; if an existing local database was created from plain `postgres:16`, recreate only the postgres container (`docker compose up -d postgres --force-recreate --no-deps`) without deleting the volume, then ensure `CREATE EXTENSION vector` and the `orders.semantic_embedding*` columns exist. Until then semantic dedup stays in safe fallback. Docker images install CPU `torch` to keep builds practical. Semantic embeddings are stored on `orders.semantic_embedding` for canonical order candidates only.

Semantic utility commands:

```bash
python -m scripts.semantic_dedup check-model
python -m scripts.semantic_dedup embed --text "Нужен лендинг для курса"
python -m scripts.semantic_dedup search --text "Ищу исполнителя на посадочную страницу"
python -m scripts.semantic_dedup backfill --dry-run --batch-size 100
python -m scripts.semantic_dedup backfill --batch-size 100
```

Basic MVP deduplication links repeated orders within the 7-day freshness window by exact Telegram identity, normalized `content_hash`, and a deterministic fingerprint from normalized text, contacts, budget, and project type. Duplicate groups choose a canonical order by earliest publication time, then completeness, relevance, and order id; only canonical orders are enqueued for notifications.

MVP REST API under `/api/v1` uses simple API-key auth via `X-API-Key` with `admin`, `operator`, and `viewer` roles. It includes order list/detail/status/export endpoints, favorites, keyword and negative keyword CRUD with dictionary cache invalidation, and `/api/v1/stats/summary`.

Telegram bot MVP runs as a separate polling process with aiogram 3 (`python -m app.bot.main` or the `bot` compose service). Configure `BOT_TOKEN` and `BOT_ALLOWED_USER_IDS` for local recipients; delivery is deduplicated through `notification_deliveries`, and callbacks can add favorites or mark orders as contacted/irrelevant.

## MVP Walkthrough

1. Configure `.env` with PostgreSQL/Redis defaults, `TG_API_ID`, `TG_API_HASH`, `TG_PHONE`, `BOT_TOKEN`, and comma-separated `BOT_ALLOWED_USER_IDS`.
2. Run `python -m alembic upgrade head` and `python -m scripts.seed_keywords`.
3. Start services with `docker compose up -d api worker collector beat bot`.
4. Add a source:

```bash
curl -X POST http://localhost:8000/api/v1/sources \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-admin-key" \
  -d "{\"link\":\"https://t.me/public_channel\"}"
```

5. Validate it through `POST /api/v1/sources/{source_id}/validate` or wait for beat to enqueue pending validations.
6. The collector reads the last 7 days plus buffer, processing/classification creates fresh high-relevance orders, duplicate detection chooses the canonical order, and the notifications queue sends one bot message per allowed recipient.
7. Use bot buttons to add favorites or mark an order as contacted/irrelevant.
8. Verify results with `GET /api/v1/orders`, `/api/v1/favorites`, and `/api/v1/stats/summary`.

Useful API headers:

```text
X-API-Key: dev-admin-key
X-API-Key: dev-operator-key
X-API-Key: dev-viewer-key
```

## Admin Panel

The minimal Next.js admin panel lives in `frontend/`.

```bash
cd frontend
npm install
copy .env.example .env.local
npm run dev
```

Configure the backend URL with:

```text
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Open `http://localhost:3000/login`, enter one of the backend API keys, and use the Orders, Sources, Keywords, and Statistics pages.

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

Opt-in checks:

```bash
set RUN_MVP_REAL_SMOKE=1
set TG_PUBLIC_TEST_SOURCE=https://t.me/public_channel
python -m pytest -q tests/integration/test_mvp_real_smoke_opt_in.py
```

The Makefile exposes the same commands as `make format`, `make lint`, `make typecheck`, `make test`, `make compose-config`, and `make build`.

## Project Layout

```text
app/
  api/        FastAPI routers
  bot/        Telegram notification bot
  collector/  Telegram collector
  core/       Settings, logging, middleware
  db/         Async database setup
  models/     SQLAlchemy 2.0 typed models
  schemas/    Pydantic schemas
  services/   Business services
  workers/    Background worker package
tests/
  unit/
  integration/
frontend/
  src/app/     Next.js admin pages
  src/lib/     Typed API client
migrations/
  versions/   Alembic revisions
scripts/
  seed_keywords.py
```
