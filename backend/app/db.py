"""SQLAlchemy engine and session factory.

SQLite in development (one file, zero setup), Postgres in production.
The same models and queries run on both.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def normalize_url(database_url: str) -> str:
    """Accept the URL Supabase shows in its dashboard and make it work with psycopg 3."""
    if database_url.startswith("postgres://"):
        database_url = "postgresql://" + database_url[len("postgres://") :]
    if database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgresql://") :]
    return database_url


def make_engine(database_url: str) -> Engine:
    database_url = normalize_url(database_url)
    is_sqlite = database_url.startswith("sqlite")
    if is_sqlite:
        connect_args: dict = {"check_same_thread": False, "timeout": 30}
    else:
        # Supabase's transaction pooler (pgbouncer) cannot use server-side prepared
        # statements, so turn them off. Harmless on a direct connection.
        connect_args = {"prepare_threshold": None}
    engine = (
        create_engine(
            database_url,
            pool_pre_ping=not is_sqlite,
            # Supabase's pooler closes connections it considers idle, and a
            # download can sit between two progress writes for minutes. Pre-ping
            # catches a dead connection when it is handed out; recycling retires
            # it before the server does, which is what stops a long job dying
            # partway through on a connection that went stale in the pool.
            pool_recycle=240,
            pool_size=5,
            max_overflow=5,
            connect_args=connect_args,
        )
        if not is_sqlite
        else create_engine(database_url, connect_args=connect_args)
    )
    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record) -> None:  # noqa: ANN001
            # WAL lets the worker threads write while the API reads.
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def init_db(engine: Engine) -> None:
    """SQLite: create tables on the fly. Postgres: require the real migration to have run.

    Creating tables from the ORM on Postgres would skip the foreign keys, Row Level
    Security, and triggers defined in supabase/migrations, so we refuse and explain.
    """
    from app import models  # noqa: F401  (registers the models on Base)

    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)
        return
    inspector = inspect(engine)
    if not inspector.has_table("downloads"):
        raise RuntimeError(
            "The database has no 'downloads' table. Apply the schema first with "
            "`uv run python scripts/migrate.py` (uses DM_DATABASE_URL; "
            "add --dry-run to validate without changing anything)."
        )
    # Missing later migrations are a warning, not a stop: single downloads still
    # work, and taking a live deployment down over it would be the worse failure.
    missing = [name for name in ("playlists", "bans") if not inspector.has_table(name)]
    if missing:
        log.warning(
            "The database is missing %s. Playlist downloads and the ban list will fail "
            "until you run `uv run python scripts/migrate.py`.",
            " and ".join(missing),
        )


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
