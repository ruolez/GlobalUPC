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
# the edge of the selected range still finds its invoice. Same-day pairs only
# need a few days, but orders entered into Shopify after the fact (pass 4)
# trail their invoice by up to a few weeks. Padded-only rows may be consumed
# by a match but are never reported on their own.
PAD_DAYS = 31

# Shopify orders are fetched for the exact range first. When in-range
# invoices are left unmatched, a second fetch pulls orders placed shortly
# before the range and up to a month after it (clipped at today — orders
# are keyed into Shopify days or weeks after the invoice ships). Padded
# orders may pair with an in-range invoice but are never reported alone.
ORDER_PAD_BEFORE_DAYS = 3
ORDER_PAD_AFTER_DAYS = 31

# Order totals may legitimately differ by a cent when a fractional unit price
# (10.00 / 3) is rounded on one side, so totals get a cent of slack. Unit
# prices are compared to half a cent: 27.49 vs 27.50 IS a difference the
# invoice wants corrected, and float noise is orders of magnitude smaller.
CENT_TOL = 0.011
PRICE_TOL = 0.005


# ---------------------------------------------------------------------------
# MSSQL fetch
# ---------------------------------------------------------------------------

def _tracking_present(value: Any) -> bool:
    """Python twin of business_overview_helper._TRACKING_BLANK: BackOffice
    writes NULL, '' or the literal '0' for not-yet-shipped."""
    v = str(value).strip() if value is not None else ""
    return bool(v) and v != "0"


_INVOICE_HEADER_SELECT = """
    SELECT h.InvoiceID, h.InvoiceNumber, h.InvoiceDate, h.CustomerID, h.BusinessName,
           h.PoNumber, h.TrackingNo, h.Shipto, h.ShipContact, h.ShipAddress1, h.ShipAddress2,
           h.ShipCity, h.ShipState, h.ShipZipCode, h.ShipPhoneNo,
           h.InvoiceSubtotal, h.TotalTaxes, h.ShippingCost, h.InvoiceTotal, h.TotQtyShp
    FROM Invoices_tbl h
    WHERE ISNULL(h.Void, 0) = 0
"""


