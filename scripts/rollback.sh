#!/usr/bin/env bash
# Rollback helper: redeploy a previously known image tag / git ref.
# Does not delete volumes. Requires CONFIRM_ROLLBACK=yes.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT_DIR}"

# shellcheck source=lib/docker_compose.sh
source "${ROOT_DIR}/scripts/lib/docker_compose.sh"
resolve_docker_compose

ENV_FILE="${ENV_FILE:-.env.production}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
TARGET_REF="${1:-}"

if [ -z "${TARGET_REF}" ]; then
  echo "Usage: $0 <git-ref-or-image-tag>" >&2
  exit 1
fi

if [ "${CONFIRM_ROLLBACK:-}" != "yes" ]; then
  echo "Refusing rollback: set CONFIRM_ROLLBACK=yes" >&2
  exit 2
fi

if [ ! -f "${ENV_FILE}" ]; then
  echo "Missing ${ENV_FILE}" >&2
  exit 1
fi

echo "Checking out ${TARGET_REF} (local git tree)..."
git rev-parse --verify "${TARGET_REF}" >/dev/null
git checkout "${TARGET_REF}"

"${DOCKER_COMPOSE[@]}" -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" build
"${DOCKER_COMPOSE[@]}" -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" up migrate --abort-on-container-exit
"${DOCKER_COMPOSE[@]}" -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" up -d --remove-orphans

echo "ROLLBACK_OK ${TARGET_REF}"
echo "Note: database migrations are forward-only unless a dedicated downgrade plan exists."
