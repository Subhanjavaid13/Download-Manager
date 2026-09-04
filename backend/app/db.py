"""SQLAlchemy engine and session factory.

SQLite in development (one file, zero setup), Postgres in production.
The same models and queries run on both.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


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
    """Create tables that do not exist yet. Production uses supabase/migrations instead."""
    from app import models  # noqa: F401  (registers the models on Base)

    Base.metadata.create_all(engine)


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
