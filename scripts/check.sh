#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT/backend"
python -m ruff check app tests evals
python -m scripts.validate_thesis_templates
python -m evals.memory_eval --check
python -m pytest tests -q

cd "$ROOT/frontend"
npm run build
npm run contract:check
