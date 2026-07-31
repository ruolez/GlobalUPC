"""
Local-data variants of the Shopify fetches the Lost Customers report makes.

Each function returns the exact shape of its live counterpart in
shopify_helper.py, so the report's orchestration, classification, judging and
SSE emission run unchanged — the endpoint just swaps the fetch when the store
has a completed sync. None of the live path's sharding/page-budget machinery
exists here: it compensates for API limits PostgreSQL does not have.

Two semantic rules are load-bearing and must mirror the live path exactly:

- Completed order = ``cancelled_at IS NULL AND financial_status IS DISTINCT
  FROM 'REFUNDED'`` — the SQL translation of ORDER_STATUS_FILTER
  ("-status:cancelled -financial_status:refunded", PARTIALLY_REFUNDED kept).
- Every window comparison happens on the shop's LOCAL calendar day, because
  Shopify's own search filters do. Timestamps are stored UTC and converted
  with ``AT TIME ZONE``.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from database import engine
from shopify_helper import (
    _days_between,
    _normalize_carrier,
    _normalize_shipping_method,
    name_key,
    normalize_email,
    normalize_name,
    normalize_zip,
)

# The SQL twin of EXCLUDED_ANALYSIS_TAGS: exact tag match, case-insensitive —
# "potential fraud" does not match "fraud", same as Shopify's tag: search.
def _no_excluded_tags(col: str) -> str:
    return (
        f"NOT EXISTS (SELECT 1 FROM unnest(coalesce({col}, '{{}}')) bt "
        f"WHERE lower(bt) IN ('banned', 'fraud'))"
    )


# The SQL twin of ANALYSIS_ORDER_FILTER. IS DISTINCT FROM, not <>: a NULL
# financial status is not "refunded" and must stay in. Orders tagged banned or
# fraudulent are not purchases either.
_COMPLETED = (
    "o.cancelled_at IS NULL AND o.financial_status IS DISTINCT FROM 'REFUNDED' "
    f"AND {_no_excluded_tags('o.tags')}"
)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _gid_num(gid: Optional[str]) -> Optional[int]:
    if not gid:
        return None
    try:
        return int(str(gid).rsplit("/", 1)[-1].split("?")[0])
    except (TypeError, ValueError):
        return None


def _tz_or_utc(tz: Optional[str]) -> str:
    return tz or "UTC"


def _run(fn, *args):
    return asyncio.to_thread(fn, *args)


# ============================================================================
# Per-store scan — local twin of fetch_customers_with_last_order (whole store
# in one query; the caller's sharding never applies).
# ============================================================================

_SCAN_SQL = f"""
SELECT
    c.shopify_id, c.shopify_gid, c.display_name, c.first_name, c.last_name,
    c.email, c.created_at AS customer_created_at, c.number_of_orders,
    c.amount_spent, c.currency, c.default_address_zip,
    lo.shopify_gid AS lo_gid, lo.name AS lo_name, lo.created_at AS lo_created_at,
    lo.fulfillment_status AS lo_fulfillment_status,
    lo.ship_province_code, lo.ship_province, lo.ship_country_code, lo.ship_zip,
    lo.shipping_line_title, lo.fulfillments AS lo_fulfillments
FROM shopify_customers c
LEFT JOIN LATERAL (
    SELECT o.* FROM shopify_orders o
    WHERE o.store_id = c.store_id AND o.customer_shopify_id = c.shopify_id
      AND {_COMPLETED}
    ORDER BY o.created_at DESC
    LIMIT 1
) lo ON true
WHERE c.store_id = :sid
  AND {_no_excluded_tags('c.tags')}
  AND EXISTS (
      SELECT 1 FROM shopify_orders o
      WHERE o.store_id = c.store_id AND o.customer_shopify_id = c.shopify_id
        AND (CAST(:hf AS date) IS NULL
             OR (o.created_at AT TIME ZONE :tz)::date >= CAST(:hf AS date))
  )
