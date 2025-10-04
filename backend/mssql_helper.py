import pyodbc
from typing import Optional, List, Dict, Any
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Chunk size for processing large tables (prevents timeout)
CHUNK_SIZE = 5000

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

def _audit_orphaned_upcs_sync(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    progress_callback: Optional[callable] = None,
    tds_version: str = "7.4"
) -> tuple[bool, Optional[str], List[Dict[str, Any]], int]:
    """
    Synchronous audit of orphaned UPCs in MSSQL database using chunked processing.

    Checks all detail tables for UPCs that don't exist in Items_tbl.
    Processes tables in chunks to prevent timeout on large datasets.

    Args:
        host: Server hostname or IP
        port: Server port
        database: Database name
        username: SQL Server username
        password: SQL Server password
        progress_callback: Optional callback function for progress updates
        tds_version: TDS protocol version

    Returns:
        Tuple of (success: bool, error_message: Optional[str], orphaned_records: List[Dict], tables_checked: int)
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

        with pyodbc.connect(conn_string, timeout=60) as conn:
            cursor = conn.cursor()

            for table in detail_tables:
                try:
                    # Notify progress - starting table check
                    if progress_callback:
                        progress_callback({
                            "status": "checking_table",
                            "table_name": table["name"]
                        })

                    # Step 1: Get total record count
                    count_query = f"""
                        SELECT COUNT(*) as total_records
                        FROM {table['name']}
                        WHERE ProductUPC IS NOT NULL AND ProductUPC != ''
                    """

                    cursor.execute(count_query)
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
                                    {table['pk']},
                                    ProductID,
                                    {table['description_field']},
                                    ProductUPC,
                                    ROW_NUMBER() OVER (ORDER BY {table['pk']}) as row_num
                                FROM {table['name']}
                                WHERE ProductUPC IS NOT NULL AND ProductUPC != ''
                            )
                            SELECT n.{table['pk']}, n.ProductID, n.{table['description_field']}, n.ProductUPC
                            FROM numbered_records n
                            LEFT JOIN Items_tbl i ON n.ProductUPC = i.ProductUPC
                            WHERE n.row_num > ? AND n.row_num <= ?
                            AND i.ProductUPC IS NULL
                        """

                        start_row = offset
                        end_row = offset + limit

                        cursor.execute(chunk_query, (start_row, end_row))
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
    tds_version: str = "7.4"
) -> tuple[bool, Optional[str], List[Dict[str, Any]], int]:
    """
    Async wrapper for orphaned UPC audit.

    Args:
        host: Server hostname or IP
        port: Server port
        database: Database name
        username: SQL Server username
        password: SQL Server password
        progress_callback: Optional callback for progress updates
        tds_version: TDS protocol version

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
            tds_version
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
