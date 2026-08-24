"""
Per-store local sync of Shopify customers and orders into PostgreSQL.

Full syncs use the Bulk Operations API (bulkOperationRunQuery -> poll ->
download JSONL) because it sidesteps the 25,000-object pagination cap and the
cost throttle entirely. Incremental syncs use normal cursor pagination with an
updated_at filter — bulk operations have multi-minute fixed latency even for a
tiny delta, while a day's worth of changes paginates in seconds. Both paths
write through the same upsert functions.

The sync-state row in shopify_sync_state is also the cross-worker concurrency
guard: prod runs 4 uvicorn workers, so an in-process lock cannot prevent two
simultaneous syncs of one store. claim_sync() takes the row with a conditional
UPDATE; a worker that dies mid-run releases it via the heartbeat staleness test.
"""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from psycopg2.extras import Json, execute_values
from sqlalchemy import text

from database import SessionLocal, engine
from shopify_helper import (
    ShopifyFetchError,
    _shopify_graphql,
    fetch_shop_timezone,
    validate_shop_domain,
)

_sync_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="shopsync")


def shutdown_sync_executor():
    _sync_executor.shutdown(wait=False)


# Orders flush in batches this size; a batch is one transaction. Line items are
# delete-then-inserted per flushed order because an order edit can replace lines.
_FLUSH_ORDERS = 500
_FLUSH_CUSTOMERS = 1000

_BULK_POLL_SECONDS = 4.0
# Claim heartbeat cadence. Must stay well under the 3-minute staleness window
# claim_sync uses for takeover.
_HEARTBEAT_SECONDS = 20.0

# Incremental pagination ceiling. Shopify refuses to paginate a cursor past
# 25,000 objects; when a delta approaches it we rerun that phase as a filtered
# bulk operation instead of truncating.
_DELTA_MAX_PAGES_CUSTOMERS = 90   # 90 * 250 = 22,500
_DELTA_MAX_PAGES_ORDERS = 100     # orders count line items toward the cap too
# Overlap subtracted from the incremental anchor so records updated while the
# previous run was in flight are not missed. Upserts make the overlap harmless.
_DELTA_OVERLAP_MINUTES = 10


# ============================================================================
# GraphQL documents
# ============================================================================

_CUSTOMER_NODE_FIELDS = """
        id
        legacyResourceId
        displayName
        firstName
        lastName
        email
        emailMarketingConsent { marketingState }
        verifiedEmail
        phone
        state
        note
        tags
        createdAt
        updatedAt
        numberOfOrders
        amountSpent { amount currencyCode }
        defaultAddress { address1 city provinceCode province zip countryCodeV2 phone }
"""

_ORDER_NODE_FIELDS = """
        id
        legacyResourceId
        name
        email
        createdAt
        processedAt
        updatedAt
        cancelledAt
        closedAt
        displayFinancialStatus
        displayFulfillmentStatus
        tags
        note
        totalPriceSet { shopMoney { amount currencyCode } }
        subtotalPriceSet { shopMoney { amount } }
        totalDiscountsSet { shopMoney { amount } }
        totalRefundedSet { shopMoney { amount } }
        totalShippingPriceSet { shopMoney { amount } }
        customer { legacyResourceId }
        shippingAddress { provinceCode province countryCodeV2 zip city }
        shippingLine { title carrierIdentifier }
        fulfillments { createdAt inTransitAt deliveredAt displayStatus status trackingInfo { company number url } }
"""

_LINE_ITEM_NODE_FIELDS = """
        id
        title
        quantity
        currentQuantity
        sku
        variantTitle
        vendor
        product { legacyResourceId title }
        variant { legacyResourceId barcode }
        originalUnitPriceSet { shopMoney { amount } }
        discountedTotalSet { shopMoney { amount } }
"""


def _bulk_customers_query(search: Optional[str] = None) -> str:
    q = f'(query: "{search}")' if search else ""
    return f"{{ customers{q} {{ edges {{ node {{ {_CUSTOMER_NODE_FIELDS} }} }} }} }}"


def _bulk_orders_query(search: Optional[str] = None) -> str:
    q = f'(query: "{search}")' if search else ""
    return f"""{{ orders{q} {{ edges {{ node {{ {_ORDER_NODE_FIELDS}
        lineItems {{ edges {{ node {{ {_LINE_ITEM_NODE_FIELDS} }} }} }}
    }} }} }} }}"""


_RUN_BULK_MUTATION = """
mutation RunBulk($query: String!) {
  bulkOperationRunQuery(query: $query) {
    bulkOperation { id status }
    userErrors { field message }
  }
}
"""

_CURRENT_BULK_QUERY = """
query CurrentBulkOp {
  currentBulkOperation(type: QUERY) {
    id status errorCode objectCount url createdAt completedAt
  }
}
"""

