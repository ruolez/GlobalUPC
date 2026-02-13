import pyodbc
from typing import Optional, List, Dict, Any, Tuple
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from mssql_helper import get_mssql_connection_string


def get_item_info(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    upc: str
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    Get item information from Items_tbl by UPC.
    Returns: (success, error_message, item_info)
    """
    conn_str = get_mssql_connection_string(host, port, database, username, password)

    try:
        conn = pyodbc.connect(conn_str, timeout=30)
        cursor = conn.cursor()

        query = """
            SELECT ProductID, ProductUPC, ProductDescription, LastReceived, LastSold,
                   UnitPrice, UnitCost, AvrCost, QuantOnHand
            FROM Items_tbl
            WHERE ProductUPC = ?
        """

        cursor.execute(query, (upc,))
        row = cursor.fetchone()

        cursor.close()
        conn.close()

        if not row:
            return True, None, None

        item_info = {
            "product_id": row[0],
            "product_upc": row[1],
            "product_description": row[2],
            "last_received": row[3],
            "last_sold": row[4],
            "unit_price": float(row[5]) if row[5] is not None else None,
            "unit_cost": float(row[6]) if row[6] is not None else None,
            "avr_cost": float(row[7]) if row[7] is not None else None,
            "quant_on_hand": float(row[8]) if row[8] is not None else None,
        }

        return True, None, item_info

    except Exception as e:
        return False, str(e), None


def get_purchases(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    upc: str,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 1000
) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """
    Get purchase history from PurchaseOrdersDetails_tbl.
    Returns: (success, error_message, purchases)
    """
    conn_str = get_mssql_connection_string(host, port, database, username, password)

    try:
        conn = pyodbc.connect(conn_str, timeout=30)
        cursor = conn.cursor()

        # Check if tables exist
        cursor.execute("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_NAME IN ('PurchaseOrdersDetails_tbl', 'PurchaseOrders_tbl')
        """)
        table_count = cursor.fetchone()[0]

        if table_count < 2:
            cursor.close()
            conn.close()
            return True, None, []

        query = """
            SELECT TOP (?) d.LineID, h.PoNumber, h.PoDate, d.DateReceived, d.QtyOrdered,
                   d.QtyReceived, d.UnitCost, d.ExtendedCost, h.BusinessName
            FROM PurchaseOrdersDetails_tbl d
            INNER JOIN PurchaseOrders_tbl h ON d.PoID = h.PoID
            WHERE d.ProductUPC = ?
        """

        params = [limit, upc]

        if date_from:
            query += " AND COALESCE(d.DateReceived, h.PoDate) >= ?"
            params.append(date_from)

        if date_to:
            query += " AND COALESCE(d.DateReceived, h.PoDate) <= ?"
            params.append(date_to)

        query += " ORDER BY COALESCE(d.DateReceived, h.PoDate) DESC"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        cursor.close()
        conn.close()

        purchases = []
        for row in rows:
            purchases.append({
                "line_id": row[0],
                "document_number": str(row[1]) if row[1] else None,
                "event_date": row[3] if row[3] else row[2],  # DateReceived or PoDate
                "qty_ordered": float(row[4]) if row[4] is not None else None,
                "quantity": float(row[5]) if row[5] is not None else None,  # QtyReceived
                "price_or_cost": float(row[6]) if row[6] is not None else None,
                "extended_amount": float(row[7]) if row[7] is not None else None,
                "business_name": row[8],
            })

        return True, None, purchases

    except Exception as e:
        return False, str(e), []


