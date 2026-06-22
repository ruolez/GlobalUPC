import pyodbc
from typing import Optional, List, Dict, Any, Tuple
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from mssql_helper import get_mssql_connection_string

_inv_time_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="invtime")


def _fetch_recount_timestamps_sync(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    target_user: str,
    date_from: str,
    date_to: str,
) -> Tuple[bool, Optional[str], List[datetime]]:
    """
    Return the ascending list of DateCreated values for one user's
    ManualInventoryUpdate rows within [date_from, date_to] (inclusive).

    date_from / date_to are "YYYY-MM-DD" strings; the upper bound is
    compared with `< date_to + 1 day` so the end date is fully inclusive.
    """
    conn_str = get_mssql_connection_string(host, port, database, username, password)

    try:
        upper = (datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    except ValueError:
        return False, f"Invalid date_to: {date_to}", []

    query = """
        SELECT DateCreated
        FROM ManualInventoryUpdate
        WHERE Username = ?
          AND DateCreated IS NOT NULL
          AND DateCreated >= ?
          AND DateCreated < ?
        ORDER BY DateCreated ASC
    """

    try:
        with pyodbc.connect(conn_str, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute(query, [target_user, date_from, upper])
            timestamps = [r[0] for r in cursor.fetchall() if r[0] is not None]
        return True, None, timestamps
    except Exception as e:
        return False, str(e), []


def _fetch_distinct_usernames_sync(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    date_from: str,
    date_to: str,
) -> Tuple[bool, Optional[str], List[str]]:
    """
    Distinct, non-blank usernames that have ManualInventoryUpdate rows within
    [date_from, date_to] (inclusive) -- i.e. only people who recounted in the
    selected range. The upper bound is compared with `< date_to + 1 day`.
    """
    conn_str = get_mssql_connection_string(host, port, database, username, password)

    try:
        upper = (datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    except ValueError:
        return False, f"Invalid date_to: {date_to}", []

    query = """
        SELECT DISTINCT Username FROM ManualInventoryUpdate
        WHERE Username IS NOT NULL AND LTRIM(RTRIM(Username)) <> ''
          AND DateCreated IS NOT NULL
          AND DateCreated >= ?
          AND DateCreated < ?
        ORDER BY Username
    """

    try:
        with pyodbc.connect(conn_str, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute(query, [date_from, upper])
            users = [r[0] for r in cursor.fetchall() if r[0]]
        return True, None, users
    except Exception as e:
        return False, str(e), []


def compute_inventory_time(
    timestamps: List[datetime],
    timeout_s: float,
    isolated_s: float,
) -> Dict[str, Any]:
    """
    Reconstruct recount working time from a stream of "item finished" timestamps.

    Pure logic (no I/O). `timestamps` must be sorted ascending. A gap larger
    than `timeout_s` between consecutive items ends a session (the break is not
    counted) and starts a new one. Per session of N items:
      - N == 1            -> isolated_s (no in-session average to estimate the start)
      - N >= 2, span > 0  -> span * N / (N - 1)  (span plus one average gap for the
                             unmeasured first item)
      - N >= 2, span == 0 -> isolated_s * N      (bulk rows sharing one timestamp)
    """
    sessions: List[Dict[str, Any]] = []
    if not timestamps:
        return {"total_seconds": 0.0, "sessions": [], "item_count": 0, "session_count": 0}

    group: List[datetime] = [timestamps[0]]
    for prev, cur in zip(timestamps, timestamps[1:]):
        if (cur - prev).total_seconds() > timeout_s:
            sessions.append(_session_record(group, isolated_s))
            group = [cur]
        else:
            group.append(cur)
    sessions.append(_session_record(group, isolated_s))

    total_seconds = sum(s["seconds"] for s in sessions)
    return {
        "total_seconds": total_seconds,
        "sessions": sessions,
        "item_count": len(timestamps),
        "session_count": len(sessions),
    }


def _session_record(group: List[datetime], isolated_s: float) -> Dict[str, Any]:
    n = len(group)
    start, end = group[0], group[-1]
    if n == 1:
        seconds = isolated_s
    else:
        span = (end - start).total_seconds()
        seconds = span * n / (n - 1) if span > 0 else isolated_s * n
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "item_count": n,
        "seconds": float(seconds),
    }


async def fetch_recount_timestamps_async(**kwargs) -> Tuple[bool, Optional[str], List[datetime]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _inv_time_executor,
        lambda: _fetch_recount_timestamps_sync(**kwargs),
    )


async def fetch_distinct_usernames_async(**kwargs) -> Tuple[bool, Optional[str], List[str]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _inv_time_executor,
        lambda: _fetch_distinct_usernames_sync(**kwargs),
    )


def shutdown_inv_time_executor():
    _inv_time_executor.shutdown(wait=False)
