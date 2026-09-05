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
            key = line_key(upc, sku, desc)
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


def _line_keys(side: Dict[str, Any], shopify: bool) -> set:
    if shopify:
        return set(_shopify_lines_by_key(side))
    return {li["key"] for li in side.get("lines", [])}


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


def _line_jaccard(order: Dict[str, Any], invoice: Dict[str, Any]) -> float:
    ok = _line_keys(order, True)
    ik = _line_keys(invoice, False)
    union = len(ok | ik)
    return (len(ok & ik) / union) if union else 0.0


def _identity_plausible(order: Dict[str, Any], invoice: Dict[str, Any]) -> bool:
    # Invoice must be dated within a day of the order — a repeat customer's
    # invoice from another week is another order.
    try:
        placed = datetime.strptime(order["local_date"], "%Y-%m-%d")
        invoiced = datetime.strptime(invoice["date"], "%Y-%m-%d")
        if abs((invoiced - placed).days) > IDENTITY_MAX_DAY_LAG:
            return False
    except (KeyError, TypeError, ValueError):
        pass
    # Both sides carrying different real tracking numbers = different shipments.
    o_real = set(split_routes(order.get("tracking_numbers", []))[0])
    i_real = set(split_routes(split_tracking(invoice["tracking_no"]))[0])
    if o_real and i_real and not (o_real & i_real):
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
    street address+zip, then name+zip.

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

    for order in orders:
        if order["id"] in used_orders:
            continue
        if take(order, [normalize_phone(p) for p in order.get("phones", [])], by_phone, "phone"):
            continue
        if take(order, [normalize_address(order.get("address1"), order.get("zip"))], by_addr, "address"):
            continue
        take(order, [normalize_name_zip(order.get("customer_name"), order.get("zip"))], by_namezip, "name_zip")

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
                j = _line_jaccard(order, inv)
                total = order.get("total") or 0
                rel = abs(total - (inv.get("total") or 0)) / total if total else 1.0
                if j >= BASKET_MIN_OVERLAP or (j >= BASKET_MIN_OVERLAP_WITH_TOTAL and rel <= BASKET_TOTAL_TOL_PCT):
                    scored.append((-j, rel, order, inv))
    scored.sort(key=lambda t: (t[0], t[1]))
    for _, _, order, inv in scored:
        if order["id"] in used_orders or inv["invoice_id"] in used_invoices:
            continue
        emit([order], [inv], "products", False, shared_note.get(("o", order["id"])))

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
    agg: Dict[str, Dict[str, Any]] = {}
    for li in order.get("lines", []):
        barcode = (li.get("barcode") or "").strip()
        sku = (li.get("sku") or "").strip()
        key = line_key(barcode, sku, li.get("title"))
        line = agg.setdefault(key, {
            "key": key, "barcode": barcode, "sku": sku,
            "title": li.get("title") or "", "qty": 0.0,
            "amount": 0.0, "ordered": 0.0,
        })
        line["qty"] += float(li.get("current_quantity") or 0)
        line["amount"] += float(li.get("discounted_total") or 0)
        line["ordered"] += float(li.get("quantity") or 0)
    return agg


def _merge_orders(orders: List[Dict[str, Any]]) -> Dict[str, Any]:
    """A combined group behaves like one order: lines concatenated (the
    per-key aggregation sums them), totals summed."""
    if len(orders) == 1:
        return orders[0]
    return {
        "lines": [li for o in orders for li in o.get("lines", [])],
        "total": sum(o.get("total") or 0 for o in orders),
    }


def _merge_invoices(invoices: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(invoices) == 1:
        return invoices[0]
    agg: Dict[str, Dict[str, Any]] = {}
    for inv in invoices:
        for li in inv.get("lines", []):
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
    } for li in invoice.get("lines", [])]


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
        "combined": len(orders) > 1 or len(invoices) > 1,
        **_order_side(orders), **_invoice_side(invoices),
        "total_delta": total_delta, "issue_kinds": kinds, "line_diffs": diffs,
    }


def build_report(orders: List[Dict[str, Any]], invoices: List[Dict[str, Any]],
                 date_from: str, date_to: str) -> Dict[str, Any]:
    """Match, compare, and assemble rows + summary. Out-of-range invoices
    (fetched only as padding) may be consumed by matches but are dropped when
    unmatched; a matched pair is reported when either side is in range."""
    result = match_orders(orders, invoices)
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
    summary["shopify_no_tracking"] = sum(
        1 for o in orders if not o.get("tracking_numbers"))
    summary["backoffice_no_tracking"] = sum(
        1 for inv in invoices if inv["in_range"] and not inv["has_tracking"])

    rows.sort(key=lambda r: (r.get("sh_date") or (r.get("bo_date") or "")[:10] or ""), reverse=True)
    return {"summary": summary, "rows": rows}


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
# A key whose fix would be half-possible (e.g. refund OK but the re-add has
# no variant) is left untouched and reported as unsupported.

