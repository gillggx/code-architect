#!/bin/bash

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT=8000
FRONTEND_PORT=3000

echo "==> Killing old processes on ports $BACKEND_PORT and $FRONTEND_PORT..."
lsof -ti :$BACKEND_PORT | xargs kill -9 2>/dev/null && echo "    Killed backend (port $BACKEND_PORT)" || echo "    No process on port $BACKEND_PORT"
lsof -ti :$FRONTEND_PORT | xargs kill -9 2>/dev/null && echo "    Killed frontend (port $FRONTEND_PORT)" || echo "    No process on port $FRONTEND_PORT"
sleep 1

# Load .env
if [ -f "$PROJECT_DIR/.env" ]; then
    echo "==> Loading .env..."
    set -a; source "$PROJECT_DIR/.env"; set +a
fi

echo ""
echo "==> Installing backend package..."
cd "$PROJECT_DIR"
pip3 install -e . --break-system-packages

echo ""
echo "==> Installing frontend dependencies..."
cd "$PROJECT_DIR/web"
npm install

echo ""
echo "==> Starting backend (port $BACKEND_PORT)..."
cd "$PROJECT_DIR"
uvicorn src.architect.api.main:app --reload --port $BACKEND_PORT &
BACKEND_PID=$!
echo "    Backend PID: $BACKEND_PID"

# Wait for backend to be ready
echo "    Waiting for backend to be ready..."
for i in $(seq 1 15); do
    if curl -s http://localhost:$BACKEND_PORT/health > /dev/null 2>&1; then
        echo "    Backend is ready!"
        break
    fi
    sleep 1
done

echo ""
echo "==> Starting frontend (port $FRONTEND_PORT)..."
cd "$PROJECT_DIR/web"
npm run dev &
FRONTEND_PID=$!
echo "    Frontend PID: $FRONTEND_PID"

echo ""
echo "========================================"
echo "  Backend:  http://localhost:$BACKEND_PORT"
echo "  API Docs: http://localhost:$BACKEND_PORT/docs"
echo "  Frontend: http://localhost:$FRONTEND_PORT"
echo "========================================"
echo "  Press Ctrl+C to stop all services"
echo "========================================"

# On Ctrl+C, kill both processes
trap "echo ''; echo 'Stopping...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT TERM

wait
