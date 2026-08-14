#!/usr/bin/env bash
set -euo pipefail

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$project_dir"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or is not on PATH." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Could not connect to the Docker daemon. Start Docker and try again." >&2
  exit 1
fi

echo "Stopping and removing the ezWebSearch Compose stack..."
docker compose down --remove-orphans --volumes

echo "Docker cleanup complete."
