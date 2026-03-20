#!/usr/bin/env bash
# Jukeboxx test runner
# Usage: ./scripts/run_tests.sh [pytest args]
# Examples:
#   ./scripts/run_tests.sh                          # run all tests
#   ./scripts/run_tests.sh -k test_auth             # run auth tests only
#   ./scripts/run_tests.sh -k test_tasks            # run task tests only
#   ./scripts/run_tests.sh --cov                    # run with coverage
#   ./scripts/run_tests.sh tests/test_concurrency.py # run specific file

set -e
cd "$(dirname "$0")/.."

# Install test dependencies into the container or local venv
if [ ! -f ".venv/bin/pytest" ] && ! command -v pytest &>/dev/null; then
    echo "[run_tests] Installing test dependencies..."
    pip install -r tests/requirements-test.txt -q
fi

# Also install backend deps if needed
if ! python -c "import fastapi" 2>/dev/null; then
    echo "[run_tests] Installing backend dependencies..."
    pip install -r backend/requirements.txt -q
fi

echo "[run_tests] Running Jukeboxx test suite..."
echo "============================================"

# Set environment for tests
export DB_PATH=":memory:"
export MUSIC_PATH="/tmp/jukeboxx_test_music"
export JWT_SECRET="test-secret-key-for-tests"
export SPOTIZERR_URL="http://localhost:19999"
export PYTHONPATH="$(pwd)/backend:$(pwd)/tests"

# Run pytest from the tests directory
pytest tests/ \
    --tb=short \
    --no-header \
    -q \
    "$@"

echo ""
echo "[run_tests] Done."