"""


def _scan_store_sync(store_id: int, tz: Optional[str], history_from: Optional[str]) -> Dict[str, Any]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(_SCAN_SQL),
            {"sid": store_id, "tz": _tz_or_utc(tz), "hf": history_from},
        ).mappings().all()

    customers: List[Dict[str, Any]] = []
    for r in rows:
        # Mirrors _normalize_lost_customer field for field.
        row: Dict[str, Any] = {
            "customer_id": r["shopify_gid"],
            "name": r["display_name"] or "",
            "first_name": r["first_name"] or "",
            "last_name": r["last_name"] or "",
            "email": r["email"],
            "customer_since": _iso(r["customer_created_at"]),
            "orders_count": int(r["number_of_orders"] or 0),
            "amount_spent": float(r["amount_spent"] or 0),
            "currency": r["currency"] or "USD",
            "last_order_id": None,
            "last_order_name": None,
            "last_order_created_at": None,
            "shipping_method": None,
            "shipping_method_raw": None,
            "state": None,
            "state_name": None,
            "country": None,
            "zips": sorted({z for z in (normalize_zip(r["default_address_zip"]),) if z}),
            "carrier": None,
            "tracking_url": None,
            "fulfillment_status": None,
            "days_to_fulfil": None,
            "days_to_deliver": None,
            "days_total": None,
        }

        if r["lo_gid"]:
            row["last_order_id"] = r["lo_gid"]
            row["last_order_name"] = r["lo_name"]
            row["last_order_created_at"] = _iso(r["lo_created_at"])
            row["fulfillment_status"] = r["lo_fulfillment_status"]
            row["shipping_method_raw"] = r["shipping_line_title"]
            row["shipping_method"] = _normalize_shipping_method(r["shipping_line_title"])
            row["state"] = (r["ship_province_code"] or "").strip().upper() or None
            row["state_name"] = (r["ship_province"] or "").strip() or None
            row["country"] = (r["ship_country_code"] or "").strip().upper() or None
            row["zips"] = sorted({z for z in (
                normalize_zip(r["default_address_zip"]),
                normalize_zip(r["ship_zip"]),
            ) if z})

            fulfillments = r["lo_fulfillments"] or []
            if fulfillments:
                created = [f.get("createdAt") for f in fulfillments if f.get("createdAt")]
                delivered = [f.get("deliveredAt") for f in fulfillments if f.get("deliveredAt")]
                first_ship = min(created) if created else None
                last_deliver = max(delivered) if delivered else None
                row["days_to_fulfil"] = _days_between(row["last_order_created_at"], first_ship)
                row["days_to_deliver"] = _days_between(first_ship, last_deliver)
                row["days_total"] = _days_between(row["last_order_created_at"], last_deliver)
                for f in fulfillments:
                    for t in f.get("trackingInfo") or []:
                        if t.get("company") and not row["carrier"]:
                            row["carrier"] = _normalize_carrier(t.get("company"))
                        if t.get("url") and not row["tracking_url"]:
                            row["tracking_url"] = t.get("url")

        customers.append(row)

    return {
        "ok": True, "complete": True, "incomplete_reason": None, "error": None,
        "customers": customers, "warnings": [], "pages": 0, "resume_from": None,
    }


async def scan_store(store_id: int, tz: Optional[str], history_from: Optional[str]) -> Dict[str, Any]:
    return await _run(_scan_store_sync, store_id, tz, history_from)


# ============================================================================
# First orders + true order counts — local twin of fetch_customer_first_orders
# ============================================================================

_FIRST_ORDERS_SQL = f"""
SELECT o.customer_shopify_id,
       count(*) AS lifetime,
       count(*) FILTER (WHERE {_COMPLETED}) AS completed,
       min(o.created_at) FILTER (WHERE {_COMPLETED}) AS first_completed