def _shape_invoice(r, lines: List[Dict[str, Any]], date_from: str, date_to: str) -> Dict[str, Any]:
    inv_date = r[2]
    day = inv_date.strftime("%Y-%m-%d") if inv_date else None
    return {
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
        "lines": lines,
    }


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

    header_query = _INVOICE_HEADER_SELECT + """
        AND h.InvoiceDate >= ? AND h.InvoiceDate < ?
        ORDER BY h.InvoiceDate ASC
    """

    try:
        with pyodbc.connect(conn_str, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute(header_query, [lo, hi])
            headers = cursor.fetchall()

            invoice_ids = [r[0] for r in headers]
            lines_by_invoice = _fetch_lines(cursor, invoice_ids)

        invoices = [_shape_invoice(r, lines_by_invoice.get(r[0], []), date_from, date_to)
                    for r in headers]
        return True, None, invoices
    except Exception as e:
        return False, str(e), []


def _fetch_invoice_sync(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    invoice_id: int,
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """One non-void invoice by InvoiceID, same shape as the range fetch
    (`in_range` is always True — there is no range)."""
    conn_str = get_mssql_connection_string(host, port, database, username, password)
    try:
        with pyodbc.connect(conn_str, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute(_INVOICE_HEADER_SELECT + " AND h.InvoiceID = ?", [invoice_id])
            r = cursor.fetchone()
            if not r:
                return False, f"Invoice {invoice_id} not found (or void)", None
            lines = _fetch_lines(cursor, [invoice_id]).get(invoice_id, [])
        return True, None, _shape_invoice(r, lines, "0000-00-00", "9999-12-31")
    except Exception as e:
        return False, str(e), None


async def fetch_invoice_async(**kwargs) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_ordsync_executor, lambda: _fetch_invoice_sync(**kwargs))


def line_key(barcode: Any, sku: Any, description: Any) -> str:
    """Comparison key shared by both sides: trimmed barcode, else SKU, else
    description — so a Shopify line and an invoice line meet on the same key."""
    b = (barcode or "").strip()
    if b:
        return b
    s = (sku or "").strip()
    if s:
        return f"sku:{s.upper()}"
    return f"desc:{(description or '').strip().lower()}"


# Both systems bill shipping as a pseudo product (UPC "ship", SKU "shipment").
# Shopify carries it either as that line item or as a real shipping line;
# the latter is folded into a synthetic "ship" line (see _shopify_lines_by_key)
# so shipping is compared and corrected like any product. It never counts
# toward basket matching (nearly every order has it) and its storefront price
# is never touched (it varies per order).
SHIPPING_BARCODES = {"ship"}
SHIPPING_SKUS = {"shipment"}
SHIPPING_KEY = "ship"


def is_shipping_line(barcode: Any, sku: Any) -> bool:
    return ((barcode or "").strip().lower() in SHIPPING_BARCODES
            or (sku or "").strip().lower() in SHIPPING_SKUS)


def _fetch_lines(cursor, invoice_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
    """Detail lines for the given invoices, chunked IN (...), aggregated per
    trimmed UPC (duplicate UPC lines sum quantity; unit price is qty-weighted).
    Shipping pseudo-lines are keyed SHIPPING_KEY whatever their spelling."""
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
            key = SHIPPING_KEY if is_shipping_line(upc, sku) else line_key(upc, sku, desc)
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


# Local deliveries carry the driver's route number (1–2 digits) in the
# tracking field on both systems, sometimes appended to a real number
# ("UDS1423123491, 2"). Route numbers are shared by dozens of orders, so they
# never act as a join key; they are surfaced separately as `route`.
_ROUTE_RE = re.compile(r"^\d{1,2}$")


def is_route_code(value: Any) -> bool:
    return bool(_ROUTE_RE.match(normalize_tracking(value)))


def split_routes(values: List[str]) -> Tuple[List[str], List[str]]:
    """(real tracking numbers, route codes) from raw values. Each value is
    itself split — Shopify packs multi-parcel shipments into one entry
    ("SP…603/SP…573") the same way BackOffice does ("SP…603, SP…573")."""
    real: List[str] = []
    routes: List[str] = []
    for v in values:
        for n in split_tracking(v):
            target = routes if _ROUTE_RE.match(n) else real
            if n not in target:
                target.append(n)
    return real, routes


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


def _invoice_lines(invoice: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Invoice lines with shipping keyed SHIPPING_KEY (fetched lines already
    are; this keeps any other source honest)."""
    out = []
    for li in invoice.get("lines", []):
        if is_shipping_line(li.get("barcode"), li.get("sku")) and li.get("key") != SHIPPING_KEY:
            li = {**li, "key": SHIPPING_KEY}
        out.append(li)
    return out


def _line_keys(side: Dict[str, Any], shopify: bool) -> set:
    """Keys used for basket matching — shipping excluded."""
    lines = _shopify_lines_by_key(side).values() if shopify else _invoice_lines(side)
    return {li["key"] for li in lines if li["key"] != SHIPPING_KEY}


def _pair_score(order: Dict[str, Any], invoice: Dict[str, Any]) -> Tuple[int, float, int, float]:
    """Lower is better: total matches to the cent, then line-set overlap
    (Jaccard on barcode keys), then closest date, then closest total."""
    delta = abs((order.get("total") or 0) - (invoice.get("total") or 0))
    ok = _line_keys(order, True)
    ik = _line_keys(invoice, False)
    union = len(ok | ik)
    jaccard = (len(ok & ik) / union) if union else 0.0
    return (0 if delta <= CENT_TOL else 1, -round(jaccard, 3), _day_delta(order, invoice), delta)


# Identity keys (phone, address, name) are shared by every order a repeat
# customer places, so a candidate found that way must also look like THIS
# order's invoice before it is accepted. Calibrated on tracking-confirmed
# pairs: the invoice is dated the same day as the Shopify order (or the day
# before, timezone), never later; totals differ by <7% in 99% of pairs.
IDENTITY_MAX_DAY_LAG = 1
IDENTITY_TOTAL_TOL_PCT = 0.25
IDENTITY_TOTAL_TOL_MIN = 50.0
IDENTITY_MIN_LINE_OVERLAP = 0.3

# Pass 3 — the customer text differs on the two systems ("Ram Ram" vs
# "TOBACCO HUT - 121") but the order is unmistakable: same day, same basket.
BASKET_MIN_OVERLAP = 0.8
BASKET_MIN_OVERLAP_WITH_TOTAL = 0.5
BASKET_TOTAL_TOL_PCT = 0.01

# Pass 4 only — a Shopify order entered with PART of the invoice (seen live:
# 53 of 67 invoice lines, no other order carrying the rest). Every order line
# must be on the invoice, and the order must still cover half the invoice's
# lines so a two-line reorder cannot latch onto a big weekly invoice.
BASKET_CONTAINMENT_MIN = 0.9
BASKET_CONTAINMENT_INVOICE_COVER = 0.5


def _line_jaccard(order: Dict[str, Any], invoice: Dict[str, Any]) -> float:
    ok = _line_keys(order, True)
    ik = _line_keys(invoice, False)
    union = len(ok | ik)
    return (len(ok & ik) / union) if union else 0.0


def _basket_match(order: Dict[str, Any], invoice: Dict[str, Any]) -> bool:
    """The same basket: near-identical line set, or half the lines plus the
    same total to within a percent."""
    j = _line_jaccard(order, invoice)
    if j >= BASKET_MIN_OVERLAP:
        return True
    total = order.get("total") or 0
    rel = abs(total - (invoice.get("total") or 0)) / total if total else 1.0
    return j >= BASKET_MIN_OVERLAP_WITH_TOTAL and rel <= BASKET_TOTAL_TOL_PCT


def _same_shipment_despite_tracking(order: Dict[str, Any], invoice: Dict[str, Any]) -> bool:
    """Seen live: BackOffice relabelled a box six days after shipping, so the
    invoice carried a newer carrier number than the Shopify order. Same day,
    same basket and the same total leave no doubt it is one order; the row
    is flagged (tracking_conflict) so the numbers can be reconciled by hand."""
    if _day_delta(order, invoice) > IDENTITY_MAX_DAY_LAG:
        return False
    if _line_jaccard(order, invoice) < BASKET_MIN_OVERLAP:
        return False
    total = order.get("total") or 0
    rel = abs(total - (invoice.get("total") or 0)) / total if total else 1.0
    return rel <= BASKET_TOTAL_TOL_PCT


def tracking_conflict(orders: List[Dict[str, Any]], invoices: List[Dict[str, Any]]) -> bool:
    """Both sides carry real tracking numbers and share none of them."""
    o_real = {n for o in orders for n in split_routes(o.get("tracking_numbers", []))[0]}
    i_real = {n for i in invoices for n in split_routes(split_tracking(i.get("tracking_no")))[0]}
    return bool(o_real and i_real and not (o_real & i_real))


def _basket_contained(order: Dict[str, Any], invoice: Dict[str, Any]) -> bool:
    """The order is a large subset of the invoice (see BASKET_CONTAINMENT_*)."""
    ok = _line_keys(order, True)
    ik = _line_keys(invoice, False)
    if not ok or not ik:
        return False
    common = len(ok & ik)
    return (common / len(ok) >= BASKET_CONTAINMENT_MIN
            and common / len(ik) >= BASKET_CONTAINMENT_INVOICE_COVER)


def _identity_plausible(order: Dict[str, Any], invoice: Dict[str, Any],
                        max_day_lag: Optional[int] = IDENTITY_MAX_DAY_LAG) -> bool:
    # Invoice must be dated within a day of the order — a repeat customer's
    # invoice from another week is another order. Pass 4 lifts the cap
    # (None) because it demands the basket instead.
    try:
        placed = datetime.strptime(order["local_date"], "%Y-%m-%d")
        invoiced = datetime.strptime(invoice["date"], "%Y-%m-%d")
        if max_day_lag is not None and abs((invoiced - placed).days) > max_day_lag:
            return False
    except (KeyError, TypeError, ValueError):
        pass
    # Both sides carrying different real tracking numbers = different
    # shipments — unless the order is unmistakable anyway (see
    # _same_shipment_despite_tracking: a relabelled / reshipped box).
    o_real = set(split_routes(order.get("tracking_numbers", []))[0])
    i_real = set(split_routes(split_tracking(invoice["tracking_no"]))[0])
    if o_real and i_real and not (o_real & i_real) and not _same_shipment_despite_tracking(order, invoice):
        return False
    # Totals far apart AND barely any products in common = another order.
    total = order.get("total") or 0
    delta = abs(total - (invoice.get("total") or 0))
    if delta > max(IDENTITY_TOTAL_TOL_PCT * total, IDENTITY_TOTAL_TOL_MIN):
        ok = _line_keys(order, True)
        ik = _line_keys(invoice, False)
        union = len(ok | ik)
        if not union or len(ok & ik) / union < IDENTITY_MIN_LINE_OVERLAP:
            return False
    return True


def _pick_candidate(order: Dict[str, Any],
                    candidates: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], bool]:
    """Best invoice for one order; ambiguous when the runner-up ties on
    (total-matches, line overlap, day-delta)."""
    if len(candidates) == 1:
        return candidates[0], False
    ranked = sorted(candidates, key=lambda inv: _pair_score(order, inv))
    best = ranked[0]
    ambiguous = _pair_score(order, ranked[1])[:3] == _pair_score(order, best)[:3]
    return best, ambiguous


def _pair_within_group(orders: List[Dict[str, Any]],
                       invoices: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], Dict[str, Any], bool]]:
    """Greedy best-score 1:1 pairing inside a shared-tracking group."""
    scored = sorted(
        ((_pair_score(o, i), oi, ii) for oi, o in enumerate(orders) for ii, i in enumerate(invoices)),
        key=lambda t: t[0],
    )
    used_o: set = set()
    used_i: set = set()
    out = []
    for score, oi, ii in scored:
        if oi in used_o or ii in used_i:
            continue
        rivals = [s for s, o2, i2 in scored if o2 == oi and i2 != ii and i2 not in used_i]
        ambiguous = any(s[:3] == score[:3] for s in rivals)
        used_o.add(oi)
        used_i.add(ii)
        out.append((orders[oi], invoices[ii], ambiguous))
    return out


def _combined_totals_match(orders: List[Dict[str, Any]], invoices: List[Dict[str, Any]]) -> bool:
    so = sum(o.get("total") or 0 for o in orders)
    si = sum(i.get("total") or 0 for i in invoices)
    return abs(so - si) <= CENT_TOL


def order_pad_windows(date_from: str, date_to: str, today: str,
                      before_days: int = ORDER_PAD_BEFORE_DAYS,
                      after_days: int = ORDER_PAD_AFTER_DAYS) -> List[Tuple[str, str]]:
    """Date windows (inclusive) for the second Shopify fetch: a few days
    before the range and up to `after_days` after it, never past `today`.
    Empty windows are omitted."""
    lo = datetime.strptime(date_from, "%Y-%m-%d")
    hi = datetime.strptime(date_to, "%Y-%m-%d")
    now = datetime.strptime(today, "%Y-%m-%d")
    windows: List[Tuple[str, str]] = []
    if before_days > 0:
        windows.append(((lo - timedelta(days=before_days)).strftime("%Y-%m-%d"),
                        (lo - timedelta(days=1)).strftime("%Y-%m-%d")))
    after_hi = min(hi + timedelta(days=after_days), now)
    if after_days > 0 and after_hi > hi:
        windows.append(((hi + timedelta(days=1)).strftime("%Y-%m-%d"), after_hi.strftime("%Y-%m-%d")))
    return windows


def match_orders_staged(orders: List[Dict[str, Any]], invoices: List[Dict[str, Any]],
                        padded_orders: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Stage 1 pairs the in-range orders with every invoice; stage 2 offers
    the padded orders only to the in-range invoices still unmatched, so a
    stage-1 pair is final and no pairing changes because the pool grew.
    Same result shape as match_orders."""
    first = match_orders(orders, invoices)
    leftovers = [inv for inv in first["unmatched_invoices"] if inv.get("in_range", True)]
    if not padded_orders or not leftovers:
        return {**first, "unmatched_orders": first["unmatched_orders"] + list(padded_orders or [])}
    second = match_orders(padded_orders, leftovers)
    taken = {inv["invoice_id"] for m in second["matches"] for inv in m["invoices"]}
    return {
        "matches": first["matches"] + second["matches"],
        "unmatched_orders": first["unmatched_orders"] + second["unmatched_orders"],
        "unmatched_invoices": [inv for inv in first["unmatched_invoices"] if inv["invoice_id"] not in taken],
        "shared_note": {**first["shared_note"], **second["shared_note"]},
    }


def match_orders(orders: List[Dict[str, Any]],
                 invoices: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Two-pass matching; each order and each invoice is consumed at most once.

    Pass 1 groups both sides by tracking number. A tracking number shared by
    several orders and/or invoices (one box, several orders) forms a group:
    1:1 groups pair directly; a one-to-many group whose combined totals
    agree becomes ONE combined match (e.g. two orders invoiced together);
    otherwise members are paired greedily by best score and leftovers stay
    unmatched, annotated with the shared tracking so the UI can explain why.

    Pass 2 matches the remaining orders on customer identity: phone, then
    street address+zip, then name+zip — invoice dated within a day.

    Pass 3 pairs same-day identical baskets whose customer text differs.

    Pass 4 catches orders entered into Shopify days or weeks after the
    invoice shipped: same identity key as pass 2 AND the same basket (or
    the order is a large subset of the invoice), any day lag inside the
    fetched window.

    Each match is {"orders": [...], "invoices": [...], "method", "ambiguous",
    "shared_tracking"}; unmatched entries carry the same shared_tracking
    annotation when they belonged to a group.
    """
    used_orders: set = set()
    used_invoices: set = set()
    matches: List[Dict[str, Any]] = []
    shared_note: Dict[Any, Dict[str, Any]] = {}     # order id / invoice id -> group annotation

    by_tracking_o: Dict[str, List[Dict[str, Any]]] = {}
    for order in orders:
        for n in split_routes(order.get("tracking_numbers", []))[0]:
            if order not in by_tracking_o.setdefault(n, []):
                by_tracking_o[n].append(order)
    by_tracking_i: Dict[str, List[Dict[str, Any]]] = {}
    for inv in invoices:
        for n in split_routes(split_tracking(inv["tracking_no"]))[0]:
            if inv not in by_tracking_i.setdefault(n, []):
                by_tracking_i[n].append(inv)

    def emit(group_orders, group_invoices, method, ambiguous, shared):
        for o in group_orders:
            used_orders.add(o["id"])
        for i in group_invoices:
            used_invoices.add(i["invoice_id"])
        matches.append({
            "orders": list(group_orders), "invoices": list(group_invoices),
            "method": method, "ambiguous": ambiguous, "shared_tracking": shared,
        })

    # Pass 1 — tracking groups, earliest order first for determinism.
    for t in sorted(by_tracking_o, key=lambda k: min(o.get("local_date") or "" for o in by_tracking_o[k])):
        group_o = [o for o in by_tracking_o[t] if o["id"] not in used_orders]
        group_i = [i for i in by_tracking_i.get(t, []) if i["invoice_id"] not in used_invoices]
        if not group_o or not group_i:
            continue
        shared = None
        if len(group_o) > 1 or len(group_i) > 1:
            shared = {
                "tracking": t,
                "orders": [o["name"] for o in group_o],
                "invoices": [i["invoice_number"] for i in group_i],
            }
            for o in group_o:
                shared_note[("o", o["id"])] = shared
            for i in group_i:
                shared_note[("i", i["invoice_id"])] = shared

        if len(group_o) == 1 and len(group_i) == 1:
            emit(group_o, group_i, "tracking", False, None)
            continue
        if min(len(group_o), len(group_i)) == 1 and _combined_totals_match(group_o, group_i):
            emit(group_o, group_i, "tracking", False, shared)
            continue
        for o, i, ambiguous in _pair_within_group(group_o, group_i):
            emit([o], [i], "tracking", ambiguous, shared)

    # Pass 2 — customer identity over what is left.
    by_phone: Dict[str, List[Dict[str, Any]]] = {}
    by_addr: Dict[str, List[Dict[str, Any]]] = {}
    by_namezip: Dict[str, List[Dict[str, Any]]] = {}
    for inv in invoices:
        if inv["invoice_id"] in used_invoices:
            continue
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

    def take(order, keys, index, method) -> bool:
        candidates: List[Dict[str, Any]] = []
        for k in keys:
            for inv in index.get(k, []):
                if (inv["invoice_id"] not in used_invoices and inv not in candidates
                        and _identity_plausible(order, inv)):
                    candidates.append(inv)
        if not candidates:
            return False
        inv, ambiguous = _pick_candidate(order, candidates)
        emit([order], [inv], method, ambiguous, shared_note.get(("o", order["id"])))
        return True

    def identity_keys(order):
        return (
            [normalize_phone(p) for p in order.get("phones", [])],
            [normalize_address(order.get("address1"), order.get("zip"))],
            [normalize_name_zip(order.get("customer_name"), order.get("zip"))],
        )

    for order in orders:
        if order["id"] in used_orders:
            continue
        phones, addrs, namezips = identity_keys(order)
        if take(order, phones, by_phone, "phone"):
            continue
        if take(order, addrs, by_addr, "address"):
            continue
        take(order, namezips, by_namezip, "name_zip")

    # Pass 3 — same-day basket fingerprint over whatever is still unmatched,
    # best overlap first so each invoice goes to its closest order.
    left_orders = [o for o in orders if o["id"] not in used_orders]
    by_day: Dict[str, List[Dict[str, Any]]] = {}
    for inv in invoices:
        if inv["invoice_id"] not in used_invoices and inv.get("date"):
            by_day.setdefault(inv["date"], []).append(inv)
    scored: List[Tuple[float, float, Dict[str, Any], Dict[str, Any]]] = []
    for order in left_orders:
        try:
            placed = datetime.strptime(order["local_date"], "%Y-%m-%d")
        except (KeyError, TypeError, ValueError):
            continue
        for lag in range(-IDENTITY_MAX_DAY_LAG, IDENTITY_MAX_DAY_LAG + 1):
            day = (placed + timedelta(days=lag)).strftime("%Y-%m-%d")
            for inv in by_day.get(day, []):
                if not _identity_plausible(order, inv):
                    continue
                if _basket_match(order, inv):
                    total = order.get("total") or 0
                    rel = abs(total - (inv.get("total") or 0)) / total if total else 1.0
                    scored.append((-_line_jaccard(order, inv), rel, order, inv))
    scored.sort(key=lambda t: (t[0], t[1]))
    for _, _, order, inv in scored:
        if order["id"] in used_orders or inv["invoice_id"] in used_invoices:
            continue
        emit([order], [inv], "products", False, shared_note.get(("o", order["id"])))

    # Pass 4 — orders keyed into Shopify after the fact (no tracking, dated
    # days after the invoice). Identity alone would pair a repeat customer's
    # orders at random and the basket alone would pair strangers, so both are
    # required; among a customer's identical weekly baskets the closest
    # invoice date wins and an exact tie is flagged ambiguous.
    late: List[Tuple[float, int, float, Dict[str, Any], Dict[str, Any]]] = []
    for order in orders:
        if order["id"] in used_orders:
            continue
        phones, addrs, namezips = identity_keys(order)
        seen: set = set()
        for keys, index in ((phones, by_phone), (addrs, by_addr), (namezips, by_namezip)):
            for k in keys:
                for inv in index.get(k, []):
                    if inv["invoice_id"] in used_invoices or inv["invoice_id"] in seen:
                        continue
                    seen.add(inv["invoice_id"])
                    if not (_basket_match(order, inv) or _basket_contained(order, inv)):
                        continue
                    if not _identity_plausible(order, inv, max_day_lag=None):
                        continue
                    late.append((-_line_jaccard(order, inv), _day_delta(order, inv),
                                 abs((order.get("total") or 0) - (inv.get("total") or 0)), order, inv))
    late.sort(key=lambda t: t[:3])
    for j, day, _, order, inv in late:
        if order["id"] in used_orders or inv["invoice_id"] in used_invoices:
            continue
        ambiguous = any(
            o2["id"] == order["id"] and i2["invoice_id"] not in used_invoices
            and i2["invoice_id"] != inv["invoice_id"] and (j2, d2) == (j, day)
            for j2, d2, _, o2, i2 in late)
        emit([order], [inv], "identity_basket", ambiguous, shared_note.get(("o", order["id"])))

    unmatched_orders = [o for o in orders if o["id"] not in used_orders]
    unmatched_invoices = [inv for inv in invoices if inv["invoice_id"] not in used_invoices]
    return {
        "matches": matches,
        "unmatched_orders": unmatched_orders,
        "unmatched_invoices": unmatched_invoices,
        "shared_note": shared_note,
    }


# ---------------------------------------------------------------------------
# Line comparison (pure)
# ---------------------------------------------------------------------------

def _shopify_lines_by_key(order: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Line items aggregated per key. Shipping charged as a shipping line
    (no "ship" line item) becomes one synthetic SHIPPING_KEY line carrying
    `shipping_line_ids`, so both Shopify conventions compare alike."""
    agg: Dict[str, Dict[str, Any]] = {}
    for li in order.get("lines", []):
        barcode = (li.get("barcode") or "").strip()
        sku = (li.get("sku") or "").strip()
        key = SHIPPING_KEY if is_shipping_line(barcode, sku) else line_key(barcode, sku, li.get("title"))
        line = agg.setdefault(key, {
            "key": key, "barcode": barcode, "sku": sku,
            "title": li.get("title") or "", "qty": 0.0,
            "amount": 0.0, "ordered": 0.0,
        })
        line["qty"] += float(li.get("current_quantity") or 0)
        line["amount"] += float(li.get("discounted_total") or 0)
        line["ordered"] += float(li.get("quantity") or 0)
    shipping_lines = [sl for sl in order.get("shipping_lines", []) if sl.get("id")]
    if SHIPPING_KEY not in agg and shipping_lines and sum(float(sl.get("price") or 0) for sl in shipping_lines) > 0:
        agg[SHIPPING_KEY] = {
            "key": SHIPPING_KEY, "barcode": SHIPPING_KEY, "sku": "shipment",
            "title": shipping_lines[0].get("title") or "Shipping", "qty": 1.0,
            "amount": round(sum(float(sl.get("price") or 0) for sl in shipping_lines), 2), "ordered": 1.0,
            "shipping_line_ids": [sl["id"] for sl in shipping_lines],
        }
    return agg


def _merge_orders(orders: List[Dict[str, Any]]) -> Dict[str, Any]:
    """A combined group behaves like one order: lines concatenated (the
    per-key aggregation sums them), totals summed."""
    if len(orders) == 1:
        return orders[0]
    return {
        "lines": [li for o in orders for li in o.get("lines", [])],
        "shipping_lines": [sl for o in orders for sl in o.get("shipping_lines", [])],
        "total": sum(o.get("total") or 0 for o in orders),
    }


def _merge_invoices(invoices: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(invoices) == 1:
        return invoices[0]
    agg: Dict[str, Dict[str, Any]] = {}
    for inv in invoices:
        for li in _invoice_lines(inv):
            line = agg.setdefault(li["key"], {**li, "qty_shipped": 0.0, "_amount": 0.0})
            line["qty_shipped"] += li["qty_shipped"]
            line["_amount"] += li["qty_shipped"] * li["unit_price"]
    lines = []
    for line in agg.values():
        amount = line.pop("_amount")
        line["unit_price"] = round(amount / line["qty_shipped"], 4) if line["qty_shipped"] else 0.0
        lines.append(line)
    return {"lines": lines, "total": sum(i.get("total") or 0 for i in invoices)}


def compare_lines(order: Dict[str, Any],
                  invoice: Dict[str, Any]) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Union of both sides' lines keyed by barcode (sku/description fallback).
    Returns (issue_kinds, line_diffs). BackOffice QtyShipped is the truth."""
    sh_lines = _shopify_lines_by_key(order)
    bo_lines = {li["key"]: li for li in _invoice_lines(invoice)}

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
            if abs(sh_price - bo_price) > PRICE_TOL:
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
            "sh_line_total": round(sh_qty * sh_price, 2) if sh else None,
            "bo_line_total": round(bo_qty * bo_price, 2) if bo else None,
            "issues": issues,
        })

    # Differences first so the drill-in leads with what's wrong.
    diffs.sort(key=lambda d: (not d["issues"], d["key"]))
    return sorted(kinds), diffs


# ---------------------------------------------------------------------------
# Report assembly (pure)
# ---------------------------------------------------------------------------

def _dedupe(values: List[str]) -> List[str]:
    out: List[str] = []
    for v in values:
        if v not in out:
            out.append(v)
    return out


def _order_side(orders: List[Dict[str, Any]]) -> Dict[str, Any]:
    tracking: List[str] = []
    routes: List[str] = []
    for o in orders:
        real, rt = split_routes(o.get("tracking_numbers", []))
        tracking += real
        routes += rt
    tracking, routes = _dedupe(tracking), _dedupe(routes)
    first = orders[0]
    return {
        "sh_orders": [{
            "id": o.get("id"), "name": o.get("name"), "date": o.get("local_date"),
            "total": o.get("total"), "customer": o.get("customer_name") or o.get("email") or None,
            "tracking": o.get("tracking_numbers", []),
        } for o in orders],
        "sh_route": routes,
        "sh_order_id": first.get("id"),
        "sh_name": " + ".join(o.get("name") or "" for o in orders),
        "sh_date": min((o.get("local_date") or "" for o in orders), default=None) or None,
        "sh_total": round(sum(o.get("total") or 0 for o in orders), 2),
        "sh_customer": first.get("customer_name") or first.get("email") or None,
        "sh_tracking": tracking,
        "sh_no_tracking": any(not o.get("tracking_numbers") for o in orders),
        "sh_outstanding": round(sum(o.get("outstanding") or 0 for o in orders), 2),
        "sh_channel": ", ".join(_dedupe([o.get("channel") for o in orders if o.get("channel")])) or None,
    }


def _invoice_side(invoices: List[Dict[str, Any]]) -> Dict[str, Any]:
    first = invoices[0]
    tracking: List[str] = []
    routes: List[str] = []
    for i in invoices:
        real, rt = split_routes(split_tracking(i["tracking_no"]))
        tracking += real
        routes += rt
    tracking, routes = _dedupe(tracking), _dedupe(routes)
    return {
        "bo_route": routes,
        "bo_invoices": [{
            "id": i["invoice_id"], "number": i["invoice_number"], "date": i["invoice_date"],
            "total": i["total"], "customer": i["business_name"] or i["ship_to"] or None,
            "tracking": i["tracking_no"] if i["has_tracking"] else None,
        } for i in invoices],
        "bo_invoice_id": first["invoice_id"],
        "bo_invoice_number": " + ".join(i["invoice_number"] for i in invoices),
        "bo_date": min((i["invoice_date"] or "" for i in invoices), default=None) or None,
        "bo_total": round(sum(i["total"] or 0 for i in invoices), 2),
        "bo_customer": first["business_name"] or first["ship_to"] or None,
        "bo_tracking": ", ".join(tracking) if tracking else None,
        "bo_no_tracking": any(not i["has_tracking"] for i in invoices),
    }


def _shopify_only_lines(order: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for li in _shopify_lines_by_key(order).values():
        price = round(li["amount"] / li["ordered"], 4) if li["ordered"] else 0.0
        out.append({
            "key": li["key"], "barcode": li["barcode"] or None, "sku": li["sku"] or None,
            "description": li["title"] or None,
            "sh_qty": li["qty"], "bo_qty": None,
            "sh_unit_price": price, "bo_unit_price": None,
            "sh_line_total": round(li["qty"] * price, 2), "bo_line_total": None,
            "issues": [],
        })
    return out


def _invoice_only_lines(invoice: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{
        "key": li["key"], "barcode": li["barcode"] or None, "sku": li["sku"] or None,
        "description": li["description"] or None,
        "sh_qty": None, "bo_qty": li["qty_shipped"],
        "sh_unit_price": None, "bo_unit_price": li["unit_price"],
        "sh_line_total": None, "bo_line_total": round(li["qty_shipped"] * li["unit_price"], 2),
        "issues": [],
    } for li in _invoice_lines(invoice)]


def build_pair_row(orders: List[Dict[str, Any]], invoices: List[Dict[str, Any]],
                   method: Optional[str], ambiguous: bool,
                   shared_tracking: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One matched row: both sides summarized, lines compared, status derived.
    Used by build_report and by the fix flow to rebuild a row after applying."""
    merged_o = _merge_orders(orders)
    merged_i = _merge_invoices(invoices)
    kinds, diffs = compare_lines(merged_o, merged_i)
    total_delta = round((merged_o.get("total") or 0) - (merged_i.get("total") or 0), 2)
    if abs(total_delta) > CENT_TOL:
        kinds = sorted(set(kinds) | {"total"})
    return {
        "status": "matched_ok" if not kinds else "matched_diffs",
        "match_method": method, "ambiguous": ambiguous,
        "shared_tracking": shared_tracking,
        "tracking_conflict": tracking_conflict(orders, invoices),
        "combined": len(orders) > 1 or len(invoices) > 1,
        **_order_side(orders), **_invoice_side(invoices),
        "total_delta": total_delta, "issue_kinds": kinds, "line_diffs": diffs,
    }


def build_report(orders: List[Dict[str, Any]], invoices: List[Dict[str, Any]],
                 date_from: str, date_to: str,
                 padded_orders: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Match, compare, and assemble rows + summary. Out-of-range invoices and
    padded orders (fetched only to find late counterparts) may be consumed by
    matches but are dropped when unmatched; a matched pair is reported when
    either side is in range. Totals count in-range rows only."""
    for o in orders:
        o.setdefault("in_range", True)
    for o in padded_orders or []:
        o["in_range"] = False
    result = match_orders_staged(orders, invoices, padded_orders or [])
    shared_note = result["shared_note"]

    rows: List[Dict[str, Any]] = []
    summary = {
        "matched_ok": 0, "matched_diffs": 0,
        "shopify_unmatched": 0, "backoffice_unmatched": 0,
        "shopify_no_tracking": 0, "backoffice_no_tracking": 0,
        "shopify_total": len(orders), "backoffice_total": 0,
        "matched_orders": 0, "combined_groups": 0, "ambiguous": 0,
        "issue_counts": {"product": 0, "qty": 0, "price": 0, "total": 0},
    }

    for m in result["matches"]:
        row = build_pair_row(m["orders"], m["invoices"], m["method"], m["ambiguous"],
                             m["shared_tracking"])
        rows.append(row)
        summary[row["status"]] += 1
        summary["matched_orders"] += len(m["orders"])
        if row["combined"]:
            summary["combined_groups"] += 1
        if m["ambiguous"]:
            summary["ambiguous"] += 1
        for k in row["issue_kinds"]:
            summary["issue_counts"][k] = summary["issue_counts"].get(k, 0) + 1

    for order in result["unmatched_orders"]:
        if not order.get("in_range", True):
            continue
        rows.append({
            "status": "shopify_unmatched", "match_method": None, "ambiguous": False,
            "shared_tracking": shared_note.get(("o", order["id"])), "combined": False,
            **_order_side([order]),
            "total_delta": None, "issue_kinds": [], "line_diffs": _shopify_only_lines(order),
        })
        summary["shopify_unmatched"] += 1

    for invoice in result["unmatched_invoices"]:
        if not invoice["in_range"]:
            continue
        rows.append({
            "status": "backoffice_unmatched", "match_method": None, "ambiguous": False,
            "shared_tracking": shared_note.get(("i", invoice["invoice_id"])), "combined": False,
            **_invoice_side([invoice]),
            "total_delta": None, "issue_kinds": [], "line_diffs": _invoice_only_lines(invoice),
        })
        summary["backoffice_unmatched"] += 1

    summary["backoffice_total"] = sum(1 for inv in invoices if inv["in_range"])
    summary["shopify_total"] = sum(1 for o in orders if o.get("in_range", True))
    summary["shopify_no_tracking"] = sum(
        1 for o in orders if o.get("in_range", True) and not o.get("tracking_numbers"))
    summary["backoffice_no_tracking"] = sum(
        1 for inv in invoices if inv["in_range"] and not inv["has_tracking"])

    rows.sort(key=lambda r: (r.get("sh_date") or (r.get("bo_date") or "")[:10] or ""), reverse=True)
    return {"summary": summary, "rows": rows}


# ---------------------------------------------------------------------------
# Balance Shopify will actually let us mark as paid (pure)
# ---------------------------------------------------------------------------

def collectible_balance(current_total: Any, net_payment: Any, can_mark_as_paid: Any) -> float:
    """What orderMarkAsPaid can still collect. Shopify's totalOutstanding is
    gross (order total minus payments, ignoring $0 item refunds), but it only
    allows a manual payment while the CURRENT total — after those refunds —
    exceeds what was received; a fix's $0 refund leaves a credit that later
    additions consume first. Zero whenever Shopify says the order is paid."""
    if not can_mark_as_paid:
        return 0.0
    try:
        balance = float(current_total or 0) - float(net_payment or 0)
    except (TypeError, ValueError):
        return 0.0
    return round(balance, 2) if balance > 0.004 else 0.0


# ---------------------------------------------------------------------------
# Products on BackOffice-only invoices that the Shopify catalog lacks (pure)
# ---------------------------------------------------------------------------

def aggregate_missing_products(orders: List[Dict[str, Any]],
                               found: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One row per barcode used on the given invoices that no ACTIVE Shopify
    variant carries. `found` is find_barcodes_in_catalog's map: a barcode
    absent from it is "missing"; present on a DRAFT/ARCHIVED product it is
    reported with that status. Lines without a barcode and shipping
    pseudo-lines are skipped. Sorted by most invoices, then most units."""
    agg: Dict[str, Dict[str, Any]] = {}
    for order in orders:
        number = str(order.get("invoice_number") or "")
        date = (order.get("date") or "")[:10]
        seen_here: set = set()
        for li in order.get("lines", []):
            barcode = (li.get("barcode") or "").strip()
            if not barcode or is_shipping_line(barcode, li.get("sku")):
                continue
            hit = found.get(barcode)
            if hit and hit.get("product_status") == "ACTIVE":
                continue
            row = agg.setdefault(barcode, {
                "barcode": barcode, "sku": (li.get("sku") or "").strip() or None,
                "description": (li.get("description") or "").strip() or None,
                "shopify_status": (hit or {}).get("product_status") or "MISSING",
                "shopify_title": (hit or {}).get("product_title") or None,
                "invoice_count": 0, "total_qty": 0.0, "invoices": [], "last_date": None,
            })
            row["total_qty"] += float(li.get("qty") or 0)
            if not row["description"] and (li.get("description") or "").strip():
                row["description"] = li["description"].strip()
            if barcode not in seen_here:
                seen_here.add(barcode)
                row["invoice_count"] += 1
                if number and number not in row["invoices"]:
                    row["invoices"].append(number)
            if date and (row["last_date"] is None or date > row["last_date"]):
                row["last_date"] = date
    rows = list(agg.values())
    rows.sort(key=lambda r: (-r["invoice_count"], -r["total_qty"], r["barcode"]))
    return rows


# ---------------------------------------------------------------------------
# Fix planning (pure)
# ---------------------------------------------------------------------------
#
# Every order in the report is FULFILLED, and Shopify's order-edit API only
# touches unfulfilled line items. So the Shopify side is corrected with:
#   refund  — $0 refund of N units (records only, no restock) to remove units
#   add     — order edit: add the variant at the invoice price (line discount
#             when that is below the variant price, temporary variant price
#             bump when above), commit, fulfill the new fulfillment order,
#             mark paid
#   replace — refund every current unit of a line + add it back at the
#             invoice price (the only way to change a fulfilled line's price)
#   tracking— push the invoice tracking number onto fulfillments lacking one
#   variant_price — for every repriced line, set the variant's storefront
#             price to the BackOffice item price (Items_tbl.UnitPrice by
#             ProductUPC = barcode) so future orders come in at that price
#   create_product — only when the caller opts in: the UPC carries no variant
#             in this Shopify store, so the product is created from the
#             BackOffice item (barcode = the UPC) and the `add` that follows
#             uses it. resolve_created_variants fills the ids in afterwards.
# A key whose fix would be half-possible (e.g. refund OK but the re-add has
# no variant) is left untouched and reported as unsupported.

UNSUPPORTED_MESSAGES = {
    "no_barcode": "Line has no barcode — cannot be located in Shopify",
    "no_variant": "No Shopify variant carries this barcode",
    "not_refundable": "Not enough refundable units on the Shopify line",
}

# Why a created product is not taking its details from Items_tbl (plan
# `notes`). None of these block the creation — the invoice line is the
# fallback source for the title and the price.
CREATE_PRODUCT_MESSAGES = {
    "lookup_failed": "BackOffice item lookup failed — the product is created from the invoice line",
    "not_found": "Not in BackOffice Items_tbl (or discontinued) — the product is created from the invoice line",
    "no_price": "BackOffice item price is empty or zero — the product is created at the invoice price",
}

# Why a repriced line's storefront price is NOT being updated (plan `notes`).
STORE_PRICE_MESSAGES = {
    "lookup_failed": "BackOffice item price lookup failed — store price left unchanged",
    "not_found": "Not in BackOffice Items_tbl (or discontinued) — store price left unchanged",
    "no_price": "BackOffice item price is empty or zero — store price left unchanged",
    "unchanged": "Store price already matches the BackOffice item price",
}


def _raw_lines_by_key(order: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    by_key: Dict[str, List[Dict[str, Any]]] = {}
    for li in order.get("lines", []):
        key = SHIPPING_KEY if is_shipping_line(li.get("barcode"), li.get("sku")) else line_key(li.get("barcode"), li.get("sku"), li.get("title"))
        by_key.setdefault(key, []).append(li)
    return by_key


def _refund_action(reason: str, diff: Dict[str, Any], lines: List[Dict[str, Any]],
                   units: float) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Drain `units` from the key's Shopify lines, last line first, bounded by
    what Shopify still allows refunding on each."""
    need = int(round(units))
    if need <= 0:
        return None, None
    picks: List[Dict[str, Any]] = []
    for li in reversed(lines):
        if need <= 0:
            break
        avail = int(min(li.get("current_quantity") or 0, li.get("refundable_quantity") or 0))
        take = min(avail, need)
        if take > 0 and li.get("line_item_id"):
            picks.append({"line_item_id": li["line_item_id"], "quantity": take})
            need -= take
    if need > 0:
        return None, "not_refundable"
    return {
        "kind": "refund", "reason": reason, "key": diff["key"],
        "barcode": diff.get("barcode"), "description": diff.get("description"),
        "qty": int(round(units)), "unit_price": diff.get("sh_unit_price"),
        "line_items": picks,
    }, None


def _add_action(reason: str, diff: Dict[str, Any], qty: float, target_price: float,
                variants_by_barcode: Dict[str, Dict[str, Any]],
                create_products: bool = False
                ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    barcode = (diff.get("barcode") or "").strip()
    if not barcode:
        return None, "no_barcode"
    variant = variants_by_barcode.get(barcode)
    units = int(round(qty))
    if not variant or not variant.get("variant_id"):
        if not create_products:
            return None, "no_variant"
        if units <= 0:
            return None, None
        # The product does not exist in this store yet. A create_product
        # action runs before the edit and resolve_created_variants then fills
        # in the ids and decides the bump against the price it was created at.
        return {
            "kind": "add", "reason": reason, "key": diff["key"],
            "barcode": barcode, "description": diff.get("description"),
            "qty": units, "unit_price": round(target_price, 2),
            "variant_id": None, "product_id": None,
            "variant_price": None, "variant_price_raw": None,
            "variant_title": None,
            "discount_total": 0.0,
            "bump_price": False,
            "create_variant": True,
        }, None
    variant_price = float(variant.get("price") or 0)
    if units <= 0:
        return None, None
    # Below the variant price → a line discount; above it → the variant price
    # is raised to the invoice price for the duration of the edit, then
    # restored (a discount can only lower a price).
    bump = variant_price + PRICE_TOL < target_price
    discount_total = 0.0 if bump else round(max(variant_price - target_price, 0.0) * units, 2)
    return {
        "kind": "add", "reason": reason, "key": diff["key"],
        "barcode": barcode, "description": diff.get("description") or variant.get("product_title"),
        "qty": units, "unit_price": round(target_price, 2),
        "variant_id": variant["variant_id"], "product_id": variant.get("product_id"),
        "variant_price": round(variant_price, 2), "variant_price_raw": variant.get("price_raw"),
        "variant_title": variant.get("product_title"),
        "discount_total": discount_total if discount_total > PRICE_TOL else 0.0,
        "bump_price": bump,
    }, None


def _create_product_action(diff: Dict[str, Any], add: Dict[str, Any],
                           item_prices: Optional[Dict[str, Dict[str, Any]]],
                           lookup_error: Optional[str]
                           ) -> Tuple[Dict[str, Any], Optional[str]]:
    """The Shopify product to create for a line whose UPC carries no variant:
    (action, note reason or None). An action is ALWAYS returned — a UPC that
    is not in Items_tbl is still created from the invoice line, and the note
    says where the details came from. `unit_price` is the storefront price
    (Items_tbl.UnitPrice); the order line is still added at the invoice
    price."""
    barcode = add["barcode"]
    item = (item_prices or {}).get(barcode)
    why: Optional[str] = None
    if item_prices is None:
        why = "lookup_failed" if lookup_error else None
    elif not item:
        why = "not_found"

    try:
        price = float(item["unit_price"]) if item and item.get("unit_price") is not None else None
    except (TypeError, ValueError):
        price = None
    if price is None or price <= 0:
        if item and why is None:
            why = "no_price"
        price, source = float(add["unit_price"]), "invoice"
    else:
        source = "items_tbl"

    try:
        cost = float(item["unit_cost"]) if item and item.get("unit_cost") is not None else None
    except (TypeError, ValueError):
        cost = None

    title = ((item or {}).get("description") or diff.get("description") or "").strip() or barcode
    sku = (diff.get("sku") or "").strip() or barcode
    return {
        "kind": "create_product", "reason": "create", "key": diff["key"],
        "barcode": barcode, "description": title,
        "title": title, "sku": sku,
        "unit_price": round(price, 2),
        "unit_cost": round(cost, 2) if cost and cost > 0 else None,
        "price_source": source,
    }, why


def resolve_created_variants(actions: List[Dict[str, Any]],
                             created_by_barcode: Dict[str, Dict[str, Any]]) -> List[str]:
    """Fill freshly created products into their `add` actions and decide the
    bump now that a variant price exists (a discount can only lower a price —
    the same rule _add_action applies to an existing variant). Mutates the
    actions in place; returns the barcodes that could not be resolved."""
    unresolved: List[str] = []
    for a in actions:
        if a.get("kind") != "add" or not a.get("create_variant"):
            continue
        variant = created_by_barcode.get(a["barcode"]) or {}
        if not variant.get("variant_id"):
            unresolved.append(a["barcode"])
            continue
        variant_price = float(variant.get("price") or 0)
        target = float(a["unit_price"])
        units = int(a["qty"])
        bump = variant_price + PRICE_TOL < target
        a.update({
            "variant_id": variant["variant_id"],
            "product_id": variant.get("product_id"),
            "variant_price": round(variant_price, 2),
            "variant_price_raw": variant.get("price_raw"),
            "variant_title": variant.get("product_title"),
            "bump_price": bump,
            "discount_total": 0.0 if bump else round(max(variant_price - target, 0.0) * units, 2),
        })
    return unresolved


def _shipping_line_action(diff: Dict[str, Any], sh_shipping: Dict[str, Any]) -> Dict[str, Any]:
    """Replace the order's shipping line(s) with one at the invoice's
    shipping amount (qty × unit price), or remove them when the invoice
    carries no shipping."""
    bo_qty = diff.get("bo_qty") or 0.0
    bo_price = diff.get("bo_unit_price") or 0.0
    amount = round(bo_qty * bo_price, 2) if diff.get("bo_qty") is not None else None
    return {
        "kind": "shipping_line",
        "reason": "shipping" if amount is not None else "shipping_remove",
        "key": SHIPPING_KEY, "barcode": SHIPPING_KEY,
        "description": diff.get("description") or sh_shipping.get("title") or "Shipping",
        "title": sh_shipping.get("title") or "Shipping",
        "remove_ids": list(sh_shipping.get("shipping_line_ids") or []),
        "sh_amount": round(float(sh_shipping.get("amount") or 0), 2),
        "amount": amount,
        "unit_price": amount,
    }


def _variant_price_action(diff: Dict[str, Any], add: Dict[str, Any],
                          item_prices: Optional[Dict[str, Dict[str, Any]]],
                          lookup_error: Optional[str]
                          ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Storefront price change for a repriced line: (action, None) or
    (None, note reason); (None, None) when no lookup was attempted.
    `unit_price` on the action is the NEW storefront price
    (Items_tbl.UnitPrice); `variant_price` is the current one."""
    if item_prices is None:
        return None, "lookup_failed" if lookup_error else None
    item = item_prices.get(add["barcode"])
    if not item:
        return None, "not_found"
    new_price = item.get("unit_price")
    if new_price is None or float(new_price) <= 0:
        return None, "no_price"
    new_price = round(float(new_price), 2)
    if abs(float(add["variant_price"]) - new_price) <= PRICE_TOL:
        return None, "unchanged"
    return {
        "kind": "variant_price", "reason": "price", "key": diff["key"],
        "barcode": add["barcode"], "description": add.get("description"),
        "variant_id": add["variant_id"], "product_id": add.get("product_id"),
        "variant_price": add["variant_price"], "variant_price_raw": add.get("variant_price_raw"),
        "unit_price": new_price,
    }, None


def plan_order_fix(order: Dict[str, Any], invoice: Dict[str, Any],
                   variants_by_barcode: Dict[str, Dict[str, Any]],
                   push_tracking: bool = True,
                   item_prices: Optional[Dict[str, Dict[str, Any]]] = None,
                   item_price_error: Optional[str] = None,
                   create_products: bool = False) -> Dict[str, Any]:
    """Actions that bring the Shopify order's lines to the invoice's lines.
    Pure: `order` is a fetch_order_for_sync dict (line ids present),
    `variants_by_barcode` comes from find_variants_by_barcode, `item_prices`
    from get_item_prices_batch_async on the BackOffice store (None when that
    lookup failed — `item_price_error` says why). With `create_products`, a
    UPC that carries no variant gets one created instead of being reported
    unsupported."""
    _kinds, diffs = compare_lines(order, invoice)
    raw_by_key = _raw_lines_by_key(order)
    sh_shipping = _shopify_lines_by_key(order).get(SHIPPING_KEY) or {}

    actions: List[Dict[str, Any]] = []
    unsupported: List[Dict[str, Any]] = []
    notes: List[Dict[str, Any]] = []
    for d in diffs:
        issues = d.get("issues") or []
        if not issues:
            continue
        if d["key"] == SHIPPING_KEY and sh_shipping.get("shipping_line_ids"):
            # Shopify charges this as a shipping line, not a line item:
            # replace the line(s) with one at the invoice amount, or drop them.
            actions.append(_shipping_line_action(d, sh_shipping))
            continue
        lines = raw_by_key.get(d["key"], [])
        sh_qty = d.get("sh_qty") or 0.0
        bo_qty = d.get("bo_qty") or 0.0
        bo_price = d.get("bo_unit_price") or 0.0
        planned: List[Tuple[Optional[Dict[str, Any]], Optional[str]]] = []

        if "missing_in_backoffice" in issues:
            planned.append(_refund_action("remove", d, lines, sh_qty))
        elif "missing_in_shopify" in issues:
            planned.append(_add_action("add", d, bo_qty, bo_price, variants_by_barcode, create_products))
        elif "price" in issues:
            planned.append(_refund_action("replace", d, lines, sh_qty))
            planned.append(_add_action("replace", d, bo_qty, bo_price, variants_by_barcode, create_products))
        elif "qty" in issues:
            if sh_qty > bo_qty:
                planned.append(_refund_action("reduce", d, lines, sh_qty - bo_qty))
            else:
                planned.append(_add_action("increase", d, bo_qty - sh_qty, bo_price, variants_by_barcode,
                                           create_products))

        reasons = [r for _a, r in planned if r]
        if reasons:
            unsupported.append({
                "key": d["key"], "barcode": d.get("barcode"), "description": d.get("description"),
                "issues": issues, "reason": reasons[0],
                "message": UNSUPPORTED_MESSAGES.get(reasons[0], reasons[0]),
                "sh_qty": d.get("sh_qty"), "bo_qty": d.get("bo_qty"),
                "sh_unit_price": d.get("sh_unit_price"), "bo_unit_price": d.get("bo_unit_price"),
            })
            continue
        for a in (a for a, _r in planned if a):
            if a["kind"] == "add" and a.get("create_variant"):
                create, why = _create_product_action(d, a, item_prices, item_price_error)
                actions.append(create)
                if why:
                    message = CREATE_PRODUCT_MESSAGES[why]
                    if why == "lookup_failed" and item_price_error:
                        message += f": {item_price_error}"
                    notes.append({"key": d["key"], "barcode": d.get("barcode"),
                                  "description": d.get("description"),
                                  "reason": why, "message": message})
            actions.append(a)

        if "price" in issues and d["key"] != SHIPPING_KEY:
            # A created product already carries Items_tbl.UnitPrice, so it
            # never needs the storefront-price step.
            add = next((a for a, _r in planned
                        if a and a["kind"] == "add" and not a.get("create_variant")), None)
            if add:
                vp, why = _variant_price_action(d, add, item_prices, item_price_error)
                if vp:
                    actions.append(vp)
                elif why:
                    message = STORE_PRICE_MESSAGES[why]
                    if why == "lookup_failed" and item_price_error:
                        message += f": {item_price_error}"
                    notes.append({"key": d["key"], "barcode": d.get("barcode"),
                                  "description": d.get("description"),
                                  "reason": why, "message": message})

    if push_tracking:
        sh_real, _ = split_routes(order.get("tracking_numbers", []))
        bo_real, _ = split_routes(split_tracking(invoice.get("tracking_no")))
        targets = order.get("fulfillment_ids_without_tracking") or []
        if not sh_real and bo_real and targets:
            actions.append({"kind": "tracking", "reason": "tracking",
                            "numbers": bo_real, "fulfillment_ids": targets})

    # A balance left behind when an earlier run added lines but could not
    # mark the order paid (Shopify's post-fulfillment lock) — finish it.
    outstanding = round(float(order.get("outstanding") or 0), 2)
    if outstanding > 0.004:
        actions.append({"kind": "mark_paid", "reason": "mark_paid", "amount": outstanding})

    refunds = [a for a in actions if a["kind"] == "refund"]
    adds = [a for a in actions if a["kind"] == "add"]
    return {
        "actions": actions,
        "unsupported": unsupported,
        "notes": notes,
        "summary": {
            "refunds": len(refunds), "refund_units": sum(a["qty"] for a in refunds),
            "adds": len(adds), "add_units": sum(a["qty"] for a in adds),
            "add_amount": round(sum(a["qty"] * a["unit_price"] for a in adds), 2),
            "tracking": any(a["kind"] == "tracking" for a in actions),
            "shipping_lines": sum(1 for a in actions if a["kind"] == "shipping_line"),
            "mark_paid": outstanding if outstanding > 0.004 else 0.0,
            "unsupported": len(unsupported),
            "variant_prices": sum(1 for a in actions if a["kind"] == "variant_price"),
            "create_products": sum(1 for a in actions if a["kind"] == "create_product"),
        },
        "noop": not actions,
    }


# ---------------------------------------------------------------------------
# Duplicate Shopify orders (pure)
#
# Most "missing tracking" rows — Shopify orders that shipped, carry nothing in
# the tracking field and found no invoice — are the same sale keyed into
# Shopify twice. This plans which of them to cancel.
#
# The unit of reasoning is a CLUSTER, not a pair: group one customer's orders
# by "same sale" (totals within tolerance, placed within a few days), elect
# exactly one survivor, and cancel the rest. Pair-at-a-time reasoning would
# happily produce A-cancels-B and B-cancels-A and lose the sale entirely;
# with clusters that is unrepresentable.
# ---------------------------------------------------------------------------

DUP_TOTAL_TOL_PCT = 0.20      # totals this far apart are still the same sale
DUP_MAX_DAYS_APART = 18       # a sale keyed twice is keyed within a couple of weeks
DUP_LOW_TOTAL = 25.00         # below this, 20% is noise — flagged, not blocked


def dup_totals_within(a: Any, b: Any, pct: float = DUP_TOTAL_TOL_PCT) -> bool:
    """Relative to the LARGER total, so the test is symmetric."""
    x, y = abs(float(a or 0)), abs(float(b or 0))
    base = max(x, y)
    if base <= 0:
        return x == y
    return abs(x - y) <= pct * base


def _dup_days_apart(a: Optional[str], b: Optional[str]) -> Optional[int]:
    if not a or not b:
        return None
    try:
        return abs((datetime.strptime(a[:10], "%Y-%m-%d") - datetime.strptime(b[:10], "%Y-%m-%d")).days)
    except ValueError:
        return None


def _dup_same_sale(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Both money figures must agree: a partial refund moves `total` but not
    `gross_total`, and either one alone would let the window drift."""
    if not dup_totals_within(a.get("total"), b.get("total")):
        return False
    if not dup_totals_within(a.get("gross_total"), b.get("gross_total")):
        return False
    days = _dup_days_apart(a.get("local_date"), b.get("local_date"))
    return days is not None and days <= DUP_MAX_DAYS_APART


def dup_has_tracking(order: Dict[str, Any]) -> bool:
    """Route codes are not tracking — every local delivery would look shipped."""
    real, _routes = split_routes(order.get("tracking_numbers") or [])
    return bool(real)


def _dup_legacy_id(order: Dict[str, Any]) -> int:
    tail = str(order.get("id") or "").rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _dup_tier(order: Dict[str, Any], invoiced_ids: set) -> int:
    """0 = reconciled to a BackOffice invoice, 1 = really shipped, 2 = neither.
    The lowest tier in a cluster is the order that must survive."""
    if order.get("id") in invoiced_ids:
        return 0
    if dup_has_tracking(order):
        return 1
    return 2


def _dup_flags(order: Dict[str, Any]) -> List[str]:
    flags: List[str] = []
    if abs(float(order.get("total") or 0)) < DUP_LOW_TOTAL:
        flags.append("low_total")
    if float(order.get("net_payment") or 0) > 0.004:
        flags.append("paid")
    if float(order.get("refunded") or 0) > 0.004:
        flags.append("refunded")
    return flags


def _dup_side(order: Dict[str, Any], tier: int) -> Dict[str, Any]:
    return {
        "sh_order_id": order.get("id"),
        "sh_name": order.get("name"),
        "sh_date": order.get("local_date"),
        "sh_total": round(float(order.get("total") or 0), 2),
        "tier": tier,
        "has_invoice": tier == 0,
        "has_tracking": dup_has_tracking(order),
        "financial_status": order.get("financial_status"),
        "net_payment": round(float(order.get("net_payment") or 0), 2),
    }


def _dup_rank_key(order: Dict[str, Any], invoiced_ids: set) -> Tuple[int, str, int]:
    """Total order over one customer's orders: reconciled beats shipped beats
    neither, then oldest. An order may only be cancelled toward one that ranks
    strictly better, which is what makes "A cancels B and B cancels A"
    impossible — the relation inherits this order's antisymmetry."""
    return (_dup_tier(order, invoiced_ids), order.get("created_at") or "", _dup_legacy_id(order))


def _dup_closeness_key(candidate: Dict[str, Any], order: Dict[str, Any],
                       invoiced_ids: set) -> Tuple[int, float, int, int]:
    """Which of the eligible survivors is most plausibly the SAME sale. Rank
    decides who may survive; this decides which one is meant. Picking by rank
    alone would reach past a next-day twin to an older order that merely
    happens to be reconciled."""
    return (_dup_tier(candidate, invoiced_ids),
            abs(float(candidate.get("total") or 0) - float(order.get("total") or 0)),
            _dup_days_apart(candidate.get("local_date"), order.get("local_date")) or 0,
            _dup_legacy_id(candidate))


def plan_duplicate_cancels(targets: List[str], pool: List[Dict[str, Any]],
                           invoiced_ids: Optional[set] = None,
                           protected_ids: Optional[set] = None) -> Dict[str, Any]:
    """
    Which of `targets` (Shopify order GIDs) duplicate another order in `pool`.

    One row per target, in the order given:
      proposed  — cancel it, `twin` survives
      ambiguous — a twin was found but the pairing needs a human: several
                  candidates, neither order carries an invoice or tracking to
                  mark it the original, a small total, or the twin is itself
                  queued for cancellation
      no_twin   — nothing qualifies, or this order IS the original
      blocked   — the order must not be cancelled by this pass

    A candidate must match the target DIRECTLY (same customer, both totals
    within tolerance, within the day window). Chaining through a third order
    is deliberately not allowed: with a repeat customer it would link a whole
    quarter of orders into one group and pair a September order with an
    August one.
    """
    invoiced_ids = invoiced_ids or set()
    protected_ids = protected_ids or set()
    by_id = {o["id"]: o for o in pool if o.get("id")}
    target_ids = list(targets)
    target_set = set(target_ids)

    by_customer: Dict[str, List[Dict[str, Any]]] = {}
    for o in by_id.values():
        cust = o.get("customer_gid")
        if cust and not o.get("cancelled"):
            by_customer.setdefault(cust, []).append(o)

    rows: List[Dict[str, Any]] = []
    summary = {"targets": len(target_ids), "proposed": 0, "ambiguous": 0,
               "no_twin": 0, "blocked": 0}

    for order_id in target_ids:
        order = by_id.get(order_id)
        row: Dict[str, Any] = {
            "sh_order_id": order_id, "sh_name": (order or {}).get("name"),
            "sh_date": (order or {}).get("local_date"),
            "sh_total": round(float((order or {}).get("total") or 0), 2),
            "customer_gid": (order or {}).get("customer_gid"),
            "financial_status": (order or {}).get("financial_status"),
            "net_payment": round(float((order or {}).get("net_payment") or 0), 2),
            "twin": None, "alternatives": [], "flags": [],
            "cluster_size": 0, "total_delta": None, "total_delta_pct": None,
            "date_delta_days": None, "reason": None,
        }
        if not order:
            row.update(status="blocked", reason="Order is no longer in Shopify, or is already cancelled")
        elif order.get("cancelled"):
            row.update(status="blocked", reason="Already cancelled in Shopify")
        elif order_id in protected_ids:
            row.update(status="blocked",
                       reason="Kept as the surviving order of an earlier duplicate cancellation")
        elif not order.get("customer_gid"):
            row.update(status="no_twin", reason="Order has no Shopify customer")
        else:
            row["flags"] = _dup_flags(order)
            direct = [c for c in by_customer.get(order["customer_gid"], [])
                      if c["id"] != order_id and _dup_same_sale(order, c)]
            own_key = _dup_rank_key(order, invoiced_ids)
            eligible = [c for c in direct if _dup_rank_key(c, invoiced_ids) < own_key]
            survivor = (min(eligible, key=lambda c: _dup_closeness_key(c, order, invoiced_ids))
                        if eligible else None)
            if not direct:
                row.update(status="no_twin", reason="No other order from this customer matches")
            elif not eligible:
                # Every match is newer/weaker than this one — this is the original.
                row.update(status="no_twin", reason="This is the earliest of the matching orders")
            else:
                twin_tier = _dup_tier(survivor, invoiced_ids)
                delta = round(float(order.get("total") or 0) - float(survivor.get("total") or 0), 2)
                base = max(abs(float(order.get("total") or 0)), abs(float(survivor.get("total") or 0)))
                alternatives = sorted(
                    (c for c in eligible if c["id"] != survivor["id"]),
                    key=lambda c: _dup_closeness_key(c, order, invoiced_ids))
                row.update(
                    twin=_dup_side(survivor, twin_tier),
                    alternatives=[_dup_side(c, _dup_tier(c, invoiced_ids)) for c in alternatives],
                    cluster_size=len(eligible) + 1,
                    total_delta=delta,
                    total_delta_pct=round(abs(delta) / base * 100, 1) if base else 0.0,
                    date_delta_days=_dup_days_apart(order.get("local_date"), survivor.get("local_date")),
                )
                reasons: List[str] = []
                if len(eligible) > 1:
                    reasons.append(f"{len(eligible)} orders from this customer qualify")
                if twin_tier == 2:
                    reasons.append("neither order has an invoice or tracking to mark it the original")
                if survivor["id"] in target_set:
                    reasons.append("the order it duplicates is also in this list")
                if "low_total" in row["flags"]:
                    reasons.append(f"order total is under ${DUP_LOW_TOTAL:,.0f}")
                row["status"] = "ambiguous" if reasons else "proposed"
                row["reason"] = "; ".join(reasons) or None
        summary[row["status"]] += 1
        rows.append(row)

    return {"rows": rows, "summary": summary}


# ---------------------------------------------------------------------------
# Sales channel + "Online Store" duplicate cancels (pure)
#
# The real, updated copy of an order arrives through an API app (the "web
# hook" channel); the Online Store copy of the same sale is stale. Every
# Online Store order that is not UNFULFILLED is cancelled — no twin is
# required, the web-hook copy is only looked up so the user can see it.
# ---------------------------------------------------------------------------

ONLINE_STORE = "Online Store"

# `sourceName` values Shopify uses for its own channels, when `app` is absent.
_SOURCE_NAME_CHANNELS = {"web": ONLINE_STORE, "pos": "Point of Sale",
                         "shopify_draft_order": "Draft Orders"}


def order_channel(app_name: Any, source_name: Any) -> Optional[str]:
    """The channel Shopify admin shows: the app that created the order, else
    its sourceName (mapped for Shopify's own channels, raw otherwise)."""
    app = (app_name or "").strip()
    if app:
        return app
    src = (source_name or "").strip()
    if not src:
        return None
    return _SOURCE_NAME_CHANNELS.get(src.lower(), src)


def is_online_store(channel: Any) -> bool:
    return (channel or "").strip().lower() == ONLINE_STORE.lower()


def _channel_flags(order: Dict[str, Any]) -> List[str]:
    flags: List[str] = []
    if float(order.get("net_payment") or 0) > 0.004:
        flags.append("paid")
    if float(order.get("refunded") or 0) > 0.004:
        flags.append("refunded")
    if dup_has_tracking(order):
        flags.append("has_tracking")
    if order.get("fulfillment_status") in ("FULFILLED", "PARTIALLY_FULFILLED"):
        flags.append("fulfilled")
    return flags


def _channel_copy_key(candidate: Dict[str, Any], order: Dict[str, Any]) -> Tuple[float, int, int]:
    return (abs(float(candidate.get("total") or 0) - float(order.get("total") or 0)),
            _dup_days_apart(candidate.get("local_date"), order.get("local_date")) or 0,
            _dup_legacy_id(candidate))


def plan_channel_cancels(pool: List[Dict[str, Any]], date_from: str, date_to: str,
                         busy_ids: Optional[set] = None) -> Dict[str, Any]:
    """
    Every Online Store order in `pool` placed in [date_from, date_to] that is
    neither cancelled nor UNFULFILLED, oldest first:
      proposed — cancel it
      blocked  — already cancelled or in flight by an earlier run (`busy_ids`)

    `copy` is the closest non-Online-Store order from the same customer
    within the duplicate tolerances (information only, never required).
    """
    busy_ids = busy_ids or set()
    live = [o for o in pool if o.get("id") and not o.get("cancelled")]
    by_customer: Dict[str, List[Dict[str, Any]]] = {}
    for o in live:
        if o.get("customer_gid") and not is_online_store(o.get("channel")):
            by_customer.setdefault(o["customer_gid"], []).append(o)

    targets = sorted(
        (o for o in live
         if is_online_store(o.get("channel"))
         and (o.get("fulfillment_status") or "") != "UNFULFILLED"
         and date_from <= (o.get("local_date") or "") <= date_to),
        key=lambda o: (o.get("created_at") or "", _dup_legacy_id(o)))

    rows: List[Dict[str, Any]] = []
    summary = {"targets": len(targets), "proposed": 0, "blocked": 0, "with_copy": 0}
    for order in targets:
        copies = [c for c in by_customer.get(order.get("customer_gid") or "", [])
                  if _dup_same_sale(order, c)]
        copy = min(copies, key=lambda c: _channel_copy_key(c, order)) if copies else None
        row: Dict[str, Any] = {
            "sh_order_id": order["id"], "sh_name": order.get("name"),
            "sh_date": order.get("local_date"),
            "sh_total": round(float(order.get("total") or 0), 2),
            "channel": order.get("channel"),
            "customer_gid": order.get("customer_gid"),
            "fulfillment_status": order.get("fulfillment_status"),
            "financial_status": order.get("financial_status"),
            "net_payment": round(float(order.get("net_payment") or 0), 2),
            "tracking": split_routes(order.get("tracking_numbers") or [])[0],
            "flags": _channel_flags(order),
            "copy": None, "total_delta": None, "date_delta_days": None,
            "status": "proposed", "reason": None,
        }
        if copy:
            row["copy"] = {**_dup_side(copy, 1 if dup_has_tracking(copy) else 2),
                           "channel": copy.get("channel"),
                           "fulfillment_status": copy.get("fulfillment_status")}
            row["total_delta"] = round(float(order.get("total") or 0) - float(copy.get("total") or 0), 2)
            row["date_delta_days"] = _dup_days_apart(order.get("local_date"), copy.get("local_date"))
            summary["with_copy"] += 1
        if order["id"] in busy_ids:
            row.update(status="blocked", reason="Already cancelled, or being cancelled, by an earlier run")
        summary[row["status"]] += 1
        rows.append(row)
    return {"rows": rows, "summary": summary}


def shutdown_order_sync_executor():
    _ordsync_executor.shutdown(wait=False)
