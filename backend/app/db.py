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


def make_engine(database_url: str) -> Engine:
    is_sqlite = database_url.startswith("sqlite")
    engine = create_engine(
        database_url,
        pool_pre_ping=not is_sqlite,
        connect_args={"check_same_thread": False, "timeout": 30} if is_sqlite else {},
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
