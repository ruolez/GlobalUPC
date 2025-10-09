import pyodbc
from typing import Optional, List, Dict, Any
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date

# Chunk size for processing large tables (prevents timeout)
CHUNK_SIZE = 5000

# Mapping of detail tables to their header tables for date filtering
# Each entry contains: header_table, join_key, and date_field
# If header_table is None, the date field exists directly in the detail table
DETAIL_TABLE_MAPPING = {
    "QuotationsDetails_tbl": {
        "header_table": "Quotations_tbl",
        "join_key": "QuotationID",
        "date_field": "QuotationDate"
    },
    "PurchaseOrdersDetails_tbl": {
        "header_table": "PurchaseOrders_tbl",
        "join_key": "PoID",
        "date_field": "PoDate"
    },
    "InvoicesDetails_tbl": {
        "header_table": "Invoices_tbl",
        "join_key": "InvoiceID",
        "date_field": "InvoiceDate"
    },
    "CreditMemosDetails_tbl": {
        "header_table": "CreditMemos_tbl",
        "join_key": "CmemoID",
        "date_field": "CmemoDate"
    },
    "PurchasesReturnsDetails_tbl": {
        "header_table": "PurchasesReturns_tbl",
        "join_key": "ReturnID",
        "date_field": "ReturnDate"
    },
    "QuotationDetails": {
        "header_table": None,  # Special case: date is directly in detail table
        "join_key": None,
        "date_field": "DateCreate"
    }
}

def get_mssql_connection_string(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    tds_version: str = "7.4",
    timeout: int = 30
) -> str:
    """
    Generate MSSQL connection string using FreeTDS driver.

    TDS Version Guide:
    - 7.0: SQL Server 7.0
    - 7.1: SQL Server 2000
    - 7.2: SQL Server 2005
    - 7.3: SQL Server 2008
    - 7.4: SQL Server 2012/2014/2016/2017/2019/2022 (default)

    Args:
        host: Server hostname or IP
        port: Server port (usually 1433)
        database: Database name
        username: SQL Server username
        password: SQL Server password
        tds_version: TDS protocol version (default: 7.4)
        timeout: Connection timeout in seconds

    Returns:
        ODBC connection string
    """
    connection_string = (
        f"DRIVER={{FreeTDS}};"
        f"SERVER={host};"
        f"PORT={port};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        f"TDS_Version={tds_version};"
        f"CHARSET=UTF8;"
        f"TIMEOUT={timeout};"
    )
    return connection_string

def test_mssql_connection(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    tds_version: str = "7.4"
) -> tuple[bool, Optional[str]]:
    """
    Test MSSQL connection.

    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    try:
        conn_string = get_mssql_connection_string(
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            tds_version=tds_version
        )

        with pyodbc.connect(conn_string, timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT @@VERSION")
            version = cursor.fetchone()[0]
            cursor.close()

        return True, None
    except pyodbc.Error as e:
        error_msg = str(e)
        return False, error_msg
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"

def get_available_drivers() -> list[str]:
    """Get list of available ODBC drivers."""
    return pyodbc.drivers()

def _search_products_by_upc_sync(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    upc: str,
    tds_version: str = "7.4"
) -> tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """Synchronous version of UPC search for thread pool execution."""
    try:
        conn_string = get_mssql_connection_string(
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            tds_version=tds_version
        )

        # Define tables to search with their primary keys
        tables = [
            {
                "name": "Items_tbl",
                "pk": "ProductID",
                "description_field": "ProductDescription"
            },
            {
                "name": "QuotationsDetails_tbl",
                "pk": "LineID",
                "description_field": "ProductDescription"
            },
            {
                "name": "PurchaseOrdersDetails_tbl",
                "pk": "LineID",
                "description_field": "ProductDescription"
            },
            {
                "name": "InvoicesDetails_tbl",
                "pk": "LineID",
                "description_field": "ProductDescription"
            },
            {
                "name": "CreditMemosDetails_tbl",
                "pk": "LineID",
                "description_field": "ProductDescription"
            },
            {
                "name": "PurchasesReturnsDetails_tbl",
                "pk": "LineID",
                "description_field": "ProductDescription"
            },
            {
                "name": "QuotationDetails",
                "pk": "id",
                "description_field": "ProductDescription"
            }
        ]

        results = []

        with pyodbc.connect(conn_string, timeout=30) as conn:
            cursor = conn.cursor()

            for table in tables:
                try:
                    # Query to get all matching rows with primary keys and description
                    query = f"""
                        SELECT {table['pk']}, {table['description_field']}, ProductUPC
                        FROM {table['name']}
                        WHERE ProductUPC = ?
                    """

                    cursor.execute(query, (upc,))
                    rows = cursor.fetchall()

                    if rows:
                        # Aggregate results for this table
                        primary_keys = [row[0] for row in rows]
                        product_description = rows[0][1] if rows[0][1] else "Unknown Product"

                        results.append({
                            "table_name": table['name'],
                            "match_count": len(rows),
                            "primary_keys": primary_keys,
                            "product_description": product_description,
                            "upc": upc
                        })
                except pyodbc.Error:
                    # Table doesn't exist in this database, skip it
                    continue

            cursor.close()

        return True, None, results

    except pyodbc.Error as e:
        error_msg = str(e)
        return False, error_msg, []
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", []

async def search_products_by_upc(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    upc: str,
    tds_version: str = "7.4"
) -> tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """
    Search for products by UPC in MSSQL database across 4 tables.

    Queries:
    - Items_tbl (ProductID as PK)
    - QuotationsDetails_tbl (LineID as PK)
    - PurchaseOrdersDetails_tbl (LineID as PK)
    - InvoicesDetails_tbl (LineID as PK)

    Returns aggregated results per table with match counts and primary keys.

    Args:
        host: Server hostname or IP
        port: Server port
        database: Database name
        username: SQL Server username
        password: SQL Server password
        upc: UPC/barcode to search for
        tds_version: TDS protocol version

    Returns:
        Tuple of (success: bool, error_message: Optional[str], results: List[Dict])
    """
    # Run synchronous pyodbc code in thread pool to avoid blocking event loop
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        return await loop.run_in_executor(
            executor,
            _search_products_by_upc_sync,
            host,
            port,
            database,
            username,
            password,
            upc,
            tds_version
        )

async def search_upc_across_mssql_stores(
    stores: List[Dict[str, Any]],
    upc: str
) -> List[Dict[str, Any]]:
    """
    Search for a UPC across multiple MSSQL stores in parallel.

    Args:
        stores: List of store dictionaries with keys: id, name, host, port, database_name, username, password
        upc: UPC/barcode to search for

    Returns:
        List of ProductVariantMatch dictionaries with MSSQL-specific fields
    """
    async def search_single_store(store: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Search a single MSSQL store and return formatted results."""
        success, error, table_results = await search_products_by_upc(
            host=store["host"],
            port=store["port"],
            database=store["database_name"],
            username=store["username"],
            password=store["password"],
            upc=upc
        )

        if not success:
            # Log error but don't fail entire search
            print(f"Error searching MSSQL store {store['name']}: {error}")
            return []

        # Format each table result as a ProductVariantMatch
        results = []
        for table_result in table_results:
            results.append({
                "store_id": store["id"],
                "store_name": store["name"],
                "store_type": "mssql",
                "product_id": str(table_result["primary_keys"][0]) if table_result["primary_keys"] else "",
                "product_title": table_result["product_description"],
                "variant_id": None,
                "variant_title": None,
                "current_barcode": table_result["upc"],
                "sku": None,
                # MSSQL-specific fields
                "table_name": table_result["table_name"],
                "match_count": table_result["match_count"],
                "primary_keys": table_result["primary_keys"]
            })

        return results

    # Search all stores in parallel
    import asyncio
    tasks = [search_single_store(store) for store in stores]
    results_list = await asyncio.gather(*tasks)

    # Flatten results
    all_results = []
    for results in results_list:
        all_results.extend(results)

    return all_results

