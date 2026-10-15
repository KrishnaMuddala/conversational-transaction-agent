#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/.."

echo "Starting PostgreSQL via Docker for local dev..."
docker run -d --name dbs-dcta-db \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=dbs_dcta \
  -p 5432:5432 \
  postgres:15-alpine || true

echo "Installing backend dependencies..."
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

echo "Starting backend with mock parser..."
USE_MOCK_PARSER=true DATABASE_URL=postgresql://postgres:postgres@localhost:5432/dbs_dcta uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!

cd ../frontend
echo "Installing frontend dependencies..."
npm install
echo "Starting frontend..."
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev &
FRONTEND_PID=$!

echo "DBS DCTA running:"
echo "  Backend:  http://localhost:8000/docs"
echo "  Frontend: http://localhost:3000"

function cleanup {
  echo "Shutting down..."
  kill $BACKEND_PID $FRONTEND_PID || true
}
trap cleanup EXIT

wait