_CANCEL_BULK_MUTATION = """
mutation CancelBulk($id: ID!) {
  bulkOperationCancel(id: $id) {
    bulkOperation { id status }
    userErrors { field message }
  }
}
"""

_CUSTOMERS_DELTA_QUERY = f"""
query CustomersDelta($q: String, $after: String) {{
  customers(first: 250, query: $q, after: $after, sortKey: UPDATED_AT) {{
    pageInfo {{ hasNextPage endCursor }}
    nodes {{ {_CUSTOMER_NODE_FIELDS} }}
  }}
}}
"""

_ORDERS_DELTA_QUERY = f"""
query OrdersDelta($q: String, $after: String) {{
  orders(first: 100, query: $q, after: $after, sortKey: UPDATED_AT) {{
    pageInfo {{ hasNextPage endCursor }}
    nodes {{ {_ORDER_NODE_FIELDS}
      lineItems(first: 100) {{
        pageInfo {{ hasNextPage endCursor }}
        nodes {{ {_LINE_ITEM_NODE_FIELDS} }}
      }}
    }}
  }}
}}
"""

# Follow-up for the rare order whose line items overflow the inline page.
# Without it the delta path would silently truncate at 100 and the
# delete-then-insert upsert would DESTROY the overflow rows the full sync had
# stored — the bulk path has no cap, so truncating here is data loss, not just
# a stale read.
_ORDER_LINE_ITEMS_PAGE_QUERY = f"""
query OrderLineItemsPage($id: ID!, $after: String) {{
  node(id: $id) {{
    ... on Order {{
      lineItems(first: 250, after: $after) {{
        pageInfo {{ hasNextPage endCursor }}
        nodes {{ {_LINE_ITEM_NODE_FIELDS} }}
      }}
    }}
  }}
}}
"""


# ============================================================================
# Row shaping
# ============================================================================


