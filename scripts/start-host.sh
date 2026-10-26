#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run alembic upgrade head
uv run uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!
uv run academic worker &
WORKER_PID=$!
trap 'kill "$API_PID" "$WORKER_PID" 2>/dev/null || true' EXIT INT TERM
printf 'Dashboard: http://127.0.0.1:8501\nAPI (documentación): http://127.0.0.1:8000/docs\n'
uv run streamlit run apps/dashboard/main.py --server.address 127.0.0.1 --server.port 8501 --server.headless=true --browser.gatherUsageStats=false
