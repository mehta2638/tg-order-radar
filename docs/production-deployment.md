# Production deployment

This document describes the Stage 20 production path for TG Order Radar.
It prepares infrastructure in-repo; it does **not** perform a live deploy for you.

## Architecture

```text
Internet
   |
   v
 Traefik (:80/:443, Let's Encrypt ACME)
   |-- Host(DOMAIN_APP) /            -> frontend
   |-- Host(DOMAIN_APP) /api,/health,/metrics -> api
   |-- Host(DOMAIN_GRAFANA)          -> grafana
   |
Internal Docker network (no public ports)
   |-- postgres (pgvector)
   |-- redis
   |-- api / worker / collector / beat / bot
   |-- prometheus
   |-- migrate (one-shot)
```

## Services in `docker-compose.prod.yml`

| Service | Role |
|---------|------|
| `traefik` | Reverse proxy + TLS |
| `frontend` | Next.js admin UI |
| `api` | FastAPI |
| `migrate` | `alembic upgrade head` before app start |
| `worker` | Celery processing queues |
| `collector` | Telegram collection worker |
| `beat` | Celery beat |
| `bot` | Notification bot |
| `postgres` | PostgreSQL + pgvector |
| `redis` | Broker/cache |
| `prometheus` | Metrics |
| `grafana` | Dashboards |
| `backup` | Optional profile for `pg_dump` |

## Secrets and sessions

1. Copy `.env.production.example` → `.env.production` on the VPS.
2. `chmod 600 .env.production`.
3. Never commit `.env.production`, Telegram `*.session`, `backups/`, or `acme.json`.
4. Telegram sessions live in Docker volume `telegram_sessions` (mode `0600` at host FS if bind-mounted).
5. `SESSION_ENC_KEY` encrypts **session backup archives** with OpenSSL (AES-256-CBC), not Telethon runtime files.
6. Prefer disk encryption (LUKS) for the VPS volume that holds Postgres/sessions.

## TLS / domains

- Traefik obtains certificates via Let's Encrypt HTTP-01 (`certificatesresolvers.le`).
- Set `DOMAIN_APP`, `DOMAIN_GRAFANA`, `ACME_EMAIL` to real values before public deploy.
- Security headers/HSTS are applied through `deploy/traefik/dynamic.yml`.
- Do not request production certificates during local smoke tests; use `docker-compose.prod.local.yml`.

## First deploy (VPS)

1. Harden the VPS (`docs/vps-hardening.md`).
2. Install Docker Engine + Compose plugin.
3. Clone repository to e.g. `/opt/tg-order-radar`.
4. Create `.env.production` from `.env.production.example` and fill secrets.
5. Point DNS A/AAAA records for `DOMAIN_APP` and `DOMAIN_GRAFANA` to the VPS.
6. Open only `80/tcp` and `443/tcp` publicly.
7. Run:
   ```bash
   CONFIRM_DEPLOY=yes ENV_FILE=.env.production bash scripts/deploy.sh
   ```
8. Verify:
   - `https://DOMAIN_APP/health/live`
   - `https://DOMAIN_APP/health/ready`
   - admin UI loads
   - Grafana at `https://DOMAIN_GRAFANA`

## Repeat deploy

```bash
git pull
CONFIRM_DEPLOY=yes ENV_FILE=.env.production bash scripts/deploy.sh
```

Migrations run via the `migrate` service before API/workers start.

## Rollback

```bash
CONFIRM_ROLLBACK=yes ENV_FILE=.env.production bash scripts/rollback.sh <git-ref>
```

Notes:
- Rollback restores application code/images for that ref.
- DB migrations are generally forward-only; keep restore backups before risky schema changes.

## Backup and restore

Manual backup (profile):

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production --profile backup run --rm backup
```

Restore is intentionally gated:

```bash
CONFIRM_RESTORE=yes \
POSTGRES_HOST=... POSTGRES_DB=... POSTGRES_USER=... PGPASSWORD=... \
bash scripts/restore_postgres.sh backups/postgres_....sql.gz
```

Always practice restore on a non-production database first:

```bash
bash scripts/test_backup_restore.sh
# Windows / when Docker is not reachable from WSL bash:
python scripts/test_backup_restore.py
```

## CI/CD

- `.github/workflows/ci.yml` — lint, tests, compose validation, image builds.
- `.github/workflows/deploy.yml` — manual template (defaults to dry-run).
- `.github/workflows/secret-guard.yml` — blocks tracked secret/backup paths.
- Dependabot updates Python/npm/actions/docker weekly.

## Local validation without ACME

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production.example config
docker compose -f docker-compose.prod.yml --env-file .env.production.example build
docker compose -f docker-compose.prod.yml -f docker-compose.prod.local.yml --env-file .env.production.example config
```
