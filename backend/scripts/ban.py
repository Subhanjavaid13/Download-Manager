"""Add, list, and lift entries in the ban list (public.bans).

    uv run python scripts/ban.py list
    uv run python scripts/ban.py add --user 6f1c...-...  --reason "ripping the same album 400 times"
    uv run python scripts/ban.py add --ip 203.0.113.7 --days 7 --reason "scripted abuse"
    uv run python scripts/ban.py add --ip-hash 1f2e3d... --reason "from events.ip_hash"
    uv run python scripts/ban.py remove --user 6f1c...-...

The API reads this table before creating any job, so a ban takes effect on the
next request with no restart and no redeploy.

Raw IPs are never stored: --ip is hashed with DM_IP_HASH_SALT, exactly as the
events table does, so the same address produces the same hash. That also means
the salt must match the one the API runs with, or the ban will never match.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.db import make_engine, make_session_factory  # noqa: E402
from app.services.bans import Bans  # noqa: E402


def _subject(args: argparse.Namespace, bans: Bans) -> tuple[str, str]:
    if args.user:
        return "user", args.user
    if args.ip:
        ip_hash = bans.hash_for(args.ip)
        assert ip_hash is not None
        return "ip_hash", ip_hash
    return "ip_hash", args.ip_hash


def _add_subject_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--user", help="a profiles.id (the Supabase user uuid)")
    group.add_argument("--ip", help="a raw address; it is hashed before it is stored")
    group.add_argument("--ip-hash", dest="ip_hash", help="a hash copied from events.ip_hash")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="block a user or an address")
    _add_subject_flags(add)
    add.add_argument("--reason", help="shown to the blocked caller, so keep it civil")
    add.add_argument("--days", type=int, help="lift the ban after this many days")
    add.add_argument("--by", default="script", help="who added it (an email is useful)")

    remove = sub.add_parser("remove", help="lift a ban")
    _add_subject_flags(remove)

    sub.add_parser("list", help="show the current bans")

    args = ap.parse_args()
    settings = get_settings()
    engine = make_engine(settings.database_url)
    bans = Bans(make_session_factory(engine), ip_salt=settings.ip_hash_salt)
    try:
        if args.command == "list":
            rows = bans.list_all()
            if not rows:
                print("no bans")
            for row in rows:
                until = row.expires_at.strftime("%Y-%m-%d") if row.expires_at else "forever"
                reason = row.reason or ""
                print(f"  {row.subject_type:<8} {row.subject:<40} until {until:<10} {reason}")
            return 0

        subject_type, subject = _subject(args, bans)
        if args.command == "add":
            record = bans.add(
                subject_type,
                subject,
                reason=args.reason,
                created_by=args.by,
                days=args.days,
            )
            print(f"blocked {record.subject_type} {record.subject}")
            print(f"  they will see: {record.message}")
            return 0

        if bans.remove(subject_type, subject):
            print(f"lifted the ban on {subject_type} {subject}")
            return 0
        print(f"no ban found for {subject_type} {subject}")
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
