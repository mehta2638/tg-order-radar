#!/usr/bin/env bash
# Production deploy helper. Does not run unless CONFIRM_DEPLOY=yes.
# Intended for VPS use after images are built/pushed.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT_DIR}"

# shellcheck source=lib/docker_compose.sh
source "${ROOT_DIR}/scripts/lib/docker_compose.sh"
resolve_docker_compose

ENV_FILE="${ENV_FILE:-.env.production}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
DRY_RUN="${DRY_RUN:-false}"

if [ ! -f "${ENV_FILE}" ]; then
  echo "Missing ${ENV_FILE}. Copy .env.production.example and fill secrets." >&2
  exit 1
fi

compose() {
  "${DOCKER_COMPOSE[@]}" -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" "$@"
}

echo "Validating compose config..."
compose config >/dev/null

if [ "${DRY_RUN}" = "true" ]; then
  echo "DRY_RUN=true; skipping deploy actions."
  exit 0
fi

if [ "${CONFIRM_DEPLOY:-}" != "yes" ]; then
  echo "Refusing deploy: set CONFIRM_DEPLOY=yes (and optionally DRY_RUN=true)." >&2
  exit 2
fi

echo "Building images..."
compose build

echo "Running migrations via migrate service..."
compose up migrate --abort-on-container-exit

echo "Starting stack..."
compose up -d --remove-orphans

echo "Waiting for API health..."
for _ in $(seq 1 60); do
  if compose exec -T api curl -fsS http://127.0.0.1:8000/health/ready >/dev/null 2>&1; then
    echo "DEPLOY_OK"
    exit 0
  fi
  sleep 2
done

echo "API readiness check failed." >&2
exit 1