def get_sales(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    upc: str,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 1000,
    show_voided: bool = False
) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """
    Get sales history from InvoicesDetails_tbl.
    Returns: (success, error_message, sales)
    """
    conn_str = get_mssql_connection_string(host, port, database, username, password)

    try:
        conn = pyodbc.connect(conn_str, timeout=30)
        cursor = conn.cursor()

        # Check if tables exist
        cursor.execute("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_NAME IN ('InvoicesDetails_tbl', 'Invoices_tbl')
        """)
        table_count = cursor.fetchone()[0]

        if table_count < 2:
            cursor.close()
            conn.close()
            return True, None, []

        query = """
            SELECT TOP (?) d.LineID, h.InvoiceNumber, h.InvoiceDate, d.QtyShipped,
                   d.UnitPrice, d.ExtendedPrice, d.UnitCost, h.BusinessName,
                   ISNULL(h.Void, 0) AS IsVoided
            FROM InvoicesDetails_tbl d
            INNER JOIN Invoices_tbl h ON d.InvoiceID = h.InvoiceID
            WHERE d.ProductUPC = ?
        """

        params = [limit, upc]

        if not show_voided:
            query += " AND ISNULL(h.Void, 0) = 0"

        if date_from:
            query += " AND h.InvoiceDate >= ?"
            params.append(date_from)

        if date_to:
            query += " AND h.InvoiceDate <= ?"
            params.append(date_to)

        query += " ORDER BY h.InvoiceDate DESC"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        cursor.close()
        conn.close()

        sales = []
        for row in rows:
            sales.append({
                "line_id": row[0],
                "document_number": str(row[1]) if row[1] else None,
                "event_date": row[2],
                "quantity": float(row[3]) if row[3] is not None else None,
                "price_or_cost": float(row[4]) if row[4] is not None else None,
                "extended_amount": float(row[5]) if row[5] is not None else None,
                "unit_cost": float(row[6]) if row[6] is not None else None,
                "business_name": row[7],
                "is_voided": bool(row[8]) if row[8] is not None else False,
            })

        return True, None, sales

    except Exception as e:
        return False, str(e), []


def get_customer_returns(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    upc: str,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 1000
) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """
    Get customer returns history from CreditMemosDetails_tbl.
    Returns: (success, error_message, returns)
    """
    conn_str = get_mssql_connection_string(host, port, database, username, password)

    try:
        conn = pyodbc.connect(conn_str, timeout=30)
        cursor = conn.cursor()

        # Check if tables exist
        cursor.execute("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_NAME IN ('CreditMemosDetails_tbl', 'CreditMemos_tbl')
        """)
        table_count = cursor.fetchone()[0]

        if table_count < 2:
            cursor.close()
            conn.close()
            return True, None, []

        query = """
            SELECT TOP (?) d.LineID, h.CmemoNumber, h.CmemoDate, d.Quantity,
                   d.UnitPrice, d.ExtendedPrice, h.BusinessName
            FROM CreditMemosDetails_tbl d
            INNER JOIN CreditMemos_tbl h ON d.CmemoID = h.CmemoID
            WHERE d.ProductUPC = ?
        """

        params = [limit, upc]

        if date_from:
            query += " AND h.CmemoDate >= ?"
            params.append(date_from)

        if date_to:
            query += " AND h.CmemoDate <= ?"
            params.append(date_to)

        query += " ORDER BY h.CmemoDate DESC"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        cursor.close()
        conn.close()

        returns = []
        for row in rows:
            returns.append({
                "line_id": row[0],
                "document_number": str(row[1]) if row[1] else None,
                "event_date": row[2],
                "quantity": float(row[3]) if row[3] is not None else None,
                "price_or_cost": float(row[4]) if row[4] is not None else None,
                "extended_amount": float(row[5]) if row[5] is not None else None,
                "business_name": row[6],
            })

        return True, None, returns

    except Exception as e:
        return False, str(e), []


