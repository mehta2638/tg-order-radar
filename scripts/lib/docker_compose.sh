#!/usr/bin/env bash
# Shared docker compose resolver for host/WSL environments.
# Prefer a Docker CLI that supports the Compose V2 plugin.
# Sourced by deploy/rollback; not meant to be executed alone.

resolve_docker_compose() {
  if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE=(docker compose)
    return 0
  fi
  if command -v docker.exe >/dev/null 2>&1 && docker.exe compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE=(docker.exe compose)
    return 0
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE=(docker-compose)
    return 0
  fi
  echo "docker compose is not available (tried: docker compose, docker.exe compose, docker-compose)" >&2
  return 1
}