FROM shopify_orders o
WHERE o.store_id = :sid AND o.customer_shopify_id = ANY(:ids)
GROUP BY o.customer_shopify_id
"""


def _first_orders_sync(store_id: int, customer_gids: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": True, "error": None, "first_orders": {}, "order_counts": {},
        "undercounted": 0, "undercounted_ids": [], "missing": 0, "warnings": [],
    }
    gid_by_num = {}
    for gid in customer_gids:
        num = _gid_num(gid)
        if num is not None:
            gid_by_num[num] = gid
    if not gid_by_num:
        return out

    with engine.connect() as conn:
        rows = conn.execute(
            text(_FIRST_ORDERS_SQL),
            {"sid": store_id, "ids": list(gid_by_num.keys())},
        ).mappings().all()

    seen = set()
    for r in rows:
        gid = gid_by_num.get(r["customer_shopify_id"])
        if not gid:
            continue
        seen.add(gid)
        # Local counts are exact — the live path's undercounting comes from a
        # capped exclusion page that does not exist here.
        out["order_counts"][gid] = (int(r["completed"] or 0), int(r["lifetime"] or 0))
        if r["first_completed"] is not None:
            out["first_orders"][gid] = _iso(r["first_completed"])
        else:
            out["missing"] += 1
    out["missing"] += sum(1 for g in gid_by_num.values() if g not in seen)
    return out


async def first_orders(store_id: int, customer_gids: List[str]) -> Dict[str, Any]:
    return await _run(_first_orders_sync, store_id, customer_gids)


# ============================================================================
# Cross-store email probe — local twin of fetch_customers_by_emails
# ============================================================================

_EMAILS_SQL = f"""
SELECT c.email_normalized,
       c.created_at AS account_created,
       lo.created_at AS last_order_at,
       fo.created_at AS first_order_at,
       w.window_dates
FROM shopify_customers c
LEFT JOIN LATERAL (
    SELECT o.created_at FROM shopify_orders o
    WHERE o.store_id = c.store_id AND o.customer_shopify_id = c.shopify_id
      AND {_COMPLETED}
    ORDER BY o.created_at DESC LIMIT 1
) lo ON true
LEFT JOIN LATERAL (
    SELECT o.created_at FROM shopify_orders o
    WHERE o.store_id = c.store_id AND o.customer_shopify_id = c.shopify_id
      AND {_COMPLETED}
    ORDER BY o.created_at ASC LIMIT 1
) fo ON :want_origin
LEFT JOIN LATERAL (
    SELECT array_agg(o.created_at ORDER BY o.created_at) AS window_dates
    FROM shopify_orders o
    WHERE o.store_id = c.store_id AND o.customer_shopify_id = c.shopify_id
      AND {_COMPLETED}
      AND (o.created_at AT TIME ZONE :tz)::date >= CAST(:win_lo AS date)
      AND (o.created_at AT TIME ZONE :tz)::date <  CAST(:win_hi AS date)
) w ON :want_window
WHERE c.store_id = :sid AND c.email_normalized = ANY(:emails)
"""


def _emails_probe_sync(
    store_id: int,
    tz: Optional[str],
    emails: List[str],
    want_origin: bool,
    window: Optional[Tuple[str, str]],
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": True, "error": None, "last_orders": {}, "first_orders": {},
        "accounts": {}, "window_orders": {}, "window_saturated": [],
        "malformed": 0, "warnings": [],
    }
    lookup = sorted({e for e in (normalize_email(x) for x in emails) if e})
    if not lookup:
        return out

    with engine.connect() as conn:
        rows = conn.execute(
            text(_EMAILS_SQL),
            {
                "sid": store_id, "emails": lookup, "tz": _tz_or_utc(tz),
                "want_origin": want_origin, "want_window": bool(window),
                "win_lo": window[0] if window else None,
                "win_hi": window[1] if window else None,
            },
        ).mappings().all()

    for r in rows:
        em = r["email_normalized"]
        if not em:
            continue
        last = _iso(r["last_order_at"])
        prev = out["last_orders"].get(em)
        if last and (prev is None or last > prev):
            out["last_orders"][em] = last
        else:
            out["last_orders"].setdefault(em, prev)
        if window:
            dates = [_iso(d) for d in (r["window_dates"] or [])]
            if dates:
                out["window_orders"].setdefault(em, []).extend(dates)
            continue
        if not want_origin:
            continue
        first = _iso(r["first_order_at"])
        prevf = out["first_orders"].get(em)
        if first and (prevf is None or first < prevf):
            out["first_orders"][em] = first
        else:
            out["first_orders"].setdefault(em, prevf)
        made = _iso(r["account_created"])
        preva = out["accounts"].get(em)
        if made and (preva is None or made < preva):
            out["accounts"][em] = made
        else:
            out["accounts"].setdefault(em, preva)

    for dates in out["window_orders"].values():
        dates.sort()
    # Never saturated: unlike the live 5-order window page, the SQL sees every
    # in-window order, so the "unknown" verdict cannot arise from truncation.
    return out


async def emails_probe(
    store_id: int,
    tz: Optional[str],
    emails: List[str],
    want_origin: bool = False,
    window: Optional[Tuple[str, str]] = None,
) -> Dict[str, Any]:
    return await _run(_emails_probe_sync, store_id, tz, emails, want_origin, window)


# ============================================================================
# Cross-store name+ZIP probe — local twin of fetch_customers_by_name
# ============================================================================

# The key must collapse whitespace exactly as normalize_name does, or a name
# stored with a double space would silently stop matching its own record.
_NAME_KEY_SQL = (
    "lower(regexp_replace(btrim(coalesce(c.first_name, '')), '\\s+', ' ', 'g')) "
    "|| '|' || "
    "lower(regexp_replace(btrim(coalesce(c.last_name, '')), '\\s+', ' ', 'g'))"
)

_NAMES_SQL = f"""
SELECT c.shopify_gid, c.first_name, c.last_name, c.email,
       c.default_address_zip, c.created_at AS account_created,
       lo.created_at AS last_order_at, lo.ship_zip AS lo_ship_zip,
       fo.created_at AS first_order_at,
       w.window_dates
