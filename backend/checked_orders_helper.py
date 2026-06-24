import pyodbc
from typing import Optional, List, Dict, Any, Tuple
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from mssql_helper import get_mssql_connection_string

_chkord_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chkord")

# SQL Server caps query parameters at ~2100; keep IN (...) batches well under that.
_ITEM_IN_CHUNK = 2000


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
) -> Tuple[bool, Optional[str], List[Tuple[str, datetime, datetime, Any, Any]]]:
    """
    Completed order checks for one checker within [date_from, date_to] (inclusive).
    Only rows with a non-NULL check_completed_at are returned (an order can't have a
    duration without an end time). Upper bound is `< date_to + 1 day`.

    Each row carries the order value = SUM(price * total_quantity) and the unique
    product count = COUNT(DISTINCT id_product) over its parcel_items. To avoid
    aggregating the whole parcel_items table (or re-scanning it per parcel), this is
    done in two steps: fetch the matched parcels, then fetch only those parcels'
    items in one chunked `IN (...)` query and aggregate in Python. NULL price/quantity
    count as 0; orders with no items yield 0 value and 0 products.
    """
    conn_str = get_mssql_connection_string(host, port, database, username, password)

    upper = _upper_bound(date_to)
    if upper is None:
        return False, f"Invalid date_to: {date_to}", []

    parcels_query = """
        SELECT p.id, p.order_number, p.created_at, p.check_completed_at
        FROM parcels p
        WHERE p.id_checker = ?
          AND p.check_completed_at IS NOT NULL
          AND p.created_at >= ?
          AND p.created_at < ?
        ORDER BY p.created_at ASC
    """

    try:
        with pyodbc.connect(conn_str, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute(parcels_query, [checker_id, date_from, upper])
            parcels = [(r[0], r[1], r[2], r[3]) for r in cursor.fetchall()]

            parcel_ids = [p[0] for p in parcels]
            value_by_parcel, products_by_parcel = _fetch_item_aggregates(cursor, parcel_ids)

        rows = [
            (
                order_number,
                created_at,
                check_completed_at,
                value_by_parcel.get(parcel_id, 0),
                len(products_by_parcel.get(parcel_id, ())),
            )
            for parcel_id, order_number, created_at, check_completed_at in parcels
        ]
        return True, None, rows
    except Exception as e:
        return False, str(e), []


def _fetch_item_aggregates(
    cursor, parcel_ids: List[int]
) -> Tuple[Dict[int, Any], Dict[int, set]]:
    """
    For the given parcel ids, return {id_parcel: summed line value} and
    {id_parcel: set of distinct id_product}, fetched in chunked `IN (...)` batches
    (SQL Server caps parameters at ~2100). Line value = price * total_quantity with
    NULLs treated as 0, computed in SQL.
    """
    value_by_parcel: Dict[int, Any] = {}
    products_by_parcel: Dict[int, set] = {}
    if not parcel_ids:
        return value_by_parcel, products_by_parcel

    for start in range(0, len(parcel_ids), _ITEM_IN_CHUNK):
        chunk = parcel_ids[start:start + _ITEM_IN_CHUNK]
        placeholders = ",".join("?" * len(chunk))
        items_query = f"""
            SELECT id_parcel,
                   ISNULL(price, 0) * ISNULL(total_quantity, 0) AS line_value,
                   id_product
            FROM parcel_items
            WHERE id_parcel IN ({placeholders})
        """
        cursor.execute(items_query, chunk)
        for id_parcel, line_value, id_product in cursor.fetchall():
            value_by_parcel[id_parcel] = value_by_parcel.get(id_parcel, 0) + (line_value or 0)
            if id_product is not None:
                products_by_parcel.setdefault(id_parcel, set()).add(id_product)

    return value_by_parcel, products_by_parcel


def compute_checked_orders(
    rows: List[Tuple[str, datetime, datetime, Any, Any]],
    slow_threshold_seconds: float = 0.0,
    seconds_per_product: float = 10.0,
) -> Dict[str, Any]:
    """
    Pure logic (no I/O). Turn (order_number, created_at, check_completed_at, order_value,
    product_count) rows into a summary. Per-order time = check_completed_at - created_at;
    rows with a non-positive duration (bad data) are skipped so they don't skew the
    average or the value totals.

    Slow orders (actual duration over `slow_threshold_seconds`) are outliers — a checker
    who walked away mid-order inflates their real time. For the summary totals only, such
    orders are counted as an estimate of `product_count * seconds_per_product` instead of
    their real duration; normal orders keep their real duration. This is gated on
    `slow_threshold_seconds > 0` (a 0 threshold disables slow-detection, matching the
    frontend), so nothing is substituted then. The per-order `seconds` in the returned
    detail list is always the *actual* duration — the table shows real times.

    Returns order_count, total_seconds, average_seconds, total_value, and the per-order
    detail list (each with its `value` and `product_count`).
    """
    orders: List[Dict[str, Any]] = []
    total_seconds = 0.0
    total_value = 0.0

    for order_number, created_at, check_completed_at, order_value, product_count in rows:
        if created_at is None or check_completed_at is None:
            continue
        seconds = (check_completed_at - created_at).total_seconds()
        if seconds <= 0:
            continue
        value = float(order_value) if order_value is not None else 0.0
        products = int(product_count) if product_count is not None else 0
        is_slow = slow_threshold_seconds > 0 and seconds > slow_threshold_seconds
        effective_seconds = products * seconds_per_product if is_slow else seconds
        total_seconds += effective_seconds
        total_value += value
        orders.append({
            "order_number": order_number,
            "created_at": created_at.isoformat(),
            "check_completed_at": check_completed_at.isoformat(),
            "seconds": float(seconds),
            "value": value,
            "product_count": products,
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


async def fetch_checked_orders_async(**kwargs) -> Tuple[bool, Optional[str], List[Tuple[str, datetime, datetime, Any, Any]]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _chkord_executor,
        lambda: _fetch_checked_orders_sync(**kwargs),
    )


def shutdown_chkord_executor():
    _chkord_executor.shutdown(wait=False)
