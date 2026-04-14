#!/bin/sh
set -e

# If this is an existing v0.2 database (no alembic_version table), stamp it
# so Alembic doesn't try to re-create tables that already exist.
NEEDS_STAMP=$(python - <<'PYEOF'
import os, sqlite3, sys

db_url = os.environ.get("DATABASE_URL", "")
if db_url.startswith("sqlite:////"):
    db_path = db_url[len("sqlite:///"):]
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()
        if "settings" in tables and "alembic_version" not in tables:
            print("yes")
            sys.exit(0)
print("no")
PYEOF
)

if [ "$NEEDS_STAMP" = "yes" ]; then
    alembic stamp head
fi

alembic upgrade head

exec python -m flask --app app run --host 0.0.0.0 --port "${APP_PORT:-5000}"