FROM shopify_customers c
LEFT JOIN LATERAL (
    SELECT o.created_at, o.ship_zip FROM shopify_orders o
    WHERE o.store_id = c.store_id AND o.customer_shopify_id = c.shopify_id
      AND {_COMPLETED}
    ORDER BY o.created_at DESC LIMIT 1
) lo ON true
LEFT JOIN LATERAL (
    SELECT o.created_at FROM shopify_orders o
    WHERE o.store_id = c.store_id AND o.customer_shopify_id = c.shopify_id
      AND {_COMPLETED}
    ORDER BY o.created_at ASC LIMIT 1
) fo ON :want_origin
LEFT JOIN LATERAL (
    SELECT array_agg(o.created_at ORDER BY o.created_at) AS window_dates
    FROM shopify_orders o
    WHERE o.store_id = c.store_id AND o.customer_shopify_id = c.shopify_id
      AND {_COMPLETED}
      AND (o.created_at AT TIME ZONE :tz)::date >= CAST(:win_lo AS date)
      AND (o.created_at AT TIME ZONE :tz)::date <  CAST(:win_hi AS date)
) w ON :want_window
WHERE c.store_id = :sid AND {_NAME_KEY_SQL} = ANY(:keys)
"""


def _names_probe_sync(
    store_id: int,
    tz: Optional[str],
    names: List[tuple],
    want_origin: bool,
    window: Optional[Tuple[str, str]],
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": True, "error": None, "candidates": [], "truncated": False, "warnings": [],
    }
    keys = sorted({
        f"{normalize_name(a)}|{normalize_name(b)}"
        for a, b in names if normalize_name(a) and normalize_name(b)
    })
    if not keys:
        return out

    with engine.connect() as conn:
        rows = conn.execute(
            text(_NAMES_SQL),
            {
                "sid": store_id, "keys": keys, "tz": _tz_or_utc(tz),
                "want_origin": want_origin, "want_window": bool(window),
                "win_lo": window[0] if window else None,
                "win_hi": window[1] if window else None,
            },
        ).mappings().all()

    for r in rows:
        k = name_key(r["first_name"], r["last_name"])
        if not k:
            continue
        extra: Dict[str, Any] = {}
        if window:
            extra = {
                "window_orders": [_iso(d) for d in (r["window_dates"] or [])],
                "window_saturated": False,
            }
        elif want_origin:
            extra = {
                "first_order": _iso(r["first_order_at"]),
                "account_created": _iso(r["account_created"]),
            }
        out["candidates"].append({
            **extra,
            "id": r["shopify_gid"],
            "name_key": k,
            "zips": sorted({z for z in (
                normalize_zip(r["default_address_zip"]),
                normalize_zip(r["lo_ship_zip"]),
            ) if z}),
            "last_order": _iso(r["last_order_at"]),
            "email": normalize_email(r["email"]),
        })
    return out


async def names_probe(
    store_id: int,
    tz: Optional[str],
    names: List[tuple],
    want_origin: bool = False,
    window: Optional[Tuple[str, str]] = None,
) -> Dict[str, Any]:
    return await _run(_names_probe_sync, store_id, tz, names, want_origin, window)


# ============================================================================
# Customer detail modal — local twin of fetch_customer_recent_orders
# ============================================================================

_RECENT_ORDERS_SQL = f"""
SELECT o.shopify_gid, o.name, o.created_at, o.cancelled_at,
       o.fulfillment_status, o.financial_status, o.total_price, o.currency,
       o.shipping_line_title, o.fulfillments
