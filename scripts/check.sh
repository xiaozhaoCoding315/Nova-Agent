#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT/backend"
python -m ruff check app
python -m pytest tests -q

cd "$ROOT/frontend"
npm run build
npm run contract:check
