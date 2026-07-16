#!/usr/bin/env bash
# Restore a logical PostgreSQL dump into a target database.
# DANGEROUS against production. Prefer scripts/test_backup_restore.sh for drills.
set -euo pipefail

DUMP_FILE="${1:-}"
if [ -z "${DUMP_FILE}" ] || [ ! -f "${DUMP_FILE}" ]; then
  echo "Usage: $0 /path/to/postgres_*.sql.gz" >&2
  exit 1
fi

POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-tg_order_radar}"
POSTGRES_USER="${POSTGRES_USER:-tg_order_radar}"
CONFIRM_RESTORE="${CONFIRM_RESTORE:-}"

if [ "${CONFIRM_RESTORE}" != "yes" ]; then
  echo "Refusing restore: set CONFIRM_RESTORE=yes to continue." >&2
  exit 2
fi

if [ -f "${DUMP_FILE}.sha256" ]; then
  echo "Verifying checksum..."
  (cd "$(dirname "${DUMP_FILE}")" && sha256sum -c "$(basename "${DUMP_FILE}.sha256")")
fi

echo "Restoring ${DUMP_FILE} into ${POSTGRES_DB} on ${POSTGRES_HOST}"
gunzip -c "${DUMP_FILE}" | psql \
  --host="${POSTGRES_HOST}" \
  --port="${POSTGRES_PORT}" \
  --username="${POSTGRES_USER}" \
  --dbname="${POSTGRES_DB}" \
  --v ON_ERROR_STOP=1

echo "RESTORE_OK ${POSTGRES_DB}"
