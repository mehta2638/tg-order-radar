#!/usr/bin/env bash
# End-to-end backup/restore drill on a temporary PostgreSQL container.
# Does NOT touch docker-compose project volumes or production data.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WORKDIR="${TMPDIR:-/tmp}/tg-order-radar-backup-drill-$$"
IMAGE="${BACKUP_TEST_IMAGE:-pgvector/pgvector:pg16}"
CONTAINER="tg-order-radar-backup-drill-$$"
DB_NAME="drill_db"
DB_USER="drill"
DB_PASSWORD="drill-pass-not-for-prod"

cleanup() {
  docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
  rm -rf "${WORKDIR}"
}
trap cleanup EXIT

mkdir -p "${WORKDIR}/backups"
echo "Starting temporary Postgres (${CONTAINER})..."
docker run -d --name "${CONTAINER}" \
  -e POSTGRES_DB="${DB_NAME}" \
  -e POSTGRES_USER="${DB_USER}" \
  -e POSTGRES_PASSWORD="${DB_PASSWORD}" \
  "${IMAGE}" >/dev/null

for _ in $(seq 1 30); do
  if docker exec "${CONTAINER}" pg_isready -U "${DB_USER}" -d "${DB_NAME}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "Seeding temporary database..."
docker exec -i "${CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" <<'SQL'
create table if not exists drill_orders (
  id serial primary key,
  title text not null
);
insert into drill_orders (title) values ('backup-restore-smoke');
SQL

echo "Creating dump..."
docker exec -e PGPASSWORD="${DB_PASSWORD}" "${CONTAINER}" \
  pg_dump -U "${DB_USER}" -d "${DB_NAME}" --format=plain --no-owner \
  | gzip -c > "${WORKDIR}/backups/drill.sql.gz"

echo "Recreating empty database..."
docker exec -e PGPASSWORD="${DB_PASSWORD}" "${CONTAINER}" \
  psql -U "${DB_USER}" -d postgres -v ON_ERROR_STOP=1 \
  -c "select pg_terminate_backend(pid) from pg_stat_activity where datname='${DB_NAME}' and pid <> pg_backend_pid();" \
  -c "drop database ${DB_NAME};" \
  -c "create database ${DB_NAME} owner ${DB_USER};"

echo "Restoring dump..."
gunzip -c "${WORKDIR}/backups/drill.sql.gz" \
  | docker exec -i -e PGPASSWORD="${DB_PASSWORD}" "${CONTAINER}" \
    psql -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 >/dev/null

COUNT="$(docker exec -e PGPASSWORD="${DB_PASSWORD}" "${CONTAINER}" \
  psql -U "${DB_USER}" -d "${DB_NAME}" -Atc "select count(*) from drill_orders where title='backup-restore-smoke';")"

if [ "${COUNT}" != "1" ]; then
  echo "BACKUP_RESTORE_SMOKE_FAILED count=${COUNT}" >&2
  exit 1
fi

echo "BACKUP_RESTORE_SMOKE_OK"
