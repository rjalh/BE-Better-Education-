#!/bin/bash
set -e
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null; then echo 'Python 3 is required'; exit 1; fi
if [ ! -d .venv ]; then python3 -m venv .venv; fi
source .venv/bin/activate
python -m pip install -q -r requirements.txt
printf '\nBetter Education: http://localhost:8000\nStop server: Ctrl+C\n\n'
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
