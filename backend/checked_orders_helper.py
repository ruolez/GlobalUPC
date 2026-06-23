import pyodbc
from typing import Optional, List, Dict, Any, Tuple
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from mssql_helper import get_mssql_connection_string

_chkord_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chkord")


def _upper_bound(date_to: str) -> Optional[str]:
    """Exclusive upper bound = date_to + 1 day, so the end date is fully inclusive."""
    try:
        return (datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _fetch_checkers_sync(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    date_from: str,
    date_to: str,
) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """
    Distinct checkers (id + display name) who completed at least one order check
    within [date_from, date_to] (inclusive). Parcels with a NULL id_checker are
    excluded by the JOIN + IS NOT NULL guard; the upper bound is `< date_to + 1 day`.
    """
    conn_str = get_mssql_connection_string(host, port, database, username, password)

    upper = _upper_bound(date_to)
    if upper is None:
        return False, f"Invalid date_to: {date_to}", []

    query = """
        SELECT DISTINCT u.id,
               COALESCE(NULLIF(LTRIM(RTRIM(u.name)), ''), u.login) AS display_name
        FROM parcels p
        JOIN users u ON u.id = p.id_checker
        WHERE p.id_checker IS NOT NULL
          AND p.check_completed_at IS NOT NULL
          AND p.created_at >= ?
          AND p.created_at < ?
        ORDER BY display_name
    """

    try:
        with pyodbc.connect(conn_str, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute(query, [date_from, upper])
            users = [{"id": r[0], "name": r[1]} for r in cursor.fetchall() if r[0] is not None]
        return True, None, users
    except Exception as e:
        return False, str(e), []


def _fetch_checked_orders_sync(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    checker_id: int,
    date_from: str,
    date_to: str,
) -> Tuple[bool, Optional[str], List[Tuple[str, datetime, datetime, Any]]]:
    """
    Completed order checks for one checker within [date_from, date_to] (inclusive).
    Only rows with a non-NULL check_completed_at are returned (an order can't have a
    duration without an end time). Upper bound is `< date_to + 1 day`.

    Each row carries the order value = SUM(price * total_quantity) over its
    parcel_items, pre-aggregated in a subquery so the one-to-many join doesn't
    multiply parcel rows. NULL price/quantity count as 0; orders with no items
    yield 0.
    """
    conn_str = get_mssql_connection_string(host, port, database, username, password)

    upper = _upper_bound(date_to)
    if upper is None:
        return False, f"Invalid date_to: {date_to}", []

    query = """
        SELECT p.order_number, p.created_at, p.check_completed_at,
               ISNULL(pv.order_value, 0) AS order_value
        FROM parcels p
        LEFT JOIN (
            SELECT id_parcel, SUM(ISNULL(price, 0) * ISNULL(total_quantity, 0)) AS order_value
            FROM parcel_items
            GROUP BY id_parcel
        ) pv ON pv.id_parcel = p.id
        WHERE p.id_checker = ?
          AND p.check_completed_at IS NOT NULL
          AND p.created_at >= ?
          AND p.created_at < ?
        ORDER BY p.created_at ASC
    """

    try:
        with pyodbc.connect(conn_str, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute(query, [checker_id, date_from, upper])
            rows = [(r[0], r[1], r[2], r[3]) for r in cursor.fetchall()]
        return True, None, rows
    except Exception as e:
        return False, str(e), []


def compute_checked_orders(
    rows: List[Tuple[str, datetime, datetime, Any]],
) -> Dict[str, Any]:
    """
    Pure logic (no I/O). Turn (order_number, created_at, check_completed_at, order_value)
    rows into a summary. Per-order time = check_completed_at - created_at; rows with a
    non-positive duration (bad data) are skipped so they don't skew the average or the
    value totals.

    Returns order_count, total_seconds, average_seconds, total_value, and the per-order
    detail list (each with its `value`).
    """
    orders: List[Dict[str, Any]] = []
    total_seconds = 0.0
    total_value = 0.0

    for order_number, created_at, check_completed_at, order_value in rows:
        if created_at is None or check_completed_at is None:
            continue
        seconds = (check_completed_at - created_at).total_seconds()
        if seconds <= 0:
            continue
        value = float(order_value) if order_value is not None else 0.0
        total_seconds += seconds
        total_value += value
        orders.append({
            "order_number": order_number,
            "created_at": created_at.isoformat(),
            "check_completed_at": check_completed_at.isoformat(),
            "seconds": float(seconds),
            "value": value,
        })

    order_count = len(orders)
    average_seconds = total_seconds / order_count if order_count else 0.0
    return {
        "order_count": order_count,
        "total_seconds": total_seconds,
        "average_seconds": average_seconds,
        "total_value": total_value,
        "orders": orders,
    }


async def fetch_checkers_async(**kwargs) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _chkord_executor,
        lambda: _fetch_checkers_sync(**kwargs),
    )


async def fetch_checked_orders_async(**kwargs) -> Tuple[bool, Optional[str], List[Tuple[str, datetime, datetime, Any]]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _chkord_executor,
        lambda: _fetch_checked_orders_sync(**kwargs),
    )


def shutdown_chkord_executor():
    _chkord_executor.shutdown(wait=False)