UNSUPPORTED_MESSAGES = {
    "no_barcode": "Line has no barcode — cannot be located in Shopify",
    "no_variant": "No Shopify variant carries this barcode",
    "not_refundable": "Not enough refundable units on the Shopify line",
}


def _raw_lines_by_key(order: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    by_key: Dict[str, List[Dict[str, Any]]] = {}
    for li in order.get("lines", []):
        by_key.setdefault(line_key(li.get("barcode"), li.get("sku"), li.get("title")), []).append(li)
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
                variants_by_barcode: Dict[str, Dict[str, Any]]
                ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    barcode = (diff.get("barcode") or "").strip()
    if not barcode:
        return None, "no_barcode"
    variant = variants_by_barcode.get(barcode)
    if not variant or not variant.get("variant_id"):
        return None, "no_variant"
    variant_price = float(variant.get("price") or 0)
    units = int(round(qty))
    if units <= 0:
        return None, None
    # Below the variant price → a line discount; above it → the variant price
    # is raised to the invoice price for the duration of the edit, then
    # restored (a discount can only lower a price).
    bump = variant_price + CENT_TOL < target_price
    discount_total = 0.0 if bump else round(max(variant_price - target_price, 0.0) * units, 2)
    return {
        "kind": "add", "reason": reason, "key": diff["key"],
        "barcode": barcode, "description": diff.get("description") or variant.get("product_title"),
        "qty": units, "unit_price": round(target_price, 2),
        "variant_id": variant["variant_id"], "product_id": variant.get("product_id"),
        "variant_price": round(variant_price, 2), "variant_price_raw": variant.get("price_raw"),
        "variant_title": variant.get("product_title"),
        "discount_total": discount_total if discount_total > CENT_TOL else 0.0,
        "bump_price": bump,
    }, None


def plan_order_fix(order: Dict[str, Any], invoice: Dict[str, Any],
                   variants_by_barcode: Dict[str, Dict[str, Any]],
                   push_tracking: bool = True) -> Dict[str, Any]:
    """Actions that bring the Shopify order's lines to the invoice's lines.
    Pure: `order` is a fetch_order_for_sync dict (line ids present),
    `variants_by_barcode` comes from find_variants_by_barcode."""
    _kinds, diffs = compare_lines(order, invoice)
    raw_by_key = _raw_lines_by_key(order)

    actions: List[Dict[str, Any]] = []
    unsupported: List[Dict[str, Any]] = []
    for d in diffs:
        issues = d.get("issues") or []
        if not issues:
            continue
        lines = raw_by_key.get(d["key"], [])
        sh_qty = d.get("sh_qty") or 0.0
        bo_qty = d.get("bo_qty") or 0.0
        bo_price = d.get("bo_unit_price") or 0.0
        planned: List[Tuple[Optional[Dict[str, Any]], Optional[str]]] = []

        if "missing_in_backoffice" in issues:
            planned.append(_refund_action("remove", d, lines, sh_qty))
        elif "missing_in_shopify" in issues:
            planned.append(_add_action("add", d, bo_qty, bo_price, variants_by_barcode))
        elif "price" in issues:
            planned.append(_refund_action("replace", d, lines, sh_qty))
            planned.append(_add_action("replace", d, bo_qty, bo_price, variants_by_barcode))
        elif "qty" in issues:
            if sh_qty > bo_qty:
                planned.append(_refund_action("reduce", d, lines, sh_qty - bo_qty))
            else:
                planned.append(_add_action("increase", d, bo_qty - sh_qty, bo_price, variants_by_barcode))

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
        actions.extend(a for a, _r in planned if a)

    if push_tracking:
        sh_real, _ = split_routes(order.get("tracking_numbers", []))
        bo_real, _ = split_routes(split_tracking(invoice.get("tracking_no")))
        targets = order.get("fulfillment_ids_without_tracking") or []
        if not sh_real and bo_real and targets:
            actions.append({"kind": "tracking", "reason": "tracking",
                            "numbers": bo_real, "fulfillment_ids": targets})

    refunds = [a for a in actions if a["kind"] == "refund"]
    adds = [a for a in actions if a["kind"] == "add"]
    return {
        "actions": actions,
        "unsupported": unsupported,
        "summary": {
            "refunds": len(refunds), "refund_units": sum(a["qty"] for a in refunds),
            "adds": len(adds), "add_units": sum(a["qty"] for a in adds),
            "add_amount": round(sum(a["qty"] * a["unit_price"] for a in adds), 2),
            "tracking": any(a["kind"] == "tracking" for a in actions),
            "unsupported": len(unsupported),
        },
        "noop": not actions,
    }


def shutdown_order_sync_executor():
    _ordsync_executor.shutdown(wait=False)
