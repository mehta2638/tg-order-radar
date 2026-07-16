# Runbook: Backup and restore

## Backup

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production --profile backup run --rm backup
```

Artifacts land in `./backups/` (gitignored):

- `postgres_*.sql.gz` (+ `.sha256`)
- optional encrypted sessions archive when `SESSION_ENC_KEY` is set

Copy backups off-box daily.

## Restore drill (safe)

Uses a temporary container and never touches project volumes:

```bash
bash scripts/test_backup_restore.sh
# Or (preferred on Windows when Docker Desktop/Rancher is used):
python scripts/test_backup_restore.py
```

Expect: `BACKUP_RESTORE_SMOKE_OK`.

## Production restore (dangerous)

Only after explicit confirmation and preferably on a restored staging host:

```bash
CONFIRM_RESTORE=yes \
POSTGRES_HOST=postgres POSTGRES_DB=tg_order_radar POSTGRES_USER=tg_order_radar \
PGPASSWORD='***' \
bash scripts/restore_postgres.sh backups/postgres_....sql.gz
```

## Session archive decrypt

```bash
openssl enc -d -aes-256-cbc -pbkdf2 \
  -in sessions_....tar.gz.enc \
  -out sessions_....tar.gz \
  -pass pass:"$SESSION_ENC_KEY"
```
