from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker
from contextlib import contextmanager
import asyncio
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://globalupc:globalupc_password@localhost:5432/globalupc")

POOL_CAPACITY = 15


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# Server-side limits on every app connection. They only end work that is
# already pathological: a lock wait or a forgotten open transaction would
# otherwise pin a pooled connection (and, on the event loop, a whole worker)
# indefinitely. All are milliseconds; 0 disables one. Bulk Shopify sync and
# other long jobs that need more lift them per connection.
PG_STATEMENT_TIMEOUT_MS = _env_int("PG_STATEMENT_TIMEOUT_MS", 900_000)          # 15 min
PG_LOCK_TIMEOUT_MS = _env_int("PG_LOCK_TIMEOUT_MS", 30_000)                    # 30 s
PG_IDLE_IN_TX_TIMEOUT_MS = _env_int("PG_IDLE_IN_TX_TIMEOUT_MS", 600_000)       # 10 min
PG_CONNECT_TIMEOUT_S = _env_int("PG_CONNECT_TIMEOUT_S", 5)
# How long a request waits for a free pooled connection before failing. Short
# on purpose: a sync query that waits here may be holding the event loop.
PG_POOL_TIMEOUT_S = _env_int("PG_POOL_TIMEOUT_S", 10)

_pg_options = " ".join(
    f"-c {k}={v}"
    for k, v in (
        ("statement_timeout", PG_STATEMENT_TIMEOUT_MS),
        ("lock_timeout", PG_LOCK_TIMEOUT_MS),
        ("idle_in_transaction_session_timeout", PG_IDLE_IN_TX_TIMEOUT_MS),
    )
)

engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_timeout=PG_POOL_TIMEOUT_S,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={"connect_timeout": PG_CONNECT_TIMEOUT_S, "options": _pg_options},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@contextmanager
def db_session():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def release_db(db: Session) -> None:
    """Hand the session's pooled connection back before slow external I/O.

    Ends the current (read) transaction without expiring loaded objects, so
    attributes already read stay usable while the request awaits MSSQL or
    Shopify. The session itself stays valid: a later query simply checks out
    a connection again. Call it only after the reads, never with pending
    writes the request did not mean to commit.
    """
    previous = db.expire_on_commit
    db.expire_on_commit = False
    try:
        db.commit()
    finally:
        db.expire_on_commit = previous


async def run_db(fn, *args, **kwargs):
    """Run fn(db, *args, **kwargs) in a worker thread with its own short session.

    Keeps blocking Postgres work off the event loop. fn must return plain data
    (or ORM objects whose needed attributes are already loaded): the session is
    closed when fn returns.
    """
    def _call():
        with db_session() as db:
            return fn(db, *args, **kwargs)

    return await asyncio.to_thread(_call)
