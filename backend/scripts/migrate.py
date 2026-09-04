"""Apply supabase/migrations/*.sql to the database in DM_DATABASE_URL, in order, once each.

    uv run python scripts/migrate.py            # apply pending migrations
    uv run python scripts/migrate.py --dry-run  # run everything in a transaction, then roll back
    uv run python scripts/migrate.py --status   # show applied / pending

Applied migrations are recorded in public.schema_migrations. Each file runs inside one
transaction, so a failing file leaves nothing half-applied. SQLite is not supported here;
the app creates SQLite tables itself.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "supabase" / "migrations"
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.db import normalize_url  # noqa: E402

TRACKING_SQL = """
create table if not exists public.schema_migrations (
  name        text primary key,
  checksum    text not null,
  applied_at  timestamptz not null default now()
);
"""


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="apply inside a transaction, then roll back"
    )
    ap.add_argument("--status", action="store_true", help="list applied and pending migrations")
    args = ap.parse_args()

    url = normalize_url(get_settings().database_url)
    if not url.startswith("postgresql"):
        print("DM_DATABASE_URL is not Postgres; SQLite needs no migrations.")
        return 0

    import psycopg

    files = sorted(MIGRATIONS.glob("*.sql"))
    if not files:
        print(f"no migrations found in {MIGRATIONS}")
        return 1

    dsn = url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(dsn, prepare_threshold=None, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(TRACKING_SQL)
            cur.execute("select name, checksum from public.schema_migrations")
            applied = dict(cur.fetchall())
        conn.commit()

        pending = []
        for f in files:
            checksum = hashlib.sha256(f.read_bytes()).hexdigest()[:16]
            if f.name in applied:
                state = (
                    "applied" if applied[f.name] == checksum else "applied (file changed since!)"
                )
            else:
                state = "pending"
                pending.append((f, checksum))
            print(f"  {state:<28} {f.name}")

        if args.status:
            return 0
        if not pending:
            print("nothing to do")
            return 0

        for f, checksum in pending:
            started = time.time()
            with conn.cursor() as cur:
                cur.execute(f.read_text(encoding="utf-8"))
                cur.execute(
                    "insert into public.schema_migrations (name, checksum) values (%s, %s)",
                    (f.name, checksum),
                )
                cur.execute(
                    "select count(*) from information_schema.tables where table_schema = 'public'"
                )
                (tables,) = cur.fetchone()
            if args.dry_run:
                conn.rollback()
                print(
                    f"  dry-run ok  {f.name}  ({time.time() - started:.1f}s, "
                    f"{tables} public tables would exist) - rolled back"
                )
            else:
                conn.commit()
                print(f"  applied     {f.name}  ({time.time() - started:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
