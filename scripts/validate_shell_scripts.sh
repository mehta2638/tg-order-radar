#!/usr/bin/env bash
# Static validation for shell scripts used in Stage 20.
# Does not execute deploy/rollback/restore against real systems.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FAILED=0

check_script() {
  local path="$1"
  if [ ! -f "${path}" ]; then
    echo "MISSING ${path}"
    FAILED=1
    return
  fi
  if ! head -n 1 "${path}" | grep -Eq '^#!/.*(bash|sh)'; then
    echo "BAD_SHEBANG ${path}"
    FAILED=1
  fi
  if grep -Eq 'compose down -v|volume rm|DROP DATABASE|rm -rf /' "${path}"; then
    echo "UNSAFE_PATTERN ${path}"
    FAILED=1
  fi
  if command -v bash >/dev/null 2>&1; then
    bash -n "${path}"
    echo "SYNTAX_OK ${path}"
  else
    echo "SYNTAX_SKIPPED ${path} (bash not available)"
  fi
}

check_script "${ROOT_DIR}/scripts/lib/docker_compose.sh"
check_script "${ROOT_DIR}/scripts/backup_postgres.sh"
check_script "${ROOT_DIR}/scripts/restore_postgres.sh"
check_script "${ROOT_DIR}/scripts/test_backup_restore.sh"
check_script "${ROOT_DIR}/scripts/deploy.sh"
check_script "${ROOT_DIR}/scripts/rollback.sh"
check_script "${ROOT_DIR}/deploy/docker/entrypoint.sh"

if [ "${FAILED}" -ne 0 ]; then
  exit 1
fi
echo "SHELL_SCRIPTS_OK"
