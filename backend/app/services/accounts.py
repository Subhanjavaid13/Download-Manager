"""Profiles, quotas, activity events, and account deletion.

Everything here takes a session factory so the API and the job store share one
database. Nothing here talks HTTP.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.auth import User
from app.db import session_scope
from app.models import Download, Event, Profile

log = logging.getLogger(__name__)


def hash_ip(ip: str | None, salt: str) -> str | None:
    if not ip:
        return None
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()[:32]


@dataclass(frozen=True)
class ProfileView:
    id: str
    email: str | None
    display_name: str | None
    role: str
    daily_quota: int
    downloads_today: int
    email_verified: bool
    email_risk: str
    created_at: str | None

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _today_start() -> datetime:
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


class Accounts:
    def __init__(self, session_factory: sessionmaker[Session], ip_salt: str) -> None:
        self._sessions = session_factory
        self._salt = ip_salt

    # -- profiles -------------------------------------------------------------

    def ensure_profile(self, user: User) -> Profile:
        """Create the profile row if the Supabase trigger did not (SQLite dev, or a race)."""
        with session_scope(self._sessions) as s:
            profile = s.get(Profile, uuid.UUID(user.id))
            if profile is None:
                profile = Profile(id=uuid.UUID(user.id), email=user.email or "")
                s.add(profile)
                s.flush()
            elif user.email and profile.email != user.email:
                profile.email = user.email
            return profile

    def get_profile(self, user: User) -> ProfileView:
        profile = self.ensure_profile(user)
        return ProfileView(
            id=str(profile.id),
            email=profile.email or user.email,
            display_name=profile.display_name,
            role=profile.role,
            daily_quota=profile.daily_quota,
            downloads_today=self.downloads_today(user.id),
            email_verified=user.email_verified,
            email_risk=profile.email_risk,
            created_at=profile.created_at.isoformat() if profile.created_at else None,
        )

    def set_email_risk(self, user_id: str, risk: str, ip_hash: str | None, ua: str | None) -> None:
        with session_scope(self._sessions) as s:
            profile = s.get(Profile, uuid.UUID(user_id))
            if profile is not None:
                profile.email_risk = risk
                profile.signup_ip_hash = profile.signup_ip_hash or ip_hash
                profile.signup_ua = profile.signup_ua or (ua[:256] if ua else None)

    # -- quotas ---------------------------------------------------------------

    def downloads_today(self, user_id: str) -> int:
        with session_scope(self._sessions) as s:
            return (
                s.scalar(
                    select(func.count())
                    .select_from(Download)
                    .where(
                        Download.user_id == uuid.UUID(user_id),
                        Download.created_at >= _today_start(),
                        Download.status != "cancelled",
                    )
                )
                or 0
            )

    def anonymous_downloads_today(self, client_id: str) -> int:
        with session_scope(self._sessions) as s:
            return (
                s.scalar(
                    select(func.count())
                    .select_from(Download)
                    .where(
                        Download.user_id.is_(None),
                        Download.client_id == client_id,
                        Download.created_at >= _today_start(),
                        Download.status != "cancelled",
                    )
                )
                or 0
            )

    def quota_for(self, user: User) -> int:
        return self.ensure_profile(user).daily_quota

    # -- history --------------------------------------------------------------

    def claim_anonymous_history(self, user: User, client_id: str | None) -> int:
        """Attach this browser's anonymous downloads to the account that just signed in."""
        if not client_id:
            return 0
        with session_scope(self._sessions) as s:
            result = s.execute(
                update(Download)
                .where(Download.user_id.is_(None), Download.client_id == client_id)
                .values(user_id=uuid.UUID(user.id))
            )
            return int(result.rowcount or 0)

    # -- events ---------------------------------------------------------------

    def record(
        self,
        name: str,
        *,
        user_id: str | None = None,
        properties: dict | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        try:
            with session_scope(self._sessions) as s:
                s.add(
                    Event(
                        user_id=uuid.UUID(user_id) if user_id else None,
                        name=name,
                        properties=properties or {},
                        ip_hash=hash_ip(ip, self._salt),
                        user_agent=(user_agent or "")[:256] or None,
                    )
                )
        except Exception:  # noqa: BLE001 - analytics must never break a request
            log.exception("could not record event %s", name)

    # -- deletion -------------------------------------------------------------

    def storage_keys_for(self, user: User) -> list[str]:
        with session_scope(self._sessions) as s:
            return [
                k
                for (k,) in s.execute(
                    select(Download.storage_key).where(
                        Download.user_id == uuid.UUID(user.id), Download.storage_key.is_not(None)
                    )
                )
            ]

    def delete_account(self, user: User) -> None:
        """Remove history, profile, and (on Supabase) the auth user itself."""
        uid = uuid.UUID(user.id)
        with session_scope(self._sessions) as s:
            s.execute(Download.__table__.delete().where(Download.user_id == uid))
            s.execute(Event.__table__.delete().where(Event.user_id == uid))
            s.execute(Profile.__table__.delete().where(Profile.id == uid))
            if s.bind is not None and s.bind.dialect.name == "postgresql":
                # Supabase: deleting the auth row signs the user out everywhere and
                # cascades to anything else that references it.
                s.execute(text("delete from auth.users where id = :id"), {"id": uid})

    def recent_events(self, user_id: str, days: int = 30) -> list[dict]:
        since = datetime.now(UTC) - timedelta(days=days)
        with session_scope(self._sessions) as s:
            rows = s.scalars(
                select(Event)
                .where(Event.user_id == uuid.UUID(user_id), Event.created_at >= since)
                .order_by(Event.created_at.desc())
                .limit(100)
            )
            return [
                {"name": e.name, "properties": e.properties, "at": e.created_at.isoformat()}
                for e in rows
            ]
