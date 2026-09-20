#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
export TVC_THREADS="${TVC_THREADS:-4}"
exec python -m uvicorn app:app --host 127.0.0.1 --port "${TVC_PORT:-18888}" --workers 1
