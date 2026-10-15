#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/../backend"
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pytest -q

echo "All backend tests passed."
