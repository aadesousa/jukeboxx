#!/usr/bin/env bash
# Run tests inside the running jukeboxx-backend container.
# Usage: ./scripts/run_tests_in_docker.sh [pytest args]

set -e
CONTAINER="jukeboxx-backend"

echo "[docker-test] Installing test deps in container..."
docker exec "$CONTAINER" pip install pytest pytest-asyncio pytest-cov httpx -q

echo "[docker-test] Copying test files into container..."
docker exec "$CONTAINER" mkdir -p /app/tests
docker cp "$(dirname "$0")/../tests/." "$CONTAINER:/app/tests/"

echo "[docker-test] Running tests..."
docker exec \
    -e DB_PATH=":memory:" \
    -e MUSIC_PATH="/tmp/jukeboxx_test_music" \
    -e JWT_SECRET="test-secret-key-for-tests" \
    -e SPOTIZERR_URL="http://localhost:19999" \
    -e PYTHONPATH="/app/backend:/app/tests" \
    "$CONTAINER" \
    python -m pytest /app/tests/ --tb=short -q "$@"

echo "[docker-test] Done."
