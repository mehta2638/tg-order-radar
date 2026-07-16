# Runbook: Deploy

## When

Shipping a new release to production VPS.

## Preconditions

- DNS points to the VPS
- `.env.production` present (`chmod 600`)
- Firewall allows 80/443 only for app traffic
- Recent DB backup exists

## Steps

1. SSH to VPS and `cd` to the app directory.
2. `git fetch && git checkout <tag-or-sha>`.
3. `CONFIRM_DEPLOY=yes ENV_FILE=.env.production bash scripts/deploy.sh`.
4. Check:
   - `curl -fsS https://$DOMAIN_APP/health/live`
   - `curl -fsS https://$DOMAIN_APP/health/ready`
   - open admin UI and Grafana

## Rollback

See `docs/runbooks/rollback.md`.