FROM shopify_orders o
WHERE o.store_id = :sid AND o.customer_shopify_id = :cid AND {_COMPLETED}
ORDER BY o.created_at DESC
LIMIT :n
"""

_ORDER_ITEMS_BY_ORDER_SQL = """
SELECT li.order_shopify_id, li.title, li.quantity, li.sku, li.variant_title,
       li.original_unit_price
FROM shopify_order_line_items li
WHERE li.store_id = :sid AND li.order_shopify_id = ANY(:oids)
ORDER BY li.id
"""


def _recent_orders_sync(store_id: int, customer_gid: str, limit: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": False, "error": None, "orders": []}
    cid = _gid_num(customer_gid)
    if cid is None:
        out["error"] = "Missing customer id"
        return out

    with engine.connect() as conn:
        rows = conn.execute(
            text(_RECENT_ORDERS_SQL),
            {"sid": store_id, "cid": cid, "n": max(1, min(limit, 20))},
        ).mappings().all()
        items_by_order: Dict[int, List[Dict[str, Any]]] = {}
        if rows:
            oids = [_gid_num(r["shopify_gid"]) for r in rows]
            for li in conn.execute(
                text(_ORDER_ITEMS_BY_ORDER_SQL),
                {"sid": store_id, "oids": [o for o in oids if o is not None]},
            ).mappings():
                items_by_order.setdefault(li["order_shopify_id"], []).append(li)

    for r in rows:
        created = _iso(r["created_at"])
        fulfillments = r["fulfillments"] or []
        f_created = [f.get("createdAt") for f in fulfillments if f.get("createdAt")]
        f_delivered = [f.get("deliveredAt") for f in fulfillments if f.get("deliveredAt")]
        first_ship = min(f_created) if f_created else None
        last_deliver = max(f_delivered) if f_delivered else None
        carrier = None
        for f in fulfillments:
            for t in f.get("trackingInfo") or []:
                if t.get("company"):
                    carrier = _normalize_carrier(t.get("company"))
                    break
            if carrier:
                break
        currency = r["currency"] or "USD"
        out["orders"].append({
            "id": r["shopify_gid"],
            "name": r["name"],
            "created_at": created,
            "cancelled_at": _iso(r["cancelled_at"]),
            "fulfillment_status": r["fulfillment_status"],
            "financial_status": r["financial_status"],
            "total_amount": str(r["total_price"] if r["total_price"] is not None else "0"),
            "currency": currency,
            "shipping_method": _normalize_shipping_method(r["shipping_line_title"]),
            "shipping_method_raw": r["shipping_line_title"],
            "carrier": carrier,
            "days_to_fulfil": _days_between(created, first_ship),
            "days_to_deliver": _days_between(first_ship, last_deliver),
            "days_total": _days_between(created, last_deliver),
            "line_items": [
                {
                    "title": li["title"] or "",
                    "quantity": li["quantity"] or 0,
                    "sku": li["sku"] or "",
                    "variant_title": li["variant_title"] or "",
                    # Live sends originalTotalSet (unit price x quantity).
                    "amount": str(
                        (li["original_unit_price"] or 0) * (li["quantity"] or 0)),
                    "currency": currency,
                }
                for li in items_by_order.get(_gid_num(r["shopify_gid"]), [])
            ],
        })
    out["ok"] = True
    return out


async def recent_orders(store_id: int, customer_gid: str, limit: int = 5) -> Dict[str, Any]:
    return await _run(_recent_orders_sync, store_id, customer_gid, limit)


# ============================================================================
# Lost-products — local twins of fetch_orders_line_items, count_orders and
# fetch_baseline_order_items
# ============================================================================

_PRODUCT_ITEMS_SQL = """
SELECT li.order_shopify_id, li.title, li.quantity, li.sku, li.variant_title,
       li.barcode, li.product_title, li.product_shopify_id
