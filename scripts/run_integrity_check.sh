#!/usr/bin/env bash
# Run the data integrity check against the live production DB.
# Safe: read-only SQLite queries. Does not modify any data.
# Usage: ./scripts/run_integrity_check.sh

set -e

DB_PATH="/home/eve/jukeboxx/backend/jukeboxx.db"

if [ ! -f "$DB_PATH" ]; then
    echo "ERROR: Database not found at $DB_PATH"
    echo "If DB is inside Docker container, run with --docker flag:"
    echo "  ./scripts/run_integrity_check.sh --docker"
    exit 1
fi

if [ "$1" = "--docker" ]; then
    CONTAINER="jukeboxx-backend"
    echo "[integrity] Running check inside container $CONTAINER..."
    docker exec "$CONTAINER" python /app/tests/../scripts/check_data_integrity.py --db /app/data/jukeboxx.db
else
    echo "[integrity] Running check on $DB_PATH..."
    python "$(dirname "$0")/check_data_integrity.py" --db "$DB_PATH"
fi
