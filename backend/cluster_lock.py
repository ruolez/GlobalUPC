"""A lock that holds across every uvicorn worker (and container) of the app.

asyncio.Lock only serializes coroutines inside one process; prod runs several
worker processes, so two orders fixed at the same time in two workers would
not wait for each other. ClusterLock keeps the in-process asyncio.Lock (cheap,
and it keeps one worker to one Postgres connection per lock) and additionally
takes a Postgres session-level advisory lock on a dedicated, unpooled
connection. If the process dies while holding it, Postgres drops the
connection and the lock is released by itself.
"""
import asyncio
import hashlib
import os
import time
from typing import Optional

import psycopg2

from database import DATABASE_URL, PG_CONNECT_TIMEOUT_S


class ClusterLockTimeout(Exception):
    pass


def lock_key(name: str) -> int:
    """Stable signed 64-bit advisory-lock key for a name."""
    return int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big", signed=True)


class ClusterLock:
    def __init__(self, name: str, wait_timeout_s: Optional[float] = None, poll_s: float = 0.25):
        self.name = name
        self.key = lock_key(name)
        self.wait_timeout_s = (
            float(os.getenv("CLUSTER_LOCK_WAIT_S", "900")) if wait_timeout_s is None else wait_timeout_s
        )
        self.poll_s = poll_s
        self._local = asyncio.Lock()
        self._conn = None

    def _acquire_sync(self) -> None:
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=PG_CONNECT_TIMEOUT_S)
        conn.autocommit = True  # session lock, no open transaction to time out
        deadline = time.monotonic() + self.wait_timeout_s
        try:
            with conn.cursor() as cur:
                while True:
                    cur.execute("SELECT pg_try_advisory_lock(%s)", (self.key,))
                    if cur.fetchone()[0]:
                        self._conn = conn
                        return
                    if time.monotonic() >= deadline:
                        raise ClusterLockTimeout(
                            f"{self.name}: still held by another worker after {self.wait_timeout_s:.0f}s"
                        )
                    time.sleep(self.poll_s)
        except BaseException:
            conn.close()
            raise

    def _release_sync(self) -> None:
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (self.key,))
        finally:
            conn.close()  # closing alone also releases it

    async def __aenter__(self):
        await self._local.acquire()
        attempt = asyncio.ensure_future(asyncio.to_thread(self._acquire_sync))
        try:
            await asyncio.shield(attempt)
        except asyncio.CancelledError:
            # The thread may still win the lock after we stop waiting: undo
            # it whenever it finishes so it is never left held.
            def _undo(f: asyncio.Future) -> None:
                try:
                    if not f.cancelled() and f.exception() is None:
                        self._release_sync()
                finally:
                    self._local.release()

            attempt.add_done_callback(_undo)
            raise
        except BaseException:
            self._local.release()
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb):
        try:
            await asyncio.to_thread(self._release_sync)
        finally:
            self._local.release()
        return False

    def locked(self) -> bool:
        return self._local.locked()
