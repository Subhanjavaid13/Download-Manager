"""The ban list: user ids and hashed IPs that may not start downloads.

A table rather than an environment variable, so blocking abuse is one INSERT and
no redeploy (`backend/scripts/ban.py`, or the SQL in
supabase/migrations/0002_playlists_and_bans.sql).

Raw IP addresses are never stored anywhere in this app, so a ban on an address is
a ban on its salted hash, using the same salt as `events.ip_hash`. That means an
admin can copy a hash straight out of the events table and block it.

Nothing here talks HTTP.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import session_scope
from app.models import Ban, as_utc
from app.services.accounts import hash_ip

log = logging.getLogger(__name__)

SUBJECT_TYPES = ("user", "ip_hash")


@dataclass(frozen=True)
class BanRecord:
    subject_type: str
    subject: str
    reason: str | None
    expires_at: datetime | None

    @property
    def message(self) -> str:
        """What the blocked caller is told. Says what happened and what to do next."""
        base = "Downloads from here are blocked"
        if self.reason:
            base += f" ({self.reason})"
        if self.expires_at is not None:
            return f"{base}. The block lifts on {self.expires_at:%d %b %Y}."
        return f"{base}. Email the site owner if you think this is a mistake."


class Bans:
    def __init__(self, session_factory: sessionmaker[Session], ip_salt: str) -> None:
        self._sessions = session_factory
        self._salt = ip_salt

    def hash_for(self, ip: str | None) -> str | None:
        return hash_ip(ip, self._salt)

    # -- the hot path ---------------------------------------------------------

    def check(self, *, user_id: str | None = None, ip: str | None = None) -> BanRecord | None:
        """The one query the API runs before creating a job. None means allowed.

        Both subjects are looked up in a single indexed query
        (bans_subject_idx on (subject_type, subject)). A failure here never
        blocks a download: a database blip must not lock everyone out.
        """
        ip_hash = self.hash_for(ip)
        if not user_id and not ip_hash:
            return None
        clauses = []
        if user_id:
            clauses.append(and_(Ban.subject_type == "user", Ban.subject == user_id))
        if ip_hash:
            clauses.append(and_(Ban.subject_type == "ip_hash", Ban.subject == ip_hash))
        try:
            with session_scope(self._sessions) as s:
                now = datetime.now(UTC)
                for ban in s.scalars(select(Ban).where(or_(*clauses))):
                    if ban.active(now):
                        return _record(ban)
        except Exception:  # noqa: BLE001 - fail open, and shout about it in the log
            log.exception("ban lookup failed; allowing the request")
        return None

    # -- administration -------------------------------------------------------

    def add(
        self,
        subject_type: str,
        subject: str,
        *,
        reason: str | None = None,
        created_by: str | None = None,
        days: int | None = None,
    ) -> BanRecord:
        if subject_type not in SUBJECT_TYPES:
            raise ValueError(f"subject_type must be one of {SUBJECT_TYPES}")
        expires_at = datetime.now(UTC) + timedelta(days=days) if days else None
        with session_scope(self._sessions) as s:
            ban = s.scalar(
                select(Ban).where(Ban.subject_type == subject_type, Ban.subject == subject)
            )
            if ban is None:
                ban = Ban(id=uuid.uuid4(), subject_type=subject_type, subject=subject)
                s.add(ban)
            ban.reason = reason
            ban.created_by = created_by
            ban.expires_at = expires_at
            s.flush()
            return _record(ban)

    def remove(self, subject_type: str, subject: str) -> bool:
        with session_scope(self._sessions) as s:
            result = s.execute(
                delete(Ban).where(Ban.subject_type == subject_type, Ban.subject == subject)
            )
            return bool(result.rowcount)

    def list_all(self, limit: int = 100) -> list[BanRecord]:
        with session_scope(self._sessions) as s:
            rows = s.scalars(select(Ban).order_by(Ban.created_at.desc()).limit(limit))
            return [_record(b) for b in rows]


def _record(ban: Ban) -> BanRecord:
    return BanRecord(
        subject_type=ban.subject_type,
        subject=ban.subject,
        reason=ban.reason,
        expires_at=as_utc(ban.expires_at) if ban.expires_at else None,
    )