FROM shopify_order_line_items li
WHERE li.store_id = :sid AND li.order_shopify_id = ANY(:oids)
ORDER BY li.id
"""


def _product_item(li) -> Dict[str, Any]:
    pid = li["product_shopify_id"]
    return {
        "title": (li["title"] or "").strip(),
        "quantity": li["quantity"] or 0,
        "sku": (li["sku"] or "").strip(),
        "variant_title": (li["variant_title"] or "").strip(),
        "product_id": f"gid://shopify/Product/{pid}" if pid else None,
        "product_title": li["product_title"],
        "barcode": (li["barcode"] or "").strip() or None,
    }


def _orders_line_items_sync(store_id: int, order_ids: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": True, "error": None, "orders": [],
        "missing": 0, "truncated": 0, "warnings": [],
    }
    oids = sorted({n for n in (_gid_num(o) for o in order_ids if o) if n is not None})
    if not oids:
        return out

    with engine.connect() as conn:
        orders = conn.execute(
            text(
                "SELECT shopify_id, shopify_gid, name, created_at FROM shopify_orders "
                "WHERE store_id = :sid AND shopify_id = ANY(:oids)"
            ),
            {"sid": store_id, "oids": oids},
        ).mappings().all()
        items_by_order: Dict[int, List[Dict[str, Any]]] = {}
        for li in conn.execute(
            text(_PRODUCT_ITEMS_SQL), {"sid": store_id, "oids": oids}
        ).mappings():
            items_by_order.setdefault(li["order_shopify_id"], []).append(li)

    found = set()
    for r in orders:
        found.add(r["shopify_id"])
        out["orders"].append({
            "id": r["shopify_gid"],
            "name": r["name"],
            "created_at": _iso(r["created_at"]),
            "truncated": False,
            "items": [_product_item(li) for li in items_by_order.get(r["shopify_id"], [])],
        })
    out["missing"] = len(oids) - len(found)
    return out


async def orders_line_items(store_id: int, order_ids: List[str]) -> Dict[str, Any]:
    return await _run(_orders_line_items_sync, store_id, order_ids)


def _count_completed_orders_sync(
    store_id: int, tz: Optional[str], start: str, end: str
) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text(
                f"SELECT count(*) FROM shopify_orders o "
                f"WHERE o.store_id = :sid AND {_COMPLETED} "
                f"  AND (o.created_at AT TIME ZONE :tz)::date >= CAST(:lo AS date) "
                f"  AND (o.created_at AT TIME ZONE :tz)::date <  CAST(:hi AS date)"
            ),
            {"sid": store_id, "tz": _tz_or_utc(tz), "lo": start, "hi": end},
        ).scalar() or 0


async def count_completed_orders(
    store_id: int, tz: Optional[str], start: str, end: str
) -> int:
    return await _run(_count_completed_orders_sync, store_id, tz, start, end)


def _baseline_order_items_sync(
    store_id: int, tz: Optional[str], windows: List[tuple]
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": True, "error": None, "orders": [], "truncated": 0,
        "warnings": [], "pages": 0,
    }
    with engine.connect() as conn:
        for start, end in windows:
            orders = conn.execute(
                text(
                    f"SELECT shopify_id, shopify_gid FROM shopify_orders o "
                    f"WHERE o.store_id = :sid AND {_COMPLETED} "
                    f"  AND (o.created_at AT TIME ZONE :tz)::date >= CAST(:lo AS date) "
                    f"  AND (o.created_at AT TIME ZONE :tz)::date <  CAST(:hi AS date)"
                ),
                {"sid": store_id, "tz": _tz_or_utc(tz), "lo": start, "hi": end},
            ).mappings().all()
            out["pages"] += 1
            if not orders:
                continue
            oids = [r["shopify_id"] for r in orders]
            items_by_order: Dict[int, List[Dict[str, Any]]] = {}
            for li in conn.execute(
                text(_PRODUCT_ITEMS_SQL), {"sid": store_id, "oids": oids}
            ).mappings():
                items_by_order.setdefault(li["order_shopify_id"], []).append(li)
            for r in orders:
                out["orders"].append({
                    "id": r["shopify_gid"],
                    "truncated": False,
                    "items": [
                        _product_item(li)
                        for li in items_by_order.get(r["shopify_id"], [])
                    ],
                })
    return out


async def baseline_order_items(
    store_id: int, tz: Optional[str], windows: List[tuple]
) -> Dict[str, Any]:
    return await _run(_baseline_order_items_sync, store_id, tz, windows)
