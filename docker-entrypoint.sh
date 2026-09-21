#!/bin/sh
set -e

# Legacy (pre-Alembic) databases have tables but no alembic_version row.
# Detect how far their schema actually got and stamp THAT revision — never
# `head` — so every later migration still runs on upgrade.
#   - settings table without the 0002 compat columns  -> stamp 0001
#   - settings table with the 0002 compat columns     -> stamp 0002
STAMP_REV=$(python - <<'PYEOF'
import os, sqlite3, sys

REV_0001 = "5ca5251db402"
REV_0002 = "8b3f1a2c9d45"

db_url = os.environ.get("DATABASE_URL", "")
if db_url.startswith("sqlite:////"):
    db_path = db_url[len("sqlite:///"):]
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        if "settings" in tables and "alembic_version" not in tables:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(settings)").fetchall()]
            print(REV_0002 if "keyword_flush_delay_lines" in cols else REV_0001)
            conn.close()
            sys.exit(0)
        conn.close()
print("")
PYEOF
)

if [ -n "$STAMP_REV" ]; then
    echo "legacy database detected; stamping alembic revision $STAMP_REV"
    alembic stamp "$STAMP_REV"
fi

alembic upgrade head

exec python -m flask --app app run --host 0.0.0.0 --port "${APP_PORT:-5000}"
