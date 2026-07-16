#!/usr/bin/env bash
# Logical PostgreSQL backup (+ optional encrypted session tarball).
# Safe: never deletes volumes. Writes only under BACKUP_DIR.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-tg_order_radar}"
POSTGRES_USER="${POSTGRES_USER:-tg_order_radar}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${BACKUP_DIR}"

DUMP_FILE="${BACKUP_DIR}/postgres_${POSTGRES_DB}_${TIMESTAMP}.sql.gz"
echo "Creating database dump: ${DUMP_FILE}"
pg_dump \
  --host="${POSTGRES_HOST}" \
  --port="${POSTGRES_PORT}" \
  --username="${POSTGRES_USER}" \
  --dbname="${POSTGRES_DB}" \
  --format=plain \
  --no-owner \
  --no-privileges \
  | gzip -c > "${DUMP_FILE}"

sha256sum "${DUMP_FILE}" > "${DUMP_FILE}.sha256"
echo "Database dump complete."

SESSIONS_DIR="${SESSIONS_DIR:-/sessions}"
if [ -d "${SESSIONS_DIR}" ] && [ -n "$(ls -A "${SESSIONS_DIR}" 2>/dev/null || true)" ]; then
  SESSION_TAR="${BACKUP_DIR}/sessions_${TIMESTAMP}.tar.gz"
  echo "Archiving Telegram sessions: ${SESSION_TAR}"
  tar -czf "${SESSION_TAR}" -C "${SESSIONS_DIR}" .
  if [ -n "${SESSION_ENC_KEY:-}" ]; then
    ENC_FILE="${SESSION_TAR}.enc"
    echo "Encrypting sessions archive with SESSION_ENC_KEY"
    openssl enc -aes-256-cbc -salt -pbkdf2 \
      -in "${SESSION_TAR}" \
      -out "${ENC_FILE}" \
      -pass "pass:${SESSION_ENC_KEY}"
    rm -f "${SESSION_TAR}"
    sha256sum "${ENC_FILE}" > "${ENC_FILE}.sha256"
    echo "Encrypted sessions archive: ${ENC_FILE}"
  else
    sha256sum "${SESSION_TAR}" > "${SESSION_TAR}.sha256"
    echo "SESSION_ENC_KEY unset; sessions archive left unencrypted (dev/test only)."
  fi
fi

echo "BACKUP_OK ${DUMP_FILE}"
