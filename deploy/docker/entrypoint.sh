#!/bin/sh
set -eu

# Default false so local Celery workers do not race on alembic.
if [ "${RUN_MIGRATIONS_ON_START:-false}" = "true" ]; then
  echo "Running database migrations..."
  python -m alembic upgrade head
fi

exec "$@"
