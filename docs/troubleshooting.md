# Troubleshooting

## Docker Or PostgreSQL Is Not Available

Symptoms:

- Integration tests are skipped with `PostgreSQL is not available`.
- API readiness returns database errors.
- `docker compose build` or `docker compose up` fails before services start.

Checks:

```bash
docker compose ps
docker compose logs postgres
docker compose logs redis
python -m alembic upgrade head
```

Fixes:

- Start Docker Desktop and wait until it is fully ready.
- Recreate local services with `docker compose up -d postgres redis`.
- If a test database is stuck, stop running tests and rerun them after PostgreSQL accepts connections.

## Telegram Validation Fails

Symptoms:

- Source validation returns `TELEGRAM_NOT_CONFIGURED`.
- Source validation returns `TELEGRAM_ACCOUNT_NOT_AUTHORIZED`.
- Source status becomes `private`, `not_found`, `floodwait`, or `error`.

Checks:

```bash
python -m scripts.auth_telegram
python -m pytest -q tests/integration/test_telethon_real_opt_in.py
```

Fixes:

- Set `TG_API_ID`, `TG_API_HASH`, and `TG_PHONE` in `.env`.
- Run `python -m scripts.auth_telegram` once on the same machine/session volume.
- Use only public `t.me/<username>` sources. Private invite links (`+...`, `joinchat`, `c/...`) are rejected by design.
- For `floodwait`, wait until `pause_until` before retrying.

## Collector Does Not Save Messages

Checks:

```bash
docker compose logs collector
docker compose logs beat
docker compose logs worker
```

Common causes:

- Source is not `enabled`, not public, or `access_status != ok`.
- Telegram account is unauthorized.
- Source is paused because of `floodwait`.
- Redis lease is held by another collector run.
- Messages are older than the initial backfill window.

## Orders Are Not Created

Common causes:

- Message did not pass prefilter (`messages.passed_prefilter=false`).
- Negative keywords matched service ads/resumes.
- Classification confidence or relevance score is below configured thresholds.
- Message is older than the freshness window.

Useful settings:

```text
CLASSIFICATION_ORDER_MIN_CONFIDENCE
ORDER_MIN_RELEVANCE_SCORE
RELEVANCE_FRESHNESS_DAYS
```

## Bot Does Not Send Notifications

Checks:

```bash
docker compose logs bot
docker compose logs worker
```

Common causes:

- `BOT_TOKEN` is empty or invalid.
- `BOT_ALLOWED_USER_IDS` does not include the recipient Telegram user id and no active `users.tg_chat_id` exists.
- Order is not canonical, not fresh, archived/irrelevant, or below `ORDER_MIN_RELEVANCE_SCORE`.
- `notification_deliveries` already has a row for `(order_id, user_id, bot)`, so repeated delivery is intentionally skipped.

## Bot Buttons Do Nothing

Common causes:

- Callback user id is not in `BOT_ALLOWED_USER_IDS` and is not an active DB user.
- User role is `viewer`; status changes require `operator` or `admin`.
- Order status transition is not allowed by the state machine.

## Worker Crash Or Retry Behavior

Celery is configured with late acknowledgements and worker-lost rejection:

```text
task_acks_late = true
task_reject_on_worker_lost = true
worker_prefetch_multiplier = 1
```

This means a worker crash before task acknowledgement should requeue the task. Delivery and persistence operations are designed to be idempotent, and bot delivery is additionally deduplicated by `notification_deliveries`.

## Useful Full Verification

```bash
python -m ruff format .
python -m ruff check .
python -m mypy app
python -m pytest -q -ra
docker compose config
docker compose build
```