def _update_upc_in_table_sync(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    table_name: str,
    primary_key_field: str,
    primary_keys: List[int],
    new_upc: str,
    tds_version: str = "7.4"
) -> tuple[bool, Optional[str], int]:
    """
    Synchronous version of UPC update for thread pool execution.

    Updates ProductUPC field in a specific table for given primary keys.

    Args:
        host: Server hostname or IP
        port: Server port
        database: Database name
        username: SQL Server username
        password: SQL Server password
        table_name: Table name (e.g., Items_tbl)
        primary_key_field: Primary key field name (e.g., ProductID, LineID)
        primary_keys: List of primary key values to update
        new_upc: New UPC value to set
        tds_version: TDS protocol version

    Returns:
        Tuple of (success: bool, error_message: Optional[str], updated_count: int)
    """
    try:
        if not primary_keys:
            return True, None, 0

        conn_string = get_mssql_connection_string(
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            tds_version=tds_version
        )

        with pyodbc.connect(conn_string, timeout=30) as conn:
            cursor = conn.cursor()

            # Build parameterized query
            # UPDATE table SET ProductUPC = ? WHERE pk IN (?, ?, ...)
            placeholders = ', '.join(['?' for _ in primary_keys])
            query = f"""
                UPDATE {table_name}
                SET ProductUPC = ?
                WHERE {primary_key_field} IN ({placeholders})
            """

            # Execute update with parameters (new_upc first, then primary keys)
            params = [new_upc] + primary_keys
            cursor.execute(query, params)

            # Get number of rows updated
            updated_count = cursor.rowcount

            # Commit transaction
            conn.commit()
            cursor.close()

            return True, None, updated_count

    except pyodbc.Error as e:
        error_msg = str(e)
        return False, error_msg, 0
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", 0

async def update_upc_in_table(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    table_name: str,
    primary_key_field: str,
    primary_keys: List[int],
    new_upc: str,
    tds_version: str = "7.4"
) -> tuple[bool, Optional[str], int]:
    """
    Update UPC in a specific MSSQL table for given primary keys.

    Args:
        host: Server hostname or IP
        port: Server port
        database: Database name
        username: SQL Server username
        password: SQL Server password
        table_name: Table name (e.g., Items_tbl)
        primary_key_field: Primary key field name (e.g., ProductID, LineID)
        primary_keys: List of primary key values to update
        new_upc: New UPC value to set
        tds_version: TDS protocol version

    Returns:
        Tuple of (success: bool, error_message: Optional[str], updated_count: int)
    """
    # Run synchronous pyodbc code in thread pool to avoid blocking event loop
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        return await loop.run_in_executor(
            executor,
            _update_upc_in_table_sync,
            host,
            port,
            database,
            username,
            password,
            table_name,
            primary_key_field,
            primary_keys,
            new_upc,
            tds_version
        )

