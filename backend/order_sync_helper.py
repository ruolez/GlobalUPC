"""
Order Sync: reconcile shipped orders between one BackOffice MSSQL store
(source of truth) and one Shopify store.

MSSQL I/O lives in _fetch_invoices_sync; everything else (normalization,
matching, line comparison, report assembly) is pure and I/O-free so it can be
unit-tested and reused if the Shopify side ever switches data source.
"""

import re
import pyodbc
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from mssql_helper import get_mssql_connection_string

_ordsync_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ordsync")

# SQL Server caps query parameters at ~2100; keep IN (...) batches well under.
_LINES_IN_CHUNK = 1000

# Invoices are fetched in a window padded on both sides so an order placed at
# the edge of the selected range still finds its invoice dated a few days
# earlier/later. Padded-only rows may be consumed by a match but are never
# reported on their own.
PAD_DAYS = 7

# A cent of float noise must not count as a price difference.
CENT_TOL = 0.011


# ---------------------------------------------------------------------------
# MSSQL fetch
# ---------------------------------------------------------------------------

def _tracking_present(value: Any) -> bool:
    """Python twin of business_overview_helper._TRACKING_BLANK: BackOffice
    writes NULL, '' or the literal '0' for not-yet-shipped."""
    v = str(value).strip() if value is not None else ""
    return bool(v) and v != "0"


