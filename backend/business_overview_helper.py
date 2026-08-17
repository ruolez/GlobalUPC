"""
Business Overview helper.

Pure period/bucket math (no I/O) plus the MSSQL and Postgres-mirror queries
behind /api/business-overview/*. Every MSSQL worker follows the house shape:
sync function taking (host, port, database, username, password, ...) and
returning (ok, err, payload), wrapped by an async twin that runs it on the
module's own thread pool.

Conventions:
  - all date params are 'YYYY-MM-DD' strings; upper bounds are EXCLUSIVE
    (`< date_to_excl`, date_to_excl = date_to + 1 day)
  - `ISNULL(h.Void, 0) = 0` on every invoice header predicate
  - optional lookup tables (Employees_tbl, Shippers_tbl, Terms_tbl,
    Suppliers_tbl, CreditMemos*) are probed via INFORMATION_SCHEMA and joined
    only when present
  - daily series are queried over [prev_start, end_excl) so the previous
    period is served by the same round trip
"""
import asyncio
import calendar
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pyodbc
from sqlalchemy import text

from database import engine
from mssql_helper import get_mssql_connection_string

_bov_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="bov")

DEFAULT_LIST_LIMIT = 500
MAX_LIST_LIMIT = 5000
MAX_PARAMS = 2000
MAX_RANGE_DAYS = 400
MSSQL_TIMEOUT = 15

BUCKETS = ("day", "week", "month")
PRESETS = (
    "today", "yesterday", "this_week", "last_week", "this_month", "last_month",
    "last_7_days", "last_30_days", "last_90_days", "this_year",
)


# ============================================================================
# Pure date / period / bucket logic
# ============================================================================

def _f(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _fo(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _io(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return str(v)


def _s(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _bool(v: Any) -> bool:
    return bool(v) if v is not None else False


def parse_ymd(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def today_in_tz(tz_name: Optional[str]) -> date:
    try:
        tz = ZoneInfo(tz_name or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date()


def upper_bound(d: date) -> str:
    """Exclusive upper bound for an inclusive end date."""
    return (d + timedelta(days=1)).isoformat()


def _month_add(d: date, months: int) -> date:
    """First-of-month arithmetic (d must be day 1)."""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, 1)


def _month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def resolve_preset(preset: str, today: date) -> Tuple[date, date]:
    """Inclusive (start, end) for a preset. Weeks start Monday."""
    p = (preset or "").strip().lower()
    if p == "today":
        return today, today
    if p == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    if p == "this_week":
        return today - timedelta(days=today.weekday()), today
    if p == "last_week":
        this_mon = today - timedelta(days=today.weekday())
        return this_mon - timedelta(days=7), this_mon - timedelta(days=1)
    if p == "this_month":
        return today.replace(day=1), today
    if p == "last_month":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return last_prev.replace(day=1), last_prev
    if p == "last_7_days":
        return today - timedelta(days=6), today
    if p == "last_30_days":
        return today - timedelta(days=29), today
    if p == "last_90_days":
        return today - timedelta(days=89), today
    if p == "this_year":
        return date(today.year, 1, 1), today
    raise ValueError(f"Unknown preset '{preset}'")


def previous_period(start: date, end: date) -> Tuple[date, date]:
    """
    Comparison window: same length ending the day before `start`.
    Special case: whole calendar month(s) compare against the same number
    of whole months immediately before (so "last month" vs "the month before").
    """
    if start.day == 1 and end == _month_end(end) and end >= start:
        months = (end.year - start.year) * 12 + (end.month - start.month) + 1
        prev_start = _month_add(start, -months)
        prev_end = start - timedelta(days=1)
        return prev_start, prev_end
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)
    return prev_start, prev_end


@dataclass
class Period:
    start: date
    end: date
    prev_start: date
    prev_end: date
    preset: Optional[str] = None
    timezone: str = "UTC"
    today: Optional[date] = None

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def end_excl(self) -> str:
        return upper_bound(self.end)

    @property
    def prev_end_excl(self) -> str:
        return upper_bound(self.prev_end)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "prev_start": self.prev_start.isoformat(),
            "prev_end": self.prev_end.isoformat(),
            "days": self.days,
            "preset": self.preset,
            "timezone": self.timezone,
            "today": (self.today or self.start).isoformat(),
        }


def resolve_period(
    date_from: Optional[str],
    date_to: Optional[str],
    preset: Optional[str],
    tz_name: Optional[str],
    today: Optional[date] = None,
) -> Period:
    """
    Explicit dates win over `preset`; neither -> today. Raises ValueError on
    bad input, reversed range, or ranges longer than MAX_RANGE_DAYS.
    """
    tz_name = tz_name or "UTC"
    today = today or today_in_tz(tz_name)
    used_preset: Optional[str] = None
    if date_from or date_to:
        if not (date_from and date_to):
            raise ValueError("date_from and date_to must be given together")
        start = parse_ymd(date_from)
        end = parse_ymd(date_to)
    else:
        used_preset = (preset or "today").strip().lower()
        start, end = resolve_preset(used_preset, today)
    if end < start:
        raise ValueError("date_to must be on or after date_from")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise ValueError(f"Range too large (max {MAX_RANGE_DAYS} days)")
    prev_start, prev_end = previous_period(start, end)
    return Period(start=start, end=end, prev_start=prev_start, prev_end=prev_end,
                  preset=used_preset, timezone=tz_name, today=today)


def bucket_start(d: date, bucket: str) -> date:
    if bucket == "week":
        return d - timedelta(days=d.weekday())
    if bucket == "month":
        return d.replace(day=1)
    return d


def _bucket_next(k: date, bucket: str) -> date:
    if bucket == "week":
        return k + timedelta(days=7)
    if bucket == "month":
        return _month_add(k, 1)
    return k + timedelta(days=1)


def bucket_label(key: date, bucket: str) -> str:
    if bucket == "month":
        return key.strftime("%b %Y")
    if bucket == "week":
        return "Wk of " + key.strftime("%b %-d")
    return key.strftime("%b %-d")


def iter_buckets(start: date, end: date, bucket: str) -> List[Tuple[date, date, date]]:
    """[(bucket_key, clipped_start, clipped_end)] covering start..end inclusive."""
    if bucket not in BUCKETS:
        raise ValueError(f"Invalid bucket '{bucket}'")
    out: List[Tuple[date, date, date]] = []
    k = bucket_start(start, bucket)
    while k <= end:
        nxt = _bucket_next(k, bucket)
        cs = max(k, start)
        ce = min(nxt - timedelta(days=1), end)
        out.append((k, cs, ce))
        k = nxt
    return out


def rollup_daily(
    daily: Dict[date, Dict[str, float]],
    start: date,
    end: date,
    bucket: str,
    fields: List[str],
) -> List[Dict[str, Any]]:
    """Zero-filled series of {key,start,end,label,values{field: sum}} dicts."""
    out: List[Dict[str, Any]] = []
    for k, cs, ce in iter_buckets(start, end, bucket):
        vals = {f: 0.0 for f in fields}
        d = cs
        while d <= ce:
            row = daily.get(d)
            if row:
                for f in fields:
                    vals[f] += _f(row.get(f))
            d += timedelta(days=1)
        out.append({
            "key": k.isoformat(),
            "start": cs.isoformat(),
            "end": ce.isoformat(),
            "label": bucket_label(k, bucket),
            "values": vals,
        })
    return out


def sum_daily(daily: Dict[date, Dict[str, float]], start: date, end: date, fields: List[str]) -> Dict[str, float]:
    tot = {f: 0.0 for f in fields}
    for d, row in daily.items():
        if start <= d <= end:
            for f in fields:
                tot[f] += _f(row.get(f))
    return tot


def pct_change(cur: Optional[float], prev: Optional[float]) -> Optional[float]:
    if prev is None or cur is None:
        return None
    if prev == 0:
        return None
    return round((cur - prev) / abs(prev) * 100.0, 2)


def margin_pct(revenue: float, cost: float) -> Optional[float]:
    if not revenue:
        return None
    return round((revenue - cost) / revenue * 100.0, 2)


def range_totals(cur: Dict[str, float], prev: Dict[str, float]) -> Dict[str, Any]:
    keys = sorted(set(cur) | set(prev))
    return {
        "current": {k: round(_f(cur.get(k)), 2) for k in keys},
        "previous": {k: round(_f(prev.get(k)), 2) for k in keys},
        "change_pct": {k: pct_change(_f(cur.get(k)), _f(prev.get(k))) for k in keys},
    }


def aging_bucket(days: Optional[int]) -> Optional[str]:
    if days is None:
        return None
    if days <= 1:
        return "0-1"
    if days <= 3:
        return "2-3"
    return "4+"


# ============================================================================
# MSSQL shared bits
# ============================================================================

def _connect(host, port, database, username, password):
    return pyodbc.connect(
        get_mssql_connection_string(host, port, database, username, password),
        timeout=MSSQL_TIMEOUT,
    )


def _tables_present(cursor, names: List[str]) -> Dict[str, bool]:
    placeholders = ",".join(["?"] * len(names))
    cursor.execute(
        f"SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME IN ({placeholders})",
        names,
    )
    found = {row[0] for row in cursor.fetchall()}
    return {n: (n in found) for n in names}


def _invoice_joins(present: Dict[str, bool]) -> Dict[str, str]:
    j: Dict[str, str] = {}
    if present.get("Employees_tbl"):
        j["rep_join"] = "LEFT JOIN Employees_tbl e ON e.EmployeeID = h.SalesRepID AND h.SalesRepID <> 0"
        j["rep_expr"] = "e.FirstName"
        j["rep_agg_expr"] = "MAX(e.FirstName)"
    else:
        j["rep_join"] = ""
        j["rep_expr"] = "CAST(NULL AS nvarchar(50))"
        j["rep_agg_expr"] = "CAST(NULL AS nvarchar(50))"
    if present.get("Shippers_tbl"):
        j["shipper_join"] = "LEFT JOIN Shippers_tbl sh ON sh.ShipperID = h.ShipperID"
        j["shipper_expr"] = "sh.Shipper"
    else:
        j["shipper_join"] = ""
        j["shipper_expr"] = "CAST(NULL AS nvarchar(50))"
    if present.get("Terms_tbl"):
        j["term_join"] = "LEFT JOIN Terms_tbl t ON t.TermID = h.TermID"
        j["term_expr"] = "t.TermDescription"
    else:
        j["term_join"] = ""
        j["term_expr"] = "CAST(NULL AS nvarchar(50))"
    if present.get("Suppliers_tbl"):
        j["sup_join"] = "LEFT JOIN Suppliers_tbl s ON s.SupplierID = h.SupplierID"
        j["sup_contact_expr"] = "s.Contactname"
        j["sup_phone_expr"] = "s.Phone_Number"
    else:
        j["sup_join"] = ""
        j["sup_contact_expr"] = "CAST(NULL AS nvarchar(50))"
        j["sup_phone_expr"] = "CAST(NULL AS nvarchar(13))"
    return j


def _excl_clause(names: List[str], column: str = "h.BusinessName") -> Tuple[str, List[Any]]:
    """AND (col IS NULL OR col NOT IN (...)) — chunked at MAX_PARAMS."""
    clean = [n for n in (names or []) if n is not None and str(n).strip() != ""]
    if not clean:
        return "", []
    parts: List[str] = []
    params: List[Any] = []
    for i in range(0, len(clean), MAX_PARAMS):
        chunk = clean[i:i + MAX_PARAMS]
        parts.append(f"{column} NOT IN ({','.join(['?'] * len(chunk))})")
        params.extend(chunk)
    return f" AND ({column} IS NULL OR ({' AND '.join(parts)}))", params


def _rows(cursor) -> List[Dict[str, Any]]:
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, r)) for r in cursor.fetchall()]