async def update_upc_across_mssql_stores(
    store_updates: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Update UPC across multiple MSSQL stores in parallel.

    Args:
        store_updates: List of dicts with:
            - store_id: int
            - store_name: str
            - host: str
            - port: int
            - database_name: str
            - username: str
            - password: str
            - tables: List of dicts with:
                - table_name: str
                - primary_key_field: str
                - primary_keys: List[int]
                - new_upc: str

    Returns:
        List of update result dictionaries with store_id, store_name, success, updated_count, error
    """
    async def update_single_store(store_update: Dict[str, Any]) -> Dict[str, Any]:
        """Update UPC in a single MSSQL store."""
        total_updated = 0
        errors = []

        # Update each table
        for table in store_update.get("tables", []):
            success, error, count = await update_upc_in_table(
                host=store_update["host"],
                port=store_update["port"],
                database=store_update["database_name"],
                username=store_update["username"],
                password=store_update["password"],
                table_name=table["table_name"],
                primary_key_field=table["primary_key_field"],
                primary_keys=table["primary_keys"],
                new_upc=table["new_upc"]
            )

            if success:
                total_updated += count
            else:
                errors.append(f"Table {table['table_name']}: {error}")

        # Return result
        return {
            "store_id": store_update["store_id"],
            "store_name": store_update["store_name"],
            "success": len(errors) == 0,
            "updated_count": total_updated,
            "error": "; ".join(errors) if errors else None
        }

    # Update all stores in parallel
    tasks = [update_single_store(store_update) for store_update in store_updates]
    results = await asyncio.gather(*tasks)

    return results

def _process_tables_cross_db(
    detail_tables: List[Dict[str, Any]],
    source_cursor,
    target_cursor,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    progress_callback: Optional[callable] = None
) -> tuple[List[Dict[str, Any]], int]:
    """
    Process detail tables with cross-database comparison.

    Queries detail tables from source database and checks UPCs against target database's Items_tbl.

    Args:
        detail_tables: List of table definitions with name, pk, description_field
        source_cursor: Database cursor for source database
        target_cursor: Database cursor for target database
        date_from: Optional start date for filtering
        date_to: Optional end date for filtering
        progress_callback: Optional callback for progress updates

    Returns:
        Tuple of (orphaned_records: List[Dict], tables_checked: int)
    """
    orphaned_records = []
    tables_checked = 0

    for table in detail_tables:
        try:
            # Notify progress - starting table check
            if progress_callback:
                progress_callback({
                    "status": "checking_table",
                    "table_name": table["name"]
                })

            # Build query components based on date filtering requirements
            table_name = table["name"]
            table_mapping = DETAIL_TABLE_MAPPING.get(table_name)

            # Determine if we need to join with header table for date filtering
            needs_header_join = (
                date_from is not None or date_to is not None
            ) and table_mapping is not None

            # Build FROM clause and WHERE clause for date filtering
            if needs_header_join and table_mapping["header_table"] is not None:
                # Join with header table for date filtering
                header_table = table_mapping["header_table"]
                join_key = table_mapping["join_key"]
                date_field = table_mapping["date_field"]
                from_clause = f"{table_name} d INNER JOIN {header_table} h ON d.{join_key} = h.{join_key}"
                date_where_parts = []
                query_params = []

                if date_from is not None:
                    date_where_parts.append(f"h.{date_field} >= ?")
                    query_params.append(date_from)
                if date_to is not None:
                    date_where_parts.append(f"h.{date_field} <= ?")
                    query_params.append(date_to)

                date_where_clause = " AND " + " AND ".join(date_where_parts) if date_where_parts else ""
                table_prefix = "d."
            elif needs_header_join and table_mapping["header_table"] is None:
                # Special case: QuotationDetails has date directly in detail table
                date_field = table_mapping["date_field"]
                from_clause = table_name
                date_where_parts = []
                query_params = []

                if date_from is not None:
                    date_where_parts.append(f"{date_field} >= ?")
                    query_params.append(date_from)
                if date_to is not None:
                    date_where_parts.append(f"{date_field} <= ?")
                    query_params.append(date_to)

                date_where_clause = " AND " + " AND ".join(date_where_parts) if date_where_parts else ""
                table_prefix = ""
            else:
                # No date filtering
                from_clause = table_name
                date_where_clause = ""
                query_params = []
                table_prefix = ""

            # Step 1: Get total record count from source database
            count_query = f"""
                SELECT COUNT(*) as total_records
                FROM {from_clause}
                WHERE {table_prefix}ProductUPC IS NOT NULL AND {table_prefix}ProductUPC != ''{date_where_clause}
            """

            source_cursor.execute(count_query, query_params)
            count_result = source_cursor.fetchone()
            total_records = count_result[0] if count_result else 0

            print(f"[CROSS-DB DEBUG] {table['name']}: total_records = {total_records}")

            if total_records == 0:
                # Table is empty or has no UPCs
                tables_checked += 1
                if progress_callback:
                    progress_callback({
                        "status": "table_complete",
                        "table_name": table["name"],
                        "orphaned_count": 0
                    })
                continue

            # Step 2: Calculate chunks based on record count
            total_chunks = max(1, (total_records + CHUNK_SIZE - 1) // CHUNK_SIZE)

            print(f"[CROSS-DB DEBUG] {table['name']}: total_records={total_records}, total_chunks={total_chunks}, chunk_size={CHUNK_SIZE}")

            # Track progress for this table
            table_orphans = []
            records_checked = 0

            # Step 3: Process records in chunks
            for chunk_num in range(total_chunks):
                offset = chunk_num * CHUNK_SIZE
                limit = CHUNK_SIZE

                print(f"[CROSS-DB DEBUG] {table['name']}: Processing chunk {chunk_num + 1}/{total_chunks}, OFFSET {offset} LIMIT {limit}")

                # Query source database for chunk of records (without JOIN to Items_tbl)
                chunk_query = f"""
                    WITH numbered_records AS (
                        SELECT
                            {table_prefix}{table['pk']} as pk,
                            {table_prefix}ProductID,
                            {table_prefix}{table['description_field']} as description,
                            {table_prefix}ProductUPC,
                            ROW_NUMBER() OVER (ORDER BY {table_prefix}{table['pk']}) as row_num
                        FROM {from_clause}
                        WHERE {table_prefix}ProductUPC IS NOT NULL AND {table_prefix}ProductUPC != ''{date_where_clause}
                    )
                    SELECT n.pk, n.ProductID, n.description, n.ProductUPC
                    FROM numbered_records n
                    WHERE n.row_num > ? AND n.row_num <= ?
                """

                start_row = offset
                end_row = offset + limit

                # Combine chunk query parameters: date params + row range params
                chunk_params = query_params + [start_row, end_row]
                source_cursor.execute(chunk_query, chunk_params)
                chunk_rows = source_cursor.fetchall()

                print(f"[CROSS-DB DEBUG] {table['name']}: Chunk {chunk_num + 1} fetched {len(chunk_rows)} records from source")

                # Collect UPCs from this chunk
                chunk_upcs = []
                records_map = {}  # Map UPC -> record details for quick lookup

                for row in chunk_rows:
                    pk, product_id, description, upc = row[0], row[1], row[2], row[3]
                    normalized_upc = str(upc).strip() if upc else ''

                    if normalized_upc:
                        chunk_upcs.append(normalized_upc)
                        records_map[normalized_upc] = {
                            "pk": pk,
                            "product_id": product_id,
                            "description": description
                        }

                # Step 4: Check which UPCs exist in target database's Items_tbl
                # Use batched queries to avoid SQL Server parameter limit (2100)
                MAX_PARAMS_PER_QUERY = 2000
                existing_upcs = set()

                if chunk_upcs:
                    print(f"[CROSS-DB DEBUG] {table['name']}: Checking {len(chunk_upcs)} UPCs against target Items_tbl")

                    for batch_start in range(0, len(chunk_upcs), MAX_PARAMS_PER_QUERY):
                        batch_end = min(batch_start + MAX_PARAMS_PER_QUERY, len(chunk_upcs))
                        upc_batch = chunk_upcs[batch_start:batch_end]

                        placeholders = ','.join(['?'] * len(upc_batch))
                        target_query = f"SELECT ProductUPC FROM Items_tbl WHERE ProductUPC IN ({placeholders})"

                        target_cursor.execute(target_query, upc_batch)
                        batch_results = {row[0].strip() if row[0] else '' for row in target_cursor.fetchall()}
                        existing_upcs.update(batch_results)

                    print(f"[CROSS-DB DEBUG] {table['name']}: Found {len(existing_upcs)} matching UPCs in target")

                # Step 5: Identify orphaned UPCs (in source but not in target)
                chunk_orphans = 0
                for upc in chunk_upcs:
                    if upc not in existing_upcs:
                        # This UPC is orphaned (exists in source detail table but not in target Items_tbl)
                        record_details = records_map[upc]

                        orphan_record = {
                            "table_name": table["name"],
                            "primary_key": record_details["pk"],
                            "upc": upc,
                            "product_id": record_details["product_id"],
                            "description": record_details["description"] if record_details["description"] else "Unknown"
                        }
                        table_orphans.append(orphan_record)
                        orphaned_records.append(orphan_record)
                        chunk_orphans += 1

                print(f"[CROSS-DB DEBUG] {table['name']}: Chunk {chunk_num + 1} found {chunk_orphans} orphaned UPCs")

                # Update progress
                records_checked = min((chunk_num + 1) * CHUNK_SIZE, total_records)

                # Send chunk progress event
                if progress_callback:
                    progress_callback({
                        "status": "chunk_progress",
                        "table_name": table["name"],
                        "chunk": chunk_num + 1,
                        "total_chunks": total_chunks,
                        "records_checked": records_checked,
                        "total_records": total_records,
                        "orphans_in_chunk": chunk_orphans,
                        "total_orphans": len(table_orphans)
                    })

            tables_checked += 1

            # Notify table complete
            if progress_callback:
                progress_callback({
                    "status": "table_complete",
                    "table_name": table["name"],
                    "orphaned_count": len(table_orphans)
                })

        except pyodbc.Error:
            # Table doesn't exist in source database, skip it
            if progress_callback:
                progress_callback({
                    "status": "table_skipped",
                    "table_name": table["name"]
                })
            continue

    return orphaned_records, tables_checked

def _audit_orphaned_upcs_sync(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    progress_callback: Optional[callable] = None,
    tds_version: str = "7.4",
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    target_host: Optional[str] = None,
    target_port: Optional[int] = None,
    target_database: Optional[str] = None,
    target_username: Optional[str] = None,
    target_password: Optional[str] = None
) -> tuple[bool, Optional[str], List[Dict[str, Any]], int]:
    """
    Synchronous audit of orphaned UPCs in MSSQL database using chunked processing.

    Checks all detail tables for UPCs that don't exist in Items_tbl.
    Processes tables in chunks to prevent timeout on large datasets.
    Optionally filters records by date range using header table dates.

    Supports cross-database comparison: when target connection parameters are provided,
    UPCs from source database detail tables are checked against target database's Items_tbl.

    Args:
        host: Source server hostname or IP
        port: Source server port
        database: Source database name
        username: Source SQL Server username
        password: Source SQL Server password
        progress_callback: Optional callback function for progress updates
        tds_version: TDS protocol version
        date_from: Optional start date for filtering (inclusive)
        date_to: Optional end date for filtering (inclusive)
        target_host: Optional target server hostname for cross-database comparison
        target_port: Optional target server port
        target_database: Optional target database name
        target_username: Optional target SQL Server username
        target_password: Optional target SQL Server password

    Returns:
        Tuple of (success: bool, error_message: Optional[str], orphaned_records: List[Dict], tables_checked: int)
    """
    try:
        # Determine if cross-database mode is enabled
        is_cross_db = all([target_host, target_port, target_database, target_username, target_password])

        # Build source connection string
        source_conn_string = get_mssql_connection_string(
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            tds_version=tds_version
        )

        # Build target connection string if cross-database mode
        target_conn_string = None
        if is_cross_db:
            target_conn_string = get_mssql_connection_string(
                host=target_host,
                port=target_port,
                database=target_database,
                username=target_username,
                password=target_password,
                tds_version=tds_version
            )

        # Define detail tables to audit (exclude Items_tbl)
        detail_tables = [
            {
                "name": "QuotationsDetails_tbl",
                "pk": "LineID",
                "description_field": "ProductDescription"
            },
            {
                "name": "PurchaseOrdersDetails_tbl",
                "pk": "LineID",
                "description_field": "ProductDescription"
            },
            {
                "name": "InvoicesDetails_tbl",
                "pk": "LineID",
                "description_field": "ProductDescription"
            },
            {
                "name": "CreditMemosDetails_tbl",
                "pk": "LineID",
                "description_field": "ProductDescription"
            },
            {
                "name": "PurchasesReturnsDetails_tbl",
                "pk": "LineID",
                "description_field": "ProductDescription"
            },
            {
                "name": "QuotationDetails",
                "pk": "id",
                "description_field": "ProductDescription"
            }
        ]

        orphaned_records = []
        tables_checked = 0

        # Open connections based on mode (single or dual)
        if is_cross_db:
            # Cross-database mode: open both source and target connections
            # Exclude quotation-related tables for cross-database comparison
            excluded_tables = {"QuotationDetails", "QuotationsDetails_tbl"}
            cross_db_tables = [t for t in detail_tables if t["name"] not in excluded_tables]

            with pyodbc.connect(source_conn_string, timeout=60) as source_conn, \
                 pyodbc.connect(target_conn_string, timeout=60) as target_conn:

                source_cursor = source_conn.cursor()
                target_cursor = target_conn.cursor()

                # Process tables with cross-database comparison
                orphaned_records, tables_checked = _process_tables_cross_db(
                    detail_tables=cross_db_tables,
                    source_cursor=source_cursor,
                    target_cursor=target_cursor,
                    date_from=date_from,
                    date_to=date_to,
                    progress_callback=progress_callback
                )

                source_cursor.close()
                target_cursor.close()
        else:
            # Same-database mode: open single connection (backward compatibility)
            with pyodbc.connect(source_conn_string, timeout=60) as conn:
                cursor = conn.cursor()

                for table in detail_tables:
                    try:
                        # Notify progress - starting table check
                        if progress_callback:
                            progress_callback({
                                "status": "checking_table",
                                "table_name": table["name"]
                            })

                        # Build query components based on date filtering requirements
                        table_name = table["name"]
                        table_mapping = DETAIL_TABLE_MAPPING.get(table_name)

                        # Determine if we need to join with header table for date filtering
                        needs_header_join = (
                            date_from is not None or date_to is not None
                        ) and table_mapping is not None

                        # Build FROM clause and WHERE clause for date filtering
                        if needs_header_join and table_mapping["header_table"] is not None:
                            # Join with header table for date filtering
                            header_table = table_mapping["header_table"]
                            join_key = table_mapping["join_key"]
                            date_field = table_mapping["date_field"]
                            from_clause = f"{table_name} d INNER JOIN {header_table} h ON d.{join_key} = h.{join_key}"
                            date_where_parts = []
                            query_params = []

                            if date_from is not None:
                                date_where_parts.append(f"h.{date_field} >= ?")
                                query_params.append(date_from)
                            if date_to is not None:
                                date_where_parts.append(f"h.{date_field} <= ?")
                                query_params.append(date_to)

                            date_where_clause = " AND " + " AND ".join(date_where_parts) if date_where_parts else ""
                            table_prefix = "d."
                        elif needs_header_join and table_mapping["header_table"] is None:
                            # Special case: QuotationDetails has date directly in detail table
                            date_field = table_mapping["date_field"]
                            from_clause = table_name
                            date_where_parts = []
                            query_params = []

                            if date_from is not None:
                                date_where_parts.append(f"{date_field} >= ?")
                                query_params.append(date_from)
                            if date_to is not None:
                                date_where_parts.append(f"{date_field} <= ?")
                                query_params.append(date_to)

                            date_where_clause = " AND " + " AND ".join(date_where_parts) if date_where_parts else ""
                            table_prefix = ""
                        else:
                            # No date filtering
                            from_clause = table_name
                            date_where_clause = ""
                            query_params = []
                            table_prefix = ""

                        # Step 1: Get total record count
                        count_query = f"""
                            SELECT COUNT(*) as total_records
                            FROM {from_clause}
                            WHERE {table_prefix}ProductUPC IS NOT NULL AND {table_prefix}ProductUPC != ''{date_where_clause}
                        """

                        cursor.execute(count_query, query_params)
                        count_result = cursor.fetchone()
                        total_records = count_result[0] if count_result else 0

                        print(f"[CHUNK DEBUG] {table['name']}: total_records = {total_records}")

                        if total_records == 0:
                            # Table is empty or has no UPCs
                            tables_checked += 1
                            if progress_callback:
                                progress_callback({
                                    "status": "table_complete",
                                    "table_name": table["name"],
                                    "orphaned_count": 0
                                })
                            continue

                        # Step 2: Calculate chunks based on RECORD COUNT (not PK range)
                        # This guarantees consistent chunk sizes even with sparse primary keys
                        total_chunks = max(1, (total_records + CHUNK_SIZE - 1) // CHUNK_SIZE)

                        print(f"[CHUNK DEBUG] {table['name']}: total_records={total_records}, total_chunks={total_chunks}, chunk_size={CHUNK_SIZE}")

                        # Track progress for this table
                        table_orphans = []
                        records_checked = 0

                        # Step 3: Process records in TRUE chunks (actually checking 5000 records at a time)
                        # This shows real progress and prevents timeout on large tables

                        for chunk_num in range(total_chunks):
                            offset = chunk_num * CHUNK_SIZE
                            limit = CHUNK_SIZE

                            print(f"[CHUNK DEBUG] {table['name']}: Processing chunk {chunk_num + 1}/{total_chunks}, OFFSET {offset} LIMIT {limit}")

                            # True chunked processing: Check a batch of 5000 records for orphans
                            # Uses CTE to number records, then LEFT JOIN to find orphans in that batch
                            chunk_query = f"""
                                WITH numbered_records AS (
                                    SELECT
                                        {table_prefix}{table['pk']} as pk,
                                        {table_prefix}ProductID,
                                        {table_prefix}{table['description_field']} as description,
                                        {table_prefix}ProductUPC,
                                        ROW_NUMBER() OVER (ORDER BY {table_prefix}{table['pk']}) as row_num
                                    FROM {from_clause}
                                    WHERE {table_prefix}ProductUPC IS NOT NULL AND {table_prefix}ProductUPC != ''{date_where_clause}
                                )
                                SELECT n.pk, n.ProductID, n.description, n.ProductUPC
                                FROM numbered_records n
                                LEFT JOIN Items_tbl i ON n.ProductUPC = i.ProductUPC
                                WHERE n.row_num > ? AND n.row_num <= ?
                                AND i.ProductUPC IS NULL
                            """

                            start_row = offset
                            end_row = offset + limit

                            # Combine chunk query parameters: date params + row range params
                            chunk_params = query_params + [start_row, end_row]
                            cursor.execute(chunk_query, chunk_params)
                            chunk_rows = cursor.fetchall()

                            chunk_orphans = len(chunk_rows)
                            print(f"[CHUNK DEBUG] {table['name']}: Chunk {chunk_num + 1} found {chunk_orphans} orphaned UPCs")

                            # Process orphaned records found in this chunk
                            for row in chunk_rows:
                                pk, product_id, description, upc = row[0], row[1], row[2], row[3]

                                orphan_record = {
                                    "table_name": table["name"],
                                    "primary_key": pk,
                                    "upc": upc,
                                    "product_id": product_id,
                                    "description": description if description else "Unknown"
                                }
                                table_orphans.append(orphan_record)
                                orphaned_records.append(orphan_record)

                            # Update progress
                            records_checked = min((chunk_num + 1) * CHUNK_SIZE, total_records)

                            # Send chunk progress event
                            if progress_callback:
                                progress_callback({
                                    "status": "chunk_progress",
                                    "table_name": table["name"],
                                    "chunk": chunk_num + 1,
                                    "total_chunks": total_chunks,
                                    "records_checked": records_checked,
                                    "total_records": total_records,
                                    "orphans_in_chunk": chunk_orphans,
                                    "total_orphans": len(table_orphans)
                                })

                        tables_checked += 1

                        # Notify table complete
                        if progress_callback:
                            progress_callback({
                                "status": "table_complete",
                                "table_name": table["name"],
                                "orphaned_count": len(table_orphans)
                            })

                    except pyodbc.Error:
                        # Table doesn't exist, skip it
                        if progress_callback:
                            progress_callback({
                                "status": "table_skipped",
                                "table_name": table["name"]
                            })
                        continue

            cursor.close()

        return True, None, orphaned_records, tables_checked

    except pyodbc.Error as e:
        error_msg = str(e)
        return False, error_msg, [], 0
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", [], 0

async def audit_orphaned_upcs(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    progress_callback: Optional[callable] = None,
    tds_version: str = "7.4",
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    target_host: Optional[str] = None,
    target_port: Optional[int] = None,
    target_database: Optional[str] = None,
    target_username: Optional[str] = None,
    target_password: Optional[str] = None
) -> tuple[bool, Optional[str], List[Dict[str, Any]], int]:
    """
    Async wrapper for orphaned UPC audit.

    Supports cross-database comparison: when target connection parameters are provided,
    UPCs from source database detail tables are checked against target database's Items_tbl.

    Args:
        host: Source server hostname or IP
        port: Source server port
        database: Source database name
        username: Source SQL Server username
        password: Source SQL Server password
        progress_callback: Optional callback for progress updates
        tds_version: TDS protocol version
        date_from: Optional start date for filtering (inclusive)
        date_to: Optional end date for filtering (inclusive)
        target_host: Optional target server hostname for cross-database comparison
        target_port: Optional target server port
        target_database: Optional target database name
        target_username: Optional target SQL Server username
        target_password: Optional target SQL Server password

    Returns:
        Tuple of (success: bool, error_message: Optional[str], orphaned_records: List[Dict], tables_checked: int)
    """
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        return await loop.run_in_executor(
            executor,
            _audit_orphaned_upcs_sync,
            host,
            port,
            database,
            username,
            password,
            progress_callback,
            tds_version,
            date_from,
            date_to,
            target_host,
            target_port,
            target_database,
            target_username,
            target_password
        )

def find_matches_by_product_id_sync(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    orphaned_records: List[Dict[str, Any]],
    tds_version: str = "7.4",
    progress_callback: Optional[callable] = None
) -> tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """
    Find matching UPCs in Items_tbl by ProductID for orphaned records using batch queries.

    Args:
        host: Server hostname or IP
        port: Server port
        database: Database name
        username: SQL Server username
        password: SQL Server password
        orphaned_records: List of orphaned UPC records with product_id
        tds_version: TDS protocol version
        progress_callback: Optional callback function to report progress

    Returns:
        Tuple of (success: bool, error_message: Optional[str], matches: List[Dict])
    """
    try:
        conn_string = get_mssql_connection_string(
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            tds_version=tds_version
        )

        matches = []
        total_records = len(orphaned_records)
        BATCH_SIZE = 500

        with pyodbc.connect(conn_string, timeout=30) as conn:
            cursor = conn.cursor()

            # Process records in batches
            for batch_start in range(0, total_records, BATCH_SIZE):
                batch_end = min(batch_start + BATCH_SIZE, total_records)
                batch = orphaned_records[batch_start:batch_end]

                # Separate records with valid ProductIDs from those without
                records_with_ids = []
                records_without_ids = []

                for record in batch:
                    product_id = record.get("product_id")
                    if product_id is None:
                        records_without_ids.append(record)
                    else:
                        records_with_ids.append(record)

                # Handle records without ProductID
                for record in records_without_ids:
                    matches.append({
                        "table_name": record["table_name"],
                        "primary_key": record["primary_key"],
                        "orphaned_upc": record["upc"],
                        "match_found": False,
                        "items_tbl_upc": None,
                        "match_field_value": "N/A"
                    })

                # Batch query for records with ProductIDs
                if records_with_ids:
                    # Extract unique ProductIDs for query
                    product_ids = [rec["product_id"] for rec in records_with_ids]

                    # Build IN clause with placeholders
                    placeholders = ",".join(["?"] * len(product_ids))
                    query = f"""
                        SELECT ProductID, ProductUPC
                        FROM Items_tbl
                        WHERE ProductID IN ({placeholders})
                    """

                    # Execute batch query
                    cursor.execute(query, product_ids)
                    results = cursor.fetchall()

                    # Build lookup dictionary: ProductID -> ProductUPC
                    upc_lookup = {row[0]: row[1] for row in results if row[1]}

                    # Map results back to individual records
                    for record in records_with_ids:
                        product_id = record["product_id"]
                        items_upc = upc_lookup.get(product_id)

                        if items_upc:
                            # Match found
                            matches.append({
                                "table_name": record["table_name"],
                                "primary_key": record["primary_key"],
                                "orphaned_upc": record["upc"],
                                "match_found": True,
                                "items_tbl_upc": items_upc,
                                "match_field_value": str(product_id)
                            })
                        else:
                            # No match
                            matches.append({
                                "table_name": record["table_name"],
                                "primary_key": record["primary_key"],
                                "orphaned_upc": record["upc"],
                                "match_found": False,
                                "items_tbl_upc": None,
                                "match_field_value": str(product_id)
                            })

                # Report progress after batch
                if progress_callback:
                    batch_matched = sum(1 for m in matches[batch_start:] if m["match_found"])
                    progress_callback({
                        "status": "checked",
                        "current": batch_end,
                        "total": total_records,
                        "matched": batch_matched > 0
                    })

            cursor.close()

        return True, None, matches

    except pyodbc.Error as e:
        error_msg = str(e)
        return False, error_msg, []
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", []

def find_matches_by_description_sync(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    orphaned_records: List[Dict[str, Any]],
    tds_version: str = "7.4",
    progress_callback: Optional[callable] = None
) -> tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """
    Find matching UPCs in Items_tbl by ProductDescription for orphaned records using batch queries.

    Args:
        host: Server hostname or IP
        port: Server port
        database: Database name
        username: SQL Server username
        password: SQL Server password
        orphaned_records: List of orphaned UPC records with description
        tds_version: TDS protocol version
        progress_callback: Optional callback function to report progress

    Returns:
        Tuple of (success: bool, error_message: Optional[str], matches: List[Dict])
    """
    try:
        conn_string = get_mssql_connection_string(
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            tds_version=tds_version
        )

        matches = []
        total_records = len(orphaned_records)
        BATCH_SIZE = 500

        with pyodbc.connect(conn_string, timeout=30) as conn:
            cursor = conn.cursor()

            # Process records in batches
            for batch_start in range(0, total_records, BATCH_SIZE):
                batch_end = min(batch_start + BATCH_SIZE, total_records)
                batch = orphaned_records[batch_start:batch_end]

                # Separate records with valid descriptions from those without
                records_with_desc = []
                records_without_desc = []

                for record in batch:
                    description = record.get("description")
                    if not description or description == "Unknown":
                        records_without_desc.append(record)
                    else:
                        records_with_desc.append(record)

                # Handle records without valid description
                for record in records_without_desc:
                    matches.append({
                        "table_name": record["table_name"],
                        "primary_key": record["primary_key"],
                        "orphaned_upc": record["upc"],
                        "match_found": False,
                        "items_tbl_upc": None,
                        "match_field_value": "N/A"
                    })

                # Batch query for records with descriptions
                if records_with_desc:
                    # Extract descriptions for query
                    descriptions = [rec["description"] for rec in records_with_desc]

                    # Build IN clause with placeholders
                    placeholders = ",".join(["?"] * len(descriptions))
                    query = f"""
                        SELECT ProductDescription, ProductUPC
                        FROM Items_tbl
                        WHERE ProductDescription IN ({placeholders})
                    """

                    # Execute batch query
                    cursor.execute(query, descriptions)
                    results = cursor.fetchall()

                    # Build lookup dictionary: ProductDescription -> ProductUPC
                    upc_lookup = {row[0]: row[1] for row in results if row[1]}

                    # Map results back to individual records
                    for record in records_with_desc:
                        description = record["description"]
                        items_upc = upc_lookup.get(description)

                        if items_upc:
                            # Match found
                            matches.append({
                                "table_name": record["table_name"],
                                "primary_key": record["primary_key"],
                                "orphaned_upc": record["upc"],
                                "match_found": True,
                                "items_tbl_upc": items_upc,
                                "match_field_value": description
                            })
                        else:
                            # No match
                            matches.append({
                                "table_name": record["table_name"],
                                "primary_key": record["primary_key"],
                                "orphaned_upc": record["upc"],
                                "match_found": False,
                                "items_tbl_upc": None,
                                "match_field_value": description
                            })

                # Report progress after batch
                if progress_callback:
                    batch_matched = sum(1 for m in matches[batch_start:] if m["match_found"])
                    progress_callback({
                        "status": "checked",
                        "current": batch_end,
                        "total": total_records,
                        "matched": batch_matched > 0
                    })

            cursor.close()

        return True, None, matches

    except pyodbc.Error as e:
        error_msg = str(e)
        return False, error_msg, []
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", []

def update_orphaned_upcs_sync(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    updates: List[Dict[str, Any]],
    tds_version: str = "7.4"
) -> tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """
    Update orphaned UPCs with matched values from Items_tbl.

    Args:
        host: Server hostname or IP
        port: Server port
        database: Database name
        username: SQL Server username
        password: SQL Server password
        updates: List of matched records to update
        tds_version: TDS protocol version

    Returns:
        Tuple of (success: bool, error_message: Optional[str], results: List[Dict])
    """
    try:
        conn_string = get_mssql_connection_string(
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            tds_version=tds_version
        )

        results = []

        with pyodbc.connect(conn_string, timeout=30) as conn:
            cursor = conn.cursor()

            for update in updates:
                table_name = update["table_name"]
                primary_key = update["primary_key"]
                new_upc = update["items_tbl_upc"]

                # Determine primary key field name based on table
                if table_name == "Items_tbl":
                    pk_field = "ProductID"
                elif table_name == "QuotationDetails":
                    pk_field = "id"
                else:
                    pk_field = "LineID"

                try:
                    # Update query
                    query = f"""
                        UPDATE {table_name}
                        SET ProductUPC = ?
                        WHERE {pk_field} = ?
                    """

                    cursor.execute(query, (new_upc, primary_key))
                    conn.commit()

                    results.append({
                        "table_name": table_name,
                        "primary_key": primary_key,
                        "success": True,
                        "updated_upc": new_upc,
                        "error": None
                    })
                except pyodbc.Error as e:
                    results.append({
                        "table_name": table_name,
                        "primary_key": primary_key,
                        "success": False,
                        "updated_upc": None,
                        "error": str(e)
                    })

            cursor.close()

        return True, None, results

    except pyodbc.Error as e:
        error_msg = str(e)
        return False, error_msg, []
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", []

async def find_matches_by_product_id(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    orphaned_records: List[Dict[str, Any]],
    tds_version: str = "7.4"
) -> tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """Async wrapper for find_matches_by_product_id."""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        return await loop.run_in_executor(
            executor,
            find_matches_by_product_id_sync,
            host,
            port,
            database,
            username,
            password,
            orphaned_records,
            tds_version
        )

async def find_matches_by_description(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    orphaned_records: List[Dict[str, Any]],
    tds_version: str = "7.4"
) -> tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """Async wrapper for find_matches_by_description."""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        return await loop.run_in_executor(
            executor,
            find_matches_by_description_sync,
            host,
            port,
            database,
            username,
            password,
            orphaned_records,
            tds_version
        )

async def update_orphaned_upcs(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    updates: List[Dict[str, Any]],
    tds_version: str = "7.4"
) -> tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """Async wrapper for update_orphaned_upcs."""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        return await loop.run_in_executor(
            executor,
            update_orphaned_upcs_sync,
            host,
            port,
            database,
            username,
            password,
            updates,
            tds_version
        )

def get_categories_sync(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    tds_version: str = "7.4"
) -> tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """
    Fetch all categories from Categories_tbl.

    Args:
        host: Server hostname or IP
        port: Server port
        database: Database name
        username: SQL Server username
        password: SQL Server password
        tds_version: TDS protocol version

    Returns:
        Tuple of (success: bool, error_message: Optional[str], categories: List[Dict])
    """
    try:
        conn_string = get_mssql_connection_string(
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            tds_version=tds_version
        )

        categories = []

        with pyodbc.connect(conn_string, timeout=30) as conn:
            cursor = conn.cursor()

            try:
                query = """
                    SELECT CategoryID, CategoryName
                    FROM Categories_tbl
                    ORDER BY CategoryName
                """

                cursor.execute(query)
                rows = cursor.fetchall()

                for row in rows:
                    categories.append({
                        "category_id": row[0],
                        "category_name": row[1]
                    })

            except pyodbc.Error:
                # Table doesn't exist in this database
                pass

            cursor.close()

        return True, None, categories

    except pyodbc.Error as e:
        error_msg = str(e)
        return False, error_msg, []
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", []

def get_subcategories_sync(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    category_id: Optional[int] = None,
    tds_version: str = "7.4"
) -> tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """
    Fetch subcategories from SubCategories_tbl, optionally filtered by CategoryID.

    Args:
        host: Server hostname or IP
        port: Server port
        database: Database name
        username: SQL Server username
        password: SQL Server password
        category_id: Optional CategoryID to filter subcategories
        tds_version: TDS protocol version

    Returns:
        Tuple of (success: bool, error_message: Optional[str], subcategories: List[Dict])
    """
    try:
        conn_string = get_mssql_connection_string(
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            tds_version=tds_version
        )

        subcategories = []

        with pyodbc.connect(conn_string, timeout=30) as conn:
            cursor = conn.cursor()

            try:
                if category_id is not None:
                    query = """
                        SELECT SubCateID, SubCateName, CategoryID
                        FROM SubCategories_tbl
                        WHERE CategoryID = ?
                        ORDER BY SubCateName
                    """
                    cursor.execute(query, (category_id,))
                else:
                    query = """
                        SELECT SubCateID, SubCateName, CategoryID
                        FROM SubCategories_tbl
                        ORDER BY SubCateName
                    """
                    cursor.execute(query)

                rows = cursor.fetchall()

                for row in rows:
                    subcategories.append({
                        "subcategory_id": row[0],
                        "subcategory_name": row[1],
                        "category_id": row[2]
                    })

            except pyodbc.Error:
                # Table doesn't exist in this database
                pass

            cursor.close()

        return True, None, subcategories

    except pyodbc.Error as e:
        error_msg = str(e)
        return False, error_msg, []
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", []

async def get_categories(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    tds_version: str = "7.4"
) -> tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """Async wrapper for get_categories_sync."""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        return await loop.run_in_executor(
            executor,
            get_categories_sync,
            host,
            port,
            database,
            username,
            password,
            tds_version
        )

async def get_subcategories(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    category_id: Optional[int] = None,
    tds_version: str = "7.4"
) -> tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """Async wrapper for get_subcategories_sync."""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        return await loop.run_in_executor(
            executor,
            get_subcategories_sync,
            host,
            port,
            database,
            username,
            password,
            category_id,
            tds_version
        )

def compare_stores_sync(
    primary_host: str,
    primary_port: int,
    primary_database: str,
    primary_username: str,
    primary_password: str,
    comparison_host: str,
    comparison_port: int,
    comparison_database: str,
    comparison_username: str,
    comparison_password: str,
    category_ids: Optional[List[int]] = None,
    subcategory_ids: Optional[List[int]] = None,
    include_discontinued: bool = False,
    progress_callback: Optional[callable] = None,
    tds_version: str = "7.4"
) -> tuple[bool, Optional[str], List[Dict[str, Any]], int]:
    """
    Compare Items_tbl between two MSSQL stores using chunked processing.

    Finds products in primary store that don't exist in comparison store (by ProductUPC).
    Supports filtering by categories, subcategories, and discontinued status.

    Args:
        primary_host: Primary store hostname
        primary_port: Primary store port
        primary_database: Primary store database name
        primary_username: Primary store username
        primary_password: Primary store password
        comparison_host: Comparison store hostname
        comparison_port: Comparison store port
        comparison_database: Comparison store database name
        comparison_username: Comparison store username
        comparison_password: Comparison store password
        category_ids: Optional list of CategoryID to filter (OR condition)
        subcategory_ids: Optional list of SubCateID to filter (OR condition)
        include_discontinued: If False, only active products (Discontinued=0). If True, include both active and discontinued.
        progress_callback: Optional callback for progress updates
        tds_version: TDS protocol version

    Returns:
        Tuple of (success: bool, error_message: Optional[str], missing_products: List[Dict], total_checked: int)
    """
    try:
        # Connect to primary store
        primary_conn_string = get_mssql_connection_string(
            host=primary_host,
            port=primary_port,
            database=primary_database,
            username=primary_username,
            password=primary_password,
            tds_version=tds_version
        )

        # Connect to comparison store
        comparison_conn_string = get_mssql_connection_string(
            host=comparison_host,
            port=comparison_port,
            database=comparison_database,
            username=comparison_username,
            password=comparison_password,
            tds_version=tds_version
        )

        missing_products = []
        total_checked = 0

        with pyodbc.connect(primary_conn_string, timeout=60) as primary_conn, \
             pyodbc.connect(comparison_conn_string, timeout=60) as comparison_conn:

            primary_cursor = primary_conn.cursor()
            comparison_cursor = comparison_conn.cursor()

            # Build WHERE clause for filters
            where_clauses = ["i.ProductUPC IS NOT NULL", "i.ProductUPC != ''"]
            query_params = []

            # Category filter (OR condition)
            if category_ids and len(category_ids) > 0:
                placeholders = ",".join(["?"] * len(category_ids))
                where_clauses.append(f"i.CateID IN ({placeholders})")
                query_params.extend(category_ids)

            # Subcategory filter (OR condition)
            if subcategory_ids and len(subcategory_ids) > 0:
                placeholders = ",".join(["?"] * len(subcategory_ids))
                where_clauses.append(f"i.SubCateID IN ({placeholders})")
                query_params.extend(subcategory_ids)

            # Discontinued filter
            # If include_discontinued is False: only show active products (Discontinued=0 or NULL)
            # If include_discontinued is True: show both active and discontinued (no filter)
            if not include_discontinued:
                where_clauses.append("(i.Discontinued = 0 OR i.Discontinued IS NULL)")

            where_clause = " AND ".join(where_clauses)

            # Step 1: Get total count of products to check
            count_query = f"""
                SELECT COUNT(*) as total_products
                FROM Items_tbl i
                WHERE {where_clause}
            """

            primary_cursor.execute(count_query, query_params)
            count_result = primary_cursor.fetchone()
            total_products = count_result[0] if count_result else 0

            if total_products == 0:
                primary_cursor.close()
                comparison_cursor.close()
                return True, None, [], 0

            # Step 2: Calculate chunks
            total_chunks = max(1, (total_products + CHUNK_SIZE - 1) // CHUNK_SIZE)

            print(f"[COMPARISON DEBUG] Total products to check: {total_products}, chunks: {total_chunks}")

            # Notify start
            if progress_callback:
                progress_callback({
                    "status": "starting",
                    "total_products": total_products,
                    "total_chunks": total_chunks
                })

            # Step 3: Process products in chunks
            for chunk_num in range(total_chunks):
                offset = chunk_num * CHUNK_SIZE
                limit = CHUNK_SIZE

                # Chunked query with category and subcategory names
                chunk_query = f"""
                    WITH numbered_products AS (
                        SELECT
                            i.ProductID,
                            i.ProductUPC,
                            i.ProductDescription,
                            i.Discontinued,
                            c.CategoryName,
                            s.SubCateName,
                            ROW_NUMBER() OVER (ORDER BY i.ProductID) as row_num
                        FROM Items_tbl i
                        LEFT JOIN Categories_tbl c ON i.CateID = c.CategoryID
                        LEFT JOIN SubCategories_tbl s ON i.SubCateID = s.SubCateID
                        WHERE {where_clause}
                    )
                    SELECT ProductID, ProductUPC, ProductDescription, Discontinued, CategoryName, SubCateName
                    FROM numbered_products
                    WHERE row_num > ? AND row_num <= ?
                """

                start_row = offset
                end_row = offset + limit

                chunk_params = query_params + [start_row, end_row]

                print(f"[COMPARISON DEBUG] Chunk {chunk_num + 1}/{total_chunks}")
                print(f"[COMPARISON DEBUG] chunk_params length: {len(chunk_params)}, values: {chunk_params}")
                print(f"[COMPARISON DEBUG] query_params length: {len(query_params)}, values: {query_params}")

                try:
                    primary_cursor.execute(chunk_query, chunk_params)
                    chunk_products = primary_cursor.fetchall()
                    print(f"[COMPARISON DEBUG] Fetched {len(chunk_products)} products from primary store")
                except Exception as e:
                    print(f"[COMPARISON DEBUG] Error executing chunk query: {e}")
                    print(f"[COMPARISON DEBUG] Query: {chunk_query}")
                    raise

                chunk_missing = 0

                # If no products in this chunk, skip
                if not chunk_products:
                    continue

                # Collect all UPCs from this chunk, filtering out None and empty strings
                chunk_upcs = []
                for product in chunk_products:
                    upc = product[1]  # product[1] is ProductUPC
                    if upc and str(upc).strip():  # Skip None and empty/whitespace-only UPCs
                        chunk_upcs.append(str(upc).strip())

                total_checked += len(chunk_products)

                # If no valid UPCs in this chunk, skip comparison query
                if not chunk_upcs:
                    print(f"[COMPARISON DEBUG] No valid UPCs in chunk {chunk_num + 1}, skipping comparison")
                    continue

                # SQL Server has a limit of 2100 parameters per query
                # Batch the UPC comparison into smaller sub-chunks to avoid hitting the limit
                MAX_PARAMS_PER_QUERY = 2000  # Safe limit below SQL Server's 2100 max
                existing_upcs = set()

                print(f"[COMPARISON DEBUG] Comparing {len(chunk_upcs)} UPCs against comparison store")
                print(f"[COMPARISON DEBUG] First 5 UPCs: {chunk_upcs[:5]}")

                # Process UPCs in batches
                for batch_start in range(0, len(chunk_upcs), MAX_PARAMS_PER_QUERY):
                    batch_end = min(batch_start + MAX_PARAMS_PER_QUERY, len(chunk_upcs))
                    upc_batch = chunk_upcs[batch_start:batch_end]

                    placeholders = ','.join(['?'] * len(upc_batch))
                    comparison_query = f"SELECT ProductUPC FROM Items_tbl WHERE ProductUPC IN ({placeholders})"

                    try:
                        comparison_cursor.execute(comparison_query, upc_batch)
                        batch_results = {row[0].strip() if row[0] else '' for row in comparison_cursor.fetchall()}
                        existing_upcs.update(batch_results)
                        print(f"[COMPARISON DEBUG] Batch {batch_start}-{batch_end}: Found {len(batch_results)} matches")
                    except Exception as e:
                        print(f"[COMPARISON DEBUG] Error executing comparison query batch: {e}")
                        print(f"[COMPARISON DEBUG] Batch params count: {len(upc_batch)}")
                        raise

                print(f"[COMPARISON DEBUG] Total matching UPCs found: {len(existing_upcs)}")

                # Find missing products (products in primary but not in comparison)
                for product in chunk_products:
                    product_id, product_upc, product_description, discontinued, category_name, subcategory_name = product

                    # Normalize UPC for comparison (strip whitespace)
                    normalized_upc = str(product_upc).strip() if product_upc else ''

                    if normalized_upc and normalized_upc not in existing_upcs:
                        # Product is missing in comparison store
                        chunk_missing += 1
                        missing_products.append({
                            "product_id": product_id,
                            "product_upc": normalized_upc,
                            "product_description": product_description if product_description else "Unknown",
                            "category_name": category_name if category_name else "Uncategorized",
                            "subcategory_name": subcategory_name if subcategory_name else "None",
                            "discontinued": bool(discontinued) if discontinued else False
                        })

                # Send chunk progress
                if progress_callback:
                    progress_callback({
                        "status": "chunk_progress",
                        "chunk": chunk_num + 1,
                        "total_chunks": total_chunks,
                        "products_checked": total_checked,
                        "total_products": total_products,
                        "missing_in_chunk": chunk_missing,
                        "total_missing": len(missing_products)
                    })

            primary_cursor.close()
            comparison_cursor.close()

        return True, None, missing_products, total_checked

    except pyodbc.Error as e:
        error_msg = str(e)
        return False, error_msg, [], 0
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", [], 0

async def compare_stores(
    primary_host: str,
    primary_port: int,
    primary_database: str,
    primary_username: str,
    primary_password: str,
    comparison_host: str,
    comparison_port: int,
    comparison_database: str,
    comparison_username: str,
    comparison_password: str,
    category_ids: Optional[List[int]] = None,
    subcategory_ids: Optional[List[int]] = None,
    include_discontinued: bool = False,
    progress_callback: Optional[callable] = None,
    tds_version: str = "7.4"
) -> tuple[bool, Optional[str], List[Dict[str, Any]], int]:
    """Async wrapper for compare_stores_sync."""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        return await loop.run_in_executor(
            executor,
            compare_stores_sync,
            primary_host,
            primary_port,
            primary_database,
            primary_username,
            primary_password,
            comparison_host,
            comparison_port,
            comparison_database,
            comparison_username,
            comparison_password,
            category_ids,
            subcategory_ids,
            include_discontinued,
            progress_callback,
            tds_version
        )
