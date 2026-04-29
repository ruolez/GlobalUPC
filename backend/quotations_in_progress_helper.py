import pyodbc
from typing import Optional, List, Dict, Any, Tuple
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from mssql_helper import get_mssql_connection_string

_qip_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="qip")

# Whitelist of sortable columns. We GROUP BY qip.QuotationNumber, so every
# non-grouped column must be wrapped in an aggregate to be valid in ORDER BY.
SORTABLE_COLUMNS = {
    "start_date":       "MIN(qip.StartDate)",
    "quotation_number": "qip.QuotationNumber",
    "packer":           "MAX(qs.Packer)",
    "checker":          "MAX(qs.Checker)",
    # Dop2/Dop3 are stored as varchar ("MM/DD/YYYY HH:MM AM/PM");
    # cast to datetime so chronological sort behaves correctly.
    "dop2":             "MAX(TRY_CONVERT(datetime, qs.Dop2))",
    "dop3":             "MAX(TRY_CONVERT(datetime, qs.Dop3))",
    "total_qty":        "MAX(qs.TotalQty)",
    "business_name":    "MAX(qs.BusinessName)",
    "source_db":        "MAX(qip.SourceDB)",
}


def _row_to_dt(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _build_scan_having(scan_filter: str) -> str:
    """
    Returns a HAVING fragment (without the HAVING keyword) describing the
    scan-state filter against aggregated values, or an empty string when no
    filter applies.

    Uses MAX(...) so the test runs against the value displayed for the
    quotation -- this is robust against multiple QuotationsStatus rows per
    QuotationNumber. Treats empty / whitespace strings the same as NULL,
    matching the frontend's "hasIn / hasOut" check.

    Workflow semantics:
      - "in"   = picking in progress (Dop2 set, Dop3 not yet)
      - "out"  = scan-out present (which in real data means complete,
                 since scan-out always follows scan-in)
      - "none" = pending, no scans
    """
    in_present = "(MAX(qs.Dop2) IS NOT NULL AND LTRIM(RTRIM(MAX(qs.Dop2))) <> '')"
    out_present = "(MAX(qs.Dop3) IS NOT NULL AND LTRIM(RTRIM(MAX(qs.Dop3))) <> '')"
    in_absent = "(MAX(qs.Dop2) IS NULL OR LTRIM(RTRIM(MAX(qs.Dop2))) = '')"
    out_absent = "(MAX(qs.Dop3) IS NULL OR LTRIM(RTRIM(MAX(qs.Dop3))) = '')"

    if scan_filter == "in":
        return f"{in_present} AND {out_absent}"
    if scan_filter == "out":
        return out_present
    if scan_filter == "none":
        return f"{in_absent} AND {out_absent}"
    return ""  # "all"


def _list_quotations_in_progress_sync(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    scan_filter: str,
    source_dbs: List[str],
    packers: List[str],
    checkers: List[str],
    search: Optional[str],
    sort_by: str,
    sort_order: str,
    limit: int,
) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """Aggregate QuotationsInProgress per QuotationNumber and LEFT JOIN QuotationsStatus."""
    conn_str = get_mssql_connection_string(host, port, database, username, password)

    sort_sql = SORTABLE_COLUMNS.get(sort_by, "start_date")
    direction = "DESC" if sort_order.lower() == "desc" else "ASC"

    where_clauses: List[str] = []
    having_clauses: List[str] = []
    params: List[Any] = []

    scan_having = _build_scan_having(scan_filter)
    if scan_having:
        having_clauses.append(scan_having)

    if source_dbs:
        placeholders = ",".join(["?"] * len(source_dbs))
        where_clauses.append(f"qip.SourceDB IN ({placeholders})")
        params.extend(source_dbs)
    if packers:
        placeholders = ",".join(["?"] * len(packers))
        where_clauses.append(f"qs.Packer IN ({placeholders})")
        params.extend(packers)
    if checkers:
        placeholders = ",".join(["?"] * len(checkers))
        where_clauses.append(f"qs.Checker IN ({placeholders})")
        params.extend(checkers)

    if search and search.strip():
        like = f"%{search.strip()}%"
        where_clauses.append(
            "("
            "qip.QuotationNumber LIKE ? OR qs.BusinessName LIKE ? OR qs.AccountNo LIKE ? "
            "OR EXISTS (SELECT 1 FROM QuotationsInProgress qip2 "
            "WHERE qip2.QuotationNumber = qip.QuotationNumber "
            "AND (qip2.ProductUPC LIKE ? OR qip2.ProductDescription LIKE ? OR qip2.ProductSKU LIKE ?))"
            ")"
        )
        params.extend([like, like, like, like, like, like])

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    having_sql = ("HAVING " + " AND ".join(having_clauses)) if having_clauses else ""

    query = f"""
        SELECT TOP (?)
            qip.QuotationNumber,
            MAX(qip.SourceDB)               AS source_db,
            MAX(qip.Status)                 AS status,
            MIN(qip.StartDate)              AS start_date,
            MAX(qip.EndDate)                AS end_date,
            MAX(qip.PauseDate)              AS pause_date,
            MAX(qip.PauseReason)            AS pause_reason,
            MAX(qip.AccountNo)              AS qip_account_no,
            MAX(qip.SalesRepID)             AS sales_rep_id,
            COUNT(*)                        AS product_count,
            SUM(ISNULL(qip.Qty, 0))         AS total_qty_qip,
            MAX(qs.Packer)                  AS packer,
            MAX(qs.Checker)                 AS checker,
            MAX(qs.BusinessName)            AS business_name,
            MAX(qs.AccountNo)               AS account_no,
            MAX(qs.SalesRep)                AS sales_rep,
            MAX(qs.Dop2)                    AS dop2,
            MAX(qs.Dop3)                    AS dop3,
            MAX(qs.LastUpdate)              AS last_update,
            MAX(qs.TotalQty)                AS total_qty,
            MAX(qs.Status)                  AS status_status,
            MAX(qs.UserStatus)              AS user_status,
            MAX(qs.InvoiceNumber)           AS invoice_number
        FROM QuotationsInProgress qip
        LEFT JOIN QuotationsStatus qs ON qs.QuotationNumber = qip.QuotationNumber
        {where_sql}
        GROUP BY qip.QuotationNumber
        {having_sql}
        ORDER BY {sort_sql} {direction}
    """

    # TOP requires a single int param; we put it first
    full_params: List[Any] = [int(limit)] + params

    try:
        with pyodbc.connect(conn_str, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute(query, full_params)
            cols = [c[0] for c in cursor.description]
            rows = cursor.fetchall()

        results: List[Dict[str, Any]] = []
        for row in rows:
            d = dict(zip(cols, row))
            results.append({
                "quotation_number": d.get("QuotationNumber"),
                "source_db": d.get("source_db"),
                "status": d.get("status_status") or d.get("status"),
                "start_date": _row_to_dt(d.get("start_date")),
                "end_date": _row_to_dt(d.get("end_date")),
                "pause_date": _row_to_dt(d.get("pause_date")),
                "pause_reason": d.get("pause_reason"),
                "account_no": d.get("account_no") or d.get("qip_account_no"),
                "sales_rep": d.get("sales_rep"),
                "sales_rep_id": d.get("sales_rep_id"),
                "product_count": int(d.get("product_count") or 0),
                "total_qty": int(d.get("total_qty") or d.get("total_qty_qip") or 0),
                "packer": d.get("packer"),
                "checker": d.get("checker"),
                "business_name": d.get("business_name"),
                "dop2": d.get("dop2"),
                "dop3": d.get("dop3"),
                "last_update": _row_to_dt(d.get("last_update")),
                "user_status": d.get("user_status"),
                "invoice_number": d.get("invoice_number"),
            })

        return True, None, results
    except Exception as e:
        return False, str(e), []


def _get_quotation_products_sync(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    quotation_number: str,
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """Return product line items + a header dict from QuotationsStatus for a single quotation."""
    conn_str = get_mssql_connection_string(host, port, database, username, password)

    products_query = """
        SELECT id, StartDate, EndDate, Status, SourceDB, QuotationNumber,
               Packer, Checker, PauseDate, PauseReason, AccountNo, SalesRepID,
               ProductDescription, ProductUPC, ProductSKU, Qty, CateID, SubCateID,
               flag1, flag2, flag3
        FROM QuotationsInProgress
        WHERE QuotationNumber = ?
        ORDER BY id ASC
    """

    header_query = """
        SELECT TOP 1 QuotationNumber, Status, SourceDB, InvoiceNumber, BusinessName,
               AccountNo, SalesRep, Packer, Checker, Username, UserStatus, LastUpdate,
               TotalQty, Shipto, ShipAddress1, ShipAddress2, ShipContact, ShipCity,
               ShipState, ShipZipCode, ShipPhoneNo, ShipperID, TermID, QuotationTotal,
               Comment, Notes, Dop1, Dop2, Dop3, DateCreate
        FROM QuotationsStatus
        WHERE QuotationNumber = ?
        ORDER BY id DESC
    """

    try:
        with pyodbc.connect(conn_str, timeout=30) as conn:
            cursor = conn.cursor()

            cursor.execute(products_query, (quotation_number,))
            p_cols = [c[0] for c in cursor.description]
            p_rows = cursor.fetchall()

            cursor.execute(header_query, (quotation_number,))
            h_cols = [c[0] for c in cursor.description]
            h_row = cursor.fetchone()

        products = []
        for row in p_rows:
            d = dict(zip(p_cols, row))
            products.append({
                "id": d.get("id"),
                "start_date": _row_to_dt(d.get("StartDate")),
                "end_date": _row_to_dt(d.get("EndDate")),
                "status": d.get("Status"),
                "source_db": d.get("SourceDB"),
                "quotation_number": d.get("QuotationNumber"),
                "packer": d.get("Packer"),
                "checker": d.get("Checker"),
                "pause_date": _row_to_dt(d.get("PauseDate")),
                "pause_reason": d.get("PauseReason"),
                "account_no": d.get("AccountNo"),
                "sales_rep_id": d.get("SalesRepID"),
                "product_description": d.get("ProductDescription"),
                "product_upc": d.get("ProductUPC"),
                "product_sku": d.get("ProductSKU"),
                "qty": int(d.get("Qty") or 0),
                "cate_id": d.get("CateID"),
                "sub_cate_id": d.get("SubCateID"),
                "flag1": bool(d.get("flag1")) if d.get("flag1") is not None else None,
                "flag2": bool(d.get("flag2")) if d.get("flag2") is not None else None,
                "flag3": bool(d.get("flag3")) if d.get("flag3") is not None else None,
            })

        header: Optional[Dict[str, Any]] = None
        if h_row:
            d = dict(zip(h_cols, h_row))
            header = {
                "quotation_number": d.get("QuotationNumber"),
                "status": d.get("Status"),
                "source_db": d.get("SourceDB"),
                "invoice_number": d.get("InvoiceNumber"),
                "business_name": d.get("BusinessName"),
                "account_no": d.get("AccountNo"),
                "sales_rep": d.get("SalesRep"),
                "packer": d.get("Packer"),
                "checker": d.get("Checker"),
                "username": d.get("Username"),
                "user_status": d.get("UserStatus"),
                "last_update": _row_to_dt(d.get("LastUpdate")),
                "total_qty": int(d.get("TotalQty") or 0) if d.get("TotalQty") is not None else None,
                "ship_to": d.get("Shipto"),
                "ship_address1": d.get("ShipAddress1"),
                "ship_address2": d.get("ShipAddress2"),
                "ship_contact": d.get("ShipContact"),
                "ship_city": d.get("ShipCity"),
                "ship_state": d.get("ShipState"),
                "ship_zip_code": d.get("ShipZipCode"),
                "ship_phone_no": d.get("ShipPhoneNo"),
                "shipper_id": d.get("ShipperID"),
                "term_id": d.get("TermID"),
                "quotation_total": d.get("QuotationTotal"),
                "comment": d.get("Comment"),
                "notes": d.get("Notes"),
                "dop1": d.get("Dop1"),
                "dop2": d.get("Dop2"),
                "dop3": d.get("Dop3"),
                "date_create": _row_to_dt(d.get("DateCreate")),
            }

        return True, None, {"products": products, "header": header}
    except Exception as e:
        return False, str(e), {"products": [], "header": None}


def _list_distinct_filter_values_sync(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
) -> Tuple[bool, Optional[str], Dict[str, List[str]]]:
    """Return distinct SourceDB / Packer / Checker / Status values for filter dropdowns."""
    conn_str = get_mssql_connection_string(host, port, database, username, password)

    try:
        with pyodbc.connect(conn_str, timeout=30) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT DISTINCT SourceDB FROM QuotationsInProgress
                WHERE SourceDB IS NOT NULL AND LTRIM(RTRIM(SourceDB)) <> ''
                ORDER BY SourceDB
            """)
            source_dbs = [r[0] for r in cursor.fetchall() if r[0]]

            cursor.execute("""
                SELECT DISTINCT qs.Packer
                FROM QuotationsInProgress qip
                INNER JOIN QuotationsStatus qs ON qs.QuotationNumber = qip.QuotationNumber
                WHERE qs.Packer IS NOT NULL AND LTRIM(RTRIM(qs.Packer)) <> ''
                ORDER BY qs.Packer
            """)
            packers = [r[0] for r in cursor.fetchall() if r[0]]

            cursor.execute("""
                SELECT DISTINCT qs.Checker
                FROM QuotationsInProgress qip
                INNER JOIN QuotationsStatus qs ON qs.QuotationNumber = qip.QuotationNumber
                WHERE qs.Checker IS NOT NULL AND LTRIM(RTRIM(qs.Checker)) <> ''
                ORDER BY qs.Checker
            """)
            checkers = [r[0] for r in cursor.fetchall() if r[0]]

            cursor.execute("""
                SELECT DISTINCT Status FROM QuotationsInProgress
                WHERE Status IS NOT NULL AND LTRIM(RTRIM(Status)) <> ''
                ORDER BY Status
            """)
            statuses = [r[0] for r in cursor.fetchall() if r[0]]

        return True, None, {
            "source_dbs": source_dbs,
            "packers": packers,
            "checkers": checkers,
            "statuses": statuses,
        }
    except Exception as e:
        return False, str(e), {"source_dbs": [], "packers": [], "checkers": [], "statuses": []}


async def list_quotations_in_progress_async(**kwargs) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _qip_executor,
        lambda: _list_quotations_in_progress_sync(**kwargs),
    )


async def get_quotation_products_async(**kwargs) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _qip_executor,
        lambda: _get_quotation_products_sync(**kwargs),
    )


async def list_distinct_filter_values_async(**kwargs) -> Tuple[bool, Optional[str], Dict[str, List[str]]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _qip_executor,
        lambda: _list_distinct_filter_values_sync(**kwargs),
    )


def shutdown_qip_executor():
    _qip_executor.shutdown(wait=False)
