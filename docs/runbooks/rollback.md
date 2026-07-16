# Runbook: Rollback

## When

A release causes errors, readiness failures, or severe regressions.

## Steps

1. Identify last known good git ref/tag.
2. Ensure a DB backup exists if the release included migrations.
3. Run:
   ```bash
   CONFIRM_ROLLBACK=yes ENV_FILE=.env.production bash scripts/rollback.sh <good-ref>
   ```
4. Verify `/health/ready` and critical user flows.

## Notes

- Application rollback does not automatically downgrade Alembic revisions.
- If a migration is incompatible, restore DB from backup onto a staging clone first, then plan a forward fix.