def _sort_sql(whitelist: Dict[str, str], sort_by: Optional[str], default: str, sort_order: Optional[str], tiebreak: str = "") -> str:
    expr = whitelist.get((sort_by or "").strip(), whitelist[default])
    direction = "ASC" if (sort_order or "desc").lower() == "asc" else "DESC"
    return f"{expr} {direction}{tiebreak}"


def _clamp_limit(limit: Any) -> int:
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = DEFAULT_LIST_LIMIT
    return max(1, min(n, MAX_LIST_LIMIT))


# ============================================================================
# Quotations in progress (DB_ADMIN)
# ============================================================================

SORTABLE_QUOTATION_COLUMNS = {
    "start_date": "MIN(qip.StartDate)",
    "quotation_number": "qip.QuotationNumber",
    "business_name": "MAX(qs.BusinessName)",
    "sales_rep": "MAX(qs.SalesRep)",
    "quotation_total": "MAX(TRY_CONVERT(money, qs.QuotationTotal))",
    "total_qty": "MAX(qs.TotalQty)",
    "status": "COALESCE(MAX(qs.Status), MAX(qip.Status))",
    "packer": "MAX(qs.Packer)",
    "checker": "MAX(qs.Checker)",
    "last_update": "MAX(qs.LastUpdate)",
}


def _quotation_status_options_sync(host, port, database, username, password) -> Tuple[bool, Optional[str], List[str]]:
    try:
        with _connect(host, port, database, username, password) as conn:
            cur = conn.cursor()
            present = _tables_present(cur, ["QuotationsInProgress", "QuotationsStatus"])
            values: List[str] = []
            if present.get("QuotationsInProgress"):
                cur.execute(
                    "SELECT DISTINCT Status FROM QuotationsInProgress "
                    "WHERE Status IS NOT NULL AND LTRIM(RTRIM(Status)) <> ''"
                )
                values.extend(str(r[0]).strip() for r in cur.fetchall())
            if present.get("QuotationsStatus"):
                cur.execute(
                    "SELECT DISTINCT Status FROM QuotationsStatus "
                    "WHERE Status IS NOT NULL AND LTRIM(RTRIM(Status)) <> ''"
                )
                values.extend(str(r[0]).strip() for r in cur.fetchall())
        seen = set()
        out: List[str] = []
        for v in values:
            if v.lower() not in seen:
                seen.add(v.lower())
                out.append(v)
        return True, None, sorted(out, key=str.lower)
    except Exception as e:
        return False, str(e), []


