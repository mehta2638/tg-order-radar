# VPS hardening checklist

Use this before exposing Traefik to the internet. Adjust for your provider.

## Baseline

1. Create a non-root sudo user; disable password SSH root login.
2. SSH keys only (`PasswordAuthentication no`).
3. Keep the OS updated (`unattended-upgrades` or equivalent).
4. Set timezone to UTC.
5. Configure automatic security updates.

## Firewall

Allow only:

- `22/tcp` from your admin IPs (or a VPN/bastion)
- `80/tcp` and `443/tcp` from the world (Traefik)

Example with UFW:

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

Do **not** publish PostgreSQL (`5432`) or Redis (`6379`) on the public interface.
Production Compose keeps them on the internal Docker network only.

## Docker

- Install Docker from the official docs for your distro.
- Add the deploy user to the `docker` group carefully (root-equivalent).
- Prefer Compose project under `/opt/tg-order-radar` owned by the deploy user.
- Ensure `acme.json` permissions are `600` after first Traefik start.

## Secrets

- Store `.env.production` with mode `600`.
- Do not put secrets in git, chat logs, or world-readable files.
- Rotate API keys, DB password, Grafana password, and bot token periodically.
- Enable GitHub secret scanning on the repository.

## Backups

- Schedule daily `pg_dump` (Compose `backup` profile or host cron calling the script).
- Keep encrypted offsite copies (object storage) with retention.
- Run `scripts/test_backup_restore.sh` after major changes.
- Encrypt the disk or volume that stores Postgres data and Telegram sessions.

## Observability

- Keep Sentry DSN configured in production.
- Restrict Grafana to `DOMAIN_GRAFANA` and a strong admin password.
- Prefer IP allow-lists / SSO in front of Grafana for higher assurance.

## Incident readiness

- Document who can SSH and where secrets live.
- Keep at least one tested DB backup younger than 24h.
- Know the rollback command: `CONFIRM_ROLLBACK=yes bash scripts/rollback.sh <ref>`.
