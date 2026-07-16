# Runbook: Incident response (short)

1. Check Traefik / API readiness: `/health/live`, `/health/ready`.
2. Check Grafana dashboard **TG Order Radar Overview** and Prometheus alerts.
3. Check Sentry for new issues (if `SENTRY_DSN` configured).
4. Inspect Celery workers and `failed_tasks` table/DLQ growth.
5. If release-related: rollback via `docs/runbooks/rollback.md`.
6. If data-related: stop writes if needed, restore from backup on staging, then decide production restore.
7. Record timeline in `audit_logs` / ops notes; rotate compromised secrets.
