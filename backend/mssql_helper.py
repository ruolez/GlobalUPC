import pyodbc
from typing import Optional, List, Dict, Any
import asyncio
from concurrent.futures import ThreadPoolExecutor

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