def _fetch_invoices_sync(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    date_from: str,
    date_to: str,
    pad_days: int = PAD_DAYS,
) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """
    Non-void invoices with InvoiceDate in [date_from - pad, date_to + pad]
    (half-open upper bound — InvoiceDate carries a time component), each with
    its non-void detail lines aggregated per trimmed ProductUPC.
    """
    conn_str = get_mssql_connection_string(host, port, database, username, password)
    try:
        lo_dt = datetime.strptime(date_from, "%Y-%m-%d") - timedelta(days=pad_days)
        hi_dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1 + pad_days)
    except ValueError as e:
        return False, f"Invalid date: {e}", []
    lo, hi = lo_dt.strftime("%Y-%m-%d"), hi_dt.strftime("%Y-%m-%d")

    header_query = """
        SELECT h.InvoiceID, h.InvoiceNumber, h.InvoiceDate, h.CustomerID, h.BusinessName,
               h.PoNumber, h.TrackingNo, h.Shipto, h.ShipContact, h.ShipAddress1, h.ShipAddress2,
               h.ShipCity, h.ShipState, h.ShipZipCode, h.ShipPhoneNo,
               h.InvoiceSubtotal, h.TotalTaxes, h.ShippingCost, h.InvoiceTotal, h.TotQtyShp
        FROM Invoices_tbl h
        WHERE ISNULL(h.Void, 0) = 0 AND h.InvoiceDate >= ? AND h.InvoiceDate < ?
        ORDER BY h.InvoiceDate ASC
    """

    try:
        with pyodbc.connect(conn_str, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute(header_query, [lo, hi])
            headers = cursor.fetchall()

            invoice_ids = [r[0] for r in headers]
            lines_by_invoice = _fetch_lines(cursor, invoice_ids)

        invoices: List[Dict[str, Any]] = []
        for r in headers:
            inv_date = r[2]
            day = inv_date.strftime("%Y-%m-%d") if inv_date else None
            invoices.append({
                "invoice_id": r[0],
                "invoice_number": str(r[1]).strip() if r[1] is not None else str(r[0]),
                "invoice_date": inv_date.isoformat() if inv_date else None,
                "date": day,
                "in_range": bool(day and date_from <= day <= date_to),
                "customer_id": r[3],
                "business_name": (r[4] or "").strip(),
                "po_number": (r[5] or "").strip(),
                "tracking_no": (r[6] or "").strip(),
                "has_tracking": _tracking_present(r[6]),
                "ship_to": (r[7] or "").strip(),
                "ship_contact": (r[8] or "").strip(),
                "ship_address1": (r[9] or "").strip(),
                "ship_address2": (r[10] or "").strip(),
                "ship_city": (r[11] or "").strip(),
                "ship_state": (r[12] or "").strip(),
                "ship_zip": (r[13] or "").strip(),
                "ship_phone": (r[14] or "").strip(),
                "subtotal": float(r[15] or 0),
                "taxes": float(r[16] or 0),
                "shipping_cost": float(r[17] or 0),
                "total": float(r[18] or 0),
                "tot_qty_shp": float(r[19] or 0),
                "lines": lines_by_invoice.get(r[0], []),
            })
        return True, None, invoices
    except Exception as e:
        return False, str(e), []


def _fetch_lines(cursor, invoice_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
    """Detail lines for the given invoices, chunked IN (...), aggregated per
    trimmed UPC (duplicate UPC lines sum quantity; unit price is qty-weighted)."""
    agg: Dict[int, Dict[str, Dict[str, Any]]] = {}
    for start in range(0, len(invoice_ids), _LINES_IN_CHUNK):
        chunk = invoice_ids[start:start + _LINES_IN_CHUNK]
        placeholders = ",".join("?" * len(chunk))
        cursor.execute(f"""
            SELECT d.InvoiceID, LTRIM(RTRIM(ISNULL(d.ProductUPC, ''))) AS upc,
                   LTRIM(RTRIM(ISNULL(d.ProductSKU, ''))) AS sku,
                   d.ProductDescription, ISNULL(d.QtyShipped, 0), ISNULL(d.UnitPrice, 0),
                   ISNULL(d.ExtendedPrice, 0)
            FROM InvoicesDetails_tbl d
            WHERE d.InvoiceID IN ({placeholders}) AND ISNULL(d.Void, 0) = 0
        """, chunk)
        for inv_id, upc, sku, desc, qty, unit_price, ext_price in cursor.fetchall():
            key = upc or (f"sku:{sku.upper()}" if sku else "")
            if not key:
                key = f"desc:{(desc or '').strip().lower()}"
            per_inv = agg.setdefault(inv_id, {})
            line = per_inv.setdefault(key, {
                "key": key, "barcode": upc, "sku": sku,
                "description": (desc or "").strip(),
                "qty": 0.0, "amount": 0.0,
            })
            line["qty"] += float(qty)
            line["amount"] += float(qty) * float(unit_price)

    out: Dict[int, List[Dict[str, Any]]] = {}
    for inv_id, per_inv in agg.items():
        lines = []
        for line in per_inv.values():
            qty = line.pop("qty")
            amount = line.pop("amount")
            line["qty_shipped"] = qty
            line["unit_price"] = round(amount / qty, 4) if qty else 0.0
            lines.append(line)
        out[inv_id] = lines
    return out


async def fetch_invoices_async(**kwargs) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_ordsync_executor, lambda: _fetch_invoices_sync(**kwargs))


# ---------------------------------------------------------------------------
# Normalization (pure)
# ---------------------------------------------------------------------------

def normalize_tracking(value: Any) -> str:
    v = str(value or "").strip().upper()
    return "" if v == "0" else v


def split_tracking(value: Any) -> List[str]:
    """One BackOffice TrackingNo field may pack several numbers; split on the
    usual separators and drop blanks/sentinels."""
    parts = re.split(r"[,;/\s]+", str(value or ""))
    seen: List[str] = []
    for p in parts:
        n = normalize_tracking(p)
        if n and n not in seen:
            seen.append(n)
    return seen


def normalize_phone(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) >= 7 else ""


def zip5(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[:5]


_ADDR_SUFFIXES = {
    "street": "st", "avenue": "ave", "av": "ave", "boulevard": "blvd",
    "drive": "dr", "road": "rd", "lane": "ln", "court": "ct", "place": "pl",
    "circle": "cir", "highway": "hwy", "parkway": "pkwy", "terrace": "ter",
    "north": "n", "south": "s", "east": "e", "west": "w",
    "apartment": "apt", "suite": "ste", "unit": "apt", "number": "",
    "no": "", "po": "pobox",
}


def _normalize_words(text: Any) -> str:
    words = re.sub(r"[^a-z0-9\s]", " ", str(text or "").lower()).split()
    return " ".join(_ADDR_SUFFIXES.get(w, w) for w in words if _ADDR_SUFFIXES.get(w, w))


def normalize_address(address1: Any, zip_code: Any) -> str:
    addr = _normalize_words(address1)
    z = zip5(zip_code)
    return f"{addr}|{z}" if addr and z else ""


def normalize_name_zip(name: Any, zip_code: Any) -> str:
    n = _normalize_words(name)
    z = zip5(zip_code)
    return f"{n}|{z}" if n and z else ""


# ---------------------------------------------------------------------------
# Matching (pure)
# ---------------------------------------------------------------------------

def _day_delta(order: Dict[str, Any], invoice: Dict[str, Any]) -> int:
    try:
        o = datetime.strptime(order["local_date"], "%Y-%m-%d")
        i = datetime.strptime(invoice["date"], "%Y-%m-%d")
        return abs((o - i).days)
    except (KeyError, TypeError, ValueError):
        return 9999


def _pick_candidate(order: Dict[str, Any],
                    candidates: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], bool]:
    """Prefer a candidate whose total matches to the cent, then the closest
    date, then the closest total. Ambiguous when >=2 candidates tie on
    (total-matches, day-delta)."""
    if len(candidates) == 1:
        return candidates[0], False

    def score(inv: Dict[str, Any]) -> Tuple[int, int, float]:
        delta = abs((order.get("total") or 0) - (inv.get("total") or 0))
        return (0 if delta <= CENT_TOL else 1, _day_delta(order, inv), delta)

    ranked = sorted(candidates, key=score)
    best = ranked[0]
    ambiguous = len(ranked) > 1 and score(ranked[1])[:2] == score(best)[:2]
    return best, ambiguous


def match_orders(orders: List[Dict[str, Any]],
                 invoices: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Greedy two-pass matching; each order and each invoice is consumed at most
    once. Pass 1 joins on tracking number, pass 2 on customer identity
    (phone, then street address, then name+zip).
    """
    used_invoices: set = set()
    pairs: List[Tuple[Dict[str, Any], Dict[str, Any], str, bool]] = []
    unmatched_orders: List[Dict[str, Any]] = []

    by_tracking: Dict[str, List[Dict[str, Any]]] = {}
    by_phone: Dict[str, List[Dict[str, Any]]] = {}
    by_addr: Dict[str, List[Dict[str, Any]]] = {}
    by_namezip: Dict[str, List[Dict[str, Any]]] = {}
    for inv in invoices:
        for t in split_tracking(inv["tracking_no"]):
            by_tracking.setdefault(t, []).append(inv)
        p = normalize_phone(inv["ship_phone"])
        if p:
            by_phone.setdefault(p, []).append(inv)
        a = normalize_address(inv["ship_address1"], inv["ship_zip"])
        if a:
            by_addr.setdefault(a, []).append(inv)
        for name in (inv["ship_to"], inv["ship_contact"], inv["business_name"]):
            nz = normalize_name_zip(name, inv["ship_zip"])
            if nz:
                by_namezip.setdefault(nz, []).append(inv)

    def take(order: Dict[str, Any], keys: List[str],
             index: Dict[str, List[Dict[str, Any]]], method: str) -> bool:
        candidates: List[Dict[str, Any]] = []
        for k in keys:
            for inv in index.get(k, []):
                if inv["invoice_id"] not in used_invoices and inv not in candidates:
                    candidates.append(inv)
        if not candidates:
            return False
        inv, ambiguous = _pick_candidate(order, candidates)
        used_invoices.add(inv["invoice_id"])
        pairs.append((order, inv, method, ambiguous))
        return True

    # Pass 1 — tracking numbers.
    remaining: List[Dict[str, Any]] = []
    for order in orders:
        keys = [normalize_tracking(t) for t in order.get("tracking_numbers", [])]
        if not take(order, [k for k in keys if k], by_tracking, "tracking"):
            remaining.append(order)

    # Pass 2 — customer identity.
    for order in remaining:
        if take(order, [normalize_phone(p) for p in order.get("phones", [])], by_phone, "phone"):
            continue
        if take(order, [normalize_address(order.get("address1"), order.get("zip"))], by_addr, "address"):
            continue
        if take(order, [normalize_name_zip(order.get("customer_name"), order.get("zip"))],
                by_namezip, "name_zip"):
            continue
        unmatched_orders.append(order)

    unmatched_invoices = [inv for inv in invoices if inv["invoice_id"] not in used_invoices]
    return {"pairs": pairs, "unmatched_orders": unmatched_orders,
            "unmatched_invoices": unmatched_invoices}


# ---------------------------------------------------------------------------
# Line comparison (pure)
# ---------------------------------------------------------------------------

def _shopify_lines_by_key(order: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    agg: Dict[str, Dict[str, Any]] = {}
    for li in order.get("lines", []):
        barcode = (li.get("barcode") or "").strip()
        sku = (li.get("sku") or "").strip()
        key = barcode or (f"sku:{sku.upper()}" if sku else f"desc:{(li.get('title') or '').strip().lower()}")
        line = agg.setdefault(key, {
            "key": key, "barcode": barcode, "sku": sku,
            "title": li.get("title") or "", "qty": 0.0,
            "amount": 0.0, "ordered": 0.0,
        })
        line["qty"] += float(li.get("current_quantity") or 0)
        line["amount"] += float(li.get("discounted_total") or 0)
        line["ordered"] += float(li.get("quantity") or 0)
    return agg


def compare_lines(order: Dict[str, Any],
                  invoice: Dict[str, Any]) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Union of both sides' lines keyed by barcode (sku/description fallback).
    Returns (issue_kinds, line_diffs). BackOffice QtyShipped is the truth."""
    sh_lines = _shopify_lines_by_key(order)
    bo_lines = {li["key"]: li for li in invoice.get("lines", [])}

    kinds: set = set()
    diffs: List[Dict[str, Any]] = []
    for key in list(sh_lines) + [k for k in bo_lines if k not in sh_lines]:
        sh = sh_lines.get(key)
        bo = bo_lines.get(key)
        issues: List[str] = []
        sh_qty = sh["qty"] if sh else None
        bo_qty = bo["qty_shipped"] if bo else None
        sh_price = round(sh["amount"] / sh["ordered"], 4) if sh and sh["ordered"] else (0.0 if sh else None)
        bo_price = bo["unit_price"] if bo else None

        if sh and not bo:
            issues.append("missing_in_backoffice")
            kinds.add("product")
        elif bo and not sh:
            issues.append("missing_in_shopify")
            kinds.add("product")
        else:
            if abs(sh_qty - bo_qty) > 1e-6:
                issues.append("qty")
                kinds.add("qty")
            if abs(sh_price - bo_price) > CENT_TOL:
                issues.append("price")
                kinds.add("price")

        diffs.append({
            "key": key,
            "barcode": (sh or bo).get("barcode") or None,
            "sku": (sh or bo).get("sku") or None,
            "description": (bo or {}).get("description") or (sh or {}).get("title") or None,
            "sh_qty": sh_qty,
            "bo_qty": bo_qty,
            "sh_unit_price": sh_price,
            "bo_unit_price": bo_price,
            "issues": issues,
        })

    # Differences first so the drill-in leads with what's wrong.
    diffs.sort(key=lambda d: (not d["issues"], d["key"]))
    return sorted(kinds), diffs


# ---------------------------------------------------------------------------
# Report assembly (pure)
# ---------------------------------------------------------------------------

def _order_side(order: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "sh_order_id": order.get("id"),
        "sh_name": order.get("name"),
        "sh_date": order.get("local_date"),
        "sh_total": order.get("total"),
        "sh_customer": order.get("customer_name") or order.get("email") or None,
        "sh_tracking": order.get("tracking_numbers", []),
        "sh_no_tracking": not order.get("tracking_numbers"),
    }


def _invoice_side(invoice: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "bo_invoice_id": invoice["invoice_id"],
        "bo_invoice_number": invoice["invoice_number"],
        "bo_date": invoice["invoice_date"],
        "bo_total": invoice["total"],
        "bo_customer": invoice["business_name"] or invoice["ship_to"] or None,
        "bo_tracking": invoice["tracking_no"] if invoice["has_tracking"] else None,
        "bo_no_tracking": not invoice["has_tracking"],
    }


def build_report(orders: List[Dict[str, Any]], invoices: List[Dict[str, Any]],
                 date_from: str, date_to: str) -> Dict[str, Any]:
    """Match, compare, and assemble rows + summary. Out-of-range invoices
    (fetched only as padding) may be consumed by matches but are dropped when
    unmatched; a matched pair is reported when either side is in range."""
    result = match_orders(orders, invoices)

    rows: List[Dict[str, Any]] = []
    summary = {
        "matched_ok": 0, "matched_diffs": 0,
        "shopify_unmatched": 0, "backoffice_unmatched": 0,
        "shopify_no_tracking": 0, "backoffice_no_tracking": 0,
        "shopify_total": len(orders), "backoffice_total": 0,
    }

    for order, invoice, method, ambiguous in result["pairs"]:
        kinds, diffs = compare_lines(order, invoice)
        total_delta = round((order.get("total") or 0) - (invoice.get("total") or 0), 2)
        if abs(total_delta) > CENT_TOL:
            kinds = sorted(set(kinds) | {"total"})
        status = "matched_ok" if not kinds else "matched_diffs"
        row = {
            "status": status, "match_method": method, "ambiguous": ambiguous,
            **_order_side(order), **_invoice_side(invoice),
            "total_delta": total_delta, "issue_kinds": kinds, "line_diffs": diffs,
        }
        rows.append(row)
        summary[status] += 1

    for order in result["unmatched_orders"]:
        diffs = [{
            "key": li["key"], "barcode": li["barcode"] or None, "sku": li["sku"] or None,
            "description": li["title"] or None,
            "sh_qty": li["qty"], "bo_qty": None,
            "sh_unit_price": round(li["amount"] / li["ordered"], 4) if li["ordered"] else 0.0,
            "bo_unit_price": None, "issues": [],
        } for li in _shopify_lines_by_key(order).values()]
        rows.append({
            "status": "shopify_unmatched", "match_method": None, "ambiguous": False,
            **_order_side(order),
            "total_delta": None, "issue_kinds": [], "line_diffs": diffs,
        })
        summary["shopify_unmatched"] += 1

    for invoice in result["unmatched_invoices"]:
        if not invoice["in_range"]:
            continue
        diffs = [{
            "key": li["key"], "barcode": li["barcode"] or None, "sku": li["sku"] or None,
            "description": li["description"] or None,
            "sh_qty": None, "bo_qty": li["qty_shipped"],
            "sh_unit_price": None, "bo_unit_price": li["unit_price"], "issues": [],
        } for li in invoice.get("lines", [])]
        rows.append({
            "status": "backoffice_unmatched", "match_method": None, "ambiguous": False,
            **_invoice_side(invoice),
            "total_delta": None, "issue_kinds": [], "line_diffs": diffs,
        })
        summary["backoffice_unmatched"] += 1

    summary["backoffice_total"] = sum(1 for inv in invoices if inv["in_range"])
    summary["shopify_no_tracking"] = sum(1 for r in rows if r.get("sh_no_tracking"))
    summary["backoffice_no_tracking"] = sum(1 for r in rows if r.get("bo_no_tracking"))

    rows.sort(key=lambda r: (r.get("sh_date") or (r.get("bo_date") or "")[:10] or ""), reverse=True)
    return {"summary": summary, "rows": rows}


def shutdown_order_sync_executor():
    _ordsync_executor.shutdown(wait=False)
