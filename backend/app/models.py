"""ORM models. Column names match supabase/migrations/0001_init.sql."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Identity,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

ACTIVE_STATUSES = ("queued", "fetching", "downloading", "processing")
TERMINAL_STATUSES = ("done", "error", "cancelled")


def utcnow() -> datetime:
    return datetime.now(UTC)


class Download(Base):
    """One download job. Also the user's history row once it finishes."""

    __tablename__ = "downloads"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Ownership: a signed-in user, or an anonymous browser identified by X-Client-Id.
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # What was requested. The full URL is never stored, only the video id.
    video_id: Mapped[str] = mapped_column(String(16))
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thumbnail: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(String(8))  # audio | video
    format: Mapped[str] = mapped_column(String(8))  # mp3 | m4a | opus | mp4
    quality: Mapped[str | None] = mapped_column(String(8), nullable=True)  # "192", "1080", "best"

    # Live state.
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    percent: Mapped[float] = mapped_column(Float, default=0.0)
    downloaded_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    total_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    speed_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    eta_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)

    # Result.
    filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("downloads_user_created_idx", "user_id", "created_at"),
        Index("downloads_client_created_idx", "client_id", "created_at"),
    )

    # -- helpers ------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def canonical_url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"

    @property
    def label(self) -> str:
        if self.mode == "audio":
            if self.format == "mp3":
                return f"MP3 {self.quality} kbps"
            return self.format.upper()
        return f"MP4 {self.quality}p" if self.quality and self.quality != "best" else "MP4 best"

    def file_available(self, now: datetime | None = None) -> bool:
        if self.status != "done" or not self.storage_key:
            return False
        if self.expires_at is None:
            return True
        return _aware(self.expires_at) > (now or utcnow())


def _aware(dt: datetime) -> datetime:
    """SQLite drops tzinfo on the way back; treat naive values as UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class Profile(Base):
    """One row per signed-in user. In Postgres the trigger in the migration creates it;
    the API also upserts it so SQLite development works without Supabase triggers."""

    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    email: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String(16), default="user")
    daily_quota: Mapped[int] = mapped_column(Integer, default=20)
    email_risk: Mapped[str] = mapped_column(String(16), default="unknown")
    signup_ip_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    signup_ua: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Event(Base):
    """Activity log. Written by the API only; read by the admin dashboard (Phase 5)."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(
        Integer().with_variant(BigInteger(), "postgresql"), Identity(), primary_key=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(48), index=True)
    properties: Mapped[dict] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), default=dict)
    ip_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
