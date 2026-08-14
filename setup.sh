#!/usr/bin/env bash
set -euo pipefail

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$project_dir"

python_bin="${PYTHON_BIN:-python3}"
if ! command -v "$python_bin" >/dev/null 2>&1; then
  echo "Could not find $python_bin. Install Python 3.10+ or set PYTHON_BIN." >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  "$python_bin" -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[server]"
.venv/bin/python -m playwright install chromium

echo
echo "Setup complete. Activate the environment with:"
echo "  source .venv/bin/activate"
echo
echo "Run the complete stack with Docker Compose:"
echo "  docker compose up --build"
echo
echo "Or run a one-off query (Docker is used for temporary SearXNG):"
echo "  .venv/bin/ezwebsearch \"your query\""