def get_vendor_returns(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    upc: str,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 1000
) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """
    Get vendor returns history from PurchasesReturnsDetails_tbl.
    Returns: (success, error_message, returns)
    """
    conn_str = get_mssql_connection_string(host, port, database, username, password)

    try:
        conn = pyodbc.connect(conn_str, timeout=30)
        cursor = conn.cursor()

        # Check if tables exist
        cursor.execute("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_NAME IN ('PurchasesReturnsDetails_tbl', 'PurchasesReturns_tbl')
        """)
        table_count = cursor.fetchone()[0]

        if table_count < 2:
            cursor.close()
            conn.close()
            return True, None, []

        query = """
            SELECT TOP (?) d.LineID, h.SlipNumber, h.ReturnDate, d.Qty,
                   d.UnitCost, d.ExtendedCost, h.BusinessName
            FROM PurchasesReturnsDetails_tbl d
            INNER JOIN PurchasesReturns_tbl h ON d.ReturnID = h.ReturnID
            WHERE d.ProductUPC = ?
        """

        params = [limit, upc]

        if date_from:
            query += " AND h.ReturnDate >= ?"
            params.append(date_from)

        if date_to:
            query += " AND h.ReturnDate <= ?"
            params.append(date_to)

        query += " ORDER BY h.ReturnDate DESC"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        cursor.close()
        conn.close()

        returns = []
        for row in rows:
            returns.append({
                "line_id": row[0],
                "document_number": str(row[1]) if row[1] else None,
                "event_date": row[2],
                "quantity": float(row[3]) if row[3] is not None else None,
                "price_or_cost": float(row[4]) if row[4] is not None else None,
                "extended_amount": float(row[5]) if row[5] is not None else None,
                "business_name": row[6],
            })

        return True, None, returns

    except Exception as e:
        return False, str(e), []


async def get_item_info_async(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    upc: str
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """Async wrapper for get_item_info."""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        return await loop.run_in_executor(
            executor,
            get_item_info,
            host, port, database, username, password, upc
        )


async def get_purchases_async(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    upc: str,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 1000
) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """Async wrapper for get_purchases."""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        return await loop.run_in_executor(
            executor,
            lambda: get_purchases(host, port, database, username, password, upc, date_from, date_to, limit)
        )


async def get_sales_async(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    upc: str,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 1000,
    show_voided: bool = False
) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """Async wrapper for get_sales."""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        return await loop.run_in_executor(
            executor,
            lambda: get_sales(host, port, database, username, password, upc, date_from, date_to, limit, show_voided)
        )


async def get_customer_returns_async(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    upc: str,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 1000
) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """Async wrapper for get_customer_returns."""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        return await loop.run_in_executor(
            executor,
            lambda: get_customer_returns(host, port, database, username, password, upc, date_from, date_to, limit)
        )


async def get_vendor_returns_async(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    upc: str,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 1000
) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """Async wrapper for get_vendor_returns."""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        return await loop.run_in_executor(
            executor,
            lambda: get_vendor_returns(host, port, database, username, password, upc, date_from, date_to, limit)
        )


def search_products_by_description(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    query: str,
    limit: int = 10
) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """
    Search Items_tbl by ProductDescription.
    Only returns active products (Discontinued=0).
    Returns: (success, error_message, products)
    """
    conn_str = get_mssql_connection_string(host, port, database, username, password)

    try:
        conn = pyodbc.connect(conn_str, timeout=30)
        cursor = conn.cursor()

        sql = """
            SELECT TOP (?) ProductID, ProductUPC, ProductDescription, QuantOnHand
            FROM Items_tbl
            WHERE ProductDescription LIKE ? + '%'
              AND Discontinued = 0
            ORDER BY ProductDescription
        """

        cursor.execute(sql, (limit, query))
        rows = cursor.fetchall()

        cursor.close()
        conn.close()

        products = []
        for row in rows:
            products.append({
                "product_id": row[0],
                "product_upc": row[1] or "",
                "product_description": row[2] or "",
                "quant_on_hand": row[3] if row[3] is not None else 0
            })

        return True, None, products

    except Exception as e:
        return False, str(e), []


async def search_products_by_description_async(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    query: str,
    limit: int = 10
) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """Async wrapper for search_products_by_description."""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        return await loop.run_in_executor(
            executor,
            lambda: search_products_by_description(host, port, database, username, password, query, limit)
        )


def get_inventory_recounts(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    upc: str,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 1000
) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """
    Get inventory recount history from ManualInventoryUpdate table.
    Returns: (success, error_message, recounts)
    """
    conn_str = get_mssql_connection_string(host, port, database, username, password)

    try:
        conn = pyodbc.connect(conn_str, timeout=30)
        cursor = conn.cursor()

        # Check if table exists
        cursor.execute("""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_NAME = 'ManualInventoryUpdate'
        """)
        table_exists = cursor.fetchone()[0] > 0

        if not table_exists:
            cursor.close()
            conn.close()
            return True, None, []

        query = """
            SELECT TOP (?) id, DateCreated, Username, UpdateType, DiffQty, NewQty
            FROM ManualInventoryUpdate
            WHERE ProductUPC = ?
        """

        params = [limit, upc]

        if date_from:
            query += " AND DateCreated >= ?"
            params.append(date_from)

        if date_to:
            query += " AND DateCreated <= ?"
            params.append(date_to)

        query += " ORDER BY DateCreated DESC"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        cursor.close()
        conn.close()

        recounts = []
        for row in rows:
            recounts.append({
                "line_id": row[0],
                "event_date": row[1],
                "username": row[2],
                "update_type": row[3],
                "quantity": float(row[4]) if row[4] is not None else None,  # DiffQty for Qty column
                "new_qty": float(row[5]) if row[5] is not None else None,   # NewQty for running_balance
            })

        return True, None, recounts

    except Exception as e:
        return False, str(e), []


async def get_inventory_recounts_async(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    upc: str,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 1000
) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """Async wrapper for get_inventory_recounts."""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        return await loop.run_in_executor(
            executor,
            lambda: get_inventory_recounts(host, port, database, username, password, upc, date_from, date_to, limit)
        )