def _parse_ts(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _gid_num(gid: Optional[str]) -> Optional[int]:
    """Numeric tail of a gid://shopify/Type/123 identifier."""
    if not gid:
        return None
    return _int_or_none(str(gid).rsplit("/", 1)[-1].split("?")[0])


def _money(node: Optional[Dict[str, Any]]) -> Optional[float]:
    return _num(((node or {}).get("shopMoney") or {}).get("amount"))


def _shape_customer(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    shopify_id = _int_or_none(node.get("legacyResourceId")) or _gid_num(node.get("id"))
    if shopify_id is None:
        return None
    email = (node.get("email") or "").strip() or None
    addr = node.get("defaultAddress") or {}
    spent = node.get("amountSpent") or {}
    return {
        "shopify_id": shopify_id,
        "shopify_gid": node.get("id") or f"gid://shopify/Customer/{shopify_id}",
        "email": email,
        "email_normalized": email.lower() if email else None,
        "first_name": node.get("firstName"),
        "last_name": node.get("lastName"),
        "display_name": node.get("displayName"),
        "phone": node.get("phone"),
        "state": node.get("state"),
        "verified_email": node.get("verifiedEmail"),
        "tags": node.get("tags") or [],
        "note": node.get("note"),
        "number_of_orders": _int_or_none(node.get("numberOfOrders")),
        "amount_spent": _num(spent.get("amount")),
        "currency": spent.get("currencyCode"),
        "default_address_zip": addr.get("zip"),
        "default_province_code": addr.get("provinceCode"),
        "default_country_code": addr.get("countryCodeV2"),
        "created_at": _parse_ts(node.get("createdAt")),
        "shopify_updated_at": _parse_ts(node.get("updatedAt")),
        "raw": node,
    }


def _shape_order(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    shopify_id = _int_or_none(node.get("legacyResourceId")) or _gid_num(node.get("id"))
    if shopify_id is None:
        return None
    ship = node.get("shippingAddress") or {}
    line = node.get("shippingLine") or {}
    total = (node.get("totalPriceSet") or {}).get("shopMoney") or {}
    fulfillments = node.get("fulfillments") or []
    # First fulfillment by createdAt drives the timing columns; the full list is
    # kept in JSONB for future analysis.
    first_f: Dict[str, Any] = {}
    if fulfillments:
        first_f = min(fulfillments, key=lambda f: (f.get("createdAt") or "9999"))
    tracking = (first_f.get("trackingInfo") or [{}])
    tracking = tracking[0] if tracking else {}
    return {
        "shopify_id": shopify_id,
        "shopify_gid": node.get("id") or f"gid://shopify/Order/{shopify_id}",
        "name": node.get("name"),
        "customer_shopify_id": _int_or_none(((node.get("customer") or {}).get("legacyResourceId"))),
        "email": (node.get("email") or "").strip() or None,
        "created_at": _parse_ts(node.get("createdAt")),
        "processed_at": _parse_ts(node.get("processedAt")),
        "shopify_updated_at": _parse_ts(node.get("updatedAt")),
        "cancelled_at": _parse_ts(node.get("cancelledAt")),
        "closed_at": _parse_ts(node.get("closedAt")),
        "financial_status": node.get("displayFinancialStatus"),
        "fulfillment_status": node.get("displayFulfillmentStatus"),
        "tags": node.get("tags") or [],
        "note": node.get("note"),
        "total_price": _num(total.get("amount")),
        "subtotal_price": _money(node.get("subtotalPriceSet")),
        "total_discounts": _money(node.get("totalDiscountsSet")),
        "total_refunded": _money(node.get("totalRefundedSet")),
        "total_shipping": _money(node.get("totalShippingPriceSet")),
        "currency": total.get("currencyCode"),
        "ship_province_code": ship.get("provinceCode"),
        "ship_province": ship.get("province"),
        "ship_country_code": ship.get("countryCodeV2"),
        "ship_zip": ship.get("zip"),
        "ship_city": ship.get("city"),
        "shipping_line_title": line.get("title"),
        "shipping_carrier_identifier": line.get("carrierIdentifier"),
        "fulfilled_at": _parse_ts(first_f.get("createdAt")),
        "in_transit_at": _parse_ts(first_f.get("inTransitAt")),
        "delivered_at": _parse_ts(first_f.get("deliveredAt")),
        "tracking_company": tracking.get("company"),
        "tracking_number": tracking.get("number"),
        "tracking_url": tracking.get("url"),
        "fulfillments": fulfillments,
        "raw": node,
    }


def _shape_line_item(node: Dict[str, Any], order_shopify_id: int) -> Optional[Dict[str, Any]]:
    shopify_id = _gid_num(node.get("id"))
    if shopify_id is None:
        return None
    product = node.get("product") or {}
    variant = node.get("variant") or {}
    return {
        "order_shopify_id": order_shopify_id,
        "shopify_id": shopify_id,
        "title": node.get("title"),
        "variant_title": node.get("variantTitle"),
        "sku": node.get("sku"),
        "vendor": node.get("vendor"),
        "barcode": (variant.get("barcode") or "").strip() or None,
        "product_title": product.get("title"),
        "product_shopify_id": _int_or_none(product.get("legacyResourceId")),
        "variant_shopify_id": _int_or_none(variant.get("legacyResourceId")),
        "quantity": _int_or_none(node.get("quantity")),
        "current_quantity": _int_or_none(node.get("currentQuantity")),
        "original_unit_price": _money(node.get("originalUnitPriceSet")),
        "discounted_total": _money(node.get("discountedTotalSet")),
        "raw": node,
    }


# ============================================================================
# Batch upserts (run in _sync_executor with their own connections)
# ============================================================================

_CUSTOMER_COLS = (
    "store_id", "shopify_id", "shopify_gid", "email", "email_normalized",
    "first_name", "last_name", "display_name", "phone", "state",
    "verified_email", "tags", "note", "number_of_orders", "amount_spent",
    "currency", "default_address_zip", "default_province_code",
    "default_country_code", "created_at", "shopify_updated_at", "raw", "synced_at",
)

_ORDER_COLS = (
    "store_id", "shopify_id", "shopify_gid", "name", "customer_shopify_id",
    "email", "created_at", "processed_at", "shopify_updated_at", "cancelled_at",
    "closed_at", "financial_status", "fulfillment_status", "tags", "note",
    "total_price", "subtotal_price", "total_discounts", "total_refunded",
    "total_shipping", "currency", "ship_province_code", "ship_province", "ship_country_code",
    "ship_zip", "ship_city", "shipping_line_title", "shipping_carrier_identifier",
    "fulfilled_at", "in_transit_at", "delivered_at", "tracking_company",
    "tracking_number", "tracking_url", "fulfillments", "raw", "synced_at",
)

_LINE_ITEM_COLS = (
    "store_id", "order_shopify_id", "shopify_id", "title", "variant_title",
    "sku", "vendor", "barcode", "product_title", "product_shopify_id",
    "variant_shopify_id", "quantity", "current_quantity", "original_unit_price",
    "discounted_total", "raw",
)


def _upsert_sql(table: str, cols: Tuple[str, ...], conflict: str) -> str:
    updates = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in cols if c not in ("store_id", "shopify_id")
    )
    return (
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s "
        f"ON CONFLICT ({conflict}) DO UPDATE SET {updates}"
    )


_CUSTOMER_UPSERT = _upsert_sql("shopify_customers", _CUSTOMER_COLS, "store_id, shopify_id")
_ORDER_UPSERT = _upsert_sql("shopify_orders", _ORDER_COLS, "store_id, shopify_id")
_LINE_ITEM_UPSERT = _upsert_sql("shopify_order_line_items", _LINE_ITEM_COLS, "store_id, shopify_id")


def _row_tuple(row: Dict[str, Any], cols: Tuple[str, ...], jsonb_cols) -> tuple:
    return tuple(
        Json(row[c]) if c in jsonb_cols and row.get(c) is not None else row.get(c)
        for c in cols
    )


def _dedupe(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Last occurrence wins within a batch. ON CONFLICT DO UPDATE refuses to touch
    the same row twice in one command, and a bulk export can hand us the same
    record more than once — observed live on an orders export.
    """
    seen: Dict[Any, Dict[str, Any]] = {}
    for r in rows:
        seen[r["shopify_id"]] = r
    return list(seen.values())


def _upsert_customers_batch(store_id: int, rows: List[Dict[str, Any]], synced_at: datetime) -> int:
    if not rows:
        return 0
    values = []
    for r in _dedupe(rows):
        r = dict(r, store_id=store_id, synced_at=synced_at)
        values.append(_row_tuple(r, _CUSTOMER_COLS, {"raw"}))
    conn = engine.raw_connection()
    try:
        with conn.cursor() as cur:
            execute_values(cur, _CUSTOMER_UPSERT, values, page_size=500)
        conn.commit()
    finally:
        conn.close()
    return len(values)


def _upsert_orders_batch(
    store_id: int,
    orders: List[Dict[str, Any]],
    line_items: List[Dict[str, Any]],
    synced_at: datetime,
) -> Tuple[int, int]:
    if not orders and not line_items:
        return 0, 0
    orders = _dedupe(orders)
    line_items = _dedupe(line_items)
    order_values = []
    for r in orders:
        r = dict(r, store_id=store_id, synced_at=synced_at)
        order_values.append(_row_tuple(r, _ORDER_COLS, {"raw", "fulfillments"}))
    item_values = []
    for r in line_items:
        r = dict(r, store_id=store_id)
        item_values.append(_row_tuple(r, _LINE_ITEM_COLS, {"raw"}))
    order_ids = [r["shopify_id"] for r in orders]

    conn = engine.raw_connection()
    try:
        with conn.cursor() as cur:
            if order_values:
                execute_values(cur, _ORDER_UPSERT, order_values, page_size=200)
            if order_ids:
                # Order edits can remove or replace lines; delete-then-insert is
                # the only correct simple strategy for a batch we fully own.
                cur.execute(
                    "DELETE FROM shopify_order_line_items "
                    "WHERE store_id = %s AND order_shopify_id = ANY(%s)",
                    (store_id, order_ids),
                )
            if item_values:
                execute_values(cur, _LINE_ITEM_UPSERT, item_values, page_size=500)
        conn.commit()
    finally:
        conn.close()
    return len(orders), len(line_items)


def _prune_stale(store_id: int, run_started: datetime) -> Tuple[int, int]:
    """Full-resync cleanup: rows the run did not touch were deleted in Shopify."""
    conn = engine.raw_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM shopify_orders WHERE store_id = %s AND synced_at < %s",
                (store_id, run_started),
            )
            orders_pruned = cur.rowcount
            cur.execute(
                "DELETE FROM shopify_customers WHERE store_id = %s AND synced_at < %s",
                (store_id, run_started),
            )
            customers_pruned = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return customers_pruned, orders_pruned


def _table_counts(store_id: int) -> Dict[str, int]:
    conn = engine.raw_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM shopify_customers WHERE store_id = %s", (store_id,))
            customers = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM shopify_orders WHERE store_id = %s", (store_id,))
            orders = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM shopify_order_line_items WHERE store_id = %s", (store_id,))
            items = cur.fetchone()[0]
    finally:
        conn.close()
    return {"customers": customers, "orders": orders, "line_items": items}


# ============================================================================
# Sync-state claim / release / progress (short-lived sessions)
# ============================================================================


def claim_sync(store_id: int, mode: str) -> Optional[datetime]:
    """
    Claim the store's sync slot. Returns the run's start timestamp, or None if
    another worker holds a live claim. A claim whose heartbeat is older than
    3 minutes is treated as dead and taken over.
    """
    db = SessionLocal()
    try:
        db.execute(
            text(
                "INSERT INTO shopify_sync_state (store_id) VALUES (:sid) "
                "ON CONFLICT (store_id) DO NOTHING"
            ),
            {"sid": store_id},
        )
        result = db.execute(
            text(
                "UPDATE shopify_sync_state "
                "SET status = 'running', mode = :mode, phase = 'starting', "
                "    run_started_at = now(), heartbeat_at = now(), error = NULL "
                "WHERE store_id = :sid "
                "  AND (status <> 'running' OR heartbeat_at < now() - interval '3 minutes') "
                "RETURNING run_started_at"
            ),
            {"sid": store_id, "mode": mode},
        )
        row = result.fetchone()
        db.commit()
        return row[0] if row else None
    finally:
        db.close()


def release_sync(
    store_id: int,
    *,
    error: Optional[str] = None,
    counts: Optional[Dict[str, int]] = None,
    run_started: Optional[datetime] = None,
    claim_token: Optional[datetime] = None,
) -> None:
    """
    claim_token is the run_started_at the caller's claim_sync returned. When
    given, the release only lands if that claim is still the live one — after
    a staleness takeover the superseded run's release must not flip the new
    claim to idle (which would let a THIRD sync claim mid-run).
    """
    fence = "AND (CAST(:ct AS timestamptz) IS NULL OR run_started_at = :ct)"
    db = SessionLocal()
    try:
        if error is None and counts is not None:
            db.execute(
                text(
                    "UPDATE shopify_sync_state SET status = 'idle', phase = NULL, "
                    "    last_completed_at = now(), last_sync_started_at = :started, "
                    "    customers_count = :c, orders_count = :o, line_items_count = :li, "
                    "    error = NULL "
                    f"WHERE store_id = :sid {fence}"
                ),
                {
                    "sid": store_id,
                    "started": run_started,
                    "ct": claim_token,
                    "c": counts.get("customers", 0),
                    "o": counts.get("orders", 0),
                    "li": counts.get("line_items", 0),
                },
            )
        else:
            db.execute(
                text(
                    "UPDATE shopify_sync_state SET "
                    "    status = CASE WHEN :err = 'cancelled' THEN 'idle' ELSE 'error' END, "
                    "    phase = NULL, error = :err "
                    f"WHERE store_id = :sid {fence}"
                ),
                {"sid": store_id, "err": error or "unknown error", "ct": claim_token},
            )
        db.commit()
    finally:
        db.close()


def _touch_state(
    store_id: int,
    phase: Optional[str] = None,
    tz: Optional[str] = None,
    claim_token: Optional[datetime] = None,
) -> None:
    db = SessionLocal()
    try:
        db.execute(
            text(
                "UPDATE shopify_sync_state SET heartbeat_at = now(), "
                "    phase = COALESCE(:phase, phase), "
                "    shop_timezone = COALESCE(:tz, shop_timezone) "
                "WHERE store_id = :sid "
                "  AND (CAST(:ct AS timestamptz) IS NULL OR run_started_at = :ct)"
            ),
            {"sid": store_id, "phase": phase, "tz": tz, "ct": claim_token},
        )
        db.commit()
    finally:
        db.close()


def get_sync_states() -> List[Dict[str, Any]]:
    """All Shopify stores joined with their sync state, for the status endpoint."""
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                "SELECT s.id AS store_id, s.name, s.is_active, "
                "       st.status, st.phase, st.mode, st.run_started_at, st.heartbeat_at, "
                "       st.last_completed_at, st.shop_timezone, "
                "       st.customers_count, st.orders_count, st.line_items_count, st.error "
                "FROM stores s "
                "JOIN shopify_connections sc ON sc.store_id = s.id "
                "LEFT JOIN shopify_sync_state st ON st.store_id = s.id "
                "WHERE s.store_type = 'shopify' "
                "ORDER BY s.id"
            )
        ).mappings().all()
    finally:
        db.close()

    out = []
    for r in rows:
        d = dict(r)
        # A claim whose heartbeat went stale is a dead run, not a running one.
        status = d.get("status") or "never"
        hb = d.get("heartbeat_at")
        if status == "running" and hb is not None:
            now = datetime.now(timezone.utc)
            if hb.tzinfo is None:
                hb = hb.replace(tzinfo=timezone.utc)
            if (now - hb) > timedelta(minutes=3):
                status = "error"
                d["error"] = d.get("error") or "sync worker died (stale heartbeat)"
        d["status"] = status
        for key in ("run_started_at", "heartbeat_at", "last_completed_at"):
            if d.get(key) is not None:
                d[key] = d[key].isoformat()
        out.append(d)
    return out


def get_synced_stores() -> Dict[int, Dict[str, Any]]:
    """
    Stores whose local data is usable for reports: a successful sync exists
    and no live FULL resync is rewriting the mirror right now. A full resync
    ends with a prune that deletes rows between a report's queries, so reading
    through one can hand a single run an inconsistent old/new mix — those
    stores fall back to the live API until it finishes. Incremental runs are
    only idempotent upserts and stay readable.
    """
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                "SELECT store_id, last_completed_at, shop_timezone "
                "FROM shopify_sync_state "
                "WHERE last_completed_at IS NOT NULL "
                "  AND NOT (status = 'running' AND mode = 'full' "
                "           AND heartbeat_at > now() - interval '3 minutes')"
            )
        ).mappings().all()
        return {r["store_id"]: dict(r) for r in rows}
    finally:
        db.close()


# ============================================================================
# Bulk operation runner
# ============================================================================


class _BulkTracker:
    """Holds the in-flight bulk op id so cancellation can reach it."""

    def __init__(self) -> None:
        self.current_id: Optional[str] = None


async def _run_bulk_query(
    session: aiohttp.ClientSession,
    store: Dict[str, Any],
    inner_query: str,
    emit,
    phase: str,
    tracker: _BulkTracker,
) -> Optional[str]:
    """
    Submit a bulk query and poll until it completes. Returns the JSONL download
    url, or None when the result set is empty. Raises ShopifyFetchError on
    FAILED/CANCELED or submission errors.
    """
    data, _ = await _shopify_graphql(
        session, store["shop_domain"], store["admin_api_key"], store["api_version"],
        _RUN_BULK_MUTATION, {"query": inner_query}, op_name=f"{phase} bulk submit",
    )
    payload = data.get("bulkOperationRunQuery") or {}
    errors = payload.get("userErrors") or []
    if errors:
        msg = "; ".join(str(e.get("message") or e) for e in errors)
        raise ShopifyFetchError(f"Bulk operation rejected: {msg}", code="BULK_REJECTED")
    op = payload.get("bulkOperation") or {}
    op_id = op.get("id")
    if not op_id:
        raise ShopifyFetchError("Bulk operation submission returned no id", code="BULK_REJECTED")
    tracker.current_id = op_id

    last_count = -1
    while True:
        await asyncio.sleep(_BULK_POLL_SECONDS)
        data, _ = await _shopify_graphql(
            session, store["shop_domain"], store["admin_api_key"], store["api_version"],
            _CURRENT_BULK_QUERY, {}, op_name=f"{phase} bulk poll",
        )
        op = data.get("currentBulkOperation") or {}
        if op.get("id") != op_id:
            raise ShopifyFetchError(
                "Another bulk operation replaced ours on this shop", code="BULK_REPLACED"
            )
        status = op.get("status")
        count = _int_or_none(op.get("objectCount")) or 0
        if count != last_count:
            last_count = count
            await emit("progress", {"phase": phase, "detail": "Shopify is exporting", "object_count": count})
        if status == "COMPLETED":
            tracker.current_id = None
            return op.get("url")
        if status in ("FAILED", "CANCELED", "EXPIRED"):
            tracker.current_id = None
            raise ShopifyFetchError(
                f"Bulk operation {status.lower()}: {op.get('errorCode') or 'no error code'}",
                code=f"BULK_{status}",
            )


async def cancel_bulk_operation(store: Dict[str, Any], op_id: str) -> None:
    """Best-effort cancel of an in-flight bulk op after the client disconnects."""
    try:
        async with aiohttp.ClientSession() as session:
            await _shopify_graphql(
                session, store["shop_domain"], store["admin_api_key"], store["api_version"],
                _CANCEL_BULK_MUTATION, {"id": op_id}, op_name="bulk cancel",
            )
    except Exception:
        pass


async def _stream_jsonl(session: aiohttp.ClientSession, url: str, line_handler) -> None:
    """
    Download a bulk-result JSONL file, invoking `await line_handler(obj)` per
    line. Streams: result files can run to hundreds of MB.
    """
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=3600)) as response:
        if response.status != 200:
            raise ShopifyFetchError(
                f"Bulk result download failed (HTTP {response.status})", code="BULK_DOWNLOAD"
            )
        buffer = b""
        async for chunk in response.content.iter_chunked(1 << 16):
            buffer += chunk
            while True:
                nl = buffer.find(b"\n")
                if nl < 0:
                    break
                line = buffer[:nl]
                buffer = buffer[nl + 1:]
                if line.strip():
                    await line_handler(json.loads(line))
        if buffer.strip():
            await line_handler(json.loads(buffer))


# ============================================================================
# Sync orchestration
# ============================================================================


async def _sync_customers_bulk(session, store, emit, run_started, search=None) -> int:
    url = await _run_bulk_query(
        session, store, _bulk_customers_query(search), emit, "customers_bulk",
        store["_tracker"],
    )
    total = 0
    if url is None:
        return total
    loop = asyncio.get_running_loop()
    buffer: List[Dict[str, Any]] = []

    async def flush():
        nonlocal total, buffer
        if not buffer:
            return
        batch, buffer = buffer, []
        total += await loop.run_in_executor(
            _sync_executor, _upsert_customers_batch, store["id"], batch, run_started
        )
        await emit("progress", {"phase": "customers_upsert", "detail": "Saving customers", "upserted": total})

    async def handle(obj):
        row = _shape_customer(obj)
        if row is not None:
            buffer.append(row)
        if len(buffer) >= _FLUSH_CUSTOMERS:
            await flush()

    await emit("progress", {"phase": "customers_download", "detail": "Downloading customers"})
    await _stream_jsonl(session, url, handle)
    await flush()
    return total


async def _sync_orders_bulk(session, store, emit, run_started, search=None) -> Tuple[int, int]:
    url = await _run_bulk_query(
        session, store, _bulk_orders_query(search), emit, "orders_bulk",
        store["_tracker"],
    )
    orders_total = 0
    items_total = 0
    if url is None:
        return orders_total, items_total
    loop = asyncio.get_running_loop()
    pending_orders: List[Dict[str, Any]] = []
    pending_items: List[Dict[str, Any]] = []
    # Bulk exports have been observed to emit the same record twice. A repeat
    # of an order line arriving WITHOUT its children in a later batch would
    # pass through the delete-then-insert upsert and wipe the line items the
    # first occurrence stored — so repeats are dropped here, not deduped later.
    seen_order_ids: set = set()

    async def flush():
        nonlocal orders_total, items_total, pending_orders, pending_items
        if not pending_orders and not pending_items:
            return
        orders_batch, pending_orders = pending_orders, []
        items_batch, pending_items = pending_items, []
        o, li = await loop.run_in_executor(
            _sync_executor, _upsert_orders_batch,
            store["id"], orders_batch, items_batch, run_started,
        )
        orders_total += o
        items_total += li
        await emit("progress", {
            "phase": "orders_upsert", "detail": "Saving orders",
            "upserted": orders_total, "line_items": items_total,
        })

    async def handle(obj):
        parent_gid = obj.get("__parentId")
        if parent_gid is None:
            # A new order line means every previously seen order (and its line
            # items, which Shopify emits after their parent) is complete.
            if len(pending_orders) >= _FLUSH_ORDERS:
                await flush()
            row = _shape_order(obj)
            if row is not None and row["shopify_id"] not in seen_order_ids:
                seen_order_ids.add(row["shopify_id"])
                pending_orders.append(row)
        else:
            parent_id = _gid_num(parent_gid)
            if parent_id is not None:
                row = _shape_line_item(obj, parent_id)
                if row is not None:
                    pending_items.append(row)

    await emit("progress", {"phase": "orders_download", "detail": "Downloading orders"})
    await _stream_jsonl(session, url, handle)
    await flush()
    return orders_total, items_total


def _delta_filter(anchor: datetime) -> str:
    since = (anchor - timedelta(minutes=_DELTA_OVERLAP_MINUTES)).astimezone(timezone.utc)
    return f"updated_at:>='{since.strftime('%Y-%m-%dT%H:%M:%SZ')}'"


async def _sync_customers_delta(session, store, emit, run_started, anchor) -> int:
    """Paginate updated customers; escalate to a filtered bulk op near the cap."""
    q = _delta_filter(anchor)
    total = 0
    cursor = None
    loop = asyncio.get_running_loop()
    for page in range(_DELTA_MAX_PAGES_CUSTOMERS):
        data, _ = await _shopify_graphql(
            session, store["shop_domain"], store["admin_api_key"], store["api_version"],
            _CUSTOMERS_DELTA_QUERY, {"q": q, "after": cursor}, op_name="customers delta",
        )
        conn = data.get("customers") or {}
        rows = [r for r in map(_shape_customer, conn.get("nodes") or []) if r is not None]
        if rows:
            total += await loop.run_in_executor(
                _sync_executor, _upsert_customers_batch, store["id"], rows, run_started
            )
            await emit("progress", {"phase": "customers_upsert", "detail": "Saving changed customers", "upserted": total})
        info = conn.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            return total
        cursor = info.get("endCursor")
    # Delta too large for cursor pagination — rerun the phase as a filtered bulk op.
    await emit("progress", {"phase": "customers_bulk", "detail": "Large delta, switching to bulk export"})
    return await _sync_customers_bulk(session, store, emit, run_started, search=q)


async def _fetch_remaining_line_items(
    session, store, order_gid: str, order_id: int, after: Optional[str]
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    cursor = after
    while cursor:
        data, _ = await _shopify_graphql(
            session, store["shop_domain"], store["admin_api_key"], store["api_version"],
            _ORDER_LINE_ITEMS_PAGE_QUERY, {"id": order_gid, "after": cursor},
            op_name="order line items page",
        )
        conn = ((data.get("node") or {}).get("lineItems")) or {}
        for li in conn.get("nodes") or []:
            item = _shape_line_item(li, order_id)
            if item is not None:
                items.append(item)
        info = conn.get("pageInfo") or {}
        cursor = info.get("endCursor") if info.get("hasNextPage") else None
    return items


async def _sync_orders_delta(session, store, emit, run_started, anchor) -> Tuple[int, int]:
    q = _delta_filter(anchor)
    orders_total = 0
    items_total = 0
    cursor = None
    loop = asyncio.get_running_loop()
    for page in range(_DELTA_MAX_PAGES_ORDERS):
        data, _ = await _shopify_graphql(
            session, store["shop_domain"], store["admin_api_key"], store["api_version"],
            _ORDERS_DELTA_QUERY, {"q": q, "after": cursor}, op_name="orders delta",
        )
        conn = data.get("orders") or {}
        orders = []
        items = []
        for node in conn.get("nodes") or []:
            row = _shape_order(node)
            if row is None:
                continue
            orders.append(row)
            li_conn = node.get("lineItems") or {}
            for li in li_conn.get("nodes") or []:
                item = _shape_line_item(li, row["shopify_id"])
                if item is not None:
                    items.append(item)
            li_info = li_conn.get("pageInfo") or {}
            if li_info.get("hasNextPage"):
                items.extend(await _fetch_remaining_line_items(
                    session, store, row["shopify_gid"], row["shopify_id"],
                    li_info.get("endCursor"),
                ))
        if orders:
            o, li = await loop.run_in_executor(
                _sync_executor, _upsert_orders_batch, store["id"], orders, items, run_started
            )
            orders_total += o
            items_total += li
            await emit("progress", {
                "phase": "orders_upsert", "detail": "Saving changed orders",
                "upserted": orders_total, "line_items": items_total,
            })
        info = conn.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            return orders_total, items_total
        cursor = info.get("endCursor")
    await emit("progress", {"phase": "orders_bulk", "detail": "Large delta, switching to bulk export"})
    return await _sync_orders_bulk(session, store, emit, run_started, search=q)


async def run_store_sync(
    store: Dict[str, Any],
    mode: str,
    anchor: Optional[datetime],
    emit,
    tracker: Optional[_BulkTracker] = None,
    claim_token: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Execute one claimed sync run. The caller has already claimed the state row
    and is responsible for release_sync in every exit path.

    store: {id, name, shop_domain, admin_api_key, api_version}
    mode: 'full' | 'incremental' (incremental requires anchor = last successful
          run's start time)
    emit: async callback(event_type, payload) feeding the SSE stream.
    tracker: pass one in to reach the in-flight bulk op id on cancellation.
    claim_token: the run_started_at claim_sync returned; fences every state
          write so a superseded run cannot touch a newer claim.
    """
    store = dict(store)
    store["shop_domain"] = validate_shop_domain(store["shop_domain"])
    tracker = tracker or _BulkTracker()
    store["_tracker"] = tracker
    run_started = datetime.now(timezone.utc)
    started_mono = asyncio.get_running_loop().time()

    heartbeat_task: Optional[asyncio.Task] = None

    async def heartbeat_loop():
        # Runs on the default executor, NOT _sync_executor: with two stores
        # syncing in one worker, two long upserts can occupy both sync threads
        # for minutes and a queued heartbeat would go stale enough to trigger
        # a takeover of a perfectly live run. And one transient DB error must
        # not kill the loop — a dead heartbeat IS a takeover, three minutes
        # later, no matter how healthy the sync is.
        while True:
            await asyncio.sleep(_HEARTBEAT_SECONDS)
            try:
                await asyncio.to_thread(
                    _touch_state, store["id"], None, None, claim_token
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[SHOPIFY-SYNC] heartbeat write failed for store {store['id']}: {e}")

    try:
        heartbeat_task = asyncio.create_task(heartbeat_loop())
        async with aiohttp.ClientSession() as session:
            tz = await fetch_shop_timezone(
                store["shop_domain"], store["admin_api_key"], store["api_version"]
            )
            first_phase = "customers_bulk" if mode == "full" else "customers_delta"
            await asyncio.to_thread(
                _touch_state, store["id"], first_phase, tz, claim_token
            )

            if mode == "incremental" and anchor is not None:
                customers = await _sync_customers_delta(session, store, emit, run_started, anchor)
                orders, items = await _sync_orders_delta(session, store, emit, run_started, anchor)
            else:
                mode = "full"
                customers = await _sync_customers_bulk(session, store, emit, run_started)
                orders, items = await _sync_orders_bulk(session, store, emit, run_started)
                await emit("progress", {"phase": "pruning", "detail": "Removing deleted records"})
                await asyncio.get_running_loop().run_in_executor(
                    _sync_executor, _prune_stale, store["id"], run_started
                )

        counts = await asyncio.get_running_loop().run_in_executor(
            _sync_executor, _table_counts, store["id"]
        )
        return {
            "mode": mode,
            "run_started": run_started,
            "synced": {"customers": customers, "orders": orders, "line_items": items},
            "totals": counts,
            "seconds": round(asyncio.get_running_loop().time() - started_mono, 1),
        }
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