def _quotations_in_progress_sync(
    host, port, database, username, password,
    statuses: List[str],
    limit: int = DEFAULT_LIST_LIMIT,
    sort_by: str = "start_date",
    sort_order: str = "desc",
    include_list: bool = True,
    source_dbs: Optional[List[str]] = None,
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    limit = _clamp_limit(limit)
    clean_statuses = [s.strip() for s in (statuses or []) if s and s.strip()]
    having_sql = ""
    having_params: List[Any] = []
    if clean_statuses:
        ph = ",".join(["?"] * len(clean_statuses))
        having_sql = f"HAVING (MAX(qs.Status) IN ({ph}) OR MAX(qip.Status) IN ({ph}))"
        having_params = clean_statuses + clean_statuses
    # Store filter: SourceDB holds the originating BackOffice database name.
    # A row predicate, so it belongs in WHERE (before the GROUP BY).
    where_sql = ""
    where_params: List[Any] = []
    clean_dbs = [d.strip().lower() for d in (source_dbs or []) if d and d.strip()]
    if source_dbs is not None:
        if not clean_dbs:
            where_sql = "WHERE 1 = 0"
        else:
            ph = ",".join(["?"] * len(clean_dbs))
            where_sql = f"WHERE LOWER(LTRIM(RTRIM(qip.SourceDB))) IN ({ph})"
            where_params = clean_dbs

    inner = f"""
        SELECT
            qip.QuotationNumber                             AS quotation_number,
            MAX(qip.SourceDB)                               AS source_db,
            COALESCE(MAX(qs.Status), MAX(qip.Status))       AS status,
            MAX(qs.UserStatus)                              AS user_status,
            MIN(qip.StartDate)                              AS start_date,
            MAX(qs.LastUpdate)                              AS last_update,
            MAX(qs.BusinessName)                            AS business_name,
            COALESCE(MAX(qs.AccountNo), MAX(qip.AccountNo)) AS account_no,
            MAX(qs.SalesRep)                                AS sales_rep,
            MAX(qip.SalesRepID)                             AS sales_rep_id,
            MAX(qs.Packer)                                  AS packer,
            MAX(qs.Checker)                                 AS checker,
            COUNT(*)                                        AS line_count,
            COALESCE(MAX(qs.TotalQty), SUM(ISNULL(qip.Qty, 0))) AS total_qty,
            MAX(TRY_CONVERT(money, qs.QuotationTotal))      AS quotation_total,
            MAX(qs.Dop2)                                    AS dop2,
            MAX(qs.Dop3)                                    AS dop3,
            MAX(qs.InvoiceNumber)                           AS invoice_number
        FROM QuotationsInProgress qip
        LEFT JOIN QuotationsStatus qs ON qs.QuotationNumber = qip.QuotationNumber
        {where_sql}
        GROUP BY qip.QuotationNumber
        {having_sql}
    """
    summary_sql = f"""
        SELECT status, COUNT(*) AS quotations, SUM(quotation_total) AS total_amount, SUM(total_qty) AS total_qty
        FROM ({inner}) x
        GROUP BY status
    """
    sort_expr = _sort_sql(SORTABLE_QUOTATION_COLUMNS, sort_by, "start_date", sort_order)
    list_sql = f"""
        SELECT TOP (?)
            qip.QuotationNumber                             AS quotation_number,
            MAX(qip.SourceDB)                               AS source_db,
            COALESCE(MAX(qs.Status), MAX(qip.Status))       AS status,
            MAX(qs.UserStatus)                              AS user_status,
            MIN(qip.StartDate)                              AS start_date,
            MAX(qs.LastUpdate)                              AS last_update,
            MAX(qs.BusinessName)                            AS business_name,
            COALESCE(MAX(qs.AccountNo), MAX(qip.AccountNo)) AS account_no,
            MAX(qs.SalesRep)                                AS sales_rep,
            MAX(qip.SalesRepID)                             AS sales_rep_id,
            MAX(qs.Packer)                                  AS packer,
            MAX(qs.Checker)                                 AS checker,
            COUNT(*)                                        AS line_count,
            COALESCE(MAX(qs.TotalQty), SUM(ISNULL(qip.Qty, 0))) AS total_qty,
            MAX(TRY_CONVERT(money, qs.QuotationTotal))      AS quotation_total,
            MAX(qs.Dop2)                                    AS dop2,
            MAX(qs.Dop3)                                    AS dop3,
            MAX(qs.InvoiceNumber)                           AS invoice_number
        FROM QuotationsInProgress qip
        LEFT JOIN QuotationsStatus qs ON qs.QuotationNumber = qip.QuotationNumber
        {where_sql}
        GROUP BY qip.QuotationNumber
        {having_sql}
        ORDER BY {sort_expr}
    """
    try:
        with _connect(host, port, database, username, password) as conn:
            cur = conn.cursor()
            present = _tables_present(cur, ["QuotationsInProgress", "QuotationsStatus"])
            missing = [t for t, ok in present.items() if not ok]
            if missing:
                return False, f"Table {', '.join(missing)} not found on this store", {}
            cur.execute(summary_sql, where_params + having_params)
            by_status: List[Dict[str, Any]] = []
            count = 0
            total_amount = 0.0
            total_qty = 0.0
            for r in _rows(cur):
                c = int(r.get("quotations") or 0)
                a = _f(r.get("total_amount"))
                q = _f(r.get("total_qty"))
                by_status.append({"status": _s(r.get("status")), "count": c,
                                  "total_amount": round(a, 2), "total_qty": q})
                count += c
                total_amount += a
                total_qty += q
            by_status.sort(key=lambda x: -x["count"])
            quotations: List[Dict[str, Any]] = []
            if include_list:
                cur.execute(list_sql, [limit] + where_params + having_params)
                for d in _rows(cur):
                    quotations.append({
                        "quotation_number": str(d.get("quotation_number")),
                        "source_db": _s(d.get("source_db")),
                        "status": _s(d.get("status")),
                        "user_status": _s(d.get("user_status")),
                        "start_date": _iso(d.get("start_date")),
                        "last_update": _iso(d.get("last_update")),
                        "business_name": _s(d.get("business_name")),
                        "account_no": _s(d.get("account_no")),
                        "sales_rep": _s(d.get("sales_rep")),
                        "sales_rep_id": _io(d.get("sales_rep_id")),
                        "packer": _s(d.get("packer")),
                        "checker": _s(d.get("checker")),
                        "line_count": int(d.get("line_count") or 0),
                        "total_qty": _f(d.get("total_qty")),
                        "quotation_total": _fo(d.get("quotation_total")),
                        "dop2": _s(d.get("dop2")),
                        "dop3": _s(d.get("dop3")),
                        "invoice_number": _s(d.get("invoice_number")),
                    })
        return True, None, {
            "quotations": quotations,
            "count": count,
            "total_amount": round(total_amount, 2),
            "total_qty": total_qty,
            "by_status": by_status,
            "statuses": clean_statuses,
            "source_dbs": (clean_dbs if source_dbs is not None else None),
            "limit": limit,
            "truncated": include_list and count > len(quotations),
        }
    except Exception as e:
        return False, str(e), {}


# ============================================================================
# Invoices (sales store)
# ============================================================================

SORTABLE_INVOICE_COLUMNS = {
    "invoice_date": "h.InvoiceDate",
    "invoice_number": "h.InvoiceNumber",
    "business_name": "h.BusinessName",
    "invoice_total": "h.InvoiceTotal",
    "ship_date": "COALESCE(h.ShipDate, h.InvoiceDate)",
    "sales_rep": "h.SalesRepID",
    "tot_qty": "h.TotQtyOrd",
    "no_lines": "h.NoLines",
}

_INVOICE_SELECT = """
    h.InvoiceID, h.InvoiceNumber, h.InvoiceDate, h.InvoiceType, h.CustomerID,
    h.BusinessName, h.AccountNo, h.PoNumber, h.ShipDate, h.ShipCity, h.ShipState,
    h.SalesRepID, {rep_expr} AS sales_rep,
    h.ShipperID,  {shipper_expr} AS shipper,
    h.TrackingNo,
    h.TotQtyOrd, h.TotQtyShp, h.NoLines, h.NoBoxes,
    h.InvoiceSubtotal, h.TotalTaxes, h.ShippingCost, h.InvoiceTotal, h.Notes
"""

_UNSHIPPED_WHERE = "ISNULL(h.Void, 0) = 0 AND (h.TrackingNo IS NULL OR LTRIM(RTRIM(h.TrackingNo)) = '')"
_SHIPPED_WHERE = "ISNULL(h.Void, 0) = 0 AND h.TrackingNo IS NOT NULL AND LTRIM(RTRIM(h.TrackingNo)) <> ''"


def _invoice_row(d: Dict[str, Any], today: Optional[date] = None) -> Dict[str, Any]:
    inv_date = d.get("InvoiceDate")
    age_days = None
    if today is not None and isinstance(inv_date, (datetime, date)):
        idate = inv_date.date() if isinstance(inv_date, datetime) else inv_date
        age_days = max(0, (today - idate).days)
    rep_id = _io(d.get("SalesRepID"))
    return {
        "invoice_id": int(d.get("InvoiceID")),
        "invoice_number": _s(d.get("InvoiceNumber")),
        "invoice_date": _iso(inv_date),
        "invoice_type": _s(d.get("InvoiceType")),
        "customer_id": _io(d.get("CustomerID")),
        "business_name": _s(d.get("BusinessName")),
        "account_no": _s(d.get("AccountNo")),
        "po_number": _s(d.get("PoNumber")),
        "ship_date": _iso(d.get("ShipDate")),
        "ship_city": _s(d.get("ShipCity")),
        "ship_state": _s(d.get("ShipState")),
        "sales_rep_id": rep_id,
        "sales_rep": _s(d.get("sales_rep")) if rep_id else None,
        "shipper_id": _io(d.get("ShipperID")),
        "shipper": _s(d.get("shipper")),
        "tracking_no": _s(d.get("TrackingNo")),
        "tot_qty_ord": _fo(d.get("TotQtyOrd")),
        "tot_qty_shp": _fo(d.get("TotQtyShp")),
        "no_lines": _io(d.get("NoLines")),
        "no_boxes": _io(d.get("NoBoxes")),
        "invoice_subtotal": _fo(d.get("InvoiceSubtotal")),
        "total_taxes": _fo(d.get("TotalTaxes")),
        "shipping_cost": _fo(d.get("ShippingCost")),
        "invoice_total": _fo(d.get("InvoiceTotal")),
        "notes": _s(d.get("Notes")),
        "age_days": age_days,
    }


def _open_invoices_sync(
    host, port, database, username, password,
    date_from: Optional[str] = None,
    date_to_excl: Optional[str] = None,
    limit: int = DEFAULT_LIST_LIMIT,
    sort_by: str = "invoice_date",
    sort_order: str = "desc",
    include_list: bool = True,
    today: Optional[date] = None,
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    limit = _clamp_limit(limit)
    today = today or date.today()
    where = _UNSHIPPED_WHERE
    params: List[Any] = []
    if date_from:
        where += " AND h.InvoiceDate >= ?"
        params.append(date_from)
    if date_to_excl:
        where += " AND h.InvoiceDate < ?"
        params.append(date_to_excl)
    try:
        with _connect(host, port, database, username, password) as conn:
            cur = conn.cursor()
            present = _tables_present(cur, ["Invoices_tbl", "Employees_tbl", "Shippers_tbl"])
            if not present.get("Invoices_tbl"):
                return False, "Table Invoices_tbl not found on this store", {}
            j = _invoice_joins(present)
            cur.execute(f"""
                SELECT COUNT(*) AS invoices, SUM(ISNULL(h.InvoiceTotal,0)) AS total_amount,
                       SUM(ISNULL(h.TotQtyOrd,0)) AS total_qty, MIN(h.InvoiceDate) AS oldest_invoice_date
                FROM Invoices_tbl h
                WHERE {where}
            """, params)
            agg = _rows(cur)[0]
            # Aging distribution (by InvoiceDate age)
            cur.execute(f"""
                SELECT CAST(h.InvoiceDate AS date) AS d, COUNT(*) AS n
                FROM Invoices_tbl h
                WHERE {where}
                GROUP BY CAST(h.InvoiceDate AS date)
            """, params)
            aging = {"0-1": 0, "2-3": 0, "4+": 0}
            for r in _rows(cur):
                d = r.get("d")
                if isinstance(d, datetime):
                    d = d.date()
                if isinstance(d, date):
                    b = aging_bucket(max(0, (today - d).days))
                    if b:
                        aging[b] += int(r.get("n") or 0)
            invoices: List[Dict[str, Any]] = []
            if include_list:
                sort_expr = _sort_sql(SORTABLE_INVOICE_COLUMNS, sort_by, "invoice_date", sort_order, ", h.InvoiceID DESC")
                cur.execute(f"""
                    SELECT TOP (?) {_INVOICE_SELECT.format(**j)}
                    FROM Invoices_tbl h
                    {j['rep_join']}
                    {j['shipper_join']}
                    WHERE {where}
                    ORDER BY {sort_expr}
                """, [limit] + params)
                invoices = [_invoice_row(d, today) for d in _rows(cur)]
        oldest = agg.get("oldest_invoice_date")
        oldest_age = None
        if isinstance(oldest, (datetime, date)):
            od = oldest.date() if isinstance(oldest, datetime) else oldest
            oldest_age = max(0, (today - od).days)
        count = int(agg.get("invoices") or 0)
        return True, None, {
            "invoices": invoices,
            "count": count,
            "total_amount": round(_f(agg.get("total_amount")), 2),
            "total_qty": _f(agg.get("total_qty")),
            "oldest_invoice_date": _iso(oldest),
            "oldest_age_days": oldest_age,
            "aging": aging,
            "limit": limit,
            "truncated": include_list and count > len(invoices),
        }
    except Exception as e:
        return False, str(e), {}


def _shipped_invoices_sync(
    host, port, database, username, password,
    date_from: str,
    date_to_excl: str,
    series_from: str,
    limit: int = DEFAULT_LIST_LIMIT,
    sort_by: str = "ship_date",
    sort_order: str = "desc",
    include_list: bool = True,
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """List = shipped in [date_from, date_to_excl); daily = [series_from, date_to_excl)."""
    limit = _clamp_limit(limit)
    try:
        with _connect(host, port, database, username, password) as conn:
            cur = conn.cursor()
            present = _tables_present(cur, ["Invoices_tbl", "Employees_tbl", "Shippers_tbl"])
            if not present.get("Invoices_tbl"):
                return False, "Table Invoices_tbl not found on this store", {}
            j = _invoice_joins(present)
            cur.execute(f"""
                SELECT CAST(COALESCE(h.ShipDate, h.InvoiceDate) AS date) AS d,
                       COUNT(*) AS invoices,
                       SUM(ISNULL(h.InvoiceTotal,0)) AS total_amount,
                       SUM(ISNULL(h.TotQtyShp,0))    AS total_qty,
                       SUM(ISNULL(h.NoBoxes,0))      AS boxes
                FROM Invoices_tbl h
                WHERE {_SHIPPED_WHERE}
                  AND COALESCE(h.ShipDate, h.InvoiceDate) >= ?
                  AND COALESCE(h.ShipDate, h.InvoiceDate) <  ?
                GROUP BY CAST(COALESCE(h.ShipDate, h.InvoiceDate) AS date)
                ORDER BY d
            """, [series_from, date_to_excl])
            daily: Dict[date, Dict[str, float]] = {}
            for r in _rows(cur):
                d = r.get("d")
                if isinstance(d, datetime):
                    d = d.date()
                if isinstance(d, date):
                    daily[d] = {
                        "invoices": _f(r.get("invoices")),
                        "total_amount": _f(r.get("total_amount")),
                        "total_qty": _f(r.get("total_qty")),
                        "boxes": _f(r.get("boxes")),
                    }
            invoices: List[Dict[str, Any]] = []
            if include_list:
                sort_expr = _sort_sql(SORTABLE_INVOICE_COLUMNS, sort_by, "ship_date", sort_order, ", h.InvoiceID DESC")
                cur.execute(f"""
                    SELECT TOP (?) {_INVOICE_SELECT.format(**j)}
                    FROM Invoices_tbl h
                    {j['rep_join']}
                    {j['shipper_join']}
                    WHERE {_SHIPPED_WHERE}
                      AND COALESCE(h.ShipDate, h.InvoiceDate) >= ?
                      AND COALESCE(h.ShipDate, h.InvoiceDate) <  ?
                    ORDER BY {sort_expr}
                """, [limit, date_from, date_to_excl])
                invoices = [_invoice_row(d) for d in _rows(cur)]
        return True, None, {"invoices": invoices, "daily": daily, "limit": limit}
    except Exception as e:
        return False, str(e), {}


def _invoice_detail_sync(host, port, database, username, password, invoice_id: int) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    try:
        with _connect(host, port, database, username, password) as conn:
            cur = conn.cursor()
            present = _tables_present(cur, ["Invoices_tbl", "InvoicesDetails_tbl", "Employees_tbl", "Shippers_tbl", "Terms_tbl"])
            if not present.get("Invoices_tbl"):
                return False, "Table Invoices_tbl not found on this store", {}
            j = _invoice_joins(present)
            cur.execute(f"""
                SELECT TOP 1
                    h.InvoiceID, h.InvoiceNumber, h.InvoiceDate, h.InvoiceType, h.InvoiceTitle,
                    h.CustomerID, h.BusinessName, h.AccountNo, h.PoNumber, h.ShipDate,
                    h.Shipto, h.ShipAddress1, h.ShipAddress2, h.ShipContact, h.ShipCity, h.ShipState,
                    h.ShipZipCode, h.ShipPhoneNo,
                    h.SalesRepID, {j['rep_expr']} AS sales_rep,
                    h.ShipperID,  {j['shipper_expr']} AS shipper,
                    h.TermID,     {j['term_expr']} AS term,
                    h.TrackingNo, h.ShippingCost, h.TotQtyOrd, h.TotQtyShp, h.TotQtyRtrnd,
                    h.NoLines, h.NoBoxes, h.TotalWeight, h.TotalDiscounts, h.InvoiceSubtotal,
                    h.TotalTaxes, h.OtherCharges, h.InvoiceTotal, h.TotalCredits, h.TotalPayments,
                    h.Notes, ISNULL(h.Void, 0) AS Void
                FROM Invoices_tbl h
                {j['rep_join']} {j['shipper_join']} {j['term_join']}
                WHERE h.InvoiceID = ?
            """, [int(invoice_id)])
            hrows = _rows(cur)
            if not hrows:
                return True, None, {"header": None, "lines": []}
            d = hrows[0]
            header = _invoice_row(d)
            header.update({
                "invoice_title": _s(d.get("InvoiceTitle")),
                "ship_to": _s(d.get("Shipto")),
                "ship_address1": _s(d.get("ShipAddress1")),
                "ship_address2": _s(d.get("ShipAddress2")),
                "ship_contact": _s(d.get("ShipContact")),
                "ship_zip_code": _s(d.get("ShipZipCode")),
                "ship_phone_no": _s(d.get("ShipPhoneNo")),
                "term_id": _io(d.get("TermID")),
                "term": _s(d.get("term")),
                "tot_qty_rtrnd": _fo(d.get("TotQtyRtrnd")),
                "total_weight": _fo(d.get("TotalWeight")),
                "total_discounts": _fo(d.get("TotalDiscounts")),
                "other_charges": _fo(d.get("OtherCharges")),
                "total_credits": _fo(d.get("TotalCredits")),
                "total_payments": _fo(d.get("TotalPayments")),
                "void": _bool(d.get("Void")),
                "is_shipped": bool(_s(d.get("TrackingNo"))),
            })
            lines: List[Dict[str, Any]] = []
            if present.get("InvoicesDetails_tbl"):
                cur.execute("""
                    SELECT d.LineID, d.ProductID, d.ProductSKU, d.ProductUPC, d.ProductDescription,
                           d.UnitDesc, d.UnitQty, d.QtyOrdered, d.QtyShipped, d.UnitPrice, d.UnitCost,
                           d.Discount, d.ds_Percent, d.ExtendedPrice, d.ExtendedCost, ISNULL(d.Void,0) AS Void
                    FROM InvoicesDetails_tbl d
                    WHERE d.InvoiceID = ?
                    ORDER BY d.LineID
                """, [int(invoice_id)])
                for r in _rows(cur):
                    qty = _f(r.get("QtyShipped"))
                    ucost = _fo(r.get("UnitCost"))
                    ext_price = _fo(r.get("ExtendedPrice"))
                    line_cost = qty * (ucost or 0.0)
                    line_profit = (ext_price - line_cost) if ext_price is not None else None
                    lines.append({
                        "line_id": int(r.get("LineID")),
                        "product_id": _io(r.get("ProductID")),
                        "product_sku": _s(r.get("ProductSKU")),
                        "product_upc": _s(r.get("ProductUPC")),
                        "product_description": _s(r.get("ProductDescription")),
                        "unit_desc": _s(r.get("UnitDesc")),
                        "unit_qty": _fo(r.get("UnitQty")),
                        "qty_ordered": _fo(r.get("QtyOrdered")),
                        "qty_shipped": _fo(r.get("QtyShipped")),
                        "unit_price": _fo(r.get("UnitPrice")),
                        "unit_cost": ucost,
                        "discount": _fo(r.get("Discount")),
                        "ds_percent": (bool(r.get("ds_Percent")) if r.get("ds_Percent") is not None else None),
                        "extended_price": ext_price,
                        "extended_cost": _fo(r.get("ExtendedCost")),
                        "line_cost": round(line_cost, 4),
                        "line_profit": (round(line_profit, 4) if line_profit is not None else None),
                        "margin_pct": margin_pct(ext_price or 0.0, line_cost) if ext_price else None,
                        "void": _bool(r.get("Void")),
                    })
            revenue = sum(_f(l["extended_price"]) for l in lines)
            cost = sum(_f(l["line_cost"]) for l in lines)
            header.update({
                "revenue": round(revenue, 2),
                "cost": round(cost, 2),
                "profit": round(revenue - cost, 2),
                "margin_pct": margin_pct(revenue, cost),
            })
        return True, None, {"header": header, "lines": lines}
    except Exception as e:
        return False, str(e), {}


# ============================================================================
# Purchase orders (purchases store)
# ============================================================================

SORTABLE_PO_COLUMNS = {
    "po_date": "h.PoDate",
    "po_number": "h.PoNumber",
    "business_name": "h.BusinessName",
    "po_total": "h.PoTotal",
    "qty_outstanding": "ISNULL(h.TotQtyOrd,0) - ISNULL(h.TotQtyRcv,0)",
    "required_date": "h.RequiredDate",
}

_INCOMING_WHERE = "h.Status = 0 AND ISNULL(h.TotQtyRcv, 0) < ISNULL(h.TotQtyOrd, 0)"
_OUTSTANDING_APPLY = """
    OUTER APPLY (
        SELECT SUM((ISNULL(d.QtyOrdered,0) - ISNULL(d.QtyReceived,0)) * ISNULL(d.UnitCost,0)) AS outstanding_value
        FROM PurchaseOrdersDetails_tbl d
        WHERE d.PoID = h.PoID AND ISNULL(d.QtyOrdered,0) > ISNULL(d.QtyReceived,0)
    ) ov
"""


def _po_row(d: Dict[str, Any]) -> Dict[str, Any]:
    ord_q = _fo(d.get("TotQtyOrd"))
    rcv_q = _fo(d.get("TotQtyRcv"))
    outstanding = d.get("qty_outstanding")
    if outstanding is None and (ord_q is not None or rcv_q is not None):
        outstanding = (ord_q or 0.0) - (rcv_q or 0.0)
    return {
        "po_id": int(d.get("PoID")),
        "po_number": _s(d.get("PoNumber")),
        "po_date": _iso(d.get("PoDate")),
        "required_date": _iso(d.get("RequiredDate")),
        "supplier_id": _io(d.get("SupplierID")),
        "business_name": _s(d.get("BusinessName")),
        "account_no": _s(d.get("AccountNo")),
        "status": _io(d.get("Status")),
        "po_total": _fo(d.get("PoTotal")),
        "no_lines": _io(d.get("NoLines")),
        "tot_qty_ord": ord_q,
        "tot_qty_rcv": rcv_q,
        "qty_outstanding": _fo(outstanding),
        "outstanding_value": _fo(d.get("outstanding_value")),
        "last_received": _iso(d.get("last_received")),
        "qty_received": _fo(d.get("qty_received")),
        "received_value": _fo(d.get("received_value")),
        "lines_received": _io(d.get("lines_received")),
    }


def _incoming_purchases_sync(
    host, port, database, username, password,
    limit: int = DEFAULT_LIST_LIMIT,
    sort_by: str = "po_date",
    sort_order: str = "desc",
    include_list: bool = True,
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    limit = _clamp_limit(limit)
    try:
        with _connect(host, port, database, username, password) as conn:
            cur = conn.cursor()
            present = _tables_present(cur, ["PurchaseOrders_tbl", "PurchaseOrdersDetails_tbl"])
            missing = [t for t, ok in present.items() if not ok]
            if missing:
                return False, f"Table {', '.join(missing)} not found on this store", {}
            cur.execute(f"""
                SELECT COUNT(*) AS purchase_orders, SUM(ISNULL(h.PoTotal,0)) AS po_total,
                       SUM(ISNULL(h.TotQtyOrd,0) - ISNULL(h.TotQtyRcv,0)) AS qty_outstanding,
                       MIN(h.PoDate) AS oldest_po_date,
                       SUM(ov.outstanding_value) AS outstanding_value
                FROM PurchaseOrders_tbl h
                {_OUTSTANDING_APPLY}
                WHERE {_INCOMING_WHERE}
            """)
            agg = _rows(cur)[0]
            pos: List[Dict[str, Any]] = []
            if include_list:
                sort_expr = _sort_sql(SORTABLE_PO_COLUMNS, sort_by, "po_date", sort_order, ", h.PoID DESC")
                cur.execute(f"""
                    SELECT TOP (?)
                        h.PoID, h.PoNumber, h.PoDate, h.RequiredDate, h.SupplierID, h.BusinessName, h.AccountNo,
                        h.Status, h.PoTotal, h.NoLines, h.TotQtyOrd, h.TotQtyRcv,
                        ISNULL(h.TotQtyOrd,0) - ISNULL(h.TotQtyRcv,0) AS qty_outstanding,
                        ov.outstanding_value
                    FROM PurchaseOrders_tbl h
                    {_OUTSTANDING_APPLY}
                    WHERE {_INCOMING_WHERE}
                    ORDER BY {sort_expr}
                """, [limit])
                pos = [_po_row(d) for d in _rows(cur)]
        count = int(agg.get("purchase_orders") or 0)
        return True, None, {
            "purchase_orders": pos,
            "count": count,
            "po_total": round(_f(agg.get("po_total")), 2),
            "outstanding_value": round(_f(agg.get("outstanding_value")), 2),
            "qty_outstanding": _f(agg.get("qty_outstanding")),
            "oldest_po_date": _iso(agg.get("oldest_po_date")),
            "limit": limit,
            "truncated": include_list and count > len(pos),
        }
    except Exception as e:
        return False, str(e), {}


def _purchased_in_range_sync(
    host, port, database, username, password,
    date_from: str,
    date_to_excl: str,
    series_from: str,
    limit: int = DEFAULT_LIST_LIMIT,
    sort_by: str = "po_date",
    sort_order: str = "desc",
    include_list: bool = True,
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    limit = _clamp_limit(limit)
    try:
        with _connect(host, port, database, username, password) as conn:
            cur = conn.cursor()
            present = _tables_present(cur, ["PurchaseOrders_tbl"])
            if not present.get("PurchaseOrders_tbl"):
                return False, "Table PurchaseOrders_tbl not found on this store", {}
            cur.execute("""
                SELECT CAST(h.PoDate AS date) AS d, COUNT(*) AS purchase_orders,
                       SUM(ISNULL(h.PoTotal,0)) AS total, SUM(ISNULL(h.TotQtyOrd,0)) AS qty
                FROM PurchaseOrders_tbl h
                WHERE h.PoDate >= ? AND h.PoDate < ?
                GROUP BY CAST(h.PoDate AS date) ORDER BY d
            """, [series_from, date_to_excl])
            daily: Dict[date, Dict[str, float]] = {}
            for r in _rows(cur):
                d = r.get("d")
                if isinstance(d, datetime):
                    d = d.date()
                if isinstance(d, date):
                    daily[d] = {"purchase_orders": _f(r.get("purchase_orders")),
                                "total": _f(r.get("total")), "qty": _f(r.get("qty"))}
            pos: List[Dict[str, Any]] = []
            if include_list:
                sort_expr = _sort_sql(SORTABLE_PO_COLUMNS, sort_by, "po_date", sort_order, ", h.PoID DESC")
                cur.execute(f"""
                    SELECT TOP (?)
                        h.PoID, h.PoNumber, h.PoDate, h.RequiredDate, h.SupplierID, h.BusinessName, h.AccountNo,
                        h.Status, h.PoTotal, h.NoLines, h.TotQtyOrd, h.TotQtyRcv,
                        ISNULL(h.TotQtyOrd,0) - ISNULL(h.TotQtyRcv,0) AS qty_outstanding
                    FROM PurchaseOrders_tbl h
                    WHERE h.PoDate >= ? AND h.PoDate < ?
                    ORDER BY {sort_expr}
                """, [limit, date_from, date_to_excl])
                pos = [_po_row(d) for d in _rows(cur)]
        return True, None, {"purchase_orders": pos, "daily": daily, "limit": limit}
    except Exception as e:
        return False, str(e), {}


def _received_in_range_sync(
    host, port, database, username, password,
    date_from: str,
    date_to_excl: str,
    series_from: str,
    limit: int = DEFAULT_LIST_LIMIT,
    include_list: bool = True,
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    limit = _clamp_limit(limit)
    try:
        with _connect(host, port, database, username, password) as conn:
            cur = conn.cursor()
            present = _tables_present(cur, ["PurchaseOrders_tbl", "PurchaseOrdersDetails_tbl"])
            missing = [t for t, ok in present.items() if not ok]
            if missing:
                return False, f"Table {', '.join(missing)} not found on this store", {}
            cur.execute("""
                SELECT CAST(d.DateReceived AS date) AS d, COUNT(DISTINCT d.PoID) AS purchase_orders,
                       SUM(ISNULL(d.QtyReceived,0)) AS qty,
                       SUM(ISNULL(d.QtyReceived,0) * ISNULL(d.UnitCost,0)) AS value
                FROM PurchaseOrdersDetails_tbl d
                WHERE d.DateReceived >= ? AND d.DateReceived < ? AND ISNULL(d.QtyReceived,0) > 0
                GROUP BY CAST(d.DateReceived AS date) ORDER BY d
            """, [series_from, date_to_excl])
            daily: Dict[date, Dict[str, float]] = {}
            for r in _rows(cur):
                d = r.get("d")
                if isinstance(d, datetime):
                    d = d.date()
                if isinstance(d, date):
                    daily[d] = {"purchase_orders": _f(r.get("purchase_orders")),
                                "qty": _f(r.get("qty")), "value": _f(r.get("value"))}
            pos: List[Dict[str, Any]] = []
            if include_list:
                cur.execute("""
                    SELECT TOP (?)
                        h.PoID, h.PoNumber, h.PoDate, h.RequiredDate, h.SupplierID, h.BusinessName, h.AccountNo,
                        h.Status, h.PoTotal, h.NoLines, h.TotQtyOrd, h.TotQtyRcv,
                        MAX(d.DateReceived)                                     AS last_received,
                        SUM(ISNULL(d.QtyReceived,0))                            AS qty_received,
                        SUM(ISNULL(d.QtyReceived,0) * ISNULL(d.UnitCost,0))     AS received_value,
                        COUNT(*)                                                AS lines_received
                    FROM PurchaseOrdersDetails_tbl d
                    INNER JOIN PurchaseOrders_tbl h ON h.PoID = d.PoID
                    WHERE d.DateReceived >= ? AND d.DateReceived < ?
                      AND ISNULL(d.QtyReceived, 0) > 0
                    GROUP BY h.PoID, h.PoNumber, h.PoDate, h.RequiredDate, h.SupplierID, h.BusinessName, h.AccountNo,
                             h.Status, h.PoTotal, h.NoLines, h.TotQtyOrd, h.TotQtyRcv
                    ORDER BY MAX(d.DateReceived) DESC, h.PoID DESC
                """, [limit, date_from, date_to_excl])
                pos = [_po_row(d) for d in _rows(cur)]
        return True, None, {"purchase_orders": pos, "daily": daily, "limit": limit}
    except Exception as e:
        return False, str(e), {}


def _purchase_order_detail_sync(host, port, database, username, password, po_id: int) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    try:
        with _connect(host, port, database, username, password) as conn:
            cur = conn.cursor()
            present = _tables_present(cur, ["PurchaseOrders_tbl", "PurchaseOrdersDetails_tbl", "Suppliers_tbl"])
            if not present.get("PurchaseOrders_tbl"):
                return False, "Table PurchaseOrders_tbl not found on this store", {}
            j = _invoice_joins(present)
            cur.execute(f"""
                SELECT TOP 1 h.PoID, h.PoNumber, h.PoDate, h.RequiredDate, h.PoTitle, h.SupplierID,
                       h.BusinessName, h.AccountNo, h.Status, h.Shipto, h.ShipAddress1, h.ShipAddress2,
                       h.ShipContact, h.ShipCity, h.ShipState, h.ShipZipCode, h.ShipPhoneNo,
                       h.EmployeeID, h.TermID, h.PoTotal, h.NoLines, h.ShipperID, h.TotQtyOrd, h.TotQtyRcv,
                       h.Notes, {j['sup_contact_expr']} AS supplier_contact, {j['sup_phone_expr']} AS supplier_phone
                FROM PurchaseOrders_tbl h
                {j['sup_join']}
                WHERE h.PoID = ?
            """, [int(po_id)])
            hrows = _rows(cur)
            if not hrows:
                return True, None, {"header": None, "lines": []}
            d = hrows[0]
            header = _po_row(d)
            header.update({
                "po_title": _s(d.get("PoTitle")),
                "ship_to": _s(d.get("Shipto")),
                "ship_address1": _s(d.get("ShipAddress1")),
                "ship_address2": _s(d.get("ShipAddress2")),
                "ship_contact": _s(d.get("ShipContact")),
                "ship_city": _s(d.get("ShipCity")),
                "ship_state": _s(d.get("ShipState")),
                "ship_zip_code": _s(d.get("ShipZipCode")),
                "ship_phone_no": _s(d.get("ShipPhoneNo")),
                "employee_id": _io(d.get("EmployeeID")),
                "term_id": _io(d.get("TermID")),
                "shipper_id": _io(d.get("ShipperID")),
                "notes": _s(d.get("Notes")),
                "supplier_contact": _s(d.get("supplier_contact")),
                "supplier_phone": _s(d.get("supplier_phone")),
                "is_received": (_io(d.get("Status")) == 1),
            })
            lines: List[Dict[str, Any]] = []
            outstanding_value = 0.0
            if present.get("PurchaseOrdersDetails_tbl"):
                cur.execute("""
                    SELECT d.LineID, d.ProductID, d.ProductSKU, d.ProductUPC, d.SupplierSKU, d.ProductDescription,
                           d.UnitDesc, d.UnitQty, d.QtyOrdered, d.QtyReceived, d.UnitCost, d.ExtendedCost, d.DateReceived
                    FROM PurchaseOrdersDetails_tbl d WHERE d.PoID = ? ORDER BY d.LineID
                """, [int(po_id)])
                for r in _rows(cur):
                    qo = _f(r.get("QtyOrdered"))
                    qr = _f(r.get("QtyReceived"))
                    outstanding = max(0.0, qo - qr)
                    outstanding_value += outstanding * _f(r.get("UnitCost"))
                    lines.append({
                        "line_id": int(r.get("LineID")),
                        "product_id": _io(r.get("ProductID")),
                        "product_sku": _s(r.get("ProductSKU")),
                        "product_upc": _s(r.get("ProductUPC")),
                        "supplier_sku": _s(r.get("SupplierSKU")),
                        "product_description": _s(r.get("ProductDescription")),
                        "unit_desc": _s(r.get("UnitDesc")),
                        "unit_qty": _fo(r.get("UnitQty")),
                        "qty_ordered": _fo(r.get("QtyOrdered")),
                        "qty_received": _fo(r.get("QtyReceived")),
                        "qty_outstanding": outstanding,
                        "unit_cost": _fo(r.get("UnitCost")),
                        "extended_cost": _fo(r.get("ExtendedCost")),
                        "date_received": _iso(r.get("DateReceived")),
                    })
            header["outstanding_value"] = round(outstanding_value, 2)
        return True, None, {"header": header, "lines": lines}
    except Exception as e:
        return False, str(e), {}


# ============================================================================
# BackOffice sales (revenue / cost / returns) and breakdown
# ============================================================================

def _backoffice_daily_sales_sync(
    host, port, database, username, password,
    date_from: str,
    date_to_excl: str,
    excluded_sales_names: Optional[List[str]] = None,
    excluded_return_names: Optional[List[str]] = None,
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    excl_sql, excl_params = _excl_clause(excluded_sales_names or [])
    ret_excl_sql, ret_excl_params = _excl_clause(excluded_return_names or [])
    try:
        with _connect(host, port, database, username, password) as conn:
            cur = conn.cursor()
            present = _tables_present(cur, ["Invoices_tbl", "InvoicesDetails_tbl", "CreditMemos_tbl", "CreditMemosDetails_tbl"])
            if not (present.get("Invoices_tbl") and present.get("InvoicesDetails_tbl")):
                return False, "Invoices_tbl / InvoicesDetails_tbl not found on this store", {}
            cur.execute(f"""
                SELECT CAST(h.InvoiceDate AS date)                          AS d,
                       COUNT(DISTINCT h.InvoiceID)                          AS invoices,
                       SUM(ISNULL(d.ExtendedPrice, 0))                      AS revenue,
                       SUM(ISNULL(d.QtyShipped, 0) * ISNULL(d.UnitCost, 0)) AS cost,
                       SUM(ISNULL(d.QtyShipped, 0))                         AS units
                FROM InvoicesDetails_tbl d
                INNER JOIN Invoices_tbl h ON h.InvoiceID = d.InvoiceID
                WHERE ISNULL(h.Void, 0) = 0
                  AND h.InvoiceDate >= ?
                  AND h.InvoiceDate <  ?
                  {excl_sql}
                GROUP BY CAST(h.InvoiceDate AS date)
                ORDER BY d
            """, [date_from, date_to_excl] + excl_params)
            days: Dict[date, Dict[str, float]] = {}
            for r in _rows(cur):
                d = r.get("d")
                if isinstance(d, datetime):
                    d = d.date()
                if isinstance(d, date):
                    days[d] = {"invoices": _f(r.get("invoices")), "revenue": _f(r.get("revenue")),
                               "cost": _f(r.get("cost")), "units": _f(r.get("units"))}
            returns: Dict[date, Dict[str, float]] = {}
            has_cm = bool(present.get("CreditMemos_tbl") and present.get("CreditMemosDetails_tbl"))
            if has_cm:
                cur.execute(f"""
                    SELECT CAST(h.CmemoDate AS date)      AS d,
                           COUNT(DISTINCT h.CmemoID)      AS credit_memos,
                           SUM(ISNULL(d.ExtendedPrice,0)) AS amount,
                           SUM(ISNULL(d.Quantity,0))      AS units
                    FROM CreditMemosDetails_tbl d
                    INNER JOIN CreditMemos_tbl h ON h.CmemoID = d.CmemoID
                    WHERE h.CmemoDate >= ? AND h.CmemoDate < ?
                      {ret_excl_sql}
                    GROUP BY CAST(h.CmemoDate AS date)
                    ORDER BY d
                """, [date_from, date_to_excl] + ret_excl_params)
                for r in _rows(cur):
                    d = r.get("d")
                    if isinstance(d, datetime):
                        d = d.date()
                    if isinstance(d, date):
                        returns[d] = {"credit_memos": _f(r.get("credit_memos")),
                                      "amount": _f(r.get("amount")), "units": _f(r.get("units"))}
        return True, None, {"days": days, "returns": returns, "has_credit_memos": has_cm}
    except Exception as e:
        return False, str(e), {}


def _backoffice_breakdown_sync(
    host, port, database, username, password,
    date_from: str,
    date_to_excl: str,
    by: str = "customer",
    limit: int = 10,
    excluded_sales_names: Optional[List[str]] = None,
) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    excl_sql, excl_params = _excl_clause(excluded_sales_names or [])
    limit = max(1, min(int(limit or 10), 200))
    try:
        with _connect(host, port, database, username, password) as conn:
            cur = conn.cursor()
            present = _tables_present(cur, ["Invoices_tbl", "InvoicesDetails_tbl", "Employees_tbl"])
            if not (present.get("Invoices_tbl") and present.get("InvoicesDetails_tbl")):
                return False, "Invoices_tbl / InvoicesDetails_tbl not found on this store", []
            j = _invoice_joins(present)
            base_where = f"ISNULL(h.Void,0)=0 AND h.InvoiceDate >= ? AND h.InvoiceDate < ? {excl_sql}"
            params = [limit, date_from, date_to_excl] + excl_params
            if by == "rep":
                sql = f"""
                    SELECT TOP (?) h.SalesRepID AS k, {j['rep_agg_expr']} AS name, CAST(NULL AS nvarchar(20)) AS secondary,
                           COUNT(DISTINCT h.InvoiceID) AS orders,
                           SUM(ISNULL(d.ExtendedPrice,0)) AS revenue,
                           SUM(ISNULL(d.QtyShipped,0)*ISNULL(d.UnitCost,0)) AS cost,
                           SUM(ISNULL(d.QtyShipped,0)) AS units
                    FROM InvoicesDetails_tbl d INNER JOIN Invoices_tbl h ON h.InvoiceID = d.InvoiceID
                    {j['rep_join']}
                    WHERE {base_where}
                    GROUP BY h.SalesRepID
                    ORDER BY revenue DESC
                """
            elif by == "product":
                sql = f"""
                    SELECT TOP (?) d.ProductUPC AS k, MAX(d.ProductDescription) AS name, MAX(d.ProductSKU) AS secondary,
                           COUNT(DISTINCT h.InvoiceID) AS orders,
                           SUM(ISNULL(d.ExtendedPrice,0)) AS revenue,
                           SUM(ISNULL(d.QtyShipped,0)*ISNULL(d.UnitCost,0)) AS cost,
                           SUM(ISNULL(d.QtyShipped,0)) AS units
                    FROM InvoicesDetails_tbl d INNER JOIN Invoices_tbl h ON h.InvoiceID = d.InvoiceID
                    WHERE {base_where}
                    GROUP BY d.ProductUPC
                    ORDER BY revenue DESC
                """
            else:
                sql = f"""
                    SELECT TOP (?) h.BusinessName AS k, h.BusinessName AS name, MAX(h.AccountNo) AS secondary,
                           COUNT(DISTINCT h.InvoiceID) AS orders,
                           SUM(ISNULL(d.ExtendedPrice,0)) AS revenue,
                           SUM(ISNULL(d.QtyShipped,0)*ISNULL(d.UnitCost,0)) AS cost,
                           SUM(ISNULL(d.QtyShipped,0)) AS units
                    FROM InvoicesDetails_tbl d INNER JOIN Invoices_tbl h ON h.InvoiceID = d.InvoiceID
                    WHERE {base_where}
                    GROUP BY h.BusinessName
                    ORDER BY revenue DESC
                """
            cur.execute(sql, params)
            rows: List[Dict[str, Any]] = []
            for r in _rows(cur):
                rev = _f(r.get("revenue"))
                cost = _f(r.get("cost"))
                k = r.get("k")
                name = _s(r.get("name"))
                if by == "rep" and (k is None or int(k or 0) == 0):
                    name = None
                rows.append({
                    "key": (str(k).strip() if k is not None else None),
                    "name": name,
                    "secondary": _s(r.get("secondary")),
                    "orders": int(r.get("orders") or 0),
                    "revenue": round(rev, 2),
                    "cost": round(cost, 2),
                    "profit": round(rev - cost, 2),
                    "margin_pct": margin_pct(rev, cost),
                    "units": _f(r.get("units")),
                    "share_pct": None,
                })
        return True, None, rows
    except Exception as e:
        return False, str(e), []


def compute_backoffice_series(payload: Dict[str, Any], period: Period, bucket: str) -> Dict[str, Any]:
    """Roll daily BackOffice payload into current/previous bucket lists + totals."""
    days: Dict[date, Dict[str, float]] = payload.get("days") or {}
    returns: Dict[date, Dict[str, float]] = payload.get("returns") or {}
    fields = ["invoices", "revenue", "cost", "units"]

    def _series(start: date, end: date) -> List[Dict[str, Any]]:
        cur = rollup_daily(days, start, end, bucket, fields)
        ret = rollup_daily(returns, start, end, bucket, ["credit_memos", "amount", "units"])
        out: List[Dict[str, Any]] = []
        for c, r in zip(cur, ret):
            v = c["values"]
            rev = v["revenue"]
            cost = v["cost"]
            out.append({
                "key": c["key"], "start": c["start"], "end": c["end"], "label": c["label"],
                "totals": _totals_dict(rev, cost, r["values"]["amount"], int(v["invoices"]), v["units"], 1.0),
            })
        return out

    def _tot(start: date, end: date) -> Dict[str, Any]:
        s = sum_daily(days, start, end, fields)
        r = sum_daily(returns, start, end, ["amount"])
        return _totals_dict(s["revenue"], s["cost"], r["amount"], int(s["invoices"]), s["units"], 1.0)

    return {
        "current": _series(period.start, period.end),
        "previous": _series(period.prev_start, period.prev_end),
        "totals": _tot(period.start, period.end),
        "previous_totals": _tot(period.prev_start, period.prev_end),
    }


def _totals_dict(revenue: float, cost: float, returns: float, orders: int, units: float,
                 cost_coverage: Optional[float] = None) -> Dict[str, Any]:
    revenue = _f(revenue)
    cost = _f(cost)
    returns = _f(returns)
    # cost_coverage == 0 means units were sold but no cost could be resolved:
    # report margin as unknown rather than a misleading 100%.
    unknown_cost = (cost_coverage is not None and cost_coverage == 0 and _f(units) > 0)
    return {
        "revenue": round(revenue, 2),
        "cost": round(cost, 2),
        "profit": round(revenue - cost, 2),
        "margin_pct": (None if unknown_cost else margin_pct(revenue, cost)),
        "returns": round(returns, 2),
        "net_revenue": round(revenue - returns, 2),
        "orders": int(orders or 0),
        "units": round(_f(units), 2),
        "cost_coverage": cost_coverage,
    }


def empty_totals() -> Dict[str, Any]:
    return _totals_dict(0.0, 0.0, 0.0, 0, 0.0)


def add_totals(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Sum two totals dicts, recomputing derived fields."""
    revenue = _f(a.get("revenue")) + _f(b.get("revenue"))
    cost = _f(a.get("cost")) + _f(b.get("cost"))
    returns = _f(a.get("returns")) + _f(b.get("returns"))
    orders = int(a.get("orders") or 0) + int(b.get("orders") or 0)
    units = _f(a.get("units")) + _f(b.get("units"))
    cov_a, cov_b = a.get("cost_coverage"), b.get("cost_coverage")
    ua, ub = _f(a.get("units")), _f(b.get("units"))
    cov = None
    if cov_a is not None or cov_b is not None:
        known = (cov_a or 0.0) * ua + (cov_b or 0.0) * ub if (ua + ub) else 0.0
        cov = round(known / (ua + ub), 4) if (ua + ub) else None
    return _totals_dict(revenue, cost, returns, orders, units, cov)


def totals_change(cur: Dict[str, Any], prev: Dict[str, Any]) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {}
    for k in ("revenue", "cost", "profit", "orders", "units", "returns", "net_revenue"):
        out[k] = pct_change(_f(cur.get(k)), _f(prev.get(k)))
    mc, mp = cur.get("margin_pct"), prev.get("margin_pct")
    out["margin_pct"] = (round(mc - mp, 2) if (mc is not None and mp is not None) else None)  # points, not %
    return out


# ============================================================================
# Shopify mirror (Postgres)
# ============================================================================

_SHOPIFY_COMPLETED = "o.cancelled_at IS NULL AND o.financial_status IS DISTINCT FROM 'REFUNDED'"


def _safe_tz(tz: Optional[str]) -> str:
    try:
        ZoneInfo(tz or "UTC")
        return tz or "UTC"
    except Exception:
        return "UTC"


def _check_bucket(bucket: str) -> str:
    if bucket not in BUCKETS:
        raise ValueError(f"Invalid bucket '{bucket}'")
    return bucket


def _shopify_bucketed_orders_sync(store_id: int, tz: str, date_from: str, date_to_excl: str, bucket: str) -> Dict[date, Dict[str, float]]:
    bucket = _check_bucket(bucket)
    tz = _safe_tz(tz)
    sql = f"""
        SELECT date_trunc('{bucket}', o.created_at AT TIME ZONE :tz)::date AS b,
               COUNT(*)                                             AS orders,
               SUM(COALESCE(o.subtotal_price, 0))                   AS revenue,
               SUM(COALESCE(o.total_refunded, 0))                   AS refunded,
               SUM(COALESCE(o.total_shipping, 0))                   AS shipping,
               SUM(COALESCE(o.total_discounts, 0))                  AS discounts,
               SUM(COALESCE(o.total_price, 0))                      AS gross_total
        FROM shopify_orders o
        WHERE o.store_id = :sid
          AND {_SHOPIFY_COMPLETED}
          AND o.created_at >= (CAST(:start AS date)::timestamp AT TIME ZONE :tz)
          AND o.created_at <  (CAST(:end_excl AS date)::timestamp AT TIME ZONE :tz)
        GROUP BY 1 ORDER BY 1
    """
    out: Dict[date, Dict[str, float]] = {}
    with engine.connect() as conn:
        rows = conn.execute(text(sql), {"sid": store_id, "tz": tz, "start": date_from, "end_excl": date_to_excl}).mappings().all()
    for r in rows:
        b = r["b"]
        if isinstance(b, datetime):
            b = b.date()
        out[b] = {"orders": _f(r["orders"]), "revenue": _f(r["revenue"]), "refunded": _f(r["refunded"]),
                  "shipping": _f(r["shipping"]), "discounts": _f(r["discounts"]), "gross_total": _f(r["gross_total"])}
    return out


def _shopify_bucketed_line_items_sync(store_id: int, tz: str, date_from: str, date_to_excl: str, bucket: str) -> List[Tuple[date, Optional[str], float, float]]:
    bucket = _check_bucket(bucket)
    tz = _safe_tz(tz)
    sql = f"""
        SELECT date_trunc('{bucket}', o.created_at AT TIME ZONE :tz)::date AS b,
               NULLIF(BTRIM(li.barcode), '')                        AS barcode,
               SUM(COALESCE(li.current_quantity, li.quantity, 0))   AS units,
               SUM(COALESCE(li.discounted_total, 0))                AS line_revenue
        FROM shopify_orders o
        JOIN shopify_order_line_items li
          ON li.store_id = o.store_id AND li.order_shopify_id = o.shopify_id
        WHERE o.store_id = :sid
          AND {_SHOPIFY_COMPLETED}
          AND o.created_at >= (CAST(:start AS date)::timestamp AT TIME ZONE :tz)
          AND o.created_at <  (CAST(:end_excl AS date)::timestamp AT TIME ZONE :tz)
        GROUP BY 1, 2
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql), {"sid": store_id, "tz": tz, "start": date_from, "end_excl": date_to_excl}).mappings().all()
    out: List[Tuple[date, Optional[str], float, float]] = []
    for r in rows:
        b = r["b"]
        if isinstance(b, datetime):
            b = b.date()
        out.append((b, r["barcode"], _f(r["units"]), _f(r["line_revenue"])))
    return out


_SHOPIFY_UNFULFILLED = ("'UNFULFILLED','PARTIALLY_FULFILLED','IN_PROGRESS','ON_HOLD',"
                        "'SCHEDULED','PENDING_FULFILLMENT','OPEN'")


def _shopify_period_orders_sync(store_id: int, tz: str, date_from: str, date_to_excl: str) -> Dict[str, float]:
    """
    Order-flow counts for one store over [date_from, date_to_excl) in the shop's
    calendar: placed (non-cancelled), revenue, cancelled, still-unfulfilled among
    those placed, and orders whose first fulfillment happened in the period.
    """
    tz = _safe_tz(tz)
    with engine.connect() as conn:
        placed = conn.execute(text(f"""
            SELECT COUNT(*) FILTER (WHERE o.cancelled_at IS NULL)                                   AS orders,
                   COALESCE(SUM(o.subtotal_price) FILTER (WHERE o.cancelled_at IS NULL), 0)         AS revenue,
                   COUNT(*) FILTER (WHERE o.cancelled_at IS NOT NULL)                               AS cancelled,
                   COUNT(*) FILTER (WHERE o.cancelled_at IS NULL
                                      AND o.fulfillment_status IN ({_SHOPIFY_UNFULFILLED}))         AS unfulfilled_from_period,
                   COUNT(*) FILTER (WHERE o.cancelled_at IS NULL
                                      AND o.fulfillment_status = 'FULFILLED')                       AS fulfilled_from_period,
                   COUNT(*) FILTER (WHERE o.cancelled_at IS NULL
                                      AND o.fulfillment_status IN ('ON_HOLD'))                      AS on_hold_from_period
            FROM shopify_orders o
            WHERE o.store_id = :sid
              AND o.created_at >= (CAST(:start AS date)::timestamp AT TIME ZONE :tz)
              AND o.created_at <  (CAST(:end_excl AS date)::timestamp AT TIME ZONE :tz)
        """), {"sid": store_id, "start": date_from, "end_excl": date_to_excl, "tz": tz}).mappings().first()
        fulfilled = conn.execute(text("""
            SELECT COUNT(*) AS fulfilled_in_period
            FROM shopify_orders o
            WHERE o.store_id = :sid
              AND o.cancelled_at IS NULL
              AND o.fulfilled_at IS NOT NULL
              AND o.fulfilled_at >= (CAST(:start AS date)::timestamp AT TIME ZONE :tz)
              AND o.fulfilled_at <  (CAST(:end_excl AS date)::timestamp AT TIME ZONE :tz)
        """), {"sid": store_id, "start": date_from, "end_excl": date_to_excl, "tz": tz}).mappings().first()
    return {
        "orders": int(placed["orders"] or 0),
        "revenue": round(_f(placed["revenue"]), 2),
        "cancelled": int(placed["cancelled"] or 0),
        "unfulfilled_from_period": int(placed["unfulfilled_from_period"] or 0),
        "fulfilled_from_period": int(placed["fulfilled_from_period"] or 0),
        "on_hold_from_period": int(placed["on_hold_from_period"] or 0),
        "fulfilled_in_period": int(fulfilled["fulfilled_in_period"] or 0),
    }


async def shopify_period_orders(store_id: int, tz: str, date_from: str, date_to_excl: str) -> Dict[str, float]:
    return await asyncio.to_thread(_shopify_period_orders_sync, store_id, tz, date_from, date_to_excl)


def _shopify_open_orders_local_sync(store_id: int) -> Dict[str, float]:
    sql = """
        SELECT COUNT(*) AS open_orders, COALESCE(SUM(o.total_price),0) AS open_value
        FROM shopify_orders o
        WHERE o.store_id = :sid
          AND o.cancelled_at IS NULL AND o.closed_at IS NULL
          AND o.fulfillment_status IN ('UNFULFILLED','PARTIALLY_FULFILLED','IN_PROGRESS',
                                       'ON_HOLD','SCHEDULED','PENDING_FULFILLMENT','OPEN')
    """
    with engine.connect() as conn:
        r = conn.execute(text(sql), {"sid": store_id}).mappings().first()
    return {"open_orders": _f(r["open_orders"]) if r else 0.0, "open_value": _f(r["open_value"]) if r else 0.0}


def _shopify_top_products_sync(store_id: int, tz: str, date_from: str, date_to_excl: str, limit: int = 10) -> List[Dict[str, Any]]:
    tz = _safe_tz(tz)
    sql = f"""
        SELECT NULLIF(BTRIM(li.barcode),'') AS upc, MAX(li.sku) AS sku,
               MAX(COALESCE(li.product_title, li.title)) AS name,
               COUNT(DISTINCT o.shopify_id) AS orders,
               SUM(COALESCE(li.discounted_total,0)) AS revenue,
               SUM(COALESCE(li.current_quantity, li.quantity, 0)) AS units
        FROM shopify_orders o
        JOIN shopify_order_line_items li ON li.store_id = o.store_id AND li.order_shopify_id = o.shopify_id
        WHERE o.store_id = :sid AND {_SHOPIFY_COMPLETED}
          AND o.created_at >= (CAST(:start AS date)::timestamp AT TIME ZONE :tz)
          AND o.created_at <  (CAST(:end_excl AS date)::timestamp AT TIME ZONE :tz)
        GROUP BY 1 ORDER BY revenue DESC LIMIT :limit
    """
    with engine.connect() as conn:
        rows = conn.execute(text(sql), {"sid": store_id, "tz": tz, "start": date_from,
                                        "end_excl": date_to_excl, "limit": int(limit)}).mappings().all()
    return [{"key": r["upc"], "name": r["name"], "secondary": r["sku"], "orders": int(r["orders"] or 0),
             "revenue": round(_f(r["revenue"]), 2), "units": _f(r["units"])} for r in rows]


async def compute_shopify_series(
    store: Dict[str, Any],
    tz: str,
    period: Period,
    bucket: str,
    cost_lookup: Callable[[List[str]], Any],
) -> Dict[str, Any]:
    """
    Per-store Shopify buckets for the current and previous ranges. Cost via
    `cost_lookup(barcodes) -> {barcode: unit_cost}` (async, memoised by caller).
    Returns {"current": [...], "previous": [...], "totals": {...}, "previous_totals": {...}}.
    """
    sid = int(store["id"])
    tz = _safe_tz(tz)

    async def _range(start: date, end: date) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        s, e_excl = start.isoformat(), upper_bound(end)
        orders_by_b, lines = await asyncio.gather(
            asyncio.to_thread(_shopify_bucketed_orders_sync, sid, tz, s, e_excl, bucket),
            asyncio.to_thread(_shopify_bucketed_line_items_sync, sid, tz, s, e_excl, bucket),
        )
        barcodes = sorted({b for (_, b, _, _) in lines if b})
        costs: Dict[str, float] = {}
        if barcodes:
            try:
                costs = await cost_lookup(barcodes) or {}
            except Exception:
                costs = {}
        # cost + coverage per bucket
        cost_by_b: Dict[date, float] = {}
        units_by_b: Dict[date, float] = {}
        known_by_b: Dict[date, float] = {}
        for (b, bc, units, _rev) in lines:
            units_by_b[b] = units_by_b.get(b, 0.0) + units
            c = costs.get(bc) if bc else None
            if c is not None:
                cost_by_b[b] = cost_by_b.get(b, 0.0) + units * _f(c)
                known_by_b[b] = known_by_b.get(b, 0.0) + units
        out: List[Dict[str, Any]] = []
        agg_rev = agg_cost = agg_ret = agg_units = agg_known = 0.0
        agg_orders = 0
        for k, cs, ce in iter_buckets(start, end, bucket):
            o = orders_by_b.get(k) or {}
            rev = _f(o.get("revenue"))
            ret = _f(o.get("refunded"))
            orders = int(_f(o.get("orders")))
            cost = cost_by_b.get(k, 0.0)
            units = units_by_b.get(k, 0.0)
            known = known_by_b.get(k, 0.0)
            cov = (round(known / units, 4) if units else None)
            out.append({"key": k.isoformat(), "start": cs.isoformat(), "end": ce.isoformat(),
                        "label": bucket_label(k, bucket),
                        "totals": _totals_dict(rev, cost, ret, orders, units, cov)})
            agg_rev += rev; agg_cost += cost; agg_ret += ret; agg_units += units; agg_known += known; agg_orders += orders
        cov_all = (round(agg_known / agg_units, 4) if agg_units else None)
        return out, _totals_dict(agg_rev, agg_cost, agg_ret, agg_orders, agg_units, cov_all)

    (cur, cur_tot), (prev, prev_tot) = await asyncio.gather(
        _range(period.start, period.end),
        _range(period.prev_start, period.prev_end),
    )
    return {"current": cur, "previous": prev, "totals": cur_tot, "previous_totals": prev_tot}


def merge_bucket_lists(lists: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Element-wise sum of aligned per-store bucket lists (same keys)."""
    if not lists:
        return []
    base = [dict(b, totals=dict(b["totals"])) for b in lists[0]]
    for other in lists[1:]:
        for i, b in enumerate(other):
            if i < len(base):
                base[i]["totals"] = add_totals(base[i]["totals"], b["totals"])
    return base


# ============================================================================
# Async wrappers
# ============================================================================

def _run(fn, **kw):
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(_bov_executor, lambda: fn(**kw))


async def quotation_status_options_async(**kw):
    return await _run(_quotation_status_options_sync, **kw)


async def quotations_in_progress_async(**kw):
    return await _run(_quotations_in_progress_sync, **kw)


async def open_invoices_async(**kw):
    return await _run(_open_invoices_sync, **kw)


async def shipped_invoices_async(**kw):
    return await _run(_shipped_invoices_sync, **kw)


async def invoice_detail_async(**kw):
    return await _run(_invoice_detail_sync, **kw)


async def incoming_purchases_async(**kw):
    return await _run(_incoming_purchases_sync, **kw)


async def purchased_in_range_async(**kw):
    return await _run(_purchased_in_range_sync, **kw)


async def received_in_range_async(**kw):
    return await _run(_received_in_range_sync, **kw)


async def purchase_order_detail_async(**kw):
    return await _run(_purchase_order_detail_sync, **kw)


async def backoffice_daily_sales_async(**kw):
    return await _run(_backoffice_daily_sales_sync, **kw)


async def backoffice_breakdown_async(**kw):
    return await _run(_backoffice_breakdown_sync, **kw)


async def shopify_open_orders_local(store_id: int) -> Dict[str, float]:
    return await asyncio.to_thread(_shopify_open_orders_local_sync, store_id)


async def shopify_top_products(store_id: int, tz: str, date_from: str, date_to_excl: str, limit: int = 10) -> List[Dict[str, Any]]:
    return await asyncio.to_thread(_shopify_top_products_sync, store_id, tz, date_from, date_to_excl, limit)


def shutdown_bov_executor():
    _bov_executor.shutdown(wait=False)
