"""Reset all demo/runtime data in the configured database.

Works against whatever DATABASE_URL resolves to (local docker Postgres or
Supabase), so it is safe to use between local test-set uploads or to clear a
deployed demo environment.

Usage:
    python scripts/reset_demo_data.py            # uses .env DATABASE_URL
    DATABASE_URL=... python scripts/reset_demo_data.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from sqlalchemy import text  # noqa: E402

from app.db import make_engine  # noqa: E402

RUNTIME_TABLES = (
    "audit_logs, match_members, exceptions, transactions, ingestion_runs, "
    "webhook_events, match_groups, sources, reconciliation_runs, evaluation_runs"
)


def main() -> int:
    engine = make_engine()
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {RUNTIME_TABLES} RESTART IDENTITY CASCADE"))
        remaining = conn.execute(
            text("select count(*) from transactions")
        ).scalar()
    print(f"runtime tables cleared; transactions remaining = {remaining}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
