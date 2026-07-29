from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Union, AsyncGenerator, Optional, Dict, Any
from pydantic import BaseModel
from contextlib import asynccontextmanager
from datetime import datetime, date, timedelta
import uvicorn
import asyncio
import json
import math
import statistics
import uuid
import os

from database import get_db, engine
from models import Store, MSSQLConnection, ShopifyConnection, Setting, StoreType, StoreCategory, UPCUpdateHistory, UPCExclusion, ItemTrackerConfig, ItemTrackerExclusion, PriceUpdateHistory, StoreMirror, SalesConfig, SalesExclusion
from schemas import (
    MSSQLStoreCreate, ShopifyStoreCreate, ShipperStoreCreate, MSSQLStoreUpdate, ShopifyStoreUpdate, ShipperStoreUpdate, StoreResponse, StoreNameUpdate, StoreCategoryUpdate,
    SettingCreate, SettingUpdate, SettingResponse,
    UPCSearchRequest, UPCSearchResponse, ProductVariantMatch,
    UPCUpdateRequest, UPCUpdateResult,
    ConfigExportResponse, ConfigImportRequest, ConfigImportResponse,
    StoreImportResult, StoreExport,
    OrphanedUPCAuditRequest, OrphanedUPCRecord, OrphanedUPCAuditResponse,
    ReconciliationRequest, ReconciliationMatch, ReconciliationResponse,
    ReconciliationUpdateRequest, ReconciliationUpdateResult, ReconciliationUpdateResponse,
    UPCUpdateHistoryResponse, UPCUpdateHistoryListRequest, UPCUpdateHistoryListResponse,
    UPCExclusionCreate, UPCExclusionResponse, UPCExclusionListResponse,
    ItemTrackerConfigCreate, ItemTrackerConfigResponse, ItemTrackerSearchRequest,
    ItemInfo, ItemTrackerEvent, ItemTrackerSearchResponse,
    DescriptionAutocompleteRequest, DescriptionAutocompleteResult, DescriptionAutocompleteResponse,
    ItemTrackerExclusionCreate, ItemTrackerExclusionResponse, ItemTrackerExclusionListResponse,
    ItemTrackerSummaryItemInfo, ItemTrackerQuantityTotals, ItemTrackerSummaryResponse,
    PriceSearchRequest, StorePriceInfo, PriceUpdateItem, PriceUpdateRequest,
    PriceUpdateHistoryResponse, PriceUpdateHistoryBatch, PriceUpdateHistoryListResponse,
    StoreMirrorCreate, StoreMirrorResponse, StoreMirrorListResponse,
    ShopifySalesRequest,
    FulfillmentStatusResponse,
    SalesReportRequest,
    SalesConfigCreate, SalesConfigResponse,
    SalesExclusionCreate, SalesExclusionResponse, SalesExclusionListResponse,
    FirstCustomerReturnsRequest,
    ShopifyFirstOrderTagUpdate,
    NewCustomersByMonthRequest,
    LostCustomersRequest,
    CustomerDetailRequest,
    LostProductsRequest,
    QuotationsInProgressFilter, QuotationsInProgressListResponse,
    QuotationsInProgressFilterOptions, QuotationInProgressSummary,
    QuotationProductsResponse, QuotationInProgressHeader, QuotationProductLine,
    QuotationSearchProduct, QuotationSearchResponse,
    DashboardStatsResponse, DashboardStoreStats, DashboardExclusionCounts,
    DashboardMirrorStats, DashboardBatchSummary, DashboardInProgressStats,
    DashboardConfigCheck,
    InventoryTimeRequest, InventoryTimeResponse, InventoryTimeSession,
    InventoryTimeUsersResponse,
    CheckedOrdersRequest, CheckedOrdersResponse, CheckedOrder,
    CheckedOrderUser, CheckedOrdersUsersResponse,
)
from mssql_helper import (
    test_mssql_connection, search_upc_across_mssql_stores, search_products_by_upc,
    update_upc_across_mssql_stores, audit_orphaned_upcs,
    find_matches_by_product_id, find_matches_by_description, update_orphaned_upcs,
    check_upc_exists,
    get_item_prices_async, update_item_prices_async,
    get_item_prices_batch_async,
    get_active_products_async, get_aggregated_sales_async, get_aggregated_returns_async,
    search_business_names_async
)
from shopify_helper import (
    test_shopify_connection, search_barcode_across_shopify_stores,
    search_products_by_barcode, update_barcodes_across_shopify_stores,
    check_barcode_exists, search_product_prices_by_barcode, update_variant_prices,
    get_all_product_variant_prices, search_product_prices_with_siblings,
    fetch_fulfilled_orders,
    fetch_orders_with_tag, fetch_customer_orders_after,
    count_fulfillment_buckets_for_store,
    fetch_customers_with_last_order, fetch_customer_recent_orders,
    fetch_orders_line_items, fetch_baseline_order_items, count_orders,
    fetch_customer_first_orders, fetch_customers_by_emails, normalize_email,
    ORDER_STATUS_FILTER
)
from item_tracker_helper import (
    get_item_info_async, get_purchases_async, get_sales_async,
    get_customer_returns_async, get_vendor_returns_async,
    search_products_by_description_async, get_inventory_recounts_async,
    get_in_progress_async,
)
from quotations_in_progress_helper import (
    list_quotations_in_progress_async,
    get_quotation_products_async,
    list_distinct_filter_values_async,
    search_products_async,
    count_in_progress_async,
)
from inventory_time_helper import (
    fetch_recount_timestamps_async,
    fetch_distinct_usernames_async,
    compute_inventory_time,
)
from checked_orders_helper import (
    fetch_checkers_async,
    fetch_checked_orders_async,
    compute_checked_orders,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    print("[SHUTDOWN] Disposing database connections...")
    engine.dispose()
    print("[SHUTDOWN] Shutting down MSSQL thread pool...")
    from mssql_helper import shutdown_mssql_executor
    shutdown_mssql_executor()
    print("[SHUTDOWN] Shutting down Item Tracker thread pool...")
    from item_tracker_helper import shutdown_item_tracker_executor
    shutdown_item_tracker_executor()
    print("[SHUTDOWN] Shutting down Quotations-In-Progress thread pool...")
    from quotations_in_progress_helper import shutdown_qip_executor
    shutdown_qip_executor()
    print("[SHUTDOWN] Shutting down Inventory Time thread pool...")
    from inventory_time_helper import shutdown_inv_time_executor
    shutdown_inv_time_executor()
    print("[SHUTDOWN] Shutting down Checked Orders thread pool...")
    from checked_orders_helper import shutdown_chkord_executor
    shutdown_chkord_executor()
    print("[SHUTDOWN] Cleanup complete.")

app = FastAPI(title="Global UPC API", version="1.0.0", lifespan=lifespan)

# Read SERVER_IP from environment variable
SERVER_IP = os.getenv("SERVER_IP", "localhost")
FRONTEND_PORT = os.getenv("FRONTEND_PORT", "8080")
ALLOWED_IFRAME_ORIGINS = os.getenv("ALLOWED_IFRAME_ORIGINS", "")

# Build CORS origins list
cors_origins = [
    f"http://{SERVER_IP}:{FRONTEND_PORT}",
    f"http://localhost:{FRONTEND_PORT}",
    "http://localhost:8080",  # Fallback for development
]

# Add iframe origins if configured
if ALLOWED_IFRAME_ORIGINS:
    iframe_origins = [origin.strip() for origin in ALLOWED_IFRAME_ORIGINS.split(",") if origin.strip()]
    cors_origins.extend(iframe_origins)

# Remove duplicates while preserving order
cors_origins = list(dict.fromkeys(cors_origins))

# Allow all origins when explicitly configured
if os.getenv("CORS_ALLOW_ALL", "").lower() == "true":
    cors_origins = ["*"]

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check
@app.get("/api/health")
def health_check():
    return {"status": "healthy", "service": "Global UPC API"}

# Connection test schemas
class MSSQLConnectionTest(BaseModel):
    host: str
    port: int = 1433
    database_name: str
    username: str
    password: str
    tds_version: str = "7.4"

class ShopifyConnectionTest(BaseModel):
    shop_domain: str
    admin_api_key: str
    api_version: str = "2025-01"

# Connection test endpoints
@app.post("/api/test/mssql")
def test_mssql(connection: MSSQLConnectionTest):
    """Test MSSQL database connection"""
    success, error = test_mssql_connection(
        host=connection.host,
        port=connection.port,
        database=connection.database_name,
        username=connection.username,
        password=connection.password,
        tds_version=connection.tds_version
    )

    if success:
        return {
            "success": True,
            "message": "Connection successful! Database is reachable."
        }
    else:
        return {
            "success": False,
            "message": error or "Connection failed"
        }

@app.post("/api/test/shopify")
def test_shopify(connection: ShopifyConnectionTest):
    """Test Shopify store connection"""
    success, error, shop_info = test_shopify_connection(
        shop_domain=connection.shop_domain,
        admin_api_key=connection.admin_api_key,
        api_version=connection.api_version
    )

    if success:
        return {
            "success": True,
            "message": f"Connection successful! Connected to: {shop_info.get('name', 'Unknown')}",
            "shop_info": shop_info
        }
    else:
        return {
            "success": False,
            "message": error or "Connection failed"
        }

# UPC Search/Update endpoints
@app.post("/api/upc/search/stream")
async def search_upc_stream(request: UPCSearchRequest, db: Session = Depends(get_db)):
    """
    Search for a UPC/barcode across all active stores with real-time progress updates.
    Returns Server-Sent Events stream.
    """
    async def generate_search_events() -> AsyncGenerator[str, None]:
        upc = request.upc.strip()

        if not upc:
            yield f"event: error\ndata: {json.dumps({'message': 'UPC is required'})}\n\n"
            return

        # Get all active stores
        active_stores = db.query(Store).filter(Store.is_active == True).all()

        if not active_stores:
            yield f"event: complete\ndata: {json.dumps({'upc': upc, 'matches': [], 'total_found': 0, 'stores_searched': 0})}\n\n"
            return

        # Separate stores by type
        shopify_stores = []
        mssql_stores = []

        for store in active_stores:
            if store.store_type == StoreType.shopify and store.shopify_connection:
                shopify_stores.append({
                    "id": store.id,
                    "name": store.name,
                    "shop_domain": store.shopify_connection.shop_domain,
                    "admin_api_key": store.shopify_connection.admin_api_key,
                    "api_version": store.shopify_connection.api_version
                })
            elif store.store_type == StoreType.mssql and store.mssql_connection:
                mssql_stores.append({
                    "id": store.id,
                    "name": store.name,
                    "host": store.mssql_connection.host,
                    "port": store.mssql_connection.port,
                    "database_name": store.mssql_connection.database_name,
                    "username": store.mssql_connection.username,
                    "password": store.mssql_connection.password
                })

        all_matches = []
        tasks = []

        try:
            # Search Shopify stores in parallel
            if shopify_stores:
                yield f"event: progress\ndata: {json.dumps({'status': 'searching', 'store_type': 'shopify', 'count': len(shopify_stores)})}\n\n"

                # Create search tasks for all Shopify stores
                async def search_shopify_store(store):
                    """Search single Shopify store and return store info + results."""
                    success, error, variants = await search_products_by_barcode(
                        shop_domain=store["shop_domain"],
                        admin_api_key=store["admin_api_key"],
                        barcode=upc,
                        api_version=store.get("api_version", "2025-01")
                    )
                    return store, success, error, variants

                # Start all store searches in parallel
                tasks = [asyncio.create_task(search_shopify_store(store)) for store in shopify_stores]

                # Process results as each store completes
                for completed_task in asyncio.as_completed(tasks):
                    store, success, error, variants = await completed_task

                    yield f"event: progress\ndata: {json.dumps({'status': 'searching_store', 'store_name': store['name'], 'store_type': 'shopify'})}\n\n"

                    if success and variants:
                        for variant in variants:
                            match = {
                                "store_id": store["id"],
                                "store_name": store["name"],
                                "store_type": "shopify",
                                "product_id": variant["product_id"],
                                "product_title": variant["product_title"],
                                "variant_id": variant["variant_id"],
                                "variant_title": variant["variant_title"],
                                "current_barcode": variant["barcode"],
                                "sku": variant["sku"]
                            }
                            all_matches.append(match)

                    yield f"event: progress\ndata: {json.dumps({'status': 'completed_store', 'store_name': store['name'], 'found': len(variants) if success else 0})}\n\n"

            # Search MSSQL stores in parallel
            if mssql_stores:
                print(f"[SEARCH] Starting MSSQL search for {len(mssql_stores)} stores")
                yield f"event: progress\ndata: {json.dumps({'status': 'searching', 'store_type': 'mssql', 'count': len(mssql_stores)})}\n\n"

                # Create search tasks for all MSSQL stores
                async def search_mssql_store(store):
                    """Search single MSSQL store and return store info + results."""
                    success, error, table_results = await search_products_by_upc(
                        host=store["host"],
                        port=store["port"],
                        database=store["database_name"],
                        username=store["username"],
                        password=store["password"],
                        upc=upc
                    )
                    return store, success, error, table_results

                # Start all store searches in parallel
                tasks = [asyncio.create_task(search_mssql_store(store)) for store in mssql_stores]

                # Track completed stores for logging
                completed_count = 0

                # Process results as each store completes
                for completed_task in asyncio.as_completed(tasks):
                    store, success, error, table_results = await completed_task
                    completed_count += 1

                    print(f"[SEARCH] MSSQL store {completed_count}/{len(mssql_stores)}: {store['name']}")
                    yield f"event: progress\ndata: {json.dumps({'status': 'searching_store', 'store_name': store['name'], 'store_type': 'mssql'})}\n\n"

                    if success and table_results:
                        for table_result in table_results:
                            # Send progress for each table found
                            yield f"event: progress\ndata: {json.dumps({'status': 'found_in_table', 'table_name': table_result['table_name'], 'count': table_result['match_count']})}\n\n"

                            match = {
                                "store_id": store["id"],
                                "store_name": store["name"],
                                "store_type": "mssql",
                                "product_id": str(table_result["primary_keys"][0]) if table_result["primary_keys"] else "",
                                "product_title": table_result["product_description"],
                                "variant_id": None,
                                "variant_title": None,
                                "current_barcode": table_result["upc"],
                                "sku": None,
                                "table_name": table_result["table_name"],
                                "match_count": table_result["match_count"],
                                "primary_keys": table_result["primary_keys"]
                            }
                            all_matches.append(match)

                    yield f"event: progress\ndata: {json.dumps({'status': 'completed_store', 'store_name': store['name'], 'found': len(table_results) if success else 0})}\n\n"

                print(f"[SEARCH] Completed MSSQL search for all {len(mssql_stores)} stores")

            # Send final results
            print(f"[SEARCH] Search complete - found {len(all_matches)} total matches")
            yield f"event: complete\ndata: {json.dumps({'upc': upc, 'matches': all_matches, 'total_found': len(all_matches), 'stores_searched': len(active_stores)})}\n\n"

        except GeneratorExit:
            print("[SEARCH] Client disconnected, cancelling search")
            for task in tasks:
                if not task.done():
                    task.cancel()
            return
        except Exception as e:
            print(f"[SEARCH] Error: {e}")
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return StreamingResponse(
        generate_search_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

@app.post("/api/upc/search", response_model=UPCSearchResponse)
async def search_upc(request: UPCSearchRequest, db: Session = Depends(get_db)):
    """
    Search for a UPC/barcode across all active stores (Shopify and MSSQL).
    Returns list of all products/variants containing this barcode.
    Legacy endpoint - use /api/upc/search/stream for progress updates.
    """
    upc = request.upc.strip()

    if not upc:
        raise HTTPException(status_code=400, detail="UPC is required")

    # Get all active stores
    active_stores = db.query(Store).filter(Store.is_active == True).all()

    if not active_stores:
        return UPCSearchResponse(
            upc=upc,
            matches=[],
            total_found=0,
            stores_searched=0
        )

    # Separate stores by type
    shopify_stores = []
    mssql_stores = []

    for store in active_stores:
        if store.store_type == StoreType.shopify and store.shopify_connection:
            shopify_stores.append({
                "id": store.id,
                "name": store.name,
                "shop_domain": store.shopify_connection.shop_domain,
                "admin_api_key": store.shopify_connection.admin_api_key,
                "api_version": store.shopify_connection.api_version
            })
        elif store.store_type == StoreType.mssql and store.mssql_connection:
            mssql_stores.append({
                "id": store.id,
                "name": store.name,
                "host": store.mssql_connection.host,
                "port": store.mssql_connection.port,
                "database_name": store.mssql_connection.database_name,
                "username": store.mssql_connection.username,
                "password": store.mssql_connection.password
            })

    # Search across all stores in parallel
    all_matches = []

    # Search Shopify stores
    if shopify_stores:
        shopify_results = await search_barcode_across_shopify_stores(shopify_stores, upc)
        all_matches.extend(shopify_results)

    # Search MSSQL stores
    if mssql_stores:
        mssql_results = await search_upc_across_mssql_stores(mssql_stores, upc)
        all_matches.extend(mssql_results)

    return UPCSearchResponse(
        upc=upc,
        matches=all_matches,
        total_found=len(all_matches),
        stores_searched=len(active_stores)
    )

@app.post("/api/upc/update/stream")
async def update_upc_stream(request: UPCUpdateRequest, db: Session = Depends(get_db)):
    """
    Update UPC/barcode across all stores with real-time progress updates.
    Returns Server-Sent Events stream.
    """
    async def generate_update_events() -> AsyncGenerator[str, None]:
        old_upc = request.old_upc.strip()
        new_upc = request.new_upc.strip()
        matches = request.matches

        if not old_upc or not new_upc:
            yield f"event: error\ndata: {json.dumps({'message': 'Both old and new UPC are required'})}\n\n"
            return

        if not matches:
            yield f"event: error\ndata: {json.dumps({'message': 'No matches provided for update'})}\n\n"
            return

        # Generate batch ID for this update operation
        batch_id = str(uuid.uuid4())

        # Group matches by store and type
        from collections import defaultdict

        # Shopify: group by store_id, then by product_id
        shopify_store_updates = defaultdict(lambda: {
            "store_id": None,
            "store_name": None,
            "shop_domain": None,
            "admin_api_key": None,
            "api_version": None,
            "update_sku": False,
            "products": defaultdict(list)
        })

        # MSSQL: group by store_id, then by table_name
        mssql_store_updates = defaultdict(lambda: {
            "store_id": None,
            "store_name": None,
            "host": None,
            "port": None,
            "database_name": None,
            "username": None,
            "password": None,
            "tables": defaultdict(lambda: {
                "table_name": None,
                "primary_key_field": None,
                "primary_keys": [],
                "new_upc": new_upc
            })
        })

        # Process matches and group by store
        for match in matches:
            store_id = match.store_id
            store_name = match.store_name
            store_type = match.store_type

            if store_type == "shopify":
                # Get store connection details
                store = db.query(Store).filter(Store.id == store_id).first()
                if not store or not store.shopify_connection:
                    continue

                # Initialize store data if needed
                if shopify_store_updates[store_id]["store_id"] is None:
                    shopify_store_updates[store_id].update({
                        "store_id": store_id,
                        "store_name": store_name,
                        "shop_domain": store.shopify_connection.shop_domain,
                        "admin_api_key": store.shopify_connection.admin_api_key,
                        "api_version": store.shopify_connection.api_version,
                        "update_sku": store.shopify_connection.update_sku_with_barcode
                    })

                # Group variants by product_id
                product_id = match.product_id
                variant_id = match.variant_id

                shopify_store_updates[store_id]["products"][product_id].append({
                    "id": variant_id,
                    "barcode": new_upc
                })

            elif store_type == "mssql":
                # Get store connection details
                store = db.query(Store).filter(Store.id == store_id).first()
                if not store or not store.mssql_connection:
                    continue

                # Initialize store data if needed
                if mssql_store_updates[store_id]["store_id"] is None:
                    mssql_store_updates[store_id].update({
                        "store_id": store_id,
                        "store_name": store_name,
                        "host": store.mssql_connection.host,
                        "port": store.mssql_connection.port,
                        "database_name": store.mssql_connection.database_name,
                        "username": store.mssql_connection.username,
                        "password": store.mssql_connection.password
                    })

                # Group by table_name
                table_name = match.table_name
                primary_keys = match.primary_keys

                # Determine primary key field based on table
                if table_name == "Items_tbl":
                    pk_field = "ProductID"
                elif table_name in ["QuotationDetails", "Items_BinLocations"]:
                    pk_field = "id"
                else:
                    pk_field = "LineID"

                if mssql_store_updates[store_id]["tables"][table_name]["table_name"] is None:
                    mssql_store_updates[store_id]["tables"][table_name].update({
                        "table_name": table_name,
                        "primary_key_field": pk_field,
                        "new_upc": new_upc
                    })

                mssql_store_updates[store_id]["tables"][table_name]["primary_keys"].extend(primary_keys)

        all_results = []
        total_updated = 0

        # Update Shopify stores
        if shopify_store_updates:
            yield f"event: progress\ndata: {json.dumps({'status': 'updating', 'store_type': 'shopify', 'count': len(shopify_store_updates)})}\n\n"

            # Convert to list format for update function
            shopify_updates_list = []
            for store_id, store_data in shopify_store_updates.items():
                products_list = []
                for product_id, variants in store_data["products"].items():
                    products_list.append({
                        "product_id": product_id,
                        "variants": variants
                    })

                shopify_updates_list.append({
                    "store_id": store_data["store_id"],
                    "store_name": store_data["store_name"],
                    "shop_domain": store_data["shop_domain"],
                    "admin_api_key": store_data["admin_api_key"],
                    "api_version": store_data["api_version"],
                    "update_sku": store_data["update_sku"],
                    "products": products_list
                })

            # Update stores
            for store_update in shopify_updates_list:
                yield f"event: progress\ndata: {json.dumps({'status': 'validating_store', 'store_name': store_update['store_name'], 'store_type': 'shopify'})}\n\n"

                # Check if new UPC already exists in this store (duplicate validation)
                duplicate_check_success, duplicate_check_error, duplicate_variants = await check_barcode_exists(
                    shop_domain=store_update["shop_domain"],
                    admin_api_key=store_update["admin_api_key"],
                    barcode=new_upc,
                    api_version=store_update.get("api_version", "2025-01")
                )

                # If duplicate found, skip this store
                if duplicate_check_success and duplicate_variants and len(duplicate_variants) > 0:
                    skip_result = {
                        "store_id": store_update["store_id"],
                        "store_name": store_update["store_name"],
                        "success": False,
                        "skipped": True,
                        "skip_reason": "duplicate_found",
                        "updated_count": 0,
                        "error": f"UPC '{new_upc}' already exists in this store"
                    }
                    all_results.append(skip_result)

                    yield f"event: progress\ndata: {json.dumps({'status': 'skipped_store', 'store_name': store_update['store_name'], 'reason': 'duplicate_found'})}\n\n"

                    # Log skip to history
                    store_matches = [m for m in matches if m.store_id == store_update["store_id"]]
                    first_match = store_matches[0] if store_matches else None

                    history_entry = UPCUpdateHistory(
                        batch_id=batch_id,
                        store_id=store_update["store_id"],
                        store_name=store_update["store_name"],
                        store_type=StoreType.shopify,
                        old_upc=old_upc,
                        new_upc=new_upc,
                        product_id=first_match.product_id if first_match else None,
                        product_title=first_match.product_title if first_match else None,
                        variant_id=first_match.variant_id if first_match else None,
                        variant_title=first_match.variant_title if first_match else None,
                        success=False,
                        items_updated_count=0,
                        error_message=f"Skipped: UPC '{new_upc}' already exists in this store"
                    )
                    db.add(history_entry)
                    db.commit()

                    continue

                # No duplicate, proceed with update
                yield f"event: progress\ndata: {json.dumps({'status': 'updating_store', 'store_name': store_update['store_name'], 'store_type': 'shopify'})}\n\n"

                # Call update function for this store
                results = await update_barcodes_across_shopify_stores([store_update])

                for result in results:
                    result["skipped"] = False
                    all_results.append(result)
                    total_updated += result["updated_count"]

                    yield f"event: progress\ndata: {json.dumps({'status': 'updated_store', 'store_name': result['store_name'], 'updated': result['updated_count'], 'success': result['success']})}\n\n"

                    # Log to history
                    # Find first product from this store for context
                    store_matches = [m for m in matches if m.store_id == result["store_id"]]
                    first_match = store_matches[0] if store_matches else None

                    history_entry = UPCUpdateHistory(
                        batch_id=batch_id,
                        store_id=result["store_id"],
                        store_name=result["store_name"],
                        store_type=StoreType.shopify,
                        old_upc=old_upc,
                        new_upc=new_upc,
                        product_id=first_match.product_id if first_match else None,
                        product_title=first_match.product_title if first_match else None,
                        variant_id=first_match.variant_id if first_match else None,
                        variant_title=first_match.variant_title if first_match else None,
                        success=result["success"],
                        items_updated_count=result["updated_count"],
                        error_message=result.get("error")
                    )
                    db.add(history_entry)
                    db.commit()

        # Update MSSQL stores
        if mssql_store_updates:
            yield f"event: progress\ndata: {json.dumps({'status': 'updating', 'store_type': 'mssql', 'count': len(mssql_store_updates)})}\n\n"

            # Convert to list format for update function
            mssql_updates_list = []
            for store_id, store_data in mssql_store_updates.items():
                tables_list = list(store_data["tables"].values())

                mssql_updates_list.append({
                    "store_id": store_data["store_id"],
                    "store_name": store_data["store_name"],
                    "host": store_data["host"],
                    "port": store_data["port"],
                    "database_name": store_data["database_name"],
                    "username": store_data["username"],
                    "password": store_data["password"],
                    "tables": tables_list
                })

            # Update stores
            for store_update in mssql_updates_list:
                yield f"event: progress\ndata: {json.dumps({'status': 'validating_store', 'store_name': store_update['store_name'], 'store_type': 'mssql'})}\n\n"

                # Check if new UPC already exists in this store (duplicate validation)
                duplicate_check_success, duplicate_check_error, duplicate_results = await check_upc_exists(
                    host=store_update["host"],
                    port=store_update["port"],
                    database=store_update["database_name"],
                    username=store_update["username"],
                    password=store_update["password"],
                    upc=new_upc
                )

                # If duplicate found, skip this store
                if duplicate_check_success and duplicate_results and len(duplicate_results) > 0:
                    skip_result = {
                        "store_id": store_update["store_id"],
                        "store_name": store_update["store_name"],
                        "success": False,
                        "skipped": True,
                        "skip_reason": "duplicate_found",
                        "updated_count": 0,
                        "error": f"UPC '{new_upc}' already exists in this store"
                    }
                    all_results.append(skip_result)

                    yield f"event: progress\ndata: {json.dumps({'status': 'skipped_store', 'store_name': store_update['store_name'], 'reason': 'duplicate_found'})}\n\n"

                    # Log skip to history
                    store_matches = [m for m in matches if m.store_id == store_update["store_id"]]
                    first_match = store_matches[0] if store_matches else None

                    history_entry = UPCUpdateHistory(
                        batch_id=batch_id,
                        store_id=store_update["store_id"],
                        store_name=store_update["store_name"],
                        store_type=StoreType.mssql,
                        old_upc=old_upc,
                        new_upc=new_upc,
                        product_id=first_match.product_id if first_match else None,
                        product_title=first_match.product_title if first_match else None,
                        table_name=first_match.table_name if first_match else None,
                        primary_keys=first_match.primary_keys if first_match else None,
                        success=False,
                        items_updated_count=0,
                        error_message=f"Skipped: UPC '{new_upc}' already exists in this store"
                    )
                    db.add(history_entry)
                    db.commit()

                    continue

                # No duplicate, proceed with update
                yield f"event: progress\ndata: {json.dumps({'status': 'updating_store', 'store_name': store_update['store_name'], 'store_type': 'mssql'})}\n\n"

                # Call update function for this store
                results = await update_upc_across_mssql_stores([store_update])

                for result in results:
                    result["skipped"] = False
                    all_results.append(result)
                    total_updated += result["updated_count"]

                    yield f"event: progress\ndata: {json.dumps({'status': 'updated_store', 'store_name': result['store_name'], 'updated': result['updated_count'], 'success': result['success']})}\n\n"

                    # Log to history
                    # Find first match from this store for context
                    store_matches = [m for m in matches if m.store_id == result["store_id"]]
                    first_match = store_matches[0] if store_matches else None

                    history_entry = UPCUpdateHistory(
                        batch_id=batch_id,
                        store_id=result["store_id"],
                        store_name=result["store_name"],
                        store_type=StoreType.mssql,
                        old_upc=old_upc,
                        new_upc=new_upc,
                        product_id=first_match.product_id if first_match else None,
                        product_title=first_match.product_title if first_match else None,
                        table_name=first_match.table_name if first_match else None,
                        primary_keys=first_match.primary_keys if first_match else None,
                        success=result["success"],
                        items_updated_count=result["updated_count"],
                        error_message=result.get("error")
                    )
                    db.add(history_entry)
                    db.commit()

        # Send final results
        yield f"event: complete\ndata: {json.dumps({'old_upc': old_upc, 'new_upc': new_upc, 'results': all_results, 'total_updated': total_updated})}\n\n"

    async def generate_update_events_safe() -> AsyncGenerator[str, None]:
        try:
            async for event in generate_update_events():
                yield event
        except GeneratorExit:
            print("[UPDATE] Client disconnected")
            return

    return StreamingResponse(
        generate_update_events_safe(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

# SQL UPC Audit endpoint
@app.post("/api/analysis/orphaned-upcs/stream")
async def audit_orphaned_upcs_stream(request: OrphanedUPCAuditRequest, db: Session = Depends(get_db)):
    """
    Audit MSSQL store for orphaned UPCs (UPCs in detail tables but not in Items_tbl).
    Returns Server-Sent Events stream with real-time progress.
    """
    async def generate_audit_events() -> AsyncGenerator[str, None]:
        store_id = request.store_id
        target_store_id = request.target_store_id
        date_from = request.date_from
        date_to = request.date_to

        # Get source store from database
        store = db.query(Store).filter(Store.id == store_id).first()
        if not store:
            yield f"event: error\ndata: {json.dumps({'message': 'Store not found'})}\n\n"
            return

        # Validate source store is MSSQL type
        if store.store_type != StoreType.mssql or not store.mssql_connection:
            yield f"event: error\ndata: {json.dumps({'message': 'Store is not an MSSQL database'})}\n\n"
            return

        # Get source connection details
        conn = store.mssql_connection
        store_name = store.name

        # Handle cross-database comparison if target_store_id is provided
        target_host = None
        target_port = None
        target_database = None
        target_username = None
        target_password = None
        target_store_name = None

        if target_store_id is not None:
            # Get target store from database
            target_store = db.query(Store).filter(Store.id == target_store_id).first()
            if not target_store:
                yield f"event: error\ndata: {json.dumps({'message': 'Target store not found'})}\n\n"
                return

            # Validate target store is MSSQL type
            if target_store.store_type != StoreType.mssql or not target_store.mssql_connection:
                yield f"event: error\ndata: {json.dumps({'message': 'Target store is not an MSSQL database'})}\n\n"
                return

            # Get target connection details
            target_conn = target_store.mssql_connection
            target_store_name = target_store.name
            target_host = target_conn.host
            target_port = target_conn.port
            target_database = target_conn.database_name
            target_username = target_conn.username
            target_password = target_conn.password

            print(f"[AUDIT] Starting cross-database audit")
            print(f"[AUDIT] Source: {store_name}")
            print(f"[AUDIT] Target: {target_store_name}")
        else:
            print(f"[AUDIT] Starting same-database audit for store: {store_name}")

        if date_from or date_to:
            print(f"[AUDIT] Date range: {date_from} to {date_to}")

        # Send start event
        yield f"event: progress\ndata: {json.dumps({'status': 'starting', 'store_name': store_name})}\n\n"

        # Create a queue for progress updates from the thread
        import queue
        progress_queue = queue.Queue()

        # Define progress callback that puts events in queue
        def progress_callback(data: dict):
            progress_queue.put(data)

        # Start audit in background task
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audit")
        audit_future = None

        try:
            # Run audit in executor
            audit_future = loop.run_in_executor(
                executor,
                lambda: audit_orphaned_upcs_sync_wrapper(
                    conn.host,
                    conn.port,
                    conn.database_name,
                    conn.username,
                    conn.password,
                    progress_callback,
                    date_from,
                    date_to,
                    target_host,
                    target_port,
                    target_database,
                    target_username,
                    target_password
                )
            )

            # Poll queue for progress updates while audit runs
            # Track last event time for heartbeat
            import time
            last_event_time = time.time()
            HEARTBEAT_INTERVAL = 15  # Send ping every 15 seconds

            while not audit_future.done():
                try:
                    # Check for progress updates (non-blocking)
                    progress_data = progress_queue.get_nowait()

                    print(f"[AUDIT] Progress: {progress_data}")

                    # Send progress event
                    yield f"event: progress\ndata: {json.dumps(progress_data)}\n\n"

                    # Update last event time
                    last_event_time = time.time()

                except queue.Empty:
                    # No progress update, check if we need to send heartbeat
                    current_time = time.time()
                    if current_time - last_event_time >= HEARTBEAT_INTERVAL:
                        # Send heartbeat ping to keep connection alive
                        yield ":ping\n\n"
                        last_event_time = current_time

                    # Wait a bit before checking again
                    await asyncio.sleep(0.1)

            # Get final result
            success, error, orphaned_records, tables_checked = await audit_future

            # Drain any remaining progress events
            while not progress_queue.empty():
                try:
                    progress_data = progress_queue.get_nowait()
                    yield f"event: progress\ndata: {json.dumps(progress_data)}\n\n"
                except queue.Empty:
                    break

            print(f"[AUDIT] Completed audit for {store_name}: {len(orphaned_records)} orphaned UPCs found")

            if not success:
                yield f"event: error\ndata: {json.dumps({'message': error or 'Audit failed'})}\n\n"
                return

            # Filter out excluded UPCs for this store
            exclusions = db.query(UPCExclusion).filter(UPCExclusion.store_id == store_id).all()
            excluded_upcs = {exclusion.upc for exclusion in exclusions}

            if excluded_upcs:
                original_count = len(orphaned_records)
                orphaned_records = [
                    record for record in orphaned_records
                    if record["upc"] not in excluded_upcs
                ]
                filtered_count = original_count - len(orphaned_records)
                print(f"[AUDIT] Filtered {filtered_count} excluded UPCs from results")

            # Send complete event with results
            result_data = {
                'store_id': store_id,
                'store_name': store_name,
                'orphaned_records': orphaned_records,
                'total_orphaned': len(orphaned_records),
                'tables_checked': tables_checked
            }

            yield f"event: complete\ndata: {json.dumps(result_data)}\n\n"

        except GeneratorExit:
            print("[AUDIT] Client disconnected, cancelling audit")
            if audit_future and not audit_future.done():
                audit_future.cancel()
            return
        except Exception as e:
            print(f"[AUDIT] Error: {e}")
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"
        finally:
            executor.shutdown(wait=False)

    return StreamingResponse(
        generate_audit_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

# Helper wrapper for audit function (for executor)
def audit_orphaned_upcs_sync_wrapper(
    host, port, database, username, password, progress_callback,
    date_from=None, date_to=None,
    target_host=None, target_port=None, target_database=None,
    target_username=None, target_password=None
):
    """Wrapper to call the sync audit function with optional cross-database comparison."""
    from mssql_helper import _audit_orphaned_upcs_sync
    return _audit_orphaned_upcs_sync(
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
        progress_callback=progress_callback,
        tds_version="7.4",
        date_from=date_from,
        date_to=date_to,
        target_host=target_host,
        target_port=target_port,
        target_database=target_database,
        target_username=target_username,
        target_password=target_password
    )

# Store endpoints
@app.get("/api/stores", response_model=List[StoreResponse])
def get_stores(db: Session = Depends(get_db)):
    stores = db.query(Store).all()
    return stores

@app.get("/api/stores/{store_id}", response_model=StoreResponse)
def get_store(store_id: int, db: Session = Depends(get_db)):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    return store

@app.post("/api/stores/mssql", response_model=StoreResponse, status_code=201)
def create_mssql_store(store_data: MSSQLStoreCreate, db: Session = Depends(get_db)):
    # Create store
    store = Store(
        name=store_data.name,
        store_type=StoreType.mssql,
        store_category=store_data.store_category,
        is_active=store_data.is_active
    )
    db.add(store)
    db.flush()

    # Create MSSQL connection
    connection = MSSQLConnection(
        store_id=store.id,
        host=store_data.connection.host,
        port=store_data.connection.port,
        database_name=store_data.connection.database_name,
        username=store_data.connection.username,
        password=store_data.connection.password
    )
    db.add(connection)
    db.commit()
    db.refresh(store)

    return store

@app.post("/api/stores/shopify", response_model=StoreResponse, status_code=201)
def create_shopify_store(store_data: ShopifyStoreCreate, db: Session = Depends(get_db)):
    # Check if shop domain already exists
    existing = db.query(ShopifyConnection).filter(
        ShopifyConnection.shop_domain == store_data.connection.shop_domain
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Shop domain already exists")

    # Create store
    store = Store(
        name=store_data.name,
        store_type=StoreType.shopify,
        store_category=store_data.store_category,
        is_active=store_data.is_active
    )
    db.add(store)
    db.flush()

    # Create Shopify connection
    connection = ShopifyConnection(
        store_id=store.id,
        shop_domain=store_data.connection.shop_domain,
        admin_api_key=store_data.connection.admin_api_key,
        api_version=store_data.connection.api_version,
        update_sku_with_barcode=store_data.connection.update_sku_with_barcode
    )
    db.add(connection)
    db.commit()
    db.refresh(store)

    return store

@app.post("/api/stores/shipper", response_model=StoreResponse, status_code=201)
def create_shipper_store(store_data: ShipperStoreCreate, db: Session = Depends(get_db)):
    # Create store (shipping-platform MSSQL database, reuses the MSSQL connection table)
    store = Store(
        name=store_data.name,
        store_type=StoreType.shipper,
        store_category=store_data.store_category,
        is_active=store_data.is_active
    )
    db.add(store)
    db.flush()

    # Create MSSQL connection
    connection = MSSQLConnection(
        store_id=store.id,
        host=store_data.connection.host,
        port=store_data.connection.port,
        database_name=store_data.connection.database_name,
        username=store_data.connection.username,
        password=store_data.connection.password
    )
    db.add(connection)
    db.commit()
    db.refresh(store)

    return store

@app.put("/api/stores/{store_id}/mssql", response_model=StoreResponse)
def update_mssql_store(store_id: int, store_data: MSSQLStoreUpdate, db: Session = Depends(get_db)):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store or store.store_type != StoreType.mssql or not store.mssql_connection:
        raise HTTPException(status_code=404, detail="MSSQL store not found")

    store.name = store_data.name.strip() or store.name
    store.store_category = store_data.store_category

    conn = store.mssql_connection
    conn.host = store_data.connection.host
    conn.port = store_data.connection.port
    conn.database_name = store_data.connection.database_name
    conn.username = store_data.connection.username
    if store_data.connection.password:  # only overwrite when provided
        conn.password = store_data.connection.password

    db.commit()
    db.refresh(store)
    return store

@app.put("/api/stores/{store_id}/shopify", response_model=StoreResponse)
def update_shopify_store(store_id: int, store_data: ShopifyStoreUpdate, db: Session = Depends(get_db)):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store or store.store_type != StoreType.shopify or not store.shopify_connection:
        raise HTTPException(status_code=404, detail="Shopify store not found")

    # shop_domain must stay unique across OTHER stores
    dupe = db.query(ShopifyConnection).filter(
        ShopifyConnection.shop_domain == store_data.connection.shop_domain,
        ShopifyConnection.store_id != store_id,
    ).first()
    if dupe:
        raise HTTPException(status_code=400, detail="Shop domain already exists")

    store.name = store_data.name.strip() or store.name
    store.store_category = store_data.store_category

    conn = store.shopify_connection
    conn.shop_domain = store_data.connection.shop_domain
    conn.api_version = store_data.connection.api_version
    conn.update_sku_with_barcode = store_data.connection.update_sku_with_barcode
    if store_data.connection.admin_api_key:  # only overwrite when provided
        conn.admin_api_key = store_data.connection.admin_api_key

    db.commit()
    db.refresh(store)
    return store

@app.put("/api/stores/{store_id}/shipper", response_model=StoreResponse)
def update_shipper_store(store_id: int, store_data: ShipperStoreUpdate, db: Session = Depends(get_db)):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store or store.store_type != StoreType.shipper or not store.mssql_connection:
        raise HTTPException(status_code=404, detail="Shipper store not found")

    store.name = store_data.name.strip() or store.name
    store.store_category = store_data.store_category

    conn = store.mssql_connection
    conn.host = store_data.connection.host
    conn.port = store_data.connection.port
    conn.database_name = store_data.connection.database_name
    conn.username = store_data.connection.username
    if store_data.connection.password:  # only overwrite when provided
        conn.password = store_data.connection.password

    db.commit()
    db.refresh(store)
    return store

@app.delete("/api/stores/{store_id}", status_code=204)
def delete_store(store_id: int, db: Session = Depends(get_db)):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    db.delete(store)
    db.commit()
    return None

@app.patch("/api/stores/{store_id}/name", response_model=StoreResponse)
def update_store_name(store_id: int, body: StoreNameUpdate, db: Session = Depends(get_db)):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Store name cannot be empty")

    store.name = name
    db.commit()
    db.refresh(store)

    return store

@app.patch("/api/stores/{store_id}/toggle", response_model=StoreResponse)
def toggle_store_active(store_id: int, db: Session = Depends(get_db)):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    store.is_active = not store.is_active
    db.commit()
    db.refresh(store)

    return store

@app.patch("/api/stores/{store_id}/category", response_model=StoreResponse)
def update_store_category(store_id: int, body: StoreCategoryUpdate, db: Session = Depends(get_db)):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    store.store_category = body.store_category
    db.commit()
    db.refresh(store)

    return store

# Settings endpoints
@app.get("/api/settings", response_model=List[SettingResponse])
def get_settings(db: Session = Depends(get_db)):
    settings = db.query(Setting).all()
    return settings

@app.get("/api/settings/{key}", response_model=SettingResponse)
def get_setting(key: str, db: Session = Depends(get_db)):
    setting = db.query(Setting).filter(Setting.key == key).first()
    if not setting:
        raise HTTPException(status_code=404, detail="Setting not found")
    return setting

@app.post("/api/settings", response_model=SettingResponse, status_code=201)
def create_setting(setting_data: SettingCreate, db: Session = Depends(get_db)):
    # Check if key already exists
    existing = db.query(Setting).filter(Setting.key == setting_data.key).first()
    if existing:
        raise HTTPException(status_code=400, detail="Setting key already exists")

    setting = Setting(**setting_data.dict())
    db.add(setting)
    db.commit()
    db.refresh(setting)

    return setting

@app.patch("/api/settings/{key}", response_model=SettingResponse)
def update_setting(key: str, setting_data: SettingUpdate, db: Session = Depends(get_db)):
    setting = db.query(Setting).filter(Setting.key == key).first()
    if not setting:
        raise HTTPException(status_code=404, detail="Setting not found")

    if setting_data.value is not None:
        setting.value = setting_data.value
    if setting_data.description is not None:
        setting.description = setting_data.description

    db.commit()
    db.refresh(setting)

    return setting

@app.delete("/api/settings/{key}", status_code=204)
def delete_setting(key: str, db: Session = Depends(get_db)):
    setting = db.query(Setting).filter(Setting.key == key).first()
    if not setting:
        raise HTTPException(status_code=404, detail="Setting not found")

    db.delete(setting)
    db.commit()
    return None

# Config Import/Export endpoints
@app.get("/api/config/export", response_model=ConfigExportResponse)
def export_configuration(db: Session = Depends(get_db)):
    """
    Export all store configurations as JSON.
    Includes both MSSQL and Shopify stores with full connection details.
    """
    from datetime import datetime as dt

    # Get all stores
    stores = db.query(Store).all()

    mssql_stores = []
    shopify_stores = []

    for store in stores:
        if store.store_type == StoreType.mssql and store.mssql_connection:
            mssql_stores.append(StoreExport(
                name=store.name,
                is_active=store.is_active,
                store_category=store.store_category.value if store.store_category else "retail",
                connection={
                    "host": store.mssql_connection.host,
                    "port": store.mssql_connection.port,
                    "database_name": store.mssql_connection.database_name,
                    "username": store.mssql_connection.username,
                    "password": store.mssql_connection.password
                }
            ))
        elif store.store_type == StoreType.shopify and store.shopify_connection:
            shopify_stores.append(StoreExport(
                name=store.name,
                is_active=store.is_active,
                store_category=store.store_category.value if store.store_category else "retail",
                connection={
                    "shop_domain": store.shopify_connection.shop_domain,
                    "admin_api_key": store.shopify_connection.admin_api_key,
                    "api_version": store.shopify_connection.api_version,
                    "update_sku_with_barcode": store.shopify_connection.update_sku_with_barcode
                }
            ))

    return ConfigExportResponse(
        version="1.0",
        exported_at=dt.utcnow(),
        mssql_stores=mssql_stores,
        shopify_stores=shopify_stores
    )

@app.post("/api/config/import", response_model=ConfigImportResponse)
def import_configuration(config: ConfigImportRequest, db: Session = Depends(get_db)):
    """
    Import store configurations from JSON.
    Skips existing Shopify stores (by shop_domain) and reports all results.
    """
    results = []
    created_count = 0
    skipped_count = 0
    failed_count = 0

    # Import MSSQL stores
    for store_data in config.mssql_stores:
        try:
            # Check if MSSQL connection already exists (by host + port + database)
            existing = db.query(MSSQLConnection).filter(
                MSSQLConnection.host == store_data.connection["host"],
                MSSQLConnection.port == store_data.connection["port"],
                MSSQLConnection.database_name == store_data.connection["database_name"]
            ).first()

            if existing:
                results.append(StoreImportResult(
                    name=store_data.name,
                    store_type="mssql",
                    status="skipped",
                    reason=f"MSSQL connection to '{store_data.connection['host']}:{store_data.connection['port']}/{store_data.connection['database_name']}' already exists"
                ))
                skipped_count += 1
                continue

            # Create store
            store = Store(
                name=store_data.name,
                store_type=StoreType.mssql,
                store_category=getattr(store_data, 'store_category', 'retail') or 'retail',
                is_active=store_data.is_active
            )
            db.add(store)
            db.flush()

            # Create connection
            connection = MSSQLConnection(
                store_id=store.id,
                host=store_data.connection["host"],
                port=store_data.connection["port"],
                database_name=store_data.connection["database_name"],
                username=store_data.connection["username"],
                password=store_data.connection["password"]
            )
            db.add(connection)
            db.commit()

            results.append(StoreImportResult(
                name=store_data.name,
                store_type="mssql",
                status="created"
            ))
            created_count += 1

        except Exception as e:
            db.rollback()
            results.append(StoreImportResult(
                name=store_data.name,
                store_type="mssql",
                status="failed",
                reason=str(e)
            ))
            failed_count += 1

    # Import Shopify stores
    for store_data in config.shopify_stores:
        try:
            # Check if shop domain already exists
            existing = db.query(ShopifyConnection).filter(
                ShopifyConnection.shop_domain == store_data.connection["shop_domain"]
            ).first()

            if existing:
                results.append(StoreImportResult(
                    name=store_data.name,
                    store_type="shopify",
                    status="skipped",
                    reason=f"Shop domain '{store_data.connection['shop_domain']}' already exists"
                ))
                skipped_count += 1
                continue

            # Create store
            store = Store(
                name=store_data.name,
                store_type=StoreType.shopify,
                store_category=getattr(store_data, 'store_category', 'retail') or 'retail',
                is_active=store_data.is_active
            )
            db.add(store)
            db.flush()

            # Create connection
            connection = ShopifyConnection(
                store_id=store.id,
                shop_domain=store_data.connection["shop_domain"],
                admin_api_key=store_data.connection["admin_api_key"],
                api_version=store_data.connection.get("api_version", "2025-01"),
                update_sku_with_barcode=store_data.connection.get("update_sku_with_barcode", False)
            )
            db.add(connection)
            db.commit()

            results.append(StoreImportResult(
                name=store_data.name,
                store_type="shopify",
                status="created"
            ))
            created_count += 1

        except Exception as e:
            db.rollback()
            results.append(StoreImportResult(
                name=store_data.name,
                store_type="shopify",
                status="failed",
                reason=str(e)
            ))
            failed_count += 1

    total_stores = len(config.mssql_stores) + len(config.shopify_stores)

    return ConfigImportResponse(
        total_stores=total_stores,
        created=created_count,
        skipped=skipped_count,
        failed=failed_count,
        results=results
    )

# SQL UPC Reconciliation endpoints
@app.post("/api/analysis/reconcile-upcs", response_model=ReconciliationResponse)
async def reconcile_orphaned_upcs(request: ReconciliationRequest, db: Session = Depends(get_db)):
    """
    Find matching UPCs in Items_tbl for orphaned records by ProductID or ProductDescription.
    """
    store_id = request.store_id
    match_type = request.match_type
    orphaned_records = request.orphaned_records

    # Get store from database
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    # Validate store is MSSQL type
    if store.store_type != StoreType.mssql or not store.mssql_connection:
        raise HTTPException(status_code=400, detail="Store is not an MSSQL database")

    # Get connection details
    conn = store.mssql_connection

    # Convert Pydantic models to dicts for helper function
    records_dict = [record.model_dump() for record in orphaned_records]

    # Call appropriate matching function
    if match_type == "product_id":
        success, error, matches = await find_matches_by_product_id(
            host=conn.host,
            port=conn.port,
            database=conn.database_name,
            username=conn.username,
            password=conn.password,
            orphaned_records=records_dict
        )
    else:  # product_description
        success, error, matches = await find_matches_by_description(
            host=conn.host,
            port=conn.port,
            database=conn.database_name,
            username=conn.username,
            password=conn.password,
            orphaned_records=records_dict
        )

    if not success:
        raise HTTPException(status_code=500, detail=error or "Reconciliation failed")

    # Calculate totals
    total_matched = sum(1 for m in matches if m["match_found"])

    return ReconciliationResponse(
        matches=matches,
        total_checked=len(matches),
        total_matched=total_matched
    )

@app.post("/api/analysis/reconcile-upcs/update", response_model=ReconciliationUpdateResponse)
async def update_reconciled_upcs(request: ReconciliationUpdateRequest, db: Session = Depends(get_db)):
    """
    Update orphaned UPCs with matched values from Items_tbl.
    """
    store_id = request.store_id
    updates = request.updates

    # Get store from database
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    # Validate store is MSSQL type
    if store.store_type != StoreType.mssql or not store.mssql_connection:
        raise HTTPException(status_code=400, detail="Store is not an MSSQL database")

    # Get connection details
    conn = store.mssql_connection

    # Convert Pydantic models to dicts for helper function
    updates_dict = [update.model_dump() for update in updates]

    # Call update function
    success, error, results = await update_orphaned_upcs(
        host=conn.host,
        port=conn.port,
        database=conn.database_name,
        username=conn.username,
        password=conn.password,
        updates=updates_dict
    )

    if not success:
        raise HTTPException(status_code=500, detail=error or "Update failed")

    # Calculate totals
    total_updated = sum(1 for r in results if r["success"])
    total_failed = sum(1 for r in results if not r["success"])

    return ReconciliationUpdateResponse(
        results=results,
        total_updated=total_updated,
        total_failed=total_failed
    )

# SSE Streaming version of reconciliation find matches
@app.post("/api/analysis/reconcile-upcs/stream")
async def reconcile_orphaned_upcs_stream(request: ReconciliationRequest, db: Session = Depends(get_db)):
    """
    Find matching UPCs in Items_tbl for orphaned records with SSE streaming progress.
    Streams progress events for each record checked.
    """
    store_id = request.store_id
    match_type = request.match_type
    orphaned_records = request.orphaned_records

    # Get store from database
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    # Validate store is MSSQL type
    if store.store_type != StoreType.mssql or not store.mssql_connection:
        raise HTTPException(status_code=400, detail="Store is not an MSSQL database")

    # Get connection details
    conn = store.mssql_connection
    store_name = store.name

    # Convert Pydantic models to dicts for helper function
    records_dict = [record.model_dump() for record in orphaned_records]

    async def generate_reconciliation_events():
        """Generator for SSE events during reconciliation"""
        import queue
        import time
        from concurrent.futures import ThreadPoolExecutor

        progress_queue = queue.Queue()
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="reconcile")
        reconcile_future = None

        def progress_callback(data: dict):
            progress_queue.put(data)

        try:
            loop = asyncio.get_event_loop()

            # Run reconciliation in executor
            reconcile_future = loop.run_in_executor(
                executor,
                lambda: reconcile_with_progress_wrapper(
                    conn.host,
                    conn.port,
                    conn.database_name,
                    conn.username,
                    conn.password,
                    records_dict,
                    match_type,
                    progress_callback
                )
            )

            # Poll queue for progress updates
            last_event_time = time.time()
            HEARTBEAT_INTERVAL = 15

            while not reconcile_future.done():
                try:
                    # Check for progress updates (non-blocking)
                    progress_data = progress_queue.get_nowait()

                    # Send progress event
                    yield f"event: progress\ndata: {json.dumps(progress_data)}\n\n"

                    # Update last event time
                    last_event_time = time.time()

                except queue.Empty:
                    # No progress update, check if we need to send heartbeat
                    current_time = time.time()
                    if current_time - last_event_time >= HEARTBEAT_INTERVAL:
                        yield ":ping\n\n"
                        last_event_time = current_time

                    # Wait a bit before checking again
                    await asyncio.sleep(0.1)

            # Get final result
            success, error, matches = await reconcile_future

            # Drain any remaining progress events
            while not progress_queue.empty():
                try:
                    progress_data = progress_queue.get_nowait()
                    yield f"event: progress\ndata: {json.dumps(progress_data)}\n\n"
                except queue.Empty:
                    break

            if not success:
                yield f"event: error\ndata: {json.dumps({'message': error or 'Reconciliation failed'})}\n\n"
                return

            # Calculate totals
            total_matched = sum(1 for m in matches if m["match_found"])

            # Send complete event with results
            result_data = {
                'matches': matches,
                'total_checked': len(matches),
                'total_matched': total_matched
            }

            yield f"event: complete\ndata: {json.dumps(result_data)}\n\n"

        except GeneratorExit:
            print("[RECONCILIATION] Client disconnected, stopping reconciliation operation")
            if reconcile_future and not reconcile_future.done():
                reconcile_future.cancel()
            return
        except Exception as e:
            print(f"[RECONCILIATION] Error in streaming: {e}")
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"
        finally:
            executor.shutdown(wait=False)

    return StreamingResponse(
        generate_reconciliation_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

# Helper wrapper for reconciliation with progress
def reconcile_with_progress_wrapper(host, port, database, username, password, orphaned_records, match_type, progress_callback):
    """Wrapper to call the sync reconciliation function with progress."""
    from mssql_helper import find_matches_by_product_id_sync, find_matches_by_description_sync

    # Call matching function with progress callback
    if match_type == "product_id":
        success, error, matches = find_matches_by_product_id_sync(
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            orphaned_records=orphaned_records,
            tds_version="7.4",
            progress_callback=progress_callback
        )
    else:  # product_description
        success, error, matches = find_matches_by_description_sync(
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            orphaned_records=orphaned_records,
            tds_version="7.4",
            progress_callback=progress_callback
        )

    return success, error, matches

# SSE Streaming version of reconciliation update
@app.post("/api/analysis/reconcile-upcs/update/stream")
async def update_reconciled_upcs_stream(request: ReconciliationUpdateRequest, db: Session = Depends(get_db)):
    """
    Update orphaned UPCs with matched values from Items_tbl with SSE streaming progress.
    Processes updates in batches and streams progress.
    """
    store_id = request.store_id
    updates = request.updates

    # Get store from database
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    # Validate store is MSSQL type
    if store.store_type != StoreType.mssql or not store.mssql_connection:
        raise HTTPException(status_code=400, detail="Store is not an MSSQL database")

    # Get connection details
    conn = store.mssql_connection
    store_name = store.name

    # Convert Pydantic models to dicts for helper function
    updates_dict = [update.model_dump() for update in updates]

    async def generate_update_events():
        """Generator for SSE events during batch updates"""
        import queue
        import time
        from concurrent.futures import ThreadPoolExecutor

        progress_queue = queue.Queue()
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="reconcile_update")
        update_future = None

        def progress_callback(data: dict):
            progress_queue.put(data)

        try:
            loop = asyncio.get_event_loop()

            # Run update in executor
            update_future = loop.run_in_executor(
                executor,
                lambda: update_with_batching_wrapper(
                    conn.host,
                    conn.port,
                    conn.database_name,
                    conn.username,
                    conn.password,
                    updates_dict,
                    progress_callback
                )
            )

            # Poll queue for progress updates
            last_event_time = time.time()
            HEARTBEAT_INTERVAL = 15

            while not update_future.done():
                try:
                    # Check for progress updates (non-blocking)
                    progress_data = progress_queue.get_nowait()

                    # Send progress event
                    yield f"event: progress\ndata: {json.dumps(progress_data)}\n\n"

                    # Update last event time
                    last_event_time = time.time()

                except queue.Empty:
                    # No progress update, check if we need to send heartbeat
                    current_time = time.time()
                    if current_time - last_event_time >= HEARTBEAT_INTERVAL:
                        yield ":ping\n\n"
                        last_event_time = current_time

                    # Wait a bit before checking again
                    await asyncio.sleep(0.1)

            # Get final result
            success, error, results = await update_future

            # Drain any remaining progress events
            while not progress_queue.empty():
                try:
                    progress_data = progress_queue.get_nowait()
                    yield f"event: progress\ndata: {json.dumps(progress_data)}\n\n"
                except queue.Empty:
                    break

            if not success:
                yield f"event: error\ndata: {json.dumps({'message': error or 'Update failed'})}\n\n"
                return

            # Calculate totals
            total_updated = sum(1 for r in results if r["success"])
            total_failed = sum(1 for r in results if not r["success"])

            # Send complete event with results
            result_data = {
                'results': results,
                'total_updated': total_updated,
                'total_failed': total_failed
            }

            yield f"event: complete\ndata: {json.dumps(result_data)}\n\n"

        except GeneratorExit:
            print("[RECONCILIATION UPDATE] Client disconnected, stopping update operation")
            if update_future and not update_future.done():
                update_future.cancel()
            return
        except Exception as e:
            print(f"[RECONCILIATION UPDATE] Error in streaming: {e}")
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"
        finally:
            executor.shutdown(wait=False)

    return StreamingResponse(
        generate_update_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

# Helper wrapper for batch updates with progress
def update_with_batching_wrapper(host, port, database, username, password, updates, progress_callback):
    """Wrapper to call the sync update function with batch processing and progress."""
    from mssql_helper import update_orphaned_upcs_sync

    BATCH_SIZE = 20
    total_updates = len(updates)
    total_batches = (total_updates + BATCH_SIZE - 1) // BATCH_SIZE  # Ceiling division

    all_results = []
    total_updated = 0
    total_failed = 0

    # Process in batches
    for batch_num in range(total_batches):
        start_idx = batch_num * BATCH_SIZE
        end_idx = min(start_idx + BATCH_SIZE, total_updates)
        batch = updates[start_idx:end_idx]

        # Send batch start event
        progress_callback({
            "status": "updating_batch",
            "batch_number": batch_num + 1,
            "total_batches": total_batches,
            "batch_size": len(batch)
        })

        # Execute batch update
        success, error, batch_results = update_orphaned_upcs_sync(
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            updates=batch,
            tds_version="7.4"
        )

        if not success:
            # If batch fails, mark all as failed
            for update in batch:
                all_results.append({
                    "table_name": update["table_name"],
                    "primary_key": update["primary_key"],
                    "success": False,
                    "updated_upc": None,
                    "error": error or "Batch update failed"
                })
                total_failed += len(batch)
        else:
            # Add batch results
            all_results.extend(batch_results)
            batch_updated = sum(1 for r in batch_results if r["success"])
            batch_failed = sum(1 for r in batch_results if not r["success"])
            total_updated += batch_updated
            total_failed += batch_failed

        # Send batch complete event
        progress_callback({
            "status": "batch_complete",
            "batch_number": batch_num + 1,
            "total_batches": total_batches,
            "batch_updated": batch_updated if success else 0,
            "batch_failed": batch_failed if success else len(batch),
            "total_updated": total_updated,
            "total_failed": total_failed
        })

    return True, None, all_results

# UPC Update History Endpoints
@app.get("/api/history/updates", response_model=UPCUpdateHistoryListResponse)
def get_update_history(
    store_id: Optional[int] = None,
    upc_search: Optional[str] = None,
    success_filter: Optional[bool] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """
    Get UPC update history grouped by batch with optional filters.
    """
    from sqlalchemy import func
    from schemas import UPCUpdateHistoryBatch

    query = db.query(UPCUpdateHistory)

    # Apply filters
    if store_id is not None:
        query = query.filter(UPCUpdateHistory.store_id == store_id)

    if upc_search:
        query = query.filter(
            (UPCUpdateHistory.old_upc.like(f"%{upc_search}%")) |
            (UPCUpdateHistory.new_upc.like(f"%{upc_search}%"))
        )

    if success_filter is not None:
        query = query.filter(UPCUpdateHistory.success == success_filter)

    if start_date:
        query = query.filter(UPCUpdateHistory.created_at >= start_date)

    if end_date:
        query = query.filter(UPCUpdateHistory.created_at <= end_date)

    # Get unique batch_ids with pagination
    batch_query = db.query(UPCUpdateHistory.batch_id, func.min(UPCUpdateHistory.created_at).label('created_at'))

    # Apply same filters to batch query
    if store_id is not None:
        batch_query = batch_query.filter(UPCUpdateHistory.store_id == store_id)
    if upc_search:
        batch_query = batch_query.filter(
            (UPCUpdateHistory.old_upc.like(f"%{upc_search}%")) |
            (UPCUpdateHistory.new_upc.like(f"%{upc_search}%"))
        )
    if success_filter is not None:
        batch_query = batch_query.filter(UPCUpdateHistory.success == success_filter)
    if start_date:
        batch_query = batch_query.filter(UPCUpdateHistory.created_at >= start_date)
    if end_date:
        batch_query = batch_query.filter(UPCUpdateHistory.created_at <= end_date)

    batch_query = batch_query.group_by(UPCUpdateHistory.batch_id)
    total = batch_query.count()

    batch_ids = batch_query.order_by(func.min(UPCUpdateHistory.created_at).desc()).offset(offset).limit(limit).all()
    batch_id_list = [b.batch_id for b in batch_ids]

    # Get all updates for these batches
    batches = []
    for batch_id in batch_id_list:
        updates = db.query(UPCUpdateHistory).filter(UPCUpdateHistory.batch_id == batch_id).all()

        if updates:
            first_update = updates[0]
            successful = sum(1 for u in updates if u.success)
            failed = len(updates) - successful
            total_items = sum(u.items_updated_count for u in updates)

            batches.append(UPCUpdateHistoryBatch(
                batch_id=batch_id,
                old_upc=first_update.old_upc,
                new_upc=first_update.new_upc,
                created_at=first_update.created_at,
                total_stores=len(updates),
                successful_stores=successful,
                failed_stores=failed,
                total_items_updated=total_items,
                updates=updates
            ))

    return UPCUpdateHistoryListResponse(
        batches=batches,
        total=total,
        limit=limit,
        offset=offset
    )

@app.get("/api/history/updates/{history_id}", response_model=UPCUpdateHistoryResponse)
def get_history_entry(history_id: int, db: Session = Depends(get_db)):
    """
    Get a specific UPC update history entry by ID.
    """
    entry = db.query(UPCUpdateHistory).filter(UPCUpdateHistory.id == history_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="History entry not found")
    return entry

# UPC Exclusion Endpoints
@app.post("/api/exclusions", response_model=UPCExclusionResponse, status_code=201)
def create_exclusion(exclusion_data: UPCExclusionCreate, db: Session = Depends(get_db)):
    """
    Add a UPC to the exclusion list for a specific store.
    Excluded UPCs will not appear in future orphaned UPC audit results.
    """
    # Verify store exists
    store = db.query(Store).filter(Store.id == exclusion_data.store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    # Check if exclusion already exists
    existing = db.query(UPCExclusion).filter(
        UPCExclusion.store_id == exclusion_data.store_id,
        UPCExclusion.upc == exclusion_data.upc
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="UPC is already excluded for this store")

    # Create exclusion
    exclusion = UPCExclusion(
        store_id=exclusion_data.store_id,
        upc=exclusion_data.upc,
        notes=exclusion_data.notes
    )
    db.add(exclusion)
    db.commit()
    db.refresh(exclusion)

    # Build response with store name
    return UPCExclusionResponse(
        id=exclusion.id,
        store_id=exclusion.store_id,
        store_name=store.name,
        upc=exclusion.upc,
        excluded_at=exclusion.excluded_at,
        notes=exclusion.notes
    )

@app.get("/api/exclusions", response_model=UPCExclusionListResponse)
def get_exclusions(store_id: Optional[int] = None, db: Session = Depends(get_db)):
    """
    Get all UPC exclusions, optionally filtered by store.
    """
    query = db.query(UPCExclusion)

    if store_id is not None:
        query = query.filter(UPCExclusion.store_id == store_id)

    exclusions = query.order_by(UPCExclusion.excluded_at.desc()).all()

    # Build response with store names
    exclusion_responses = []
    for exclusion in exclusions:
        store = db.query(Store).filter(Store.id == exclusion.store_id).first()
        exclusion_responses.append(UPCExclusionResponse(
            id=exclusion.id,
            store_id=exclusion.store_id,
            store_name=store.name if store else "Unknown",
            upc=exclusion.upc,
            excluded_at=exclusion.excluded_at,
            notes=exclusion.notes
        ))

    return UPCExclusionListResponse(
        exclusions=exclusion_responses,
        total=len(exclusion_responses)
    )

@app.delete("/api/exclusions/{exclusion_id}", status_code=204)
def delete_exclusion(exclusion_id: int, db: Session = Depends(get_db)):
    """
    Remove a UPC from the exclusion list.
    The UPC will appear in future orphaned UPC audit results again.
    """
    exclusion = db.query(UPCExclusion).filter(UPCExclusion.id == exclusion_id).first()
    if not exclusion:
        raise HTTPException(status_code=404, detail="Exclusion not found")

    db.delete(exclusion)
    db.commit()
    return None

# Store Mirrors Endpoints
@app.get("/api/store-mirrors", response_model=StoreMirrorListResponse)
def get_store_mirrors(db: Session = Depends(get_db)):
    mirrors = db.query(StoreMirror).order_by(StoreMirror.created_at.desc()).all()

    mirror_responses = []
    for mirror in mirrors:
        source = db.query(Store).filter(Store.id == mirror.source_store_id).first()
        mirror_store = db.query(Store).filter(Store.id == mirror.mirror_store_id).first()
        if source and mirror_store:
            mirror_responses.append(StoreMirrorResponse(
                id=mirror.id,
                source_store_id=source.id,
                source_store_name=source.name,
                source_store_type=source.store_type.value if hasattr(source.store_type, 'value') else source.store_type,
                mirror_store_id=mirror_store.id,
                mirror_store_name=mirror_store.name,
                mirror_store_type=mirror_store.store_type.value if hasattr(mirror_store.store_type, 'value') else mirror_store.store_type,
                created_at=mirror.created_at,
            ))

    return StoreMirrorListResponse(mirrors=mirror_responses, total=len(mirror_responses))


@app.post("/api/store-mirrors", response_model=StoreMirrorResponse, status_code=201)
def create_store_mirror(data: StoreMirrorCreate, db: Session = Depends(get_db)):
    source = db.query(Store).filter(Store.id == data.source_store_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source store not found")

    mirror_store = db.query(Store).filter(Store.id == data.mirror_store_id).first()
    if not mirror_store:
        raise HTTPException(status_code=404, detail="Mirror store not found")

    if data.source_store_id == data.mirror_store_id:
        raise HTTPException(status_code=400, detail="Source and mirror store cannot be the same")

    existing = db.query(StoreMirror).filter(
        StoreMirror.source_store_id == data.source_store_id,
        StoreMirror.mirror_store_id == data.mirror_store_id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="This mirror relationship already exists")

    is_already_mirror = db.query(StoreMirror).filter(
        StoreMirror.mirror_store_id == data.source_store_id
    ).first()
    if is_already_mirror:
        raise HTTPException(status_code=400, detail="Source store is already a mirror of another store (no chaining)")

    is_already_source = db.query(StoreMirror).filter(
        StoreMirror.source_store_id == data.mirror_store_id
    ).first()
    if is_already_source:
        raise HTTPException(status_code=400, detail="Mirror store is already a source of another mirror (no chaining)")

    mirror = StoreMirror(
        source_store_id=data.source_store_id,
        mirror_store_id=data.mirror_store_id,
    )
    db.add(mirror)
    db.commit()
    db.refresh(mirror)

    return StoreMirrorResponse(
        id=mirror.id,
        source_store_id=source.id,
        source_store_name=source.name,
        source_store_type=source.store_type.value if hasattr(source.store_type, 'value') else source.store_type,
        mirror_store_id=mirror_store.id,
        mirror_store_name=mirror_store.name,
        mirror_store_type=mirror_store.store_type.value if hasattr(mirror_store.store_type, 'value') else mirror_store.store_type,
        created_at=mirror.created_at,
    )


@app.delete("/api/store-mirrors/{mirror_id}", status_code=204)
def delete_store_mirror(mirror_id: int, db: Session = Depends(get_db)):
    mirror = db.query(StoreMirror).filter(StoreMirror.id == mirror_id).first()
    if not mirror:
        raise HTTPException(status_code=404, detail="Mirror not found")

    db.delete(mirror)
    db.commit()
    return None


# ============================================================================
# Item Tracker Endpoints
# ============================================================================

@app.get("/api/item-tracker/config", response_model=ItemTrackerConfigResponse)
def get_item_tracker_config(db: Session = Depends(get_db)):
    """Get Item Tracker configuration."""
    config = db.query(ItemTrackerConfig).first()

    if not config:
        # Return empty config
        return ItemTrackerConfigResponse(
            id=0,
            s2s_store_id=None,
            s2s_store_name=None,
            sales_store_ids=[],
            sales_store_names=[],
            inventory_store_id=None,
            inventory_store_name=None,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )

    # Get store names
    s2s_store_name = None
    if config.s2s_store_id:
        s2s_store = db.query(Store).filter(Store.id == config.s2s_store_id).first()
        if s2s_store:
            s2s_store_name = s2s_store.name

    sales_store_names = []
    if config.sales_store_ids:
        for store_id in config.sales_store_ids:
            store = db.query(Store).filter(Store.id == store_id).first()
            if store:
                sales_store_names.append(store.name)

    inventory_store_name = None
    if config.inventory_store_id:
        inventory_store = db.query(Store).filter(Store.id == config.inventory_store_id).first()
        if inventory_store:
            inventory_store_name = inventory_store.name

    return ItemTrackerConfigResponse(
        id=config.id,
        s2s_store_id=config.s2s_store_id,
        s2s_store_name=s2s_store_name,
        sales_store_ids=config.sales_store_ids or [],
        sales_store_names=sales_store_names,
        inventory_store_id=config.inventory_store_id,
        inventory_store_name=inventory_store_name,
        created_at=config.created_at,
        updated_at=config.updated_at
    )


@app.post("/api/item-tracker/config", response_model=ItemTrackerConfigResponse)
def save_item_tracker_config(config_data: ItemTrackerConfigCreate, db: Session = Depends(get_db)):
    """Save or update Item Tracker configuration (upsert)."""
    # Validate s2s_store_id if provided
    if config_data.s2s_store_id:
        s2s_store = db.query(Store).filter(
            Store.id == config_data.s2s_store_id,
            Store.store_type == StoreType.mssql
        ).first()
        if not s2s_store:
            raise HTTPException(status_code=400, detail="Invalid S2S store ID")

    # Validate sales_store_ids if provided
    if config_data.sales_store_ids:
        for store_id in config_data.sales_store_ids:
            store = db.query(Store).filter(
                Store.id == store_id,
                Store.store_type == StoreType.mssql
            ).first()
            if not store:
                raise HTTPException(status_code=400, detail=f"Invalid sales store ID: {store_id}")

    # Validate inventory_store_id if provided
    if config_data.inventory_store_id:
        inventory_store = db.query(Store).filter(
            Store.id == config_data.inventory_store_id,
            Store.store_type == StoreType.mssql
        ).first()
        if not inventory_store:
            raise HTTPException(status_code=400, detail="Invalid inventory store ID")

    # Get existing config or create new one
    config = db.query(ItemTrackerConfig).first()

    if config:
        config.s2s_store_id = config_data.s2s_store_id
        config.sales_store_ids = config_data.sales_store_ids
        config.inventory_store_id = config_data.inventory_store_id
    else:
        config = ItemTrackerConfig(
            s2s_store_id=config_data.s2s_store_id,
            sales_store_ids=config_data.sales_store_ids,
            inventory_store_id=config_data.inventory_store_id
        )
        db.add(config)

    db.commit()
    db.refresh(config)

    # Get store names for response
    s2s_store_name = None
    if config.s2s_store_id:
        s2s_store = db.query(Store).filter(Store.id == config.s2s_store_id).first()
        if s2s_store:
            s2s_store_name = s2s_store.name

    sales_store_names = []
    if config.sales_store_ids:
        for store_id in config.sales_store_ids:
            store = db.query(Store).filter(Store.id == store_id).first()
            if store:
                sales_store_names.append(store.name)

    inventory_store_name = None
    if config.inventory_store_id:
        inventory_store = db.query(Store).filter(Store.id == config.inventory_store_id).first()
        if inventory_store:
            inventory_store_name = inventory_store.name

    return ItemTrackerConfigResponse(
        id=config.id,
        s2s_store_id=config.s2s_store_id,
        s2s_store_name=s2s_store_name,
        sales_store_ids=config.sales_store_ids or [],
        sales_store_names=sales_store_names,
        inventory_store_id=config.inventory_store_id,
        inventory_store_name=inventory_store_name,
        created_at=config.created_at,
        updated_at=config.updated_at
    )


def get_item_tracker_stores(db: Session):
    config = db.query(ItemTrackerConfig).first()
    if not config or not config.s2s_store_id:
        raise HTTPException(status_code=400, detail="Item Tracker not configured. Please configure S2S database in Settings.")

    s2s_store = db.query(Store).filter(
        Store.id == config.s2s_store_id,
        Store.store_type == StoreType.mssql
    ).first()

    if not s2s_store or not s2s_store.mssql_connection:
        raise HTTPException(status_code=400, detail="S2S database not found or missing connection details")

    s2s_conn = s2s_store.mssql_connection

    sales_stores = []
    if config.sales_store_ids:
        sales_stores = db.query(Store).filter(
            Store.id.in_(config.sales_store_ids),
            Store.store_type == StoreType.mssql
        ).all()

    inventory_store = None
    if config.inventory_store_id:
        inventory_store = db.query(Store).filter(
            Store.id == config.inventory_store_id,
            Store.store_type == StoreType.mssql
        ).first()

    return config, s2s_store, s2s_conn, sales_stores, inventory_store


def apply_exclusion_filter(all_events, event_counts, db: Session):
    exclusions = db.query(ItemTrackerExclusion).all()

    exclusion_map = {}
    for excl in exclusions:
        key = excl.business_name.lower()
        if key not in exclusion_map:
            exclusion_map[key] = []
        exclusion_map[key].append(excl)

    def should_exclude(event):
        if not event.business_name:
            return False
        key = event.business_name.lower()
        if key not in exclusion_map:
            return False
        for excl in exclusion_map[key]:
            if excl.void_status is None:
                return True
            if event.event_type == "sale" and event.is_voided is not None:
                if excl.void_status == 1 and event.is_voided:
                    return True
                if excl.void_status == 0 and not event.is_voided:
                    return True
        return False

    if exclusion_map:
        all_events = [e for e in all_events if not should_exclude(e)]
        event_counts = {
            "purchase": 0,
            "sale": 0,
            "customer_return": 0,
            "vendor_return": 0,
            "inventory_recount": 0,
            "in_progress": 0,
        }
        for event in all_events:
            event_counts[event.event_type] += 1

    return all_events, event_counts


def compute_quantity_totals(all_events):
    totals = {
        "purchase": 0.0,
        "sale": 0.0,
        "customer_return": 0.0,
        "vendor_return": 0.0,
        "inventory_recount": 0.0,
        "in_progress": 0.0,
    }
    for event in all_events:
        totals[event.event_type] += event.quantity or 0.0
    return totals


def compute_adjusted_balance(quant_on_hand, gap_events):
    balance = quant_on_hand
    for event in gap_events:
        qty = event.quantity or 0
        if event.event_type == "inventory_recount":
            balance -= qty
        elif event.event_type == "sale":
            balance += qty
        elif event.event_type == "purchase":
            balance -= qty
        elif event.event_type == "customer_return":
            balance -= qty
        elif event.event_type == "vendor_return":
            balance += qty
    return balance


async def fetch_gap_events(upc, date_to, show_voided, s2s_conn, s2s_store_name, sales_stores, inventory_store, db):
    today = date.today()
    gap_from = date_to + timedelta(days=1)
    if gap_from > today:
        return []

    gap_events = []
    tasks = []

    conn_kwargs = dict(
        host=s2s_conn.host,
        port=s2s_conn.port,
        database=s2s_conn.database_name,
        username=s2s_conn.username,
        password=s2s_conn.password,
    )

    tasks.append(("purchase", s2s_store_name, get_purchases_async(**conn_kwargs, upc=upc, date_from=gap_from, date_to=today)))
    tasks.append(("vendor_return", s2s_store_name, get_vendor_returns_async(**conn_kwargs, upc=upc, date_from=gap_from, date_to=today)))

    for store in sales_stores:
        if store.mssql_connection:
            c = store.mssql_connection
            sk = dict(host=c.host, port=c.port, database=c.database_name, username=c.username, password=c.password)
            tasks.append(("sale", store.name, get_sales_async(**sk, upc=upc, date_from=gap_from, date_to=today, show_voided=show_voided)))
            tasks.append(("customer_return", store.name, get_customer_returns_async(**sk, upc=upc, date_from=gap_from, date_to=today)))

    if inventory_store and inventory_store.mssql_connection:
        inv_conn = inventory_store.mssql_connection
        tasks.append(("inventory_recount", inventory_store.name, get_inventory_recounts_async(
            host=inv_conn.host, port=inv_conn.port, database=inv_conn.database_name,
            username=inv_conn.username, password=inv_conn.password,
            upc=upc, date_from=gap_from, date_to=today
        )))

    results = await asyncio.gather(*[t[2] for t in tasks], return_exceptions=True)

    for (event_type, store_name, _), result in zip(tasks, results):
        if isinstance(result, Exception):
            continue
        success, error, rows = result
        if not success:
            continue
        for r in rows:
            if event_type == "inventory_recount":
                gap_events.append(ItemTrackerEvent(
                    event_type=event_type,
                    event_date=r["event_date"],
                    store_name=store_name,
                    document_number=r["update_type"],
                    quantity=r["quantity"],
                    price_or_cost=None,
                    business_name=r["username"],
                    line_id=r["line_id"],
                    extended_amount=r.get("new_qty"),
                    username=r["username"],
                    update_type=r["update_type"]
                ))
            else:
                gap_events.append(ItemTrackerEvent(
                    event_type=event_type,
                    event_date=r["event_date"],
                    store_name=store_name,
                    document_number=r["document_number"],
                    quantity=r["quantity"],
                    price_or_cost=r.get("price_or_cost"),
                    business_name=r.get("business_name"),
                    line_id=r["line_id"],
                    extended_amount=r.get("extended_amount"),
                    is_voided=r.get("is_voided", False) if event_type == "sale" else None
                ))

    gap_events, _ = apply_exclusion_filter(gap_events, {}, db)
    gap_events.sort(key=lambda e: e.event_date if e.event_date else datetime.min, reverse=True)
    return gap_events


@app.post("/api/item-tracker/search/stream")
async def search_item_tracker_stream(request: ItemTrackerSearchRequest, db: Session = Depends(get_db)):
    """
    Search for item history by UPC with real-time progress updates.
    Returns Server-Sent Events stream.
    """
    async def generate_search_events() -> AsyncGenerator[str, None]:
        upc = request.upc.strip()
        date_from = request.date_from
        date_to = request.date_to
        show_voided = request.show_voided

        if not upc:
            yield f"event: error\ndata: {json.dumps({'message': 'UPC is required'})}\n\n"
            return

        # Get Item Tracker config
        config = db.query(ItemTrackerConfig).first()

        if not config or not config.s2s_store_id:
            yield f"event: error\ndata: {json.dumps({'message': 'Item Tracker not configured. Please configure S2S database in Settings.'})}\n\n"
            return

        # Get S2S store connection
        s2s_store = db.query(Store).filter(
            Store.id == config.s2s_store_id,
            Store.store_type == StoreType.mssql
        ).first()

        if not s2s_store or not s2s_store.mssql_connection:
            yield f"event: error\ndata: {json.dumps({'message': 'S2S database not found or missing connection details'})}\n\n"
            return

        s2s_conn = s2s_store.mssql_connection
        all_events = []
        event_counts = {
            "purchase": 0,
            "sale": 0,
            "customer_return": 0,
            "vendor_return": 0,
            "inventory_recount": 0,
            "in_progress": 0,
        }
        stores_searched = 1  # S2S store
        item_info = None
        sales_stores = []
        inventory_store = None
        errors = []

        try:
            # 1. Get Item Info from S2S
            yield f"event: progress\ndata: {json.dumps({'status': 'searching', 'message': f'Fetching item info from {s2s_store.name}...'})}\n\n"

            success, error, item_data = await get_item_info_async(
                host=s2s_conn.host,
                port=s2s_conn.port,
                database=s2s_conn.database_name,
                username=s2s_conn.username,
                password=s2s_conn.password,
                upc=upc
            )

            if not success:
                errors.append(f"S2S Items_tbl: {error}")
            elif item_data:
                item_info = ItemInfo(
                    product_id=item_data["product_id"],
                    product_upc=item_data["product_upc"],
                    product_description=item_data["product_description"],
                    last_received=item_data["last_received"],
                    last_sold=item_data["last_sold"],
                    unit_price=item_data["unit_price"],
                    unit_cost=item_data["unit_cost"],
                    avr_cost=item_data["avr_cost"],
                    quant_on_hand=item_data["quant_on_hand"]
                )

                description = item_data["product_description"] or upc
                yield f"event: progress\ndata: {json.dumps({'status': 'found_item', 'message': f'Found item: {description}'})}\n\n"
            else:
                yield f"event: progress\ndata: {json.dumps({'status': 'not_found', 'message': 'Item not found in S2S Items_tbl'})}\n\n"

            # 2. Get Purchases from S2S (run in parallel with vendor returns)
            yield f"event: progress\ndata: {json.dumps({'status': 'searching', 'message': 'Fetching purchase history...'})}\n\n"

            purchases_task = get_purchases_async(
                host=s2s_conn.host,
                port=s2s_conn.port,
                database=s2s_conn.database_name,
                username=s2s_conn.username,
                password=s2s_conn.password,
                upc=upc,
                date_from=date_from,
                date_to=date_to
            )

            # 3. Get Vendor Returns from S2S
            vendor_returns_task = get_vendor_returns_async(
                host=s2s_conn.host,
                port=s2s_conn.port,
                database=s2s_conn.database_name,
                username=s2s_conn.username,
                password=s2s_conn.password,
                upc=upc,
                date_from=date_from,
                date_to=date_to
            )

            # Wait for both S2S queries
            purchases_result, vendor_returns_result = await asyncio.gather(
                purchases_task, vendor_returns_task
            )

            # Process purchases
            success, error, purchases = purchases_result
            if not success:
                errors.append(f"S2S Purchases: {error}")
            else:
                for p in purchases:
                    event = ItemTrackerEvent(
                        event_type="purchase",
                        event_date=p["event_date"],
                        store_name=s2s_store.name,
                        document_number=p["document_number"],
                        quantity=p["quantity"],
                        price_or_cost=p["price_or_cost"],
                        business_name=p["business_name"],
                        line_id=p["line_id"],
                        extended_amount=p["extended_amount"]
                    )
                    all_events.append(event)
                event_counts["purchase"] = len(purchases)

            yield f"event: progress\ndata: {json.dumps({'status': 'completed', 'message': f'Found {len(purchases)} purchases'})}\n\n"

            # Process vendor returns
            success, error, vendor_returns = vendor_returns_result
            if not success:
                errors.append(f"S2S Vendor Returns: {error}")
            else:
                for r in vendor_returns:
                    event = ItemTrackerEvent(
                        event_type="vendor_return",
                        event_date=r["event_date"],
                        store_name=s2s_store.name,
                        document_number=r["document_number"],
                        quantity=r["quantity"],
                        price_or_cost=r["price_or_cost"],
                        business_name=r["business_name"],
                        line_id=r["line_id"],
                        extended_amount=r["extended_amount"]
                    )
                    all_events.append(event)
                event_counts["vendor_return"] = len(vendor_returns)

            yield f"event: progress\ndata: {json.dumps({'status': 'completed', 'message': f'Found {len(vendor_returns)} vendor returns'})}\n\n"

            # 4. Get Sales and Customer Returns from Sales Stores
            if config.sales_store_ids:
                sales_stores = db.query(Store).filter(
                    Store.id.in_(config.sales_store_ids),
                    Store.store_type == StoreType.mssql
                ).all()

                stores_searched += len(sales_stores)

                # Create tasks for all sales stores
                sales_tasks = []
                customer_return_tasks = []

                for store in sales_stores:
                    if store.mssql_connection:
                        conn = store.mssql_connection

                        # Sales task
                        sales_tasks.append((
                            store.name,
                            get_sales_async(
                                host=conn.host,
                                port=conn.port,
                                database=conn.database_name,
                                username=conn.username,
                                password=conn.password,
                                upc=upc,
                                date_from=date_from,
                                date_to=date_to,
                                show_voided=show_voided
                            )
                        ))

                        # Customer returns task
                        customer_return_tasks.append((
                            store.name,
                            get_customer_returns_async(
                                host=conn.host,
                                port=conn.port,
                                database=conn.database_name,
                                username=conn.username,
                                password=conn.password,
                                upc=upc,
                                date_from=date_from,
                                date_to=date_to
                            )
                        ))

                # Process sales from all stores in parallel
                if sales_tasks:
                    yield f"event: progress\ndata: {json.dumps({'status': 'searching', 'message': f'Searching sales across {len(sales_tasks)} stores...'})}\n\n"

                    for store_name, task in sales_tasks:
                        success, error, sales = await task
                        if not success:
                            errors.append(f"{store_name} Sales: {error}")
                        else:
                            for s in sales:
                                event = ItemTrackerEvent(
                                    event_type="sale",
                                    event_date=s["event_date"],
                                    store_name=store_name,
                                    document_number=s["document_number"],
                                    quantity=s["quantity"],
                                    price_or_cost=s["price_or_cost"],
                                    business_name=s["business_name"],
                                    line_id=s["line_id"],
                                    extended_amount=s["extended_amount"],
                                    is_voided=s.get("is_voided", False)
                                )
                                all_events.append(event)
                            event_counts["sale"] += len(sales)

                            yield f"event: progress\ndata: {json.dumps({'status': 'store_complete', 'store_name': store_name, 'event_type': 'sale', 'count': len(sales)})}\n\n"

                # Process customer returns from all stores in parallel
                if customer_return_tasks:
                    yield f"event: progress\ndata: {json.dumps({'status': 'searching', 'message': f'Searching customer returns across {len(customer_return_tasks)} stores...'})}\n\n"

                    for store_name, task in customer_return_tasks:
                        success, error, returns = await task
                        if not success:
                            errors.append(f"{store_name} Customer Returns: {error}")
                        else:
                            for r in returns:
                                event = ItemTrackerEvent(
                                    event_type="customer_return",
                                    event_date=r["event_date"],
                                    store_name=store_name,
                                    document_number=r["document_number"],
                                    quantity=r["quantity"],
                                    price_or_cost=r["price_or_cost"],
                                    business_name=r["business_name"],
                                    line_id=r["line_id"],
                                    extended_amount=r["extended_amount"]
                                )
                                all_events.append(event)
                            event_counts["customer_return"] += len(returns)

                            yield f"event: progress\ndata: {json.dumps({'status': 'store_complete', 'store_name': store_name, 'event_type': 'customer_return', 'count': len(returns)})}\n\n"

            # 5. Get Inventory Recounts (if configured)
            if config.inventory_store_id:
                inventory_store = db.query(Store).filter(
                    Store.id == config.inventory_store_id,
                    Store.store_type == StoreType.mssql
                ).first()

                if inventory_store and inventory_store.mssql_connection:
                    stores_searched += 1
                    inv_conn = inventory_store.mssql_connection

                    yield f"event: progress\ndata: {json.dumps({'status': 'searching', 'message': f'Fetching inventory recounts from {inventory_store.name}...'})}\n\n"

                    success, error, recounts = await get_inventory_recounts_async(
                        host=inv_conn.host,
                        port=inv_conn.port,
                        database=inv_conn.database_name,
                        username=inv_conn.username,
                        password=inv_conn.password,
                        upc=upc,
                        date_from=date_from,
                        date_to=date_to
                    )

                    if not success:
                        errors.append(f"Inventory Recounts: {error}")
                    else:
                        for r in recounts:
                            event = ItemTrackerEvent(
                                event_type="inventory_recount",
                                event_date=r["event_date"],
                                store_name=inventory_store.name,
                                document_number=r["update_type"],
                                quantity=r["quantity"],  # DiffQty for Qty column
                                price_or_cost=None,
                                business_name=r["username"],
                                line_id=r["line_id"],
                                extended_amount=r.get("new_qty"),  # NewQty for running_balance
                                username=r["username"],
                                update_type=r["update_type"]
                            )
                            all_events.append(event)
                        event_counts["inventory_recount"] = len(recounts)

                        yield f"event: progress\ndata: {json.dumps({'status': 'completed', 'message': f'Found {len(recounts)} inventory recounts'})}\n\n"

            # In-progress reservations from the centralized DB_ADMIN store
            # (QuotationsInProgress). Informational only -- these events do
            # NOT contribute to the running balance walk; they are simply
            # surfaced in the timeline at their StartDate so the user can
            # see when the UPC was reserved by a quotation.
            admin_store = _resolve_admin_store_soft(db)
            if admin_store and admin_store.mssql_connection:
                stores_searched += 1
                admin_conn = admin_store.mssql_connection

                yield f"event: progress\ndata: {json.dumps({'status': 'searching', 'message': f'Fetching in-progress reservations from {admin_store.name}...'})}\n\n"

                success, error, in_progress_rows = await get_in_progress_async(
                    host=admin_conn.host,
                    port=admin_conn.port,
                    database=admin_conn.database_name,
                    username=admin_conn.username,
                    password=admin_conn.password,
                    upc=upc,
                    date_from=date_from,
                    date_to=date_to
                )

                if not success:
                    errors.append(f"In Progress: {error}")
                else:
                    for r in in_progress_rows:
                        # Use the originating store's name (SourceDB column
                        # in QuotationsInProgress) so the timeline reflects
                        # which store the reservation came from, not the
                        # central DB_ADMIN store we queried.
                        source_db = (r.get("source_db") or "").strip()
                        event = ItemTrackerEvent(
                            event_type="in_progress",
                            event_date=r["event_date"],
                            store_name=source_db or admin_store.name,
                            document_number=r["document_number"],
                            quantity=r["quantity"],
                            price_or_cost=None,
                            business_name=r.get("business_name"),
                            line_id=r["line_id"],
                        )
                        all_events.append(event)
                    event_counts["in_progress"] = len(in_progress_rows)

                    yield f"event: progress\ndata: {json.dumps({'status': 'completed', 'message': f'Found {len(in_progress_rows)} in-progress reservations'})}\n\n"

            # Filter out excluded business names (void-aware)
            all_events, event_counts = apply_exclusion_filter(all_events, event_counts, db)

            # Sort all events by date (newest first)
            all_events.sort(key=lambda e: e.event_date if e.event_date else datetime.min, reverse=True)

            # Calculate running balance (working backwards from current QoH)
            if item_info and item_info.quant_on_hand is not None:
                balance = item_info.quant_on_hand
                if date_to and date_to < date.today():
                    gap_events = await fetch_gap_events(
                        upc, date_to, show_voided, s2s_conn, s2s_store.name,
                        sales_stores, inventory_store, db
                    )
                    balance = compute_adjusted_balance(balance, gap_events)
                for event in all_events:
                    if event.event_type == "inventory_recount":
                        event.expected_balance = balance
                        new_qty = event.extended_amount  # NewQty stored in extended_amount
                        event.running_balance = new_qty  # Absolute qty after recount
                        event.extended_amount = None  # Clear it, not needed in response
                        balance = (new_qty or 0) - (event.quantity or 0)  # Reset to pre-recount qty
                    else:
                        event.running_balance = balance
                        qty = event.quantity or 0
                        if event.event_type == "sale":
                            balance += qty
                        elif event.event_type == "purchase":
                            balance -= qty
                        elif event.event_type == "customer_return":
                            balance -= qty
                        elif event.event_type == "vendor_return":
                            balance += qty

            # Convert events to dict for JSON serialization
            events_dict = []
            for event in all_events:
                event_data = {
                    "event_type": event.event_type,
                    "event_date": event.event_date.isoformat() if event.event_date else None,
                    "store_name": event.store_name,
                    "document_number": event.document_number,
                    "quantity": event.quantity,
                    "price_or_cost": event.price_or_cost,
                    "business_name": event.business_name,
                    "line_id": event.line_id,
                    "extended_amount": event.extended_amount,
                    "is_voided": event.is_voided,
                    "username": event.username,
                    "update_type": event.update_type,
                    "running_balance": event.running_balance,
                    "expected_balance": event.expected_balance
                }
                events_dict.append(event_data)

            # Prepare item_info for JSON
            item_info_dict = None
            if item_info:
                item_info_dict = {
                    "product_id": item_info.product_id,
                    "product_upc": item_info.product_upc,
                    "product_description": item_info.product_description,
                    "last_received": item_info.last_received.isoformat() if item_info.last_received else None,
                    "last_sold": item_info.last_sold.isoformat() if item_info.last_sold else None,
                    "unit_price": item_info.unit_price,
                    "unit_cost": item_info.unit_cost,
                    "avr_cost": item_info.avr_cost,
                    "quant_on_hand": item_info.quant_on_hand
                }

            # Send complete event
            result = {
                "upc": upc,
                "item_info": item_info_dict,
                "events": events_dict,
                "event_counts": event_counts,
                "total_events": len(all_events),
                "stores_searched": stores_searched,
                "errors": errors if errors else None
            }

            yield f"event: complete\ndata: {json.dumps(result)}\n\n"

        except GeneratorExit:
            print("[ITEM-TRACKER] Client disconnected")
            return
        except Exception as e:
            print(f"[ITEM-TRACKER] Error: {e}")
            import traceback
            traceback.print_exc()
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return StreamingResponse(
        generate_search_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.get("/api/item-tracker/summary", response_model=ItemTrackerSummaryResponse)
async def get_item_tracker_summary(
    upc: str,
    date_from: Optional[date] = Query(None, alias="from"),
    date_to: Optional[date] = Query(None, alias="to"),
    show_voided: bool = Query(True),
    db: Session = Depends(get_db),
):
    upc = upc.strip()
    if not upc:
        raise HTTPException(status_code=400, detail="UPC is required")

    config, s2s_store, s2s_conn, sales_stores, inventory_store = get_item_tracker_stores(db)

    all_events = []
    event_counts = {
        "purchase": 0,
        "sale": 0,
        "customer_return": 0,
        "vendor_return": 0,
        "inventory_recount": 0
    }
    stores_searched = 1
    item_info = None
    errors = []

    conn_kwargs = dict(
        host=s2s_conn.host,
        port=s2s_conn.port,
        database=s2s_conn.database_name,
        username=s2s_conn.username,
        password=s2s_conn.password,
    )

    # 1. Get Item Info from S2S
    success, error, item_data = await get_item_info_async(**conn_kwargs, upc=upc)
    if not success:
        errors.append(f"S2S Items_tbl: {error}")
    elif item_data:
        item_info = ItemInfo(
            product_id=item_data["product_id"],
            product_upc=item_data["product_upc"],
            product_description=item_data["product_description"],
            last_received=item_data["last_received"],
            last_sold=item_data["last_sold"],
            unit_price=item_data["unit_price"],
            unit_cost=item_data["unit_cost"],
            avr_cost=item_data["avr_cost"],
            quant_on_hand=item_data["quant_on_hand"]
        )

    # 2. Get Purchases + Vendor Returns from S2S in parallel
    purchases_result, vendor_returns_result = await asyncio.gather(
        get_purchases_async(**conn_kwargs, upc=upc, date_from=date_from, date_to=date_to),
        get_vendor_returns_async(**conn_kwargs, upc=upc, date_from=date_from, date_to=date_to),
    )

    success, error, purchases = purchases_result
    if not success:
        errors.append(f"S2S Purchases: {error}")
    else:
        for p in purchases:
            all_events.append(ItemTrackerEvent(
                event_type="purchase",
                event_date=p["event_date"],
                store_name=s2s_store.name,
                document_number=p["document_number"],
                quantity=p["quantity"],
                price_or_cost=p["price_or_cost"],
                business_name=p["business_name"],
                line_id=p["line_id"],
                extended_amount=p["extended_amount"]
            ))
        event_counts["purchase"] = len(purchases)

    success, error, vendor_returns = vendor_returns_result
    if not success:
        errors.append(f"S2S Vendor Returns: {error}")
    else:
        for r in vendor_returns:
            all_events.append(ItemTrackerEvent(
                event_type="vendor_return",
                event_date=r["event_date"],
                store_name=s2s_store.name,
                document_number=r["document_number"],
                quantity=r["quantity"],
                price_or_cost=r["price_or_cost"],
                business_name=r["business_name"],
                line_id=r["line_id"],
                extended_amount=r["extended_amount"]
            ))
        event_counts["vendor_return"] = len(vendor_returns)

    # 3. Get Sales + Customer Returns from all sales stores
    if sales_stores:
        stores_searched += len(sales_stores)
        sales_tasks = []
        cr_tasks = []
        for store in sales_stores:
            if store.mssql_connection:
                c = store.mssql_connection
                sk = dict(host=c.host, port=c.port, database=c.database_name, username=c.username, password=c.password)
                sales_tasks.append((store.name, get_sales_async(**sk, upc=upc, date_from=date_from, date_to=date_to, show_voided=show_voided)))
                cr_tasks.append((store.name, get_customer_returns_async(**sk, upc=upc, date_from=date_from, date_to=date_to)))

        for store_name, task in sales_tasks:
            success, error, sales = await task
            if not success:
                errors.append(f"{store_name} Sales: {error}")
            else:
                for s in sales:
                    all_events.append(ItemTrackerEvent(
                        event_type="sale",
                        event_date=s["event_date"],
                        store_name=store_name,
                        document_number=s["document_number"],
                        quantity=s["quantity"],
                        price_or_cost=s["price_or_cost"],
                        business_name=s["business_name"],
                        line_id=s["line_id"],
                        extended_amount=s["extended_amount"],
                        is_voided=s.get("is_voided", False)
                    ))
                event_counts["sale"] += len(sales)

        for store_name, task in cr_tasks:
            success, error, returns = await task
            if not success:
                errors.append(f"{store_name} Customer Returns: {error}")
            else:
                for r in returns:
                    all_events.append(ItemTrackerEvent(
                        event_type="customer_return",
                        event_date=r["event_date"],
                        store_name=store_name,
                        document_number=r["document_number"],
                        quantity=r["quantity"],
                        price_or_cost=r["price_or_cost"],
                        business_name=r["business_name"],
                        line_id=r["line_id"],
                        extended_amount=r["extended_amount"]
                    ))
                event_counts["customer_return"] += len(returns)

    # 4. Inventory Recounts
    if inventory_store and inventory_store.mssql_connection:
        stores_searched += 1
        inv_conn = inventory_store.mssql_connection
        success, error, recounts = await get_inventory_recounts_async(
            host=inv_conn.host,
            port=inv_conn.port,
            database=inv_conn.database_name,
            username=inv_conn.username,
            password=inv_conn.password,
            upc=upc,
            date_from=date_from,
            date_to=date_to
        )
        if not success:
            errors.append(f"Inventory Recounts: {error}")
        else:
            for r in recounts:
                all_events.append(ItemTrackerEvent(
                    event_type="inventory_recount",
                    event_date=r["event_date"],
                    store_name=inventory_store.name,
                    document_number=r["update_type"],
                    quantity=r["quantity"],
                    price_or_cost=None,
                    business_name=r["username"],
                    line_id=r["line_id"],
                    extended_amount=r.get("new_qty"),
                    username=r["username"],
                    update_type=r["update_type"]
                ))
            event_counts["inventory_recount"] = len(recounts)

    # 5. Apply exclusion filter
    all_events, event_counts = apply_exclusion_filter(all_events, event_counts, db)

    # 6. Sort by date (newest first) and calculate running balance
    all_events.sort(key=lambda e: e.event_date if e.event_date else datetime.min, reverse=True)

    beginning_inventory = None
    ending_inventory = None

    if item_info and item_info.quant_on_hand is not None and all_events:
        balance = item_info.quant_on_hand
        if date_to and date_to < date.today():
            gap_events = await fetch_gap_events(
                upc, date_to, show_voided, s2s_conn, s2s_store.name,
                sales_stores, inventory_store, db
            )
            balance = compute_adjusted_balance(balance, gap_events)
        for event in all_events:
            if event.event_type == "inventory_recount":
                new_qty = event.extended_amount
                event.running_balance = new_qty
                event.extended_amount = None
                balance = (new_qty or 0) - (event.quantity or 0)  # Reset to pre-recount qty
            else:
                event.running_balance = balance
                qty = event.quantity or 0
                if event.event_type == "sale":
                    balance += qty
                elif event.event_type == "purchase":
                    balance -= qty
                elif event.event_type == "customer_return":
                    balance -= qty
                elif event.event_type == "vendor_return":
                    balance += qty

        ending_inventory = all_events[0].running_balance
        last_event = all_events[-1]
        if last_event.event_type == "inventory_recount":
            beginning_inventory = last_event.running_balance - (last_event.quantity or 0)
        else:
            qty = last_event.quantity or 0
            if last_event.event_type == "sale":
                beginning_inventory = last_event.running_balance + qty
            elif last_event.event_type == "purchase":
                beginning_inventory = last_event.running_balance - qty
            elif last_event.event_type == "customer_return":
                beginning_inventory = last_event.running_balance - qty
            elif last_event.event_type == "vendor_return":
                beginning_inventory = last_event.running_balance + qty
            else:
                beginning_inventory = last_event.running_balance

    # 7. Compute quantity totals and net quantity
    qty_totals = compute_quantity_totals(all_events)
    net_quantity = qty_totals["purchase"] - qty_totals["sale"] + qty_totals["customer_return"] - qty_totals["vendor_return"]

    summary_item_info = None
    if item_info:
        summary_item_info = ItemTrackerSummaryItemInfo(
            product_upc=item_info.product_upc,
            product_description=item_info.product_description,
            quant_on_hand=item_info.quant_on_hand,
            unit_price=item_info.unit_price,
            unit_cost=item_info.unit_cost,
            avr_cost=item_info.avr_cost
        )

    return ItemTrackerSummaryResponse(
        upc=upc,
        item_info=summary_item_info,
        event_counts=event_counts,
        quantity_totals=ItemTrackerQuantityTotals(**qty_totals),
        net_quantity=net_quantity,
        beginning_inventory=beginning_inventory,
        ending_inventory=ending_inventory,
        total_events=len(all_events),
        stores_searched=stores_searched,
        errors=errors if errors else None
    )


@app.post("/api/item-tracker/description/autocomplete", response_model=DescriptionAutocompleteResponse)
async def autocomplete_product_description(request: DescriptionAutocompleteRequest, db: Session = Depends(get_db)):
    """
    Search for products by description for autocomplete suggestions.
    Only returns active products (Discontinued=0) from the configured S2S database.
    """
    query = request.query.strip()

    if not query or len(query) < 2:
        return DescriptionAutocompleteResponse(results=[], count=0)

    config = db.query(ItemTrackerConfig).first()

    if not config or not config.s2s_store_id:
        raise HTTPException(
            status_code=400,
            detail="Item Tracker not configured. Please configure S2S database in Settings."
        )

    s2s_store = db.query(Store).filter(
        Store.id == config.s2s_store_id,
        Store.store_type == StoreType.mssql
    ).first()

    if not s2s_store or not s2s_store.mssql_connection:
        raise HTTPException(
            status_code=400,
            detail="S2S database not found or missing connection details"
        )

    conn = s2s_store.mssql_connection

    success, error, products = await search_products_by_description_async(
        host=conn.host,
        port=conn.port,
        database=conn.database_name,
        username=conn.username,
        password=conn.password,
        query=query,
        limit=10
    )

    if not success:
        raise HTTPException(status_code=500, detail=f"Database error: {error}")

    results = [
        DescriptionAutocompleteResult(
            product_id=p["product_id"],
            product_upc=p["product_upc"],
            product_description=p["product_description"],
            quant_on_hand=p["quant_on_hand"]
        )
        for p in products
    ]

    return DescriptionAutocompleteResponse(results=results, count=len(results))


@app.post("/api/item-tracker/exclusions", response_model=ItemTrackerExclusionResponse)
async def add_item_tracker_exclusion(request: ItemTrackerExclusionCreate, db: Session = Depends(get_db)):
    """
    Add a business name (customer/supplier) to the Item Tracker exclusion list.
    void_status: NULL=all events, 0=non-voided only, 1=voided only
    """
    business_name = request.business_name.strip()
    if not business_name:
        raise HTTPException(status_code=400, detail="Business name is required")

    # Check for existing exclusion with same business_name AND void_status
    query = db.query(ItemTrackerExclusion).filter(
        ItemTrackerExclusion.business_name.ilike(business_name)
    )
    if request.void_status is None:
        query = query.filter(ItemTrackerExclusion.void_status.is_(None))
    else:
        query = query.filter(ItemTrackerExclusion.void_status == request.void_status)

    existing = query.first()

    if existing:
        scope_text = "all events"
        if request.void_status == 0:
            scope_text = "non-voided invoices"
        elif request.void_status == 1:
            scope_text = "voided invoices"
        raise HTTPException(
            status_code=409,
            detail=f"Business name '{business_name}' is already excluded for {scope_text}"
        )

    exclusion = ItemTrackerExclusion(
        business_name=business_name,
        void_status=request.void_status,
        notes=request.notes
    )
    db.add(exclusion)
    db.commit()
    db.refresh(exclusion)

    return ItemTrackerExclusionResponse(
        id=exclusion.id,
        business_name=exclusion.business_name,
        void_status=exclusion.void_status,
        excluded_at=exclusion.excluded_at,
        notes=exclusion.notes
    )


@app.get("/api/item-tracker/exclusions", response_model=ItemTrackerExclusionListResponse)
async def list_item_tracker_exclusions(db: Session = Depends(get_db)):
    """
    List all excluded business names for Item Tracker.
    """
    exclusions = db.query(ItemTrackerExclusion).order_by(
        ItemTrackerExclusion.excluded_at.desc()
    ).all()

    return ItemTrackerExclusionListResponse(
        exclusions=[
            ItemTrackerExclusionResponse(
                id=e.id,
                business_name=e.business_name,
                void_status=e.void_status,
                excluded_at=e.excluded_at,
                notes=e.notes
            )
            for e in exclusions
        ],
        total=len(exclusions)
    )


@app.delete("/api/item-tracker/exclusions/{exclusion_id}")
async def delete_item_tracker_exclusion(exclusion_id: int, db: Session = Depends(get_db)):
    """
    Remove a business name from the Item Tracker exclusion list.
    """
    exclusion = db.query(ItemTrackerExclusion).filter(
        ItemTrackerExclusion.id == exclusion_id
    ).first()

    if not exclusion:
        raise HTTPException(status_code=404, detail="Exclusion not found")

    db.delete(exclusion)
    db.commit()

    return {"message": "Exclusion removed successfully"}


## ==================== Price Updates ====================

@app.post("/api/price-updates/fetch-prices/stream")
async def fetch_prices_stream(request: PriceSearchRequest, db: Session = Depends(get_db)):
    async def generate_events() -> AsyncGenerator[str, None]:
        upc = request.upc.strip()
        if not upc:
            yield f"event: error\ndata: {json.dumps({'message': 'UPC is required'})}\n\n"
            return

        if not request.store_ids:
            yield f"event: error\ndata: {json.dumps({'message': 'No stores selected'})}\n\n"
            return

        prices = []
        sibling_prices = []

        stores_by_id = {}
        for store_id in request.store_ids:
            store = db.query(Store).filter(Store.id == store_id, Store.is_active == True).first()
            if store:
                stores_by_id[store_id] = store

        if request.include_sibling_barcodes:
            # ── PATH A: Siblings checked (parallel) ──

            # Phase 1: Parallel Shopify sibling discovery
            all_barcodes = {upc}
            sibling_barcode_info = {}
            shopify_cache = {}

            shopify_stores_phase1 = [
                (sid, s) for sid, s in stores_by_id.items()
                if s.store_type == StoreType.shopify and s.shopify_connection
            ]

            if shopify_stores_phase1:
                yield f"event: progress\ndata: {json.dumps({'status': 'searching', 'message': 'Discovering sibling barcodes...'})}\n\n"

                async def discover_siblings(store_id, store):
                    conn = store.shopify_connection
                    success, error, matched, variants_by_pid = await search_product_prices_with_siblings(
                        shop_domain=conn.shop_domain,
                        admin_api_key=conn.admin_api_key,
                        barcodes=[upc],
                        api_version=conn.api_version
                    )
                    return store_id, store, success, error, matched, variants_by_pid

                tasks = [asyncio.create_task(discover_siblings(sid, s)) for sid, s in shopify_stores_phase1]

                for completed_task in asyncio.as_completed(tasks):
                    store_id, store, success, error, matched, variants_by_pid = await completed_task

                    if not (success and matched):
                        continue

                    shopify_cache[store_id] = (store, matched, variants_by_pid)

                    searched_variant_ids = {v["variant_id"] for v in matched}
                    for pid, prod_variants in variants_by_pid.items():
                        searched_price = None
                        for v in matched:
                            if v.get("product_id") == pid and v.get("price") is not None:
                                searched_price = str(v["price"])
                                break
                        if searched_price is None:
                            continue

                        for v in prod_variants:
                            bc = (v.get("barcode") or "").strip()
                            if bc and bc != upc and v["variant_id"] not in searched_variant_ids and str(v.get("price")) == searched_price:
                                all_barcodes.add(bc)
                                sibling_barcode_info[bc] = v.get("variant_title", "")

            if len(all_barcodes) > 1:
                yield f"event: progress\ndata: {json.dumps({'status': 'searching', 'message': f'Found {len(all_barcodes) - 1} sibling barcode(s)'})}\n\n"

                sibling_barcodes = all_barcodes - {upc}
                for store_id in list(shopify_cache.keys()):
                    _, _, variants_by_pid = shopify_cache[store_id]
                    cached_barcodes = set()
                    for prod_variants in variants_by_pid.values():
                        for v in prod_variants:
                            bc = (v.get("barcode") or "").strip()
                            if bc:
                                cached_barcodes.add(bc)
                    if not sibling_barcodes.issubset(cached_barcodes):
                        del shopify_cache[store_id]

            # Phase 2: Parallel search across all stores
            mssql_stores_p2 = [
                (sid, s) for sid, s in stores_by_id.items()
                if s.store_type == StoreType.mssql and s.mssql_connection
            ]
            uncached_shopify = [
                (sid, s) for sid, s in shopify_stores_phase1
                if sid not in shopify_cache
            ]

            total_steps = len(mssql_stores_p2) + len(uncached_shopify)
            yield f"event: progress\ndata: {json.dumps({'status': 'total_steps', 'total': total_steps})}\n\n"

            # Emit cached Shopify results immediately
            for store_id, (store, matched, variants_by_pid) in shopify_cache.items():
                searched_variant_ids = {v["variant_id"] for v in matched}
                found_variants = {}
                for v in matched:
                    v["is_searched"] = True
                    found_variants[v["variant_id"]] = v

                for pid, prod_variants in variants_by_pid.items():
                    searched_price = None
                    for mv in matched:
                        if mv.get("product_id") == pid and mv.get("price") is not None:
                            searched_price = str(mv["price"])
                            break

                    for v in prod_variants:
                        vid = v["variant_id"]
                        if vid in found_variants:
                            continue
                        bc = (v.get("barcode") or "").strip()
                        if bc and bc in all_barcodes:
                            if searched_price is not None and str(v.get("price")) == searched_price:
                                v["is_searched"] = vid in searched_variant_ids
                                found_variants[vid] = v

                if found_variants:
                    variant_list = list(found_variants.values())
                    product_title = next(
                        (v.get("product_title") for v in variant_list if v.get("is_searched")),
                        variant_list[0].get("product_title")
                    )
                    prices.append({
                        "store_id": store.id,
                        "store_name": store.name,
                        "store_type": "shopify",
                        "product_found": True,
                        "product_description": product_title,
                        "unit_price": None,
                        "unit_cost": None,
                        "unit_delivery_b": None,
                        "unit_list_price": None,
                        "variants": variant_list,
                    })
                    yield f"event: progress\ndata: {json.dumps({'status': 'found', 'message': f'Found {len(variant_list)} variant(s) in {store.name}'})}\n\n"
                else:
                    prices.append({
                        "store_id": store.id,
                        "store_name": store.name,
                        "store_type": "shopify",
                        "product_found": False,
                        "product_description": None,
                        "unit_price": None,
                        "unit_cost": None,
                        "unit_delivery_b": None,
                        "unit_list_price": None,
                        "variants": None,
                    })
                    yield f"event: progress\ndata: {json.dumps({'status': 'not_found', 'message': f'Not found in {store.name}'})}\n\n"

            # Launch parallel tasks for MSSQL (batch) and uncached Shopify stores
            sorted_barcodes = sorted(all_barcodes)

            async def search_mssql_batch(store_id, store):
                conn = store.mssql_connection
                success, error, items_map = await get_item_prices_batch_async(
                    host=conn.host,
                    port=conn.port,
                    database=conn.database_name,
                    username=conn.username,
                    password=conn.password,
                    upcs=sorted_barcodes
                )
                return "mssql", store_id, store, success, error, items_map

            async def search_shopify_uncached(store_id, store):
                conn = store.shopify_connection
                success, error, matched, variants_by_pid = await search_product_prices_with_siblings(
                    shop_domain=conn.shop_domain,
                    admin_api_key=conn.admin_api_key,
                    barcodes=sorted_barcodes,
                    api_version=conn.api_version
                )
                return "shopify", store_id, store, success, error, (matched, variants_by_pid)

            phase2_tasks = []
            for sid, s in mssql_stores_p2:
                yield f"event: progress\ndata: {json.dumps({'status': 'searching', 'message': f'Searching {s.name}...'})}\n\n"
                phase2_tasks.append(asyncio.create_task(search_mssql_batch(sid, s)))
            for sid, s in uncached_shopify:
                yield f"event: progress\ndata: {json.dumps({'status': 'searching', 'message': f'Searching {s.name}...'})}\n\n"
                phase2_tasks.append(asyncio.create_task(search_shopify_uncached(sid, s)))

            for completed_task in asyncio.as_completed(phase2_tasks):
                result = await completed_task
                store_type_tag = result[0]

                if store_type_tag == "mssql":
                    _, store_id, store, success, error, items_map = result

                    if not success:
                        prices.append({
                            "store_id": store.id,
                            "store_name": store.name,
                            "store_type": "mssql",
                            "product_found": False,
                            "product_description": None,
                            "unit_price": None,
                            "unit_cost": None,
                            "unit_delivery_b": None,
                            "unit_list_price": None,
                            "variants": None,
                        })
                        yield f"event: progress\ndata: {json.dumps({'status': 'error', 'message': f'Error searching {store.name}: {error}'})}\n\n"
                        continue

                    primary_data = items_map.get(upc)
                    if primary_data:
                        prices.append({
                            "store_id": store.id,
                            "store_name": store.name,
                            "store_type": "mssql",
                            "product_found": True,
                            "product_description": primary_data["description"],
                            "unit_price": primary_data["unit_price"],
                            "unit_cost": primary_data["unit_cost"],
                            "unit_delivery_b": primary_data["unit_delivery_b"],
                            "unit_list_price": primary_data["unit_list_price"],
                            "variants": None,
                        })
                        yield f"event: progress\ndata: {json.dumps({'status': 'found', 'message': f'Found in {store.name}'})}\n\n"
                    else:
                        prices.append({
                            "store_id": store.id,
                            "store_name": store.name,
                            "store_type": "mssql",
                            "product_found": False,
                            "product_description": None,
                            "unit_price": None,
                            "unit_cost": None,
                            "unit_delivery_b": None,
                            "unit_list_price": None,
                            "variants": None,
                        })
                        yield f"event: progress\ndata: {json.dumps({'status': 'not_found', 'message': f'Not found in {store.name}'})}\n\n"

                    for bc, item_data in items_map.items():
                        if bc == upc:
                            continue
                        variant_title = sibling_barcode_info.get(bc, "")
                        sibling_prices.append({
                            "store_id": store.id,
                            "store_name": store.name,
                            "store_type": "mssql",
                            "product_found": True,
                            "product_description": item_data["description"],
                            "unit_price": item_data["unit_price"],
                            "unit_cost": item_data["unit_cost"],
                            "unit_delivery_b": item_data["unit_delivery_b"],
                            "unit_list_price": item_data["unit_list_price"],
                            "variants": None,
                            "sibling_barcode": bc,
                            "sibling_variant_title": variant_title,
                        })

                    sibling_not_found = [bc for bc in sorted_barcodes if bc != upc and bc not in items_map]
                    for bc in sibling_not_found:
                        variant_title = sibling_barcode_info.get(bc, "")
                        sibling_prices.append({
                            "store_id": store.id,
                            "store_name": store.name,
                            "store_type": "mssql",
                            "product_found": False,
                            "product_description": None,
                            "unit_price": None,
                            "unit_cost": None,
                            "unit_delivery_b": None,
                            "unit_list_price": None,
                            "variants": None,
                            "sibling_barcode": bc,
                            "sibling_variant_title": variant_title,
                        })

                else:
                    _, store_id, store, success, error, (matched, variants_by_pid) = result

                    if not (success and matched):
                        prices.append({
                            "store_id": store.id,
                            "store_name": store.name,
                            "store_type": "shopify",
                            "product_found": False,
                            "product_description": None,
                            "unit_price": None,
                            "unit_cost": None,
                            "unit_delivery_b": None,
                            "unit_list_price": None,
                            "variants": None,
                        })
                        msg = f'Error searching {store.name}: {error}' if error else f'Not found in {store.name}'
                        status = 'error' if error else 'not_found'
                        yield f"event: progress\ndata: {json.dumps({'status': status, 'message': msg})}\n\n"
                        continue

                    searched_variant_ids = {v["variant_id"] for v in matched if (v.get("barcode") or "").strip() == upc}
                    found_variants = {}
                    for v in matched:
                        bc = (v.get("barcode") or "").strip()
                        v["is_searched"] = bc == upc
                        found_variants[v["variant_id"]] = v

                    for pid, prod_variants in variants_by_pid.items():
                        searched_price = None
                        for mv in matched:
                            if mv.get("product_id") == pid and mv.get("price") is not None:
                                searched_price = str(mv["price"])
                                break

                        for v in prod_variants:
                            vid = v["variant_id"]
                            if vid in found_variants:
                                continue
                            bc = (v.get("barcode") or "").strip()
                            if bc and bc in all_barcodes:
                                if searched_price is not None and str(v.get("price")) == searched_price:
                                    v["is_searched"] = vid in searched_variant_ids
                                    found_variants[vid] = v

                    variant_list = list(found_variants.values())
                    product_title = next(
                        (v.get("product_title") for v in variant_list if v.get("is_searched")),
                        variant_list[0].get("product_title") if variant_list else None
                    )
                    prices.append({
                        "store_id": store.id,
                        "store_name": store.name,
                        "store_type": "shopify",
                        "product_found": True,
                        "product_description": product_title,
                        "unit_price": None,
                        "unit_cost": None,
                        "unit_delivery_b": None,
                        "unit_list_price": None,
                        "variants": variant_list,
                    })
                    yield f"event: progress\ndata: {json.dumps({'status': 'found', 'message': f'Found {len(variant_list)} variant(s) in {store.name}'})}\n\n"

        else:
            # ── PATH B: Siblings unchecked (parallel) ──
            total_steps = len(stores_by_id)
            yield f"event: progress\ndata: {json.dumps({'status': 'total_steps', 'total': total_steps})}\n\n"

            async def search_store_b(store_id, store):
                if store.store_type == StoreType.mssql and store.mssql_connection:
                    conn = store.mssql_connection
                    success, error, item_data = await get_item_prices_async(
                        host=conn.host,
                        port=conn.port,
                        database=conn.database_name,
                        username=conn.username,
                        password=conn.password,
                        upc=upc
                    )
                    return "mssql", store_id, store, success, error, item_data
                elif store.store_type == StoreType.shopify and store.shopify_connection:
                    conn = store.shopify_connection
                    success, error, matched, variants_by_pid = await search_product_prices_with_siblings(
                        shop_domain=conn.shop_domain,
                        admin_api_key=conn.admin_api_key,
                        barcodes=[upc],
                        api_version=conn.api_version
                    )
                    return "shopify", store_id, store, success, error, (matched, variants_by_pid)
                return None, store_id, store, False, "No connection", None

            tasks_b = []
            for store_id, store in stores_by_id.items():
                yield f"event: progress\ndata: {json.dumps({'status': 'searching', 'message': f'Searching {store.name}...'})}\n\n"
                tasks_b.append(asyncio.create_task(search_store_b(store_id, store)))

            for completed_task in asyncio.as_completed(tasks_b):
                result = await completed_task
                store_type_tag = result[0]

                if store_type_tag == "mssql":
                    _, store_id, store, success, error, item_data = result

                    if success and item_data:
                        prices.append({
                            "store_id": store.id,
                            "store_name": store.name,
                            "store_type": "mssql",
                            "product_found": True,
                            "product_description": item_data["description"],
                            "unit_price": item_data["unit_price"],
                            "unit_cost": item_data["unit_cost"],
                            "unit_delivery_b": item_data["unit_delivery_b"],
                            "unit_list_price": item_data["unit_list_price"],
                            "variants": None,
                        })
                        yield f"event: progress\ndata: {json.dumps({'status': 'found', 'message': f'Found in {store.name}'})}\n\n"
                    elif success:
                        prices.append({
                            "store_id": store.id,
                            "store_name": store.name,
                            "store_type": "mssql",
                            "product_found": False,
                            "product_description": None,
                            "unit_price": None,
                            "unit_cost": None,
                            "unit_delivery_b": None,
                            "unit_list_price": None,
                            "variants": None,
                        })
                        yield f"event: progress\ndata: {json.dumps({'status': 'not_found', 'message': f'Not found in {store.name}'})}\n\n"
                    else:
                        prices.append({
                            "store_id": store.id,
                            "store_name": store.name,
                            "store_type": "mssql",
                            "product_found": False,
                            "product_description": None,
                            "unit_price": None,
                            "unit_cost": None,
                            "unit_delivery_b": None,
                            "unit_list_price": None,
                            "variants": None,
                        })
                        yield f"event: progress\ndata: {json.dumps({'status': 'error', 'message': f'Error searching {store.name}: {error}'})}\n\n"

                elif store_type_tag == "shopify":
                    _, store_id, store, success, error, (matched, variants_by_pid) = result

                    if success and matched:
                        merged_variants = []
                        for v in matched:
                            v["is_searched"] = True
                            merged_variants.append(v)

                        prices.append({
                            "store_id": store.id,
                            "store_name": store.name,
                            "store_type": "shopify",
                            "product_found": True,
                            "product_description": matched[0].get("product_title"),
                            "unit_price": None,
                            "unit_cost": None,
                            "unit_delivery_b": None,
                            "unit_list_price": None,
                            "variants": merged_variants,
                        })
                        yield f"event: progress\ndata: {json.dumps({'status': 'found', 'message': f'Found {len(merged_variants)} variant(s) in {store.name}'})}\n\n"
                    elif success:
                        prices.append({
                            "store_id": store.id,
                            "store_name": store.name,
                            "store_type": "shopify",
                            "product_found": False,
                            "product_description": None,
                            "unit_price": None,
                            "unit_cost": None,
                            "unit_delivery_b": None,
                            "unit_list_price": None,
                            "variants": None,
                        })
                        yield f"event: progress\ndata: {json.dumps({'status': 'not_found', 'message': f'Not found in {store.name}'})}\n\n"
                    else:
                        prices.append({
                            "store_id": store.id,
                            "store_name": store.name,
                            "store_type": "shopify",
                            "product_found": False,
                            "product_description": None,
                            "unit_price": None,
                            "unit_cost": None,
                            "unit_delivery_b": None,
                            "unit_list_price": None,
                            "variants": None,
                        })
                        yield f"event: progress\ndata: {json.dumps({'status': 'error', 'message': f'Error searching {store.name}: {error}'})}\n\n"

        yield f"event: complete\ndata: {json.dumps({'prices': prices, 'sibling_prices': sibling_prices})}\n\n"

    async def generate_events_safe() -> AsyncGenerator[str, None]:
        try:
            async for event in generate_events():
                yield event
        except GeneratorExit:
            print("[PRICE-FETCH] Client disconnected")
            return

    return StreamingResponse(
        generate_events_safe(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
    )


@app.post("/api/price-updates/update/stream")
async def update_prices_stream(request: PriceUpdateRequest, db: Session = Depends(get_db)):
    async def generate_events() -> AsyncGenerator[str, None]:
        upc = request.upc.strip()
        if not upc:
            yield f"event: error\ndata: {json.dumps({'message': 'UPC is required'})}\n\n"
            return

        batch_id = str(uuid.uuid4())
        results = []

        valid_updates = []
        for update in request.updates:
            store = db.query(Store).filter(Store.id == update.store_id, Store.is_active == True).first()
            if not store:
                results.append({"store_id": update.store_id, "store_name": "Unknown", "success": False, "error": "Store not found"})
                continue
            valid_updates.append((update, store))

        if not valid_updates:
            yield f"event: complete\ndata: {json.dumps({'results': results, 'batch_id': batch_id})}\n\n"
            return

        yield f"event: progress\ndata: {json.dumps({'status': 'updating', 'message': f'Updating {len(valid_updates)} store(s) in parallel...'})}\n\n"

        async def update_mssql_store(update, store):
            conn = store.mssql_connection
            effective_upc = update.upc or upc
            success, error, rows, server_time = await update_item_prices_async(
                host=conn.host,
                port=conn.port,
                database=conn.database_name,
                username=conn.username,
                password=conn.password,
                upc=effective_upc,
                unit_price=update.new_price,
                unit_cost=update.new_cost,
                unit_delivery_b=update.new_delivery_b,
                unit_list_price=update.new_list_price
            )
            return {
                "type": "mssql",
                "update": update,
                "store": store,
                "effective_upc": effective_upc,
                "success": success,
                "error": error,
                "rows": rows,
                "server_time": server_time,
            }

        async def update_shopify_store(update, store):
            conn = store.shopify_connection
            products = {}
            for vu in update.variant_updates:
                pid = vu["product_id"]
                if pid not in products:
                    products[pid] = []
                products[pid].append(vu)

            sem = asyncio.Semaphore(4)

            async def update_product(product_id, variants):
                async with sem:
                    return await update_variant_prices(
                        shop_domain=conn.shop_domain,
                        admin_api_key=conn.admin_api_key,
                        product_id=product_id,
                        variant_updates=variants,
                        api_version=conn.api_version
                    )

            product_results = await asyncio.gather(
                *(update_product(pid, variants) for pid, variants in products.items())
            )

            total_updated = 0
            errors = []
            for success, error, count in product_results:
                if success:
                    total_updated += count
                else:
                    errors.append(error)

            return {
                "type": "shopify",
                "update": update,
                "store": store,
                "success": len(errors) == 0,
                "total_updated": total_updated,
                "errors": errors,
            }

        tasks = {}
        for update, store in valid_updates:
            if update.store_type == "mssql" and store.mssql_connection:
                task = asyncio.create_task(update_mssql_store(update, store))
                tasks[task] = store.name
            elif update.store_type == "shopify" and store.shopify_connection and update.variant_updates:
                task = asyncio.create_task(update_shopify_store(update, store))
                tasks[task] = store.name

        for coro in asyncio.as_completed(list(tasks.keys())):
            result = await coro

            if result["type"] == "mssql":
                store = result["store"]
                update = result["update"]
                success = result["success"]
                error = result["error"]
                rows = result["rows"]
                server_time = result["server_time"]
                effective_upc = result["effective_upc"]

                results.append({
                    "store_id": store.id,
                    "store_name": store.name,
                    "success": success,
                    "rows_affected": rows,
                    "error": error,
                })

                history_entry = PriceUpdateHistory(
                    batch_id=batch_id,
                    store_id=store.id,
                    store_name=store.name,
                    store_type=update.store_type,
                    upc=effective_upc,
                    product_description=update.product_description,
                    variant_barcode=effective_upc,
                    old_price=update.old_price,
                    old_cost=update.old_cost,
                    new_price=update.new_price,
                    new_cost=update.new_cost,
                    old_delivery_b=update.old_delivery_b,
                    new_delivery_b=update.new_delivery_b,
                    old_list_price=update.old_list_price,
                    new_list_price=update.new_list_price,
                    success=success,
                    rows_affected=rows or 0,
                    error_message=error,
                    created_at=server_time
                )
                db.add(history_entry)
                db.commit()

                if success:
                    yield f"event: progress\ndata: {json.dumps({'status': 'updated', 'message': f'Updated {store.name} ({rows} row(s))'})}\n\n"
                else:
                    yield f"event: progress\ndata: {json.dumps({'status': 'error', 'message': f'Failed to update {store.name}: {error}'})}\n\n"

            elif result["type"] == "shopify":
                store = result["store"]
                update = result["update"]
                store_success = result["success"]
                total_updated = result["total_updated"]
                errors = result["errors"]

                results.append({
                    "store_id": store.id,
                    "store_name": store.name,
                    "success": store_success,
                    "rows_affected": total_updated,
                    "error": "; ".join(errors) if errors else None,
                })

                for vu in update.variant_updates:
                    history_entry = PriceUpdateHistory(
                        batch_id=batch_id,
                        store_id=store.id,
                        store_name=store.name,
                        store_type=update.store_type,
                        upc=upc,
                        product_description=vu.get("product_title"),
                        variant_id=str(vu.get("variant_id", "")),
                        variant_title=vu.get("variant_title"),
                        variant_barcode=vu.get("barcode"),
                        old_price=vu.get("old_price"),
                        old_cost=vu.get("old_cost"),
                        new_price=vu.get("new_price"),
                        new_cost=vu.get("new_cost"),
                        success=store_success,
                        rows_affected=1 if store_success else 0,
                        error_message="; ".join(errors) if errors else None
                    )
                    db.add(history_entry)
                db.commit()

                if store_success:
                    yield f"event: progress\ndata: {json.dumps({'status': 'updated', 'message': f'Updated {store.name} ({total_updated} variant(s))'})}\n\n"
                else:
                    error_detail = '; '.join(errors)
                    yield f"event: progress\ndata: {json.dumps({'status': 'error', 'message': f'Failed to update {store.name}: {error_detail}'})}\n\n"

        # Mirror propagation phase
        successful_store_ids = {r["store_id"] for r in results if r.get("success")}
        if successful_store_ids:
            mirrors = db.query(StoreMirror).filter(
                StoreMirror.source_store_id.in_(successful_store_ids)
            ).all()

            active_mirrors = []
            for m in mirrors:
                mirror_store = db.query(Store).filter(Store.id == m.mirror_store_id, Store.is_active == True).first()
                if mirror_store:
                    source_store = db.query(Store).filter(Store.id == m.source_store_id).first()
                    active_mirrors.append((m, source_store, mirror_store))

            if active_mirrors:
                yield f"event: progress\ndata: {json.dumps({'status': 'mirroring', 'message': f'Propagating to {len(active_mirrors)} mirror store(s)...'})}\n\n"

            for mirror_link, source_store, mirror_store in active_mirrors:
                source_update = next((u for u, s in valid_updates if s.id == source_store.id), None)
                if not source_update:
                    continue

                source_result = next((r for r in results if r["store_id"] == source_store.id), None)
                if not source_result or not source_result.get("success"):
                    continue

                mirror_new_price = source_update.new_price
                mirror_new_cost = source_update.new_cost
                if source_update.store_type == "shopify" and source_update.variant_updates:
                    first_vu = source_update.variant_updates[0]
                    mirror_new_price = first_vu.get("new_price")
                    mirror_new_cost = first_vu.get("new_cost")

                if mirror_new_price is None and mirror_new_cost is None:
                    continue

                yield f"event: progress\ndata: {json.dumps({'status': 'mirroring', 'message': f'Mirroring to {mirror_store.name} (from {source_store.name})...'})}\n\n"

                try:
                    if mirror_store.store_type.value == "mssql" if hasattr(mirror_store.store_type, 'value') else mirror_store.store_type == "mssql":
                        conn = mirror_store.mssql_connection
                        if not conn:
                            raise Exception("No MSSQL connection configured")
                        m_success, m_error, m_rows, m_server_time = await update_item_prices_async(
                            host=conn.host,
                            port=conn.port,
                            database=conn.database_name,
                            username=conn.username,
                            password=conn.password,
                            upc=upc,
                            unit_price=mirror_new_price,
                            unit_cost=mirror_new_cost,
                        )

                        history_entry = PriceUpdateHistory(
                            batch_id=batch_id,
                            store_id=mirror_store.id,
                            store_name=mirror_store.name,
                            store_type="mssql",
                            upc=upc,
                            product_description=source_update.product_description if hasattr(source_update, 'product_description') else None,
                            variant_barcode=upc,
                            new_price=mirror_new_price,
                            new_cost=mirror_new_cost,
                            success=m_success,
                            rows_affected=m_rows or 0,
                            error_message=m_error,
                            is_mirror=True,
                            mirror_source_store_id=source_store.id,
                            created_at=m_server_time,
                        )
                        db.add(history_entry)
                        db.commit()

                        mirror_result = {
                            "store_id": mirror_store.id,
                            "store_name": mirror_store.name,
                            "success": m_success,
                            "rows_affected": m_rows or 0,
                            "error": m_error,
                            "is_mirror": True,
                            "mirror_source_store_id": source_store.id,
                            "mirror_source_store_name": source_store.name,
                        }
                        results.append(mirror_result)

                        if m_success:
                            yield f"event: progress\ndata: {json.dumps({'status': 'updated', 'message': f'Mirrored to {mirror_store.name} ({m_rows} row(s))'})}\n\n"
                        else:
                            yield f"event: progress\ndata: {json.dumps({'status': 'error', 'message': f'Failed to mirror to {mirror_store.name}: {m_error}'})}\n\n"

                    else:
                        conn = mirror_store.shopify_connection
                        if not conn:
                            raise Exception("No Shopify connection configured")
                        search_ok, search_err, found_variants = await search_product_prices_by_barcode(
                            shop_domain=conn.shop_domain,
                            admin_api_key=conn.admin_api_key,
                            barcode=upc,
                            api_version=conn.api_version,
                        )

                        if not search_ok or not found_variants:
                            err_msg = search_err or "Product not found in mirror store"
                            history_entry = PriceUpdateHistory(
                                batch_id=batch_id,
                                store_id=mirror_store.id,
                                store_name=mirror_store.name,
                                store_type="shopify",
                                upc=upc,
                                success=False,
                                rows_affected=0,
                                error_message=err_msg,
                                is_mirror=True,
                                mirror_source_store_id=source_store.id,
                            )
                            db.add(history_entry)
                            db.commit()
                            results.append({
                                "store_id": mirror_store.id,
                                "store_name": mirror_store.name,
                                "success": False,
                                "error": err_msg,
                                "is_mirror": True,
                                "mirror_source_store_id": source_store.id,
                                "mirror_source_store_name": source_store.name,
                            })
                            yield f"event: progress\ndata: {json.dumps({'status': 'error', 'message': f'Failed to mirror to {mirror_store.name}: {err_msg}'})}\n\n"
                            continue

                        products = {}
                        for v in found_variants:
                            pid = v["product_id"]
                            if pid not in products:
                                products[pid] = []
                            vu = {"variant_id": v["variant_id"]}
                            if mirror_new_price is not None:
                                vu["new_price"] = mirror_new_price
                            if mirror_new_cost is not None:
                                vu["new_cost"] = mirror_new_cost
                            products[pid].append(vu)

                        total_mirror_updated = 0
                        mirror_errors = []
                        for pid, vus in products.items():
                            s_ok, s_err, s_count = await update_variant_prices(
                                shop_domain=conn.shop_domain,
                                admin_api_key=conn.admin_api_key,
                                product_id=pid,
                                variant_updates=vus,
                                api_version=conn.api_version,
                            )
                            if s_ok:
                                total_mirror_updated += s_count
                            else:
                                mirror_errors.append(s_err)

                        shopify_mirror_success = len(mirror_errors) == 0

                        for v in found_variants:
                            history_entry = PriceUpdateHistory(
                                batch_id=batch_id,
                                store_id=mirror_store.id,
                                store_name=mirror_store.name,
                                store_type="shopify",
                                upc=upc,
                                product_description=v.get("product_title"),
                                variant_id=str(v.get("variant_id", "")),
                                variant_title=v.get("variant_title"),
                                variant_barcode=v.get("barcode"),
                                new_price=mirror_new_price,
                                new_cost=mirror_new_cost,
                                success=shopify_mirror_success,
                                rows_affected=1 if shopify_mirror_success else 0,
                                error_message="; ".join(mirror_errors) if mirror_errors else None,
                                is_mirror=True,
                                mirror_source_store_id=source_store.id,
                            )
                            db.add(history_entry)
                        db.commit()

                        results.append({
                            "store_id": mirror_store.id,
                            "store_name": mirror_store.name,
                            "success": shopify_mirror_success,
                            "rows_affected": total_mirror_updated,
                            "error": "; ".join(mirror_errors) if mirror_errors else None,
                            "is_mirror": True,
                            "mirror_source_store_id": source_store.id,
                            "mirror_source_store_name": source_store.name,
                        })

                        if shopify_mirror_success:
                            yield f"event: progress\ndata: {json.dumps({'status': 'updated', 'message': f'Mirrored to {mirror_store.name} ({total_mirror_updated} variant(s))'})}\n\n"
                        else:
                            shopify_mirror_err = "; ".join(mirror_errors)
                            yield f"event: progress\ndata: {json.dumps({'status': 'error', 'message': f'Failed to mirror to {mirror_store.name}: {shopify_mirror_err}'})}\n\n"

                except Exception as e:
                    err_msg = str(e)
                    history_entry = PriceUpdateHistory(
                        batch_id=batch_id,
                        store_id=mirror_store.id,
                        store_name=mirror_store.name,
                        store_type=mirror_store.store_type.value if hasattr(mirror_store.store_type, 'value') else mirror_store.store_type,
                        upc=upc,
                        success=False,
                        rows_affected=0,
                        error_message=err_msg,
                        is_mirror=True,
                        mirror_source_store_id=source_store.id,
                    )
                    db.add(history_entry)
                    db.commit()
                    results.append({
                        "store_id": mirror_store.id,
                        "store_name": mirror_store.name,
                        "success": False,
                        "error": err_msg,
                        "is_mirror": True,
                        "mirror_source_store_id": source_store.id,
                        "mirror_source_store_name": source_store.name,
                    })
                    yield f"event: progress\ndata: {json.dumps({'status': 'error', 'message': f'Failed to mirror to {mirror_store.name}: {err_msg}'})}\n\n"

        yield f"event: complete\ndata: {json.dumps({'results': results, 'batch_id': batch_id})}\n\n"

    async def generate_events_safe() -> AsyncGenerator[str, None]:
        try:
            async for event in generate_events():
                yield event
        except GeneratorExit:
            print("[PRICE-UPDATE] Client disconnected")
            return

    return StreamingResponse(
        generate_events_safe(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
    )


@app.get("/api/price-updates/history", response_model=PriceUpdateHistoryListResponse)
def get_price_update_history(
    store_ids: Optional[str] = None,
    upc_search: Optional[str] = None,
    description_search: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 25,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    from sqlalchemy import func

    base_filters = []
    if store_ids:
        id_list = [int(s.strip()) for s in store_ids.split(",") if s.strip()]
        if id_list:
            base_filters.append(PriceUpdateHistory.store_id.in_(id_list))
    if upc_search:
        base_filters.append(PriceUpdateHistory.upc.like(f"%{upc_search}%"))
    if description_search:
        base_filters.append(PriceUpdateHistory.product_description.ilike(f"%{description_search}%"))
    if start_date:
        base_filters.append(PriceUpdateHistory.created_at >= start_date)
    if end_date:
        base_filters.append(PriceUpdateHistory.created_at <= end_date)

    batch_query = db.query(
        PriceUpdateHistory.batch_id,
        func.min(PriceUpdateHistory.created_at).label('created_at')
    ).filter(*base_filters).group_by(PriceUpdateHistory.batch_id)

    total = batch_query.count()
    batch_ids = batch_query.order_by(
        func.min(PriceUpdateHistory.created_at).desc()
    ).offset(offset).limit(limit).all()

    batch_id_list = [b.batch_id for b in batch_ids]

    mirror_source_name_cache = {}

    batches = []
    for bid in batch_id_list:
        entries = db.query(PriceUpdateHistory).filter(
            PriceUpdateHistory.batch_id == bid
        ).order_by(PriceUpdateHistory.id.asc()).all()

        if entries:
            first = entries[0]
            successful = sum(1 for e in entries if e.success)
            failed = len(entries) - successful

            entry_responses = []
            for entry in entries:
                mirror_source_name = None
                if entry.is_mirror and entry.mirror_source_store_id:
                    if entry.mirror_source_store_id not in mirror_source_name_cache:
                        src = db.query(Store).filter(Store.id == entry.mirror_source_store_id).first()
                        mirror_source_name_cache[entry.mirror_source_store_id] = src.name if src else "Deleted Store"
                    mirror_source_name = mirror_source_name_cache[entry.mirror_source_store_id]

                entry_responses.append(PriceUpdateHistoryResponse(
                    id=entry.id,
                    batch_id=entry.batch_id,
                    store_id=entry.store_id,
                    store_name=entry.store_name,
                    store_type=entry.store_type.value if hasattr(entry.store_type, 'value') else entry.store_type,
                    upc=entry.upc,
                    product_description=entry.product_description,
                    variant_id=entry.variant_id,
                    variant_title=entry.variant_title,
                    variant_barcode=entry.variant_barcode,
                    old_price=float(entry.old_price) if entry.old_price is not None else None,
                    old_cost=float(entry.old_cost) if entry.old_cost is not None else None,
                    new_price=float(entry.new_price) if entry.new_price is not None else None,
                    new_cost=float(entry.new_cost) if entry.new_cost is not None else None,
                    old_delivery_b=float(entry.old_delivery_b) if entry.old_delivery_b is not None else None,
                    new_delivery_b=float(entry.new_delivery_b) if entry.new_delivery_b is not None else None,
                    old_list_price=float(entry.old_list_price) if entry.old_list_price is not None else None,
                    new_list_price=float(entry.new_list_price) if entry.new_list_price is not None else None,
                    success=entry.success,
                    rows_affected=entry.rows_affected or 0,
                    error_message=entry.error_message,
                    is_mirror=entry.is_mirror or False,
                    mirror_source_store_id=entry.mirror_source_store_id,
                    mirror_source_store_name=mirror_source_name,
                    created_at=entry.created_at,
                ))

            batches.append(PriceUpdateHistoryBatch(
                batch_id=bid,
                upc=first.upc,
                product_description=first.product_description,
                created_at=first.created_at,
                total_stores=len(entries),
                successful_stores=successful,
                failed_stores=failed,
                entries=entry_responses
            ))

    return PriceUpdateHistoryListResponse(
        batches=batches,
        total=total,
        limit=limit,
        offset=offset
    )


@app.post("/api/price-updates/description/autocomplete", response_model=DescriptionAutocompleteResponse)
async def price_updates_autocomplete(request: DescriptionAutocompleteRequest, store_id: int, db: Session = Depends(get_db)):
    query = request.query.strip()

    if not query or len(query) < 2:
        return DescriptionAutocompleteResponse(results=[], count=0)

    store = db.query(Store).filter(
        Store.id == store_id,
        Store.store_type == StoreType.mssql
    ).first()

    if not store or not store.mssql_connection:
        raise HTTPException(status_code=400, detail="MSSQL store not found or missing connection details")

    conn = store.mssql_connection

    success, error, products = await search_products_by_description_async(
        host=conn.host,
        port=conn.port,
        database=conn.database_name,
        username=conn.username,
        password=conn.password,
        query=query,
        limit=50
    )

    if not success:
        raise HTTPException(status_code=500, detail=f"Database error: {error}")

    results = [
        DescriptionAutocompleteResult(
            product_id=p["product_id"],
            product_upc=p["product_upc"],
            product_description=p["product_description"],
            quant_on_hand=p["quant_on_hand"]
        )
        for p in products
    ]

    return DescriptionAutocompleteResponse(results=results, count=len(results))


@app.get("/api/shopify/fulfillment-status", response_model=FulfillmentStatusResponse)
async def shopify_fulfillment_status(exclude_ids: str = "", db: Session = Depends(get_db)):
    """
    Count open orders across active Shopify stores, broken into buckets per store
    (open, on hold, in process, on picklist, to fulfill) plus grand totals. Uses
    the lightweight Shopify ordersCount query fanned out per store.

    exclude_ids is an optional comma-separated list of store ids to skip entirely
    (no Shopify API calls are made for them).
    """
    excluded = {
        int(part) for part in exclude_ids.split(",")
        if part.strip().isdigit()
    }

    stores = db.query(Store).filter(
        Store.store_type == StoreType.shopify,
        Store.is_active == True
    ).all()

    store_dicts = []
    for store in stores:
        if store.id in excluded:
            continue
        if store.shopify_connection:
            store_dicts.append({
                "id": store.id,
                "name": store.name,
                "shop_domain": store.shopify_connection.shop_domain,
                "admin_api_key": store.shopify_connection.admin_api_key,
                "api_version": store.shopify_connection.api_version,
            })

    rows = await asyncio.gather(*[
        count_fulfillment_buckets_for_store(s) for s in store_dicts
    ]) if store_dicts else []

    rows = sorted(rows, key=lambda r: r["store_name"].lower())

    totals = {"open_orders": 0, "on_hold": 0, "in_process": 0, "on_picklist": 0, "to_fulfill": 0}
    for row in rows:
        if row["error"] is None:
            totals["open_orders"] += row["open_orders"]
            totals["on_hold"] += row["on_hold"]
            totals["in_process"] += row["in_process"]
            totals["on_picklist"] += row["on_picklist"]
            totals["to_fulfill"] += row["to_fulfill"]

    return {"stores": rows, "totals": totals}


@app.post("/api/shopify-sales/stream")
async def shopify_sales_stream(request: ShopifySalesRequest, db: Session = Depends(get_db)):
    async def generate_sales_events() -> AsyncGenerator[str, None]:
        store_ids = request.store_ids
        start_date = request.start_date
        end_date = request.end_date

        if not store_ids:
            yield f"event: error\ndata: {json.dumps({'message': 'No stores selected'})}\n\n"
            return

        stores = db.query(Store).filter(
            Store.id.in_(store_ids),
            Store.store_type == StoreType.shopify,
            Store.is_active == True
        ).all()

        if not stores:
            yield f"event: error\ndata: {json.dumps({'message': 'No active Shopify stores found for selected IDs'})}\n\n"
            return

        store_map = {}
        for store in stores:
            if store.shopify_connection:
                store_map[store.id] = {
                    "id": store.id,
                    "name": store.name,
                    "shop_domain": store.shopify_connection.shop_domain,
                    "admin_api_key": store.shopify_connection.admin_api_key,
                    "api_version": store.shopify_connection.api_version
                }

        all_line_items = []
        total_stores = len(store_map)

        yield f"event: progress\ndata: {json.dumps({'status': 'started', 'total_stores': total_stores})}\n\n"

        for s in store_map.values():
            yield f"event: progress\ndata: {json.dumps({'status': 'searching_store', 'store_name': s['name']})}\n\n"

        async def fetch_store_orders(store_info):
            return store_info, await fetch_fulfilled_orders(
                shop_domain=store_info["shop_domain"],
                admin_api_key=store_info["admin_api_key"],
                start_date=start_date,
                end_date=end_date,
                api_version=store_info["api_version"]
            )

        tasks = [asyncio.create_task(fetch_store_orders(s)) for s in store_map.values()]
        completed_count = 0

        for completed_task in asyncio.as_completed(tasks):
            store_info, (success, error, line_items) = await completed_task
            completed_count += 1

            if success:
                for item in line_items:
                    item["store_name"] = store_info["name"]
                    item["store_id"] = store_info["id"]
                all_line_items.extend(line_items)

                yield f"event: progress\ndata: {json.dumps({'status': 'completed_store', 'store_name': store_info['name'], 'orders_found': len(set(i['order_name'] for i in line_items)), 'line_items': len(line_items), 'completed': completed_count, 'total_stores': total_stores})}\n\n"
            else:
                yield f"event: progress\ndata: {json.dumps({'status': 'error_store', 'store_name': store_info['name'], 'message': error or 'Unknown error', 'completed': completed_count, 'total_stores': total_stores})}\n\n"

        yield f"event: progress\ndata: {json.dumps({'status': 'aggregating'})}\n\n"

        # Read SKU exclusion prefixes from settings
        sku_exclude_setting = db.query(Setting).filter(Setting.key == "shopify_sales_sku_exclude_prefixes").first()
        sku_exclude_prefixes = []
        if sku_exclude_setting and sku_exclude_setting.value:
            sku_exclude_prefixes = [p.strip().upper() for p in sku_exclude_setting.value.split(",") if p.strip()]

        if sku_exclude_prefixes:
            included_items = []
            excluded_items = []
            for item in all_line_items:
                if any((item.get("sku") or "").upper().startswith(p) for p in sku_exclude_prefixes):
                    excluded_items.append(item)
                else:
                    included_items.append(item)
        else:
            included_items = all_line_items
            excluded_items = []

        seen_orders = set()
        total_shipping = 0.0
        for item in all_line_items:
            key = (item.get("store_id"), item.get("order_name"))
            if key not in seen_orders:
                seen_orders.add(key)
                total_shipping += float(item.get("shipping_amount", 0))

        excluded_by_product = {}
        for item in excluded_items:
            title = item.get("product_title", "Unknown")
            qty = item.get("quantity", 0)
            revenue = float(item.get("unit_price", 0)) * qty
            if title not in excluded_by_product:
                excluded_by_product[title] = {"product_title": title, "quantity": 0, "revenue": 0.0}
            excluded_by_product[title]["quantity"] += qty
            excluded_by_product[title]["revenue"] += revenue
        excluded_products = sorted(excluded_by_product.values(), key=lambda x: x["revenue"], reverse=True)
        excluded_total_revenue = sum(p["revenue"] for p in excluded_products)
        excluded_total_quantity = sum(p["quantity"] for p in excluded_products)
        for p in excluded_products:
            p["revenue"] = f"{p['revenue']:.2f}"

        all_line_items = included_items

        aggregated = {}
        for item in all_line_items:
            barcode = item.get("barcode", "")
            product_title = item.get("product_title", "")
            variant_title = item.get("variant_title", "")
            store_name = item.get("store_name", "")
            currency = item.get("currency", "USD")

            if barcode:
                key = (item["store_id"], barcode, variant_title, currency)
            else:
                key = (item["store_id"], product_title, variant_title, currency)

            qty = item.get("quantity", 0)
            price = float(item.get("unit_price", 0))

            if key not in aggregated:
                aggregated[key] = {
                    "store_name": store_name,
                    "product_title": product_title,
                    "variant_title": variant_title,
                    "barcode": barcode,
                    "sku": item.get("sku", ""),
                    "total_quantity": 0,
                    "total_revenue": 0.0,
                    "currency": currency
                }

            aggregated[key]["total_quantity"] += qty
            aggregated[key]["total_revenue"] += price * qty
            if not aggregated[key]["sku"] and item.get("sku"):
                aggregated[key]["sku"] = item["sku"]
            if not aggregated[key]["product_title"] and product_title:
                aggregated[key]["product_title"] = product_title

        results = []
        for entry in aggregated.values():
            qty = entry["total_quantity"]
            revenue = entry["total_revenue"]
            avg_price = f"{(revenue / qty):.2f}" if qty > 0 else "0.00"
            variant_display = "" if entry["variant_title"] == "Default Title" else entry["variant_title"]
            results.append({
                "store_name": entry["store_name"],
                "product_title": entry["product_title"],
                "variant_title": variant_display,
                "barcode": entry["barcode"],
                "sku": entry["sku"],
                "avg_price": avg_price,
                "total_quantity": qty,
                "total_revenue": f"{revenue:.2f}",
                "currency": entry["currency"]
            })

        results.sort(key=lambda r: float(r["total_revenue"]), reverse=True)

        s2s_setting = db.query(Setting).filter(Setting.key == "shopify_sales_s2s_store_id").first()
        if s2s_setting and s2s_setting.value:
            try:
                s2s_store_id = int(s2s_setting.value)
                s2s_store = db.query(Store).filter(
                    Store.id == s2s_store_id,
                    Store.store_type == StoreType.mssql,
                    Store.is_active == True
                ).first()
                if s2s_store and s2s_store.mssql_connection:
                    conn = s2s_store.mssql_connection
                    barcodes = list({r["barcode"].strip() for r in results if r.get("barcode", "").strip()})
                    if barcodes:
                        success, error, prices_map = await get_item_prices_batch_async(
                            conn.host, conn.port, conn.database_name,
                            conn.username, conn.password, barcodes,
                            include_discontinued=True
                        )
                        if success:
                            for r in results:
                                bc = r.get("barcode", "").strip()
                                if bc and bc in prices_map:
                                    cost_val = prices_map[bc].get("unit_delivery_b")
                                    r["cost"] = f"{cost_val:.2f}" if cost_val is not None else None
                                else:
                                    r["cost"] = None
                        else:
                            for r in results:
                                r["cost"] = None
                    else:
                        for r in results:
                            r["cost"] = None
                else:
                    for r in results:
                        r["cost"] = None
            except Exception:
                for r in results:
                    r["cost"] = None
        else:
            for r in results:
                r["cost"] = None

        total_quantity = sum(r["total_quantity"] for r in results)
        total_revenue = sum(float(r["total_revenue"]) for r in results)

        yield f"event: complete\ndata: {json.dumps({'results': results, 'summary': {'total_items': len(results), 'total_quantity': total_quantity, 'total_revenue': f'{total_revenue:.2f}', 'total_shipping': f'{total_shipping:.2f}', 'stores_searched': len(store_map), 'date_range': {'start': start_date, 'end': end_date}, 'excluded_products': excluded_products, 'excluded_total_revenue': f'{excluded_total_revenue:.2f}', 'excluded_total_quantity': excluded_total_quantity}})}\n\n"

    async def generate_sales_events_safe() -> AsyncGenerator[str, None]:
        try:
            async for event in generate_sales_events():
                yield event
        except GeneratorExit:
            print("[SHOPIFY-SALES] Client disconnected")
            return

    return StreamingResponse(
        generate_sales_events_safe(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.get("/api/sales/config", response_model=SalesConfigResponse)
def get_sales_config(db: Session = Depends(get_db)):
    config = db.query(SalesConfig).first()
    if not config:
        return SalesConfigResponse(
            id=0, s2s_store_id=None, s2s_store_name=None,
            mssql_store_ids=[], mssql_store_names=[],
            shopify_store_ids=[], shopify_store_names=[],
            created_at=datetime.now(), updated_at=datetime.now()
        )

    s2s_store_name = None
    if config.s2s_store_id:
        s2s_store = db.query(Store).filter(Store.id == config.s2s_store_id).first()
        if s2s_store:
            s2s_store_name = s2s_store.name

    mssql_store_names = []
    for sid in (config.mssql_store_ids or []):
        store = db.query(Store).filter(Store.id == sid).first()
        if store:
            mssql_store_names.append(store.name)

    shopify_store_names = []
    for sid in (config.shopify_store_ids or []):
        store = db.query(Store).filter(Store.id == sid).first()
        if store:
            shopify_store_names.append(store.name)

    return SalesConfigResponse(
        id=config.id,
        s2s_store_id=config.s2s_store_id, s2s_store_name=s2s_store_name,
        mssql_store_ids=config.mssql_store_ids or [], mssql_store_names=mssql_store_names,
        shopify_store_ids=config.shopify_store_ids or [], shopify_store_names=shopify_store_names,
        excluded_subcategories=config.excluded_subcategories or [],
        created_at=config.created_at, updated_at=config.updated_at
    )


@app.post("/api/sales/config", response_model=SalesConfigResponse)
def save_sales_config(config_data: SalesConfigCreate, db: Session = Depends(get_db)):
    if config_data.s2s_store_id:
        s2s = db.query(Store).filter(Store.id == config_data.s2s_store_id, Store.store_type == StoreType.mssql).first()
        if not s2s:
            raise HTTPException(status_code=400, detail="Invalid S2S store ID")

    for sid in config_data.mssql_store_ids:
        if not db.query(Store).filter(Store.id == sid, Store.store_type == StoreType.mssql).first():
            raise HTTPException(status_code=400, detail=f"Invalid MSSQL store ID: {sid}")

    for sid in config_data.shopify_store_ids:
        if not db.query(Store).filter(Store.id == sid, Store.store_type == StoreType.shopify).first():
            raise HTTPException(status_code=400, detail=f"Invalid Shopify store ID: {sid}")

    config = db.query(SalesConfig).first()
    if config:
        config.s2s_store_id = config_data.s2s_store_id
        config.mssql_store_ids = config_data.mssql_store_ids
        config.shopify_store_ids = config_data.shopify_store_ids
    else:
        config = SalesConfig(
            s2s_store_id=config_data.s2s_store_id,
            mssql_store_ids=config_data.mssql_store_ids,
            shopify_store_ids=config_data.shopify_store_ids,
        )
        db.add(config)

    db.commit()
    db.refresh(config)
    return get_sales_config(db)


@app.put("/api/sales/config/excluded-subcategories")
def update_excluded_subcategories(data: dict, db: Session = Depends(get_db)):
    config = db.query(SalesConfig).first()
    if not config:
        raise HTTPException(status_code=400, detail="Sales config not found")
    config.excluded_subcategories = data.get("excluded_subcategories", [])
    db.commit()
    return {"excluded_subcategories": config.excluded_subcategories}


@app.get("/api/sales/business-names")
async def search_sales_business_names(query: str = "", db: Session = Depends(get_db)):
    config = db.query(SalesConfig).first()
    if not config or not config.s2s_store_id:
        return {"results": []}

    all_names = set()
    store_ids = (config.mssql_store_ids or [])
    if not store_ids:
        return {"results": []}

    for store_id in store_ids:
        store = db.query(Store).filter(
            Store.id == store_id, Store.store_type == StoreType.mssql, Store.is_active == True
        ).first()
        if not store or not store.mssql_connection:
            continue
        conn = store.mssql_connection
        success, error, names = await search_business_names_async(
            conn.host, conn.port, conn.database_name,
            conn.username, conn.password, query
        )
        if success:
            all_names.update(names)

    return {"results": sorted(all_names)[:20]}


@app.post("/api/sales/exclusions", response_model=SalesExclusionResponse)
def add_sales_exclusion(exclusion: SalesExclusionCreate, db: Session = Depends(get_db)):
    existing = db.query(SalesExclusion).filter(
        SalesExclusion.business_name == exclusion.business_name,
        SalesExclusion.void_status == exclusion.void_status if exclusion.void_status is not None
        else SalesExclusion.void_status.is_(None)
    ).first()
    if existing:
        scope = "all events" if exclusion.void_status is None else ("non-voided" if exclusion.void_status == 0 else "voided")
        raise HTTPException(status_code=409, detail=f"Already excluded: {exclusion.business_name} ({scope})")

    db_excl = SalesExclusion(
        business_name=exclusion.business_name,
        void_status=exclusion.void_status,
        notes=exclusion.notes,
    )
    db.add(db_excl)
    db.commit()
    db.refresh(db_excl)
    return db_excl


@app.get("/api/sales/exclusions", response_model=SalesExclusionListResponse)
def list_sales_exclusions(db: Session = Depends(get_db)):
    exclusions = db.query(SalesExclusion).order_by(SalesExclusion.excluded_at.desc()).all()
    return SalesExclusionListResponse(exclusions=exclusions, total=len(exclusions))


@app.delete("/api/sales/exclusions/{exclusion_id}")
def delete_sales_exclusion(exclusion_id: int, db: Session = Depends(get_db)):
    excl = db.query(SalesExclusion).filter(SalesExclusion.id == exclusion_id).first()
    if not excl:
        raise HTTPException(status_code=404, detail="Exclusion not found")
    db.delete(excl)
    db.commit()
    return {"message": "Exclusion removed"}


@app.post("/api/sales/report/stream")
async def sales_report_stream(request: SalesReportRequest, db: Session = Depends(get_db)):
    async def generate_report_events() -> AsyncGenerator[str, None]:
        if not request.mssql_store_ids and not request.shopify_store_ids:
            yield f"event: error\ndata: {json.dumps({'message': 'No stores selected'})}\n\n"
            return

        config = db.query(SalesConfig).first()
        if not config or not config.s2s_store_id:
            yield f"event: error\ndata: {json.dumps({'message': 'Sales config not set. Please configure the primary database first.'})}\n\n"
            return

        s2s_store = db.query(Store).filter(
            Store.id == config.s2s_store_id,
            Store.store_type == StoreType.mssql,
            Store.is_active == True
        ).first()
        if not s2s_store or not s2s_store.mssql_connection:
            yield f"event: error\ndata: {json.dumps({'message': 'S2S database store not found or inactive'})}\n\n"
            return

        s2s_conn = s2s_store.mssql_connection

        yield f"event: progress\ndata: {json.dumps({'status': 'fetching_products'})}\n\n"

        success, error, products_list = await get_active_products_async(
            s2s_conn.host, s2s_conn.port, s2s_conn.database_name,
            s2s_conn.username, s2s_conn.password
        )

        if not success:
            yield f"event: error\ndata: {json.dumps({'message': f'Failed to fetch products: {error}'})}\n\n"
            return

        products_map = {}
        subcategories = {}
        for p in products_list:
            products_map[p["upc"]] = {
                "upc": p["upc"],
                "description": p["description"],
                "quant_on_hand": p["quant_on_hand"],
                "subcategory": p.get("subcategory"),
                "reorder_level": p.get("reorder_level", 0),
                "bin_location": p.get("bin_location"),
                "total_sold": 0.0,
                "total_returned": 0.0,
                "net_sold": 0.0,
                "store_sales": {},
            }
            sc = p.get("subcategory")
            if sc and sc not in subcategories:
                subcategories[sc] = sc

        yield f"event: progress\ndata: {json.dumps({'status': 'products_fetched', 'count': len(products_map)})}\n\n"

        exclusions = db.query(SalesExclusion).all()
        excluded_sales_names = []
        excluded_return_names = []
        for excl in exclusions:
            if excl.void_status is None or excl.void_status == 0:
                excluded_sales_names.append(excl.business_name)
            if excl.void_status is None:
                excluded_return_names.append(excl.business_name)

        total_stores = len(request.mssql_store_ids) + len(request.shopify_store_ids)
        completed_count = 0
        store_names = []

        for store_id in request.mssql_store_ids:
            store = db.query(Store).filter(
                Store.id == store_id,
                Store.store_type == StoreType.mssql,
                Store.is_active == True
            ).first()
            if not store or not store.mssql_connection:
                completed_count += 1
                yield f"event: progress\ndata: {json.dumps({'status': 'error_store', 'store_name': f'Store ID {store_id}', 'message': 'Store not found or inactive', 'completed': completed_count, 'total_stores': total_stores})}\n\n"
                continue

            conn = store.mssql_connection
            store_name = store.name
            store_names.append({"id": store.id, "name": store_name, "type": "mssql"})

            yield f"event: progress\ndata: {json.dumps({'status': 'searching_store', 'store_name': store_name, 'store_type': 'mssql'})}\n\n"

            try:
                sales_task = get_aggregated_sales_async(
                    conn.host, conn.port, conn.database_name,
                    conn.username, conn.password,
                    request.date_from, request.date_to,
                    excluded_sales_names or None
                )
                returns_task = get_aggregated_returns_async(
                    conn.host, conn.port, conn.database_name,
                    conn.username, conn.password,
                    request.date_from, request.date_to,
                    excluded_return_names or None
                )

                (sales_ok, sales_err, sales_data), (returns_ok, returns_err, returns_data) = await asyncio.gather(
                    sales_task, returns_task
                )

                if not sales_ok:
                    completed_count += 1
                    yield f"event: progress\ndata: {json.dumps({'status': 'error_store', 'store_name': store_name, 'message': sales_err or 'Failed to fetch sales', 'completed': completed_count, 'total_stores': total_stores})}\n\n"
                    continue

                if not returns_ok:
                    returns_data = {}

                products_found = 0
                all_upcs = set(sales_data.keys()) | set(returns_data.keys())
                for upc in all_upcs:
                    sold = sales_data.get(upc, 0.0)
                    returned = returns_data.get(upc, 0.0)
                    net = sold - returned

                    if upc in products_map:
                        products_map[upc]["total_sold"] += sold
                        products_map[upc]["total_returned"] += returned
                        products_map[upc]["net_sold"] += net
                        products_map[upc]["store_sales"][store_name] = {
                            "sold": sold, "returned": returned, "net": net
                        }
                        products_found += 1

                completed_count += 1
                yield f"event: progress\ndata: {json.dumps({'status': 'completed_store', 'store_name': store_name, 'products_found': products_found, 'completed': completed_count, 'total_stores': total_stores})}\n\n"

            except Exception as e:
                completed_count += 1
                yield f"event: progress\ndata: {json.dumps({'status': 'error_store', 'store_name': store_name, 'message': str(e), 'completed': completed_count, 'total_stores': total_stores})}\n\n"

        for store_id in request.shopify_store_ids:
            store = db.query(Store).filter(
                Store.id == store_id,
                Store.store_type == StoreType.shopify,
                Store.is_active == True
            ).first()
            if not store or not store.shopify_connection:
                completed_count += 1
                yield f"event: progress\ndata: {json.dumps({'status': 'error_store', 'store_name': f'Store ID {store_id}', 'message': 'Store not found or inactive', 'completed': completed_count, 'total_stores': total_stores})}\n\n"
                continue

            shopify_conn = store.shopify_connection
            store_name = store.name
            store_names.append({"id": store.id, "name": store_name, "type": "shopify"})

            yield f"event: progress\ndata: {json.dumps({'status': 'searching_store', 'store_name': store_name, 'store_type': 'shopify'})}\n\n"

            try:
                start_date = request.date_from or "2000-01-01"
                end_date = request.date_to or datetime.now().strftime("%Y-%m-%d")

                success, error, line_items = await fetch_fulfilled_orders(
                    shop_domain=shopify_conn.shop_domain,
                    admin_api_key=shopify_conn.admin_api_key,
                    start_date=start_date,
                    end_date=end_date,
                    api_version=shopify_conn.api_version
                )

                if not success:
                    completed_count += 1
                    yield f"event: progress\ndata: {json.dumps({'status': 'error_store', 'store_name': store_name, 'message': error or 'Failed to fetch Shopify orders', 'completed': completed_count, 'total_stores': total_stores})}\n\n"
                    continue

                shopify_by_barcode = {}
                for item in line_items:
                    barcode = (item.get("barcode") or "").strip()
                    if barcode:
                        qty = item.get("quantity", 0)
                        shopify_by_barcode[barcode] = shopify_by_barcode.get(barcode, 0) + qty

                products_found = 0
                for upc, qty in shopify_by_barcode.items():
                    if upc in products_map:
                        products_map[upc]["total_sold"] += qty
                        products_map[upc]["net_sold"] += qty
                        products_map[upc]["store_sales"][store_name] = {
                            "sold": qty, "returned": 0, "net": qty
                        }
                        products_found += 1

                completed_count += 1
                yield f"event: progress\ndata: {json.dumps({'status': 'completed_store', 'store_name': store_name, 'products_found': products_found, 'completed': completed_count, 'total_stores': total_stores})}\n\n"

            except Exception as e:
                completed_count += 1
                yield f"event: progress\ndata: {json.dumps({'status': 'error_store', 'store_name': store_name, 'message': str(e), 'completed': completed_count, 'total_stores': total_stores})}\n\n"

        yield f"event: progress\ndata: {json.dumps({'status': 'merging'})}\n\n"

        products = list(products_map.values())
        products.sort(key=lambda p: p["net_sold"], reverse=True)

        sold_count = sum(1 for p in products if p["net_sold"] > 0)
        not_sold_count = sum(1 for p in products if p["net_sold"] <= 0)
        total_net_sold = sum(p["net_sold"] for p in products)
        total_sold = sum(p["total_sold"] for p in products)
        total_returned = sum(p["total_returned"] for p in products)

        summary = {
            "total_products": len(products),
            "sold_count": sold_count,
            "not_sold_count": not_sold_count,
            "total_sold": total_sold,
            "total_returned": total_returned,
            "total_net_sold": total_net_sold,
            "date_range": {"start": request.date_from, "end": request.date_to},
            "stores_searched": completed_count,
        }

        yield f"event: complete\ndata: {json.dumps({'products': products, 'summary': summary, 'stores': store_names, 'subcategories': sorted(subcategories.keys())})}\n\n"

    async def generate_report_events_safe() -> AsyncGenerator[str, None]:
        try:
            async for event in generate_report_events():
                yield event
        except GeneratorExit:
            print("[SALES-REPORT] Client disconnected")
            return

    return StreamingResponse(
        generate_report_events_safe(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


# Quotations In Progress endpoints (DB_ADMIN-backed)
ADMIN_STORE_SETTING_KEY = "admin_store_id"

# Markup applied to Items_tbl.UnitCost when computing the displayed Price
# in the In Progress section. cost * PRICE_MARKUP -> displayed price.
PRICE_MARKUP = 1.05


def _resolve_item_tracker_s2s_conn(db: Session):
    """
    Soft variant of get_item_tracker_stores(). Returns the s2s
    MSSQLConnection if Item Tracker is configured with an active MSSQL
    s2s store, otherwise returns None -- so missing config doesn't break
    the In Progress page; prices simply render blank.
    """
    config = db.query(ItemTrackerConfig).first()
    if not config or not config.s2s_store_id:
        return None
    store = db.query(Store).filter(
        Store.id == config.s2s_store_id,
        Store.store_type == StoreType.mssql,
        Store.is_active == True,
    ).first()
    if not store or not store.mssql_connection:
        return None
    return store.mssql_connection


async def _enrich_products_with_prices(products, s2s_conn):
    """
    Attach `unit_cost` and `price` to every product dict in `products`
    in place. `price` = `unit_cost * PRICE_MARKUP`, rounded to 2dp.

    No-op (sets both fields to None) when:
      - s2s_conn is None (Item Tracker not configured)
      - the products list has no usable UPCs
      - the batch lookup against Items_tbl fails for any reason
    """
    def _set_blank():
        for p in products or []:
            p["unit_cost"] = None
            p["price"] = None

    if not products:
        return
    if s2s_conn is None:
        _set_blank()
        return

    upcs = sorted(
        {
            (p.get("product_upc") or "").strip()
            for p in products
            if (p.get("product_upc") or "").strip()
        }
    )
    if not upcs:
        _set_blank()
        return

    success, _err, by_upc = await get_item_prices_batch_async(
        host=s2s_conn.host,
        port=s2s_conn.port,
        database=s2s_conn.database_name,
        username=s2s_conn.username,
        password=s2s_conn.password,
        upcs=upcs,
        include_discontinued=True,
    )
    if not success or not isinstance(by_upc, dict):
        _set_blank()
        return

    for p in products:
        upc = (p.get("product_upc") or "").strip()
        entry = by_upc.get(upc) if upc else None
        cost = entry.get("unit_cost") if entry else None
        if cost is None:
            p["unit_cost"] = None
            p["price"] = None
        else:
            p["unit_cost"] = float(cost)
            p["price"] = round(float(cost) * PRICE_MARKUP, 2)


def _resolve_admin_store(db: Session) -> Store:
    """
    Look up the configured DB_ADMIN store via the `admin_store_id` setting.
    Raises HTTPException if unset, missing, or not an active MSSQL store.
    """
    setting = db.query(Setting).filter(Setting.key == ADMIN_STORE_SETTING_KEY).first()
    if not setting or not setting.value:
        raise HTTPException(
            status_code=400,
            detail="Admin (DB_ADMIN) store is not configured. Set it under Settings."
        )

    try:
        store_id = int(setting.value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Admin store setting is invalid.")

    store = db.query(Store).filter(Store.id == store_id, Store.is_active == True).first()
    if not store or store.store_type != StoreType.mssql or not store.mssql_connection:
        raise HTTPException(
            status_code=400,
            detail="Configured admin store is missing, inactive, or not an MSSQL store."
        )
    return store


def _resolve_admin_store_soft(db: Session) -> Optional[Store]:
    """
    Soft variant of _resolve_admin_store -- returns None instead of
    raising when DB_ADMIN is unconfigured / invalid. Used by Item
    Tracker so the timeline still works for users who never configured
    the admin store; in_progress events are simply skipped.
    """
    setting = db.query(Setting).filter(Setting.key == ADMIN_STORE_SETTING_KEY).first()
    if not setting or not setting.value:
        return None
    try:
        store_id = int(setting.value)
    except (TypeError, ValueError):
        return None
    store = db.query(Store).filter(Store.id == store_id, Store.is_active == True).first()
    if not store or store.store_type != StoreType.mssql or not store.mssql_connection:
        return None
    return store


INVENTORY_TIMEOUT_SETTING_KEY = "inventory_recount_timeout_minutes"
INVENTORY_ISOLATED_SETTING_KEY = "isolated_product_recount_minutes"
DEFAULT_INVENTORY_TIMEOUT_MINUTES = 10.0
DEFAULT_INVENTORY_ISOLATED_MINUTES = 1.0

CHECKED_ORDERS_SLOW_SETTING_KEY = "checked_orders_slow_minutes"
DEFAULT_CHECKED_ORDERS_SLOW_MINUTES = 15.0

CHECKED_ORDERS_SECONDS_PER_PRODUCT_SETTING_KEY = "checked_orders_seconds_per_product"
DEFAULT_CHECKED_ORDERS_SECONDS_PER_PRODUCT = 10.0


def _get_float_setting(db: Session, key: str, default: float) -> float:
    """Read a numeric setting (stored as a string), falling back to `default`."""
    setting = db.query(Setting).filter(Setting.key == key).first()
    if not setting or setting.value is None:
        return default
    try:
        return float(setting.value)
    except (TypeError, ValueError):
        return default


@app.get("/api/inventory-time/users", response_model=InventoryTimeUsersResponse)
async def list_inventory_time_users(
    date_from: str,
    date_to: str,
    db: Session = Depends(get_db),
):
    """Usernames with ManualInventoryUpdate rows in [date_from, date_to] on the admin DB."""
    if date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from must be on or before date_to.")

    store = _resolve_admin_store_soft(db)
    if not store:
        return InventoryTimeUsersResponse(configured=False, users=[])

    conn = store.mssql_connection
    success, error, users = await fetch_distinct_usernames_async(
        host=conn.host,
        port=conn.port,
        database=conn.database_name,
        username=conn.username,
        password=conn.password,
        date_from=date_from,
        date_to=date_to,
    )
    if not success:
        raise HTTPException(status_code=502, detail=f"MSSQL query failed: {error}")
    return InventoryTimeUsersResponse(configured=True, users=users)


@app.post("/api/inventory-time", response_model=InventoryTimeResponse)
async def calculate_inventory_time(
    req: InventoryTimeRequest,
    db: Session = Depends(get_db),
):
    """Reconstruct a user's recount working time from ManualInventoryUpdate timestamps."""
    if not req.username or not req.username.strip():
        raise HTTPException(status_code=400, detail="A username is required.")
    if req.date_from > req.date_to:
        raise HTTPException(status_code=400, detail="date_from must be on or before date_to.")

    store = _resolve_admin_store_soft(db)
    if not store:
        return InventoryTimeResponse(configured=False)

    timeout_minutes = _get_float_setting(
        db, INVENTORY_TIMEOUT_SETTING_KEY, DEFAULT_INVENTORY_TIMEOUT_MINUTES
    )
    isolated_minutes = _get_float_setting(
        db, INVENTORY_ISOLATED_SETTING_KEY, DEFAULT_INVENTORY_ISOLATED_MINUTES
    )

    conn = store.mssql_connection
    success, error, timestamps = await fetch_recount_timestamps_async(
        host=conn.host,
        port=conn.port,
        database=conn.database_name,
        username=conn.username,
        password=conn.password,
        target_user=req.username.strip(),
        date_from=req.date_from,
        date_to=req.date_to,
    )
    if not success:
        raise HTTPException(status_code=502, detail=f"MSSQL query failed: {error}")

    result = compute_inventory_time(
        timestamps,
        timeout_s=timeout_minutes * 60.0,
        isolated_s=isolated_minutes * 60.0,
    )

    return InventoryTimeResponse(
        configured=True,
        total_seconds=result["total_seconds"],
        session_count=result["session_count"],
        item_count=result["item_count"],
        sessions=[InventoryTimeSession(**s) for s in result["sessions"]],
        timeout_minutes=timeout_minutes,
        isolated_minutes=isolated_minutes,
    )


# ---- Checked Orders (shipper DB) ----

def _resolve_shipper_store_soft(db: Session) -> Optional[Store]:
    """
    Return the single active shipper store (lowest id if several exist), or None
    when none is configured. Soft resolver so the Checked Orders page can show a
    'not configured' state instead of erroring.
    """
    store = (
        db.query(Store)
        .filter(Store.store_type == StoreType.shipper, Store.is_active == True)
        .order_by(Store.id)
        .first()
    )
    if not store or not store.mssql_connection:
        return None
    return store


@app.get("/api/checked-orders/users", response_model=CheckedOrdersUsersResponse)
async def list_checked_orders_users(
    date_from: str,
    date_to: str,
    db: Session = Depends(get_db),
):
    """Checkers (id + name) who completed order checks in [date_from, date_to] on the shipper DB."""
    if date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from must be on or before date_to.")

    store = _resolve_shipper_store_soft(db)
    if not store:
        return CheckedOrdersUsersResponse(configured=False, users=[])

    conn = store.mssql_connection
    success, error, users = await fetch_checkers_async(
        host=conn.host,
        port=conn.port,
        database=conn.database_name,
        username=conn.username,
        password=conn.password,
        date_from=date_from,
        date_to=date_to,
    )
    if not success:
        raise HTTPException(status_code=502, detail=f"MSSQL query failed: {error}")
    return CheckedOrdersUsersResponse(
        configured=True,
        users=[CheckedOrderUser(**u) for u in users],
    )


@app.post("/api/checked-orders", response_model=CheckedOrdersResponse)
async def calculate_checked_orders(
    req: CheckedOrdersRequest,
    db: Session = Depends(get_db),
):
    """Summarize a checker's completed order checks (count, total time, average) on the shipper DB."""
    if req.date_from > req.date_to:
        raise HTTPException(status_code=400, detail="date_from must be on or before date_to.")

    store = _resolve_shipper_store_soft(db)
    if not store:
        return CheckedOrdersResponse(configured=False)

    conn = store.mssql_connection
    success, error, rows = await fetch_checked_orders_async(
        host=conn.host,
        port=conn.port,
        database=conn.database_name,
        username=conn.username,
        password=conn.password,
        checker_id=req.checker_id,
        date_from=req.date_from,
        date_to=req.date_to,
    )
    if not success:
        raise HTTPException(status_code=502, detail=f"MSSQL query failed: {error}")

    slow_threshold_minutes = _get_float_setting(
        db, CHECKED_ORDERS_SLOW_SETTING_KEY, DEFAULT_CHECKED_ORDERS_SLOW_MINUTES
    )
    seconds_per_product = _get_float_setting(
        db,
        CHECKED_ORDERS_SECONDS_PER_PRODUCT_SETTING_KEY,
        DEFAULT_CHECKED_ORDERS_SECONDS_PER_PRODUCT,
    )

    result = compute_checked_orders(
        rows,
        slow_threshold_seconds=slow_threshold_minutes * 60.0,
        seconds_per_product=seconds_per_product,
    )

    return CheckedOrdersResponse(
        configured=True,
        order_count=result["order_count"],
        total_seconds=result["total_seconds"],
        average_seconds=result["average_seconds"],
        total_value=result["total_value"],
        slow_threshold_minutes=slow_threshold_minutes,
        seconds_per_product=seconds_per_product,
        orders=[CheckedOrder(**o) for o in result["orders"]],
    )


@app.post("/api/quotations/in-progress", response_model=QuotationsInProgressListResponse)
async def list_quotations_in_progress(
    filters: QuotationsInProgressFilter,
    db: Session = Depends(get_db)
):
    """List quotations from QuotationsInProgress + QuotationsStatus on the admin DB."""
    store = _resolve_admin_store(db)
    conn = store.mssql_connection

    success, error, rows = await list_quotations_in_progress_async(
        host=conn.host,
        port=conn.port,
        database=conn.database_name,
        username=conn.username,
        password=conn.password,
        scan_filter=filters.scan_filter,
        source_dbs=filters.source_dbs,
        packers=filters.packers,
        checkers=filters.checkers,
        search=filters.search,
        sort_by=filters.sort_by,
        sort_order=filters.sort_order,
        limit=filters.limit,
    )
    if not success:
        raise HTTPException(status_code=502, detail=f"MSSQL query failed: {error}")

    opt_success, opt_error, options = await list_distinct_filter_values_async(
        host=conn.host,
        port=conn.port,
        database=conn.database_name,
        username=conn.username,
        password=conn.password,
    )
    if not opt_success:
        # Non-fatal — return empty options
        options = {"source_dbs": [], "packers": [], "checkers": [], "statuses": []}

    return QuotationsInProgressListResponse(
        quotations=[QuotationInProgressSummary(**r) for r in rows],
        filter_options=QuotationsInProgressFilterOptions(**options),
        admin_store_id=store.id,
        admin_store_name=store.name,
    )


@app.get(
    "/api/quotations/in-progress/{quotation_number}/products",
    response_model=QuotationProductsResponse,
)
async def get_quotation_in_progress_products(
    quotation_number: str,
    db: Session = Depends(get_db),
):
    """Return all product line items + header for a single quotation in progress."""
    store = _resolve_admin_store(db)
    conn = store.mssql_connection

    success, error, payload = await get_quotation_products_async(
        host=conn.host,
        port=conn.port,
        database=conn.database_name,
        username=conn.username,
        password=conn.password,
        quotation_number=quotation_number,
    )
    if not success:
        raise HTTPException(status_code=502, detail=f"MSSQL query failed: {error}")

    # Enrich each product line with unit_cost / price from the Item
    # Tracker s2s store. Soft-fails to None when not configured.
    s2s_conn = _resolve_item_tracker_s2s_conn(db)
    await _enrich_products_with_prices(payload["products"], s2s_conn)

    return QuotationProductsResponse(
        products=[QuotationProductLine(**p) for p in payload["products"]],
        header=QuotationInProgressHeader(**payload["header"]) if payload["header"] else None,
    )


@app.post(
    "/api/quotations/in-progress/search-products",
    response_model=QuotationSearchResponse,
)
async def search_quotation_in_progress_products(
    filters: QuotationsInProgressFilter,
    db: Session = Depends(get_db),
):
    """
    Flat product-level search across in-progress quotations.

    Returns one row per matched product (UPC / SKU / description LIKE the
    search term), annotated with quotation context and scan timestamps.
    Honors the same scan / source-DB / packer / checker filters as the
    list endpoint so the summary stays consistent with the narrowed list.
    """
    if not filters.search or not filters.search.strip():
        raise HTTPException(
            status_code=400,
            detail="Search term is required for product search",
        )

    store = _resolve_admin_store(db)
    conn = store.mssql_connection

    success, error, payload = await search_products_async(
        host=conn.host,
        port=conn.port,
        database=conn.database_name,
        username=conn.username,
        password=conn.password,
        search=filters.search,
        scan_filter=filters.scan_filter,
        source_dbs=filters.source_dbs,
        packers=filters.packers,
        checkers=filters.checkers,
        limit=filters.limit,
    )
    if not success:
        raise HTTPException(status_code=502, detail=f"MSSQL query failed: {error}")

    # Enrich each matched product with unit_cost / price from the Item
    # Tracker s2s store. Soft-fails to None when not configured.
    s2s_conn = _resolve_item_tracker_s2s_conn(db)
    await _enrich_products_with_prices(payload["products"], s2s_conn)

    return QuotationSearchResponse(
        products=[QuotationSearchProduct(**p) for p in payload["products"]],
        quotation_count=payload["quotation_count"],
    )


# ───────────────────────── Dashboard ─────────────────────────


@app.get("/api/dashboard/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(db: Session = Depends(get_db)):
    """
    Aggregate operational stats for the home dashboard. All inputs are
    cheap (counts, soft resolvers, one optional DB_ADMIN ping). Safe to
    poll on a 60s auto-refresh.
    """
    from sqlalchemy import func, distinct

    # Stores: total, active, by_type, by_category
    stores = db.query(Store).all()
    by_type: Dict[str, int] = {}
    by_category: Dict[str, int] = {}
    active_count = 0
    for s in stores:
        st = s.store_type.value if hasattr(s.store_type, "value") else str(s.store_type)
        by_type[st] = by_type.get(st, 0) + 1
        cat = s.store_category.value if hasattr(s.store_category, "value") else str(s.store_category or "retail")
        by_category[cat] = by_category.get(cat, 0) + 1
        if s.is_active:
            active_count += 1

    store_stats = DashboardStoreStats(
        total=len(stores),
        active=active_count,
        by_type=by_type,
        by_category=by_category,
    )

    # Exclusion counts (3 tables) + mirror count
    exclusions = DashboardExclusionCounts(
        upc=db.query(UPCExclusion).count(),
        item_tracker=db.query(ItemTrackerExclusion).count(),
        sales=db.query(SalesExclusion).count(),
    )
    mirror_stats = DashboardMirrorStats(count=db.query(StoreMirror).count())

    # 7-day batch summaries (UPC + Price update history). A batch is
    # "successful" only if every row in it succeeded; "failed batch"
    # = at least one row with success=False.
    cutoff = datetime.utcnow() - timedelta(days=7)

    def _summarize(model) -> DashboardBatchSummary:
        total = (
            db.query(distinct(model.batch_id))
            .filter(model.created_at >= cutoff)
            .count()
        )
        if not total:
            return DashboardBatchSummary(batches=0, success_rate=None)
        failed = (
            db.query(distinct(model.batch_id))
            .filter(model.created_at >= cutoff, model.success == False)
            .count()
        )
        return DashboardBatchSummary(
            batches=total,
            success_rate=round((total - failed) / total, 4),
        )

    upc_summary = _summarize(UPCUpdateHistory)
    price_summary = _summarize(PriceUpdateHistory)

    # In-progress count via soft-resolved admin store
    admin_store = _resolve_admin_store_soft(db)
    if admin_store is None:
        in_progress = DashboardInProgressStats(configured=False)
    else:
        conn = admin_store.mssql_connection
        ok, err, payload = await count_in_progress_async(
            host=conn.host,
            port=conn.port,
            database=conn.database_name,
            username=conn.username,
            password=conn.password,
        )
        if ok:
            in_progress = DashboardInProgressStats(
                configured=True,
                total=payload.get("total", 0),
                oldest_started_at=payload.get("oldest_started_at"),
            )
        else:
            in_progress = DashboardInProgressStats(
                configured=True,
                total=0,
                oldest_started_at=None,
                error=err,
            )

    # Configuration health (3 role assignments)
    config_health: List[DashboardConfigCheck] = []

    # admin_store_id
    config_health.append(DashboardConfigCheck(
        key="admin_store_id",
        ok=admin_store is not None,
        store_name=admin_store.name if admin_store else None,
    ))

    # Item Tracker S2S
    it_conn = _resolve_item_tracker_s2s_conn(db)
    it_store_name: Optional[str] = None
    if it_conn is not None:
        it_store = db.query(Store).filter(Store.id == it_conn.store_id).first()
        it_store_name = it_store.name if it_store else None
    config_health.append(DashboardConfigCheck(
        key="item_tracker_s2s",
        ok=it_conn is not None,
        store_name=it_store_name,
    ))

    # Shopify Sales S2S (separate setting)
    shopify_s2s_setting = db.query(Setting).filter(
        Setting.key == "shopify_sales_s2s_store_id"
    ).first()
    shopify_s2s_store_name: Optional[str] = None
    shopify_s2s_ok = False
    if shopify_s2s_setting and shopify_s2s_setting.value:
        try:
            shopify_s2s_id = int(shopify_s2s_setting.value)
            shopify_s2s_store = db.query(Store).filter(
                Store.id == shopify_s2s_id, Store.is_active == True
            ).first()
            if shopify_s2s_store and shopify_s2s_store.store_type == StoreType.mssql:
                shopify_s2s_ok = True
                shopify_s2s_store_name = shopify_s2s_store.name
        except (TypeError, ValueError):
            pass
    config_health.append(DashboardConfigCheck(
        key="shopify_sales_s2s",
        ok=shopify_s2s_ok,
        store_name=shopify_s2s_store_name,
    ))

    return DashboardStatsResponse(
        stores=store_stats,
        exclusions=exclusions,
        mirrors=mirror_stats,
        upc_updates_7d=upc_summary,
        price_updates_7d=price_summary,
        in_progress=in_progress,
        config_health=config_health,
        generated_at=datetime.utcnow(),
    )


# ============================================================================
# Shopify Analytics
# ============================================================================

DEFAULT_FIRST_ORDER_TAG = "First order"


@app.put("/api/shopify-analytics/stores/{store_id}/tag")
async def shopify_analytics_set_first_order_tag(
    store_id: int,
    body: ShopifyFirstOrderTagUpdate,
    db: Session = Depends(get_db),
):
    store = db.query(Store).filter(
        Store.id == store_id,
        Store.store_type == StoreType.shopify,
    ).first()
    if not store or not store.shopify_connection:
        raise HTTPException(status_code=404, detail="Shopify store not found")

    new_tag = (body.first_order_tag or "").strip()
    if not new_tag:
        raise HTTPException(status_code=400, detail="first_order_tag must not be empty")
    if len(new_tag) > 100:
        raise HTTPException(status_code=400, detail="first_order_tag exceeds 100 characters")

    store.shopify_connection.first_order_tag = new_tag
    db.commit()
    return {"store_id": store_id, "first_order_tag": new_tag}


@app.post("/api/shopify-analytics/first-customer-returns/stream")
async def shopify_analytics_first_customer_returns_stream(
    request: FirstCustomerReturnsRequest,
    db: Session = Depends(get_db),
):
    async def generate() -> AsyncGenerator[str, None]:
        store_id = request.store_id
        start_date = request.start_date
        end_date = request.end_date

        store = db.query(Store).filter(
            Store.id == store_id,
            Store.store_type == StoreType.shopify,
            Store.is_active == True,
        ).first()

        if not store or not store.shopify_connection:
            yield f"event: error\ndata: {json.dumps({'message': 'Shopify store not found or inactive'})}\n\n"
            return

        conn = store.shopify_connection
        shop_domain = conn.shop_domain
        admin_api_key = conn.admin_api_key
        api_version = conn.api_version

        # Tag resolution: explicit request override > store's saved tag > default.
        request_tag = (request.tag or "").strip() if request.tag is not None else ""
        saved_tag = (conn.first_order_tag or "").strip()
        tag = request_tag or saved_tag or DEFAULT_FIRST_ORDER_TAG

        yield f"event: progress\ndata: {json.dumps({'phase': 'started', 'store_name': store.name, 'tag': tag, 'start_date': start_date, 'end_date': end_date})}\n\n"

        # Phase 1: fetch all tagged orders in the date range
        success, error, tagged_orders = await fetch_orders_with_tag(
            shop_domain=shop_domain,
            admin_api_key=admin_api_key,
            start_date=start_date,
            end_date=end_date,
            tag=tag,
            api_version=api_version,
        )

        if not success:
            yield f"event: error\ndata: {json.dumps({'message': error or 'Failed to fetch tagged orders'})}\n\n"
            return

        # Dedupe by customer_id; track unmatched (no customer) count separately
        first_orders_by_customer: Dict[str, Dict[str, Any]] = {}
        no_customer_count = 0
        for o in tagged_orders:
            cid = o.get("customer_id")
            if not cid:
                no_customer_count += 1
                continue
            # Keep the earliest first-order per customer (defensive — should be 1 anyway)
            existing = first_orders_by_customer.get(cid)
            o_date = o.get("processed_at") or o.get("created_at") or ""
            if existing is None:
                first_orders_by_customer[cid] = o
            else:
                e_date = existing.get("processed_at") or existing.get("created_at") or ""
                if o_date and (not e_date or o_date < e_date):
                    first_orders_by_customer[cid] = o

        total_customers = len(first_orders_by_customer)

        yield f"event: progress\ndata: {json.dumps({'phase': 'tagged_orders_complete', 'tagged_orders': len(tagged_orders), 'first_time_customers': total_customers, 'orders_without_customer': no_customer_count})}\n\n"

        if total_customers == 0:
            yield f"event: complete\ndata: {json.dumps({'summary': {'first_time_customers': 0, 'customers_with_returns': 0, 'total_subsequent_orders': 0, 'total_subsequent_amount': '0.00', 'currency': 'USD'}, 'rows': []})}\n\n"
            return

        # Phase 2: per-customer fan-out with bounded concurrency
        semaphore = asyncio.Semaphore(5)
        rows: List[Dict[str, Any]] = []
        completed = 0
        last_heartbeat = asyncio.get_event_loop().time()

        async def process_customer(cid: str, first_order: Dict[str, Any]) -> Dict[str, Any]:
            async with semaphore:
                after_iso = first_order.get("processed_at") or first_order.get("created_at") or ""
                ok, err, orders = await fetch_customer_orders_after(
                    shop_domain=shop_domain,
                    admin_api_key=admin_api_key,
                    customer_id=cid,
                    after_date_iso=after_iso,
                    api_version=api_version,
                )
                if not ok:
                    return {"_error": err, "_customer_id": cid, "_first_order": first_order}

                first_order_id = first_order.get("id")
                subsequent_count = 0
                subsequent_amount = 0.0
                subsequent_currency = first_order.get("currency", "USD")

                for o in orders:
                    if o.get("id") == first_order_id:
                        continue  # exclude the first order itself
                    # Lenient success rule (confirmed):
                    #   not cancelled AND not fully REFUNDED AND has tracking
                    if o.get("cancelled_at"):
                        continue
                    if (o.get("display_financial_status") or "").upper() == "REFUNDED":
                        continue
                    if not o.get("has_tracking"):
                        continue
                    subsequent_count += 1
                    try:
                        subsequent_amount += float(o.get("total_amount") or 0)
                    except (TypeError, ValueError):
                        pass
                    if o.get("currency"):
                        subsequent_currency = o["currency"]

                first_name = first_order.get("customer_first_name") or ""
                last_name = first_order.get("customer_last_name") or ""
                customer_name = (first_name + " " + last_name).strip()
                if not customer_name:
                    customer_name = first_order.get("customer_email") or "(unknown)"

                first_date_iso = first_order.get("processed_at") or first_order.get("created_at")
                first_date_short = (first_date_iso or "")[:10] or None

                return {
                    "customer_id": cid,
                    "customer_name": customer_name,
                    "customer_email": first_order.get("customer_email"),
                    "first_order_id": first_order_id,
                    "first_order_name": first_order.get("name", ""),
                    "first_order_date": first_date_short,
                    "first_order_amount": f"{float(first_order.get('total_amount') or 0):.2f}",
                    "first_order_currency": first_order.get("currency", "USD"),
                    "subsequent_count": subsequent_count,
                    "subsequent_amount": f"{subsequent_amount:.2f}",
                    "subsequent_currency": subsequent_currency,
                }

        tasks = [
            asyncio.create_task(process_customer(cid, fo))
            for cid, fo in first_orders_by_customer.items()
        ]

        try:
            for fut in asyncio.as_completed(tasks):
                result = await fut
                completed += 1

                if "_error" in result:
                    yield f"event: progress\ndata: {json.dumps({'phase': 'customer_error', 'completed': completed, 'total': total_customers, 'message': result.get('_error') or 'Unknown error'})}\n\n"
                else:
                    rows.append(result)
                    yield f"event: customer\ndata: {json.dumps({'row': result, 'completed': completed, 'total': total_customers})}\n\n"

                now = asyncio.get_event_loop().time()
                if now - last_heartbeat > 15:
                    yield f": heartbeat\n\n"
                    last_heartbeat = now
        except GeneratorExit:
            print("[SHOPIFY-ANALYTICS] Client disconnected — cancelling pending tasks")
            for t in tasks:
                if not t.done():
                    t.cancel()
            raise

        # Final summary
        customers_with_returns = sum(1 for r in rows if r["subsequent_count"] > 0)
        total_subseq_orders = sum(r["subsequent_count"] for r in rows)
        total_subseq_amount = sum(float(r["subsequent_amount"]) for r in rows)
        currency_top = rows[0]["subsequent_currency"] if rows else "USD"

        rows.sort(key=lambda r: r["subsequent_count"], reverse=True)

        yield f"event: complete\ndata: {json.dumps({'summary': {'first_time_customers': total_customers, 'customers_with_returns': customers_with_returns, 'total_subsequent_orders': total_subseq_orders, 'total_subsequent_amount': f'{total_subseq_amount:.2f}', 'currency': currency_top}, 'rows': rows})}\n\n"

    async def generate_safe() -> AsyncGenerator[str, None]:
        try:
            async for event in generate():
                yield event
        except GeneratorExit:
            print("[SHOPIFY-ANALYTICS] Stream cancelled")
            return

    return StreamingResponse(
        generate_safe(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


_MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _month_spine(start_date: str, end_date: str) -> List[str]:
    """Continuous list of YYYY-MM keys from start through end, inclusive."""
    try:
        sy, sm = int(start_date[0:4]), int(start_date[5:7])
        ey, em = int(end_date[0:4]), int(end_date[5:7])
    except (ValueError, IndexError):
        return []

    spine: List[str] = []
    y, m = sy, sm
    # Guard against a reversed or absurd range producing an unbounded loop.
    while (y, m) <= (ey, em) and len(spine) < 600:
        spine.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return spine


def _month_label(month_key: str) -> str:
    try:
        y, m = int(month_key[0:4]), int(month_key[5:7])
        return f"{_MONTH_ABBR[m - 1]} {y}"
    except (ValueError, IndexError):
        return month_key


def _mom_pct(current: int, previous: Optional[int]) -> Optional[float]:
    """Month-over-month growth %. None for the first month or a zero baseline."""
    if previous is None or previous == 0:
        return None
    return round(((current - previous) / previous) * 100, 1)


@app.post("/api/shopify-analytics/new-customers-by-month/stream")
async def shopify_analytics_new_customers_by_month_stream(
    request: NewCustomersByMonthRequest,
    db: Session = Depends(get_db),
):
    async def generate() -> AsyncGenerator[str, None]:
        start_date = request.start_date
        end_date = request.end_date

        spine = _month_spine(start_date, end_date)
        if not spine:
            yield f"event: error\ndata: {json.dumps({'message': 'Invalid date range'})}\n\n"
            return

        store_ids = request.store_ids or []
        if not store_ids:
            yield f"event: error\ndata: {json.dumps({'message': 'Select at least one Shopify store'})}\n\n"
            return

        stores = db.query(Store).filter(
            Store.id.in_(store_ids),
            Store.store_type == StoreType.shopify,
            Store.is_active == True,
        ).all()

        # Tag resolution per store: explicit request override > store's saved tag > default.
        request_tag = (request.tag or "").strip() if request.tag is not None else ""

        store_list: List[Dict[str, Any]] = []
        for s in stores:
            conn = s.shopify_connection
            if not conn:
                continue
            saved_tag = (conn.first_order_tag or "").strip()
            store_list.append({
                "id": s.id,
                "name": s.name,
                "shop_domain": conn.shop_domain,
                "admin_api_key": conn.admin_api_key,
                "api_version": conn.api_version,
                "tag": request_tag or saved_tag or DEFAULT_FIRST_ORDER_TAG,
            })

        if not store_list:
            yield f"event: error\ndata: {json.dumps({'message': 'No active Shopify stores found for the selected ids'})}\n\n"
            return

        store_list.sort(key=lambda s: s["id"])

        yield f"event: progress\ndata: {json.dumps({'phase': 'started', 'start_date': start_date, 'end_date': end_date, 'months': [{'month': m, 'label': _month_label(m)} for m in spine], 'stores': [{'store_id': s['id'], 'store_name': s['name'], 'tag': s['tag']} for s in store_list]})}\n\n"

        semaphore = asyncio.Semaphore(5)

        async def fetch_for_store(s: Dict[str, Any]) -> Dict[str, Any]:
            async with semaphore:
                ok, err, orders = await fetch_orders_with_tag(
                    shop_domain=s["shop_domain"],
                    admin_api_key=s["admin_api_key"],
                    start_date=start_date,
                    end_date=end_date,
                    tag=s["tag"],
                    api_version=s["api_version"],
                )

                if not ok:
                    return {
                        "store": s, "ok": False, "error": err or "Unknown error",
                        "counts": {}, "total": 0, "anonymous": 0, "orders_scanned": 0,
                    }

                # Dedupe per customer across the whole window, keeping the earliest
                # tagged order, so sum(months) == store total. Orders with no customer
                # (deleted/redacted, anonymous POS) are still real acquisitions but
                # can't be deduped against each other — key them by order id.
                earliest: Dict[str, str] = {}
                for o in orders:
                    created = o.get("created_at") or o.get("processed_at") or ""
                    if len(created) < 7:
                        continue
                    key = o.get("customer_id") or f"anon:{o.get('id')}"
                    prev = earliest.get(key)
                    if prev is None or created < prev:
                        earliest[key] = created

                # Bucket by shop-LOCAL month: created_at is ISO8601 with the shop's
                # offset, and Shopify evaluates the created_at:>= filter in shop-local
                # time too. Converting to UTC would move an order into a month outside
                # the range the filter selected. Slice, don't convert.
                counts = {m: 0 for m in spine}
                anon = 0
                for key, created in earliest.items():
                    month_key = created[:7]
                    if month_key in counts:
                        counts[month_key] += 1
                    if key.startswith("anon:"):
                        anon += 1

                return {
                    "store": s, "ok": True, "error": None, "counts": counts,
                    "total": sum(counts.values()), "anonymous": anon,
                    "orders_scanned": len(orders),
                }

        tasks = [asyncio.create_task(fetch_for_store(s)) for s in store_list]
        results: Dict[int, Dict[str, Any]] = {}
        completed = 0
        last_heartbeat = asyncio.get_event_loop().time()

        try:
            for fut in asyncio.as_completed(tasks):
                res = await fut
                completed += 1
                results[res["store"]["id"]] = res

                yield f"event: store\ndata: {json.dumps({'store_id': res['store']['id'], 'store_name': res['store']['name'], 'tag': res['store']['tag'], 'ok': res['ok'], 'error': res['error'], 'counts': res['counts'], 'total_new_customers': res['total'], 'anonymous_new_customers': res['anonymous'], 'orders_scanned': res['orders_scanned'], 'completed': completed, 'total_stores': len(store_list)})}\n\n"

                now = asyncio.get_event_loop().time()
                if now - last_heartbeat > 15:
                    yield f": heartbeat\n\n"
                    last_heartbeat = now
        except GeneratorExit:
            print("[SHOPIFY-ANALYTICS] New-customers client disconnected — cancelling pending tasks")
            for t in tasks:
                if not t.done():
                    t.cancel()
            raise

        # Authoritative final payload. Failed stores are excluded from every total
        # so a fetch failure never reads as a zero.
        ok_ids = [s["id"] for s in store_list if results.get(s["id"], {}).get("ok")]

        month_rows: List[Dict[str, Any]] = []
        prev_total: Optional[int] = None
        for month_key in spine:
            per_store = {
                str(sid): results[sid]["counts"].get(month_key, 0) for sid in ok_ids
            }
            total = sum(per_store.values())
            month_rows.append({
                "month": month_key,
                "label": _month_label(month_key),
                "counts": per_store,
                "total": total,
                "mom_growth_pct": _mom_pct(total, prev_total),
            })
            prev_total = total

        merged_states: Dict[str, Dict[str, Any]] = {}
        for r in complete:
            for k, e in (r.get("states") or {}).items():
                tgt = merged_states.setdefault(
                    k, {"code": e["code"], "label": e["label"], "lost": 0, "active": 0})
                tgt["lost"] += e["lost"]
                tgt["active"] += e["active"]
        state_rows = []
        for e in merged_states.values():
            total = e["lost"] + e["active"]
            state_rows.append({
                "code": e["code"],
                "label": e["label"],
                "lost": e["lost"],
                "active": e["active"],
                "total": total,
                # Suppressed on tiny samples: 1 of 1 is not a 100% loss rate.
                "loss_rate": (round(e["lost"] / total * 100, 1)
                              if total >= _STATE_MIN_CUSTOMERS else None),
            })
        state_rows.sort(key=lambda x: (-x["lost"], x["label"]))

        payload = {
            "states": state_rows,
            "state_min_customers": _STATE_MIN_CUSTOMERS,
            "stores": [{
                "store_id": s["id"],
                "store_name": s["name"],
                "tag": s["tag"],
                "ok": results.get(s["id"], {}).get("ok", False),
                "error": results.get(s["id"], {}).get("error"),
                "total_new_customers": results.get(s["id"], {}).get("total", 0),
                "orders_scanned": results.get(s["id"], {}).get("orders_scanned", 0),
                "anonymous_new_customers": results.get(s["id"], {}).get("anonymous", 0),
            } for s in store_list],
            "months": month_rows,
            "totals_by_store": {str(sid): results[sid]["total"] for sid in ok_ids},
            "grand_total": sum(results[sid]["total"] for sid in ok_ids),
            "start_date": start_date,
            "end_date": end_date,
        }

        yield f"event: complete\ndata: {json.dumps(payload)}\n\n"

    async def generate_safe() -> AsyncGenerator[str, None]:
        try:
            async for event in generate():
                yield event
        except GeneratorExit:
            print("[SHOPIFY-ANALYTICS] New-customers stream cancelled")
            return

    return StreamingResponse(
        generate_safe(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# ============================================================================
# Lost Customers
#
# Whether a customer is lost is decided here, not by Shopify. The `order_date` filter has
# any-order semantics ("has placed at least one order in this range"), and
# negating it does not invert that — verified against live stores, where every
# negated form still returned 12% of customers who HAD ordered after the
# cutoff. So the query only bounds the window; classification is ours.
# ============================================================================

# Wall-clock per store is latency-bound (~5s per 250-customer page), so the
# window is split into concurrent shards. This also keeps each cursor walk
# under Shopify's 25,000-object pagination ceiling.
_LOST_MAX_SHARDS = 4
_LOST_SHARD_MIN_DAYS = 90


def _lost_shards(active_since: str, upper: str) -> List[tuple]:
    """Split [active_since, upper) into up to 4 contiguous sub-ranges."""
    from datetime import date, timedelta

    try:
        start = date.fromisoformat(active_since)
        end = date.fromisoformat(upper)
    except ValueError:
        return [(active_since, None)]

    span = (end - start).days
    if span <= _LOST_SHARD_MIN_DAYS:
        return [(active_since, None)]

    n = min(_LOST_MAX_SHARDS, max(2, span // _LOST_SHARD_MIN_DAYS))
    step = span // n
    bounds = [start + timedelta(days=step * i) for i in range(n)] + [end]
    # Last shard is left open-ended so orders placed after `upper` (i.e. today)
    # still classify their owner as active.
    return [
        (bounds[i].isoformat(), bounds[i + 1].isoformat() if i < n - 1 else None)
        for i in range(n)
    ]


def _median(values: List[float]) -> Optional[float]:
    """Median, not mean — delivery times are right-skewed and a few stuck
    parcels would drag a mean somewhere no customer actually experienced."""
    if not values:
        return None
    return round(statistics.median(values), 2)


def _timing_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    fulfil = [r["days_to_fulfil"] for r in rows if r.get("days_to_fulfil") is not None]
    deliver = [r["days_to_deliver"] for r in rows if r.get("days_to_deliver") is not None]
    total = [r["days_total"] for r in rows if r.get("days_total") is not None]
    return {
        "days_to_fulfil": _median(fulfil),
        "days_to_deliver": _median(deliver),
        "days_total": _median(total),
        "n": len(rows),
        # Coverage is reported separately so a median over 12 orders is never
        # mistaken for one over 12,000.
        "n_fulfil": len(fulfil),
        "n_deliver": len(deliver),
        "n_total": len(total),
    }


@app.post("/api/shopify-analytics/lost-customers/stream")
async def shopify_analytics_lost_customers_stream(
    request: LostCustomersRequest,
    db: Session = Depends(get_db),
):
    async def generate() -> AsyncGenerator[str, None]:
        active_since = request.active_since
        silent_since = request.silent_since
        min_orders = max(1, int(request.min_orders or 1))

        if not active_since or not silent_since or active_since >= silent_since:
            yield f"event: error\ndata: {json.dumps({'message': 'Active-since must be earlier than silent-since'})}\n\n"
            return
        if not request.store_ids:
            yield f"event: error\ndata: {json.dumps({'message': 'Select at least one Shopify store'})}\n\n"
            return

        stores = db.query(Store).filter(
            Store.id.in_(request.store_ids),
            Store.store_type == StoreType.shopify,
            Store.is_active == True,
        ).all()

        store_list: List[Dict[str, Any]] = []
        for s in stores:
            conn = s.shopify_connection
            if not conn:
                continue
            store_list.append({
                "id": s.id, "name": s.name,
                "shop_domain": conn.shop_domain,
                "admin_api_key": conn.admin_api_key,
                "api_version": conn.api_version,
            })
        if not store_list:
            yield f"event: error\ndata: {json.dumps({'message': 'No active Shopify stores found for the selected ids'})}\n\n"
            return
        store_list.sort(key=lambda s: s["id"])

        # Someone who stops buying here and starts at a sister shop has not
        # churned. Shopify keeps a separate customer record per shop, so the
        # only way to see that is to look — and it has to include shops the
        # user did not select, since that is exactly where they may have gone.
        all_shopify: List[Dict[str, Any]] = []
        for st_all in db.query(Store).filter(
            Store.store_type == StoreType.shopify, Store.is_active == True,
        ).all():
            if not st_all.shopify_connection:
                continue
            all_shopify.append({
                "id": st_all.id, "name": st_all.name,
                "shop_domain": st_all.shopify_connection.shop_domain,
                "admin_api_key": st_all.shopify_connection.admin_api_key,
                "api_version": st_all.shopify_connection.api_version,
            })
        cross_store = bool(request.exclude_cross_store) and len(all_shopify) > 1

        today = datetime.now().strftime("%Y-%m-%d")
        shards = _lost_shards(active_since, today)

        yield f"event: progress\ndata: {json.dumps({'phase': 'started', 'active_since': active_since, 'silent_since': silent_since, 'min_orders': min_orders, 'shards': len(shards), 'total_units': len(shards) * len(store_list), 'stores': [{'store_id': s['id'], 'store_name': s['name']} for s in store_list]})}\n\n"

        # Retries and page progress must reach the client while work is still in
        # flight, so workers publish to a queue rather than only returning.
        events: asyncio.Queue = asyncio.Queue()
        semaphore = asyncio.Semaphore(5)

        async def fetch_for_store(s: Dict[str, Any]) -> Dict[str, Any]:
            async with semaphore:
                def on_retry(attempt, max_attempts, reason, _s=s):
                    events.put_nowait(("retry", {
                        "store_id": _s["id"], "store_name": _s["name"],
                        "attempt": attempt, "max_attempts": max_attempts, "reason": reason,
                    }))

                events.put_nowait(("store_start", {
                    "store_id": s["id"], "store_name": s["name"], "shards": len(shards),
                }))

                async def run_shard(index: int, lo: str, hi: Optional[str]):
                    # Page callbacks are what prove the run is alive during a
                    # long cursor walk — a store can spend minutes on one shard.
                    pages = 0

                    def on_page(scanned: int, _i=index):
                        nonlocal pages
                        pages += 1
                        events.put_nowait(("page", {
                            "store_id": s["id"], "store_name": s["name"],
                            "shard": _i, "pages": pages, "scanned": scanned,
                        }))

                    res = await fetch_customers_with_last_order(
                        shop_domain=s["shop_domain"],
                        admin_api_key=s["admin_api_key"],
                        active_since=active_since,
                        api_version=s["api_version"],
                        shard_start=lo,
                        shard_end=hi,
                        on_retry=on_retry,
                        on_page=on_page,
                    )
                    events.put_nowait(("shard_done", {
                        "store_id": s["id"], "store_name": s["name"], "shard": index,
                        "ok": bool(res.get("ok")), "pages": res.get("pages", 0),
                        "scanned": len(res.get("customers") or []),
                    }))
                    return res

                shard_results = await asyncio.gather(*[
                    run_shard(i, lo, hi) for i, (lo, hi) in enumerate(shards)
                ], return_exceptions=True)

                by_id: Dict[str, Dict[str, Any]] = {}
                warnings: List[str] = []
                failed_shards = 0
                incomplete_reasons: List[str] = []

                for res in shard_results:
                    if isinstance(res, BaseException):
                        failed_shards += 1
                        incomplete_reasons.append(str(res)[:200])
                        continue
                    if not res.get("ok"):
                        failed_shards += 1
                        if res.get("error"):
                            incomplete_reasons.append(res["error"][:200])
                    if res.get("incomplete_reason"):
                        incomplete_reasons.append(res["incomplete_reason"])
                    warnings.extend(res.get("warnings") or [])
                    # A customer with orders in several shards appears in each;
                    # the record is identical, so first write wins.
                    for c in res.get("customers") or []:
                        if c.get("customer_id"):
                            by_id.setdefault(c["customer_id"], c)

                if failed_shards >= len(shards):
                    return {
                        "store": s, "ok": False, "complete": False,
                        "error": incomplete_reasons[0] if incomplete_reasons else "Fetch failed",
                        "lost": [], "lost_all": [], "active": [],
                    }

                lost, active = [], []
                never_purchased = 0
                for c in by_id.values():
                    last = c.get("last_order_created_at")
                    if not last:
                        # Every order they placed was cancelled or refunded, so
                        # there is no purchase here to have lost.
                        never_purchased += 1
                        continue
                    if last >= silent_since:
                        active.append(c)
                    elif last >= active_since:
                        lost.append(c)

                # "Was ordering since" means the customer STARTED here. Shopify's
                # order_date filter only proves they ordered at some point in the
                # window, so anyone already buying beforehand is still in `lost`
                # at this stage. Look up each candidate's oldest order and drop
                # the pre-existing ones outright — they must not reach the rows,
                # the totals, the KPIs or the benchmark.
                candidates = [c["customer_id"] for c in (lost + active) if c.get("customer_id")]
                first_map: Dict[str, Any] = {}
                first_err = None
                unknown_first = 0
                if candidates:
                    events.put_nowait(("phase", {
                        "store_id": s["id"], "store_name": s["name"],
                        "label": "checking when each customer started",
                    }))
                    fo = await fetch_customer_first_orders(
                        shop_domain=s["shop_domain"],
                        admin_api_key=s["admin_api_key"],
                        customer_ids=candidates,
                        api_version=s["api_version"],
                        on_batch=lambda d, t, _s=s: events.put_nowait(("first_orders", {
                            "store_id": _s["id"], "store_name": _s["name"],
                            "done": d, "total": t,
                        })),
                        on_retry=on_retry,
                    )
                    if fo.get("ok"):
                        first_map = fo.get("first_orders") or {}
                        unknown_first = fo.get("missing", 0)
                    else:
                        first_err = fo.get("error")

                def acquired_in_window(c):
                    first = first_map.get(c.get("customer_id"))
                    if not first:
                        # No first order resolved: excluded rather than assumed
                        # in, so a lookup gap can never inflate the cohort.
                        return False
                    c["first_order_created_at"] = first
                    return first >= active_since

                if first_err:
                    # Without first-order data the acquisition filter cannot be
                    # honoured, so report the store as partial instead of
                    # silently falling back to the old, wider meaning.
                    incomplete_reasons.append(
                        f"Could not determine when customers started ordering: {first_err}")
                    for c in lost + active:
                        c["first_order_created_at"] = None
                    lost_in, active_in = lost, active
                else:
                    lost_in = [c for c in lost if acquired_in_window(c)]
                    active_in = [c for c in active if acquired_in_window(c)]

                excluded_pre_existing = (len(lost) - len(lost_in)) + (len(active) - len(active_in))

                lost_kept = [c for c in lost_in if c["orders_count"] >= min_orders]
                lost_kept.sort(key=lambda c: c["amount_spent"], reverse=True)
                # The comparison group must be filtered identically. Applying
                # min_orders — or the acquisition window — to only one side
                # would compare newly-acquired leavers against a control drawn
                # from a different population.
                active_kept = [c for c in active_in if c["orders_count"] >= min_orders]

                # Cross-store check runs last, on the smallest possible list.
                moved_breakdown: Dict[str, int] = {}
                no_email = 0
                cross_errors: List[str] = []
                if cross_store and lost_kept:
                    others = [o for o in all_shopify if o["id"] != s["id"]]
                    emails = [normalize_email(c.get("email")) for c in lost_kept]
                    no_email = sum(1 for c in lost_kept if not normalize_email(c.get("email")))
                    lookup = [e for e in emails if e]

                    events.put_nowait(("phase", {
                        "store_id": s["id"], "store_name": s["name"],
                        "label": f"checking {len(others)} other store(s) for these customers",
                    }))

                    # email -> name of the shop they are still buying from
                    moved_to: Dict[str, str] = {}
                    for other in others:
                        if not lookup:
                            break
                        res = await fetch_customers_by_emails(
                            shop_domain=other["shop_domain"],
                            admin_api_key=other["admin_api_key"],
                            emails=lookup,
                            api_version=other["api_version"],
                            on_batch=lambda d, t, _s=s, _o=other: events.put_nowait(("cross_store", {
                                "store_id": _s["id"], "store_name": _s["name"],
                                "other": _o["name"], "done": d, "total": t,
                            })),
                            on_retry=on_retry,
                        )
                        if not res.get("ok"):
                            # Never silently keep a customer we failed to check.
                            cross_errors.append(f"{other['name']}: {res.get('error')}")
                            continue
                        for em, last in (res.get("last_orders") or {}).items():
                            if last and last >= silent_since and em not in moved_to:
                                moved_to[em] = other["name"]

                    if moved_to:
                        for c in lost_kept:
                            em = normalize_email(c.get("email"))
                            if em and em in moved_to:
                                c["moved_to_store"] = moved_to[em]
                        kept = []
                        for c in lost_kept:
                            if c.get("moved_to_store"):
                                moved_breakdown[c["moved_to_store"]] = (
                                    moved_breakdown.get(c["moved_to_store"], 0) + 1)
                            else:
                                kept.append(c)
                        lost_kept = kept
                    if cross_errors:
                        incomplete_reasons.append(
                            "Could not check every other store for customers who moved: "
                            + "; ".join(cross_errors[:2]))

                # Lost and still-active counted the same way, so the share of a
                # state's customers that went quiet is comparable between
                # states — a raw count would only rank population size.
                states: Dict[str, Dict[str, Any]] = {}
                for c in lost_kept:
                    k, label = _state_key(c)
                    e = states.setdefault(k, {"code": k, "label": label, "lost": 0, "active": 0})
                    e["lost"] += 1
                for c in active_kept:
                    k, label = _state_key(c)
                    e = states.setdefault(k, {"code": k, "label": label, "lost": 0, "active": 0})
                    e["active"] += 1

                return {
                    "store": s,
                    "ok": True,
                    # A failed shard removes a contiguous date range, so what
                    # survives is a biased sample — flag it rather than pretend.
                    "complete": failed_shards == 0 and not incomplete_reasons,
                    "incomplete_reason": incomplete_reasons[0] if incomplete_reasons else None,
                    "error": None,
                    "warnings": warnings[:3],
                    "lost": lost_kept,
                    "lost_all": lost_in,
                    "active": active_kept,
                    "active_all": active_in,
                    "excluded_pre_existing": excluded_pre_existing,
                    "unknown_first_order": unknown_first,
                    "never_purchased": never_purchased,
                    "states": states,
                    "moved_breakdown": moved_breakdown,
                    "moved_total": sum(moved_breakdown.values()),
                    "no_email": no_email,
                }

        tasks = [asyncio.create_task(fetch_for_store(s)) for s in store_list]

        async def collect(t):
            try:
                res = await t
            except asyncio.CancelledError:
                raise
            except Exception as e:
                res = {"store": None, "ok": False, "complete": False,
                       "error": f"Unexpected error: {e}", "lost": [], "lost_all": [], "active": []}
            await events.put(("done", res))

        collectors = [asyncio.create_task(collect(t)) for t in tasks]

        results: List[Dict[str, Any]] = []
        completed = 0
        last_heartbeat = asyncio.get_event_loop().time()

        try:
            while completed < len(store_list):
                try:
                    kind, payload = await asyncio.wait_for(events.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    last_heartbeat = asyncio.get_event_loop().time()
                    continue

                # Everything except "done" is liveness reporting and must not
                # advance the completed-store counter.
                if kind in ("retry", "store_start", "page", "shard_done",
                            "phase", "first_orders", "cross_store"):
                    yield f"event: progress\ndata: {json.dumps({'phase': kind, **payload})}\n\n"
                    continue

                completed += 1
                results.append(payload)
                st = payload.get("store") or {}
                lost = payload.get("lost") or []
                yield f"event: store\ndata: {json.dumps({'store_id': st.get('id'), 'store_name': st.get('name'), 'ok': payload.get('ok'), 'complete': payload.get('complete'), 'incomplete_reason': payload.get('incomplete_reason'), 'error': payload.get('error'), 'warnings': payload.get('warnings') or [], 'excluded_pre_existing': payload.get('excluded_pre_existing', 0), 'unknown_first_order': payload.get('unknown_first_order', 0), 'never_purchased': payload.get('never_purchased', 0), 'moved_total': payload.get('moved_total', 0), 'moved_breakdown': payload.get('moved_breakdown', {}), 'no_email': payload.get('no_email', 0), 'lost_count': len(lost), 'active_count': len(payload.get('active') or []), 'lost_timing': _timing_summary(lost), 'active_timing': _timing_summary(payload.get('active') or []), 'rows': lost, 'completed': completed, 'total_stores': len(store_list)})}\n\n"

                now = asyncio.get_event_loop().time()
                if now - last_heartbeat > 15:
                    yield ": heartbeat\n\n"
                    last_heartbeat = now
        except GeneratorExit:
            print("[SHOPIFY-ANALYTICS] Lost client disconnected — cancelling")
            for t in list(tasks) + list(collectors):
                if not t.done():
                    t.cancel()
            raise

        # Only stores with a complete fetch feed the benchmark. A partial store
        # is missing a date range, and the benchmark is the number the user acts on.
        complete = [r for r in results if r.get("ok") and r.get("complete")]
        all_lost = [c for r in complete for c in (r.get("lost") or [])]
        all_active = [c for r in complete for c in (r.get("active") or [])]

        # "When did they leave" — month of last order.
        by_month: Dict[str, int] = {}
        for c in all_lost:
            key = (c.get("last_order_created_at") or "")[:7]
            if key:
                by_month[key] = by_month.get(key, 0) + 1

        merged_states: Dict[str, Dict[str, Any]] = {}
        for r in complete:
            for k, e in (r.get("states") or {}).items():
                tgt = merged_states.setdefault(
                    k, {"code": e["code"], "label": e["label"], "lost": 0, "active": 0})
                tgt["lost"] += e["lost"]
                tgt["active"] += e["active"]
        state_rows = []
        for e in merged_states.values():
            total = e["lost"] + e["active"]
            state_rows.append({
                "code": e["code"],
                "label": e["label"],
                "lost": e["lost"],
                "active": e["active"],
                "total": total,
                # Suppressed on tiny samples: 1 of 1 is not a 100% loss rate.
                "loss_rate": (round(e["lost"] / total * 100, 1)
                              if total >= _STATE_MIN_CUSTOMERS else None),
            })
        state_rows.sort(key=lambda x: (-x["lost"], x["label"]))

        payload = {
            "states": state_rows,
            "state_min_customers": _STATE_MIN_CUSTOMERS,
            "stores": [{
                "store_id": (r.get("store") or {}).get("id"),
                "store_name": (r.get("store") or {}).get("name"),
                "ok": r.get("ok"),
                "complete": r.get("complete"),
                "incomplete_reason": r.get("incomplete_reason"),
                "error": r.get("error"),
                "warnings": r.get("warnings") or [],
                "lost_count": len(r.get("lost") or []),
                "active_count": len(r.get("active") or []),
                "excluded_pre_existing": r.get("excluded_pre_existing", 0),
                "unknown_first_order": r.get("unknown_first_order", 0),
                "never_purchased": r.get("never_purchased", 0),
                "moved_total": r.get("moved_total", 0),
                "moved_breakdown": r.get("moved_breakdown", {}),
                "no_email": r.get("no_email", 0),
                "lost_timing": _timing_summary(r.get("lost") or []),
                "active_timing": _timing_summary(r.get("active") or []),
            } for r in results],
            "benchmark": {
                "lost": _timing_summary(all_lost),
                "active": _timing_summary(all_active),
                "stores_included": len(complete),
                "stores_total": len(store_list),
            },
            "totals": {
                "excluded_pre_existing": sum(r.get("excluded_pre_existing", 0) for r in complete),
                "moved_to_other_store": sum(r.get("moved_total", 0) for r in complete),
                "never_purchased": sum(r.get("never_purchased", 0) for r in complete),
                "no_email": sum(r.get("no_email", 0) for r in complete),
                "unknown_first_order": sum(r.get("unknown_first_order", 0) for r in complete),
                "lost_customers": len(all_lost),
                "revenue_lost": round(sum(c["amount_spent"] for c in all_lost), 2),
                "median_orders": _median([float(c["orders_count"]) for c in all_lost]),
                "currency": (all_lost[0]["currency"] if all_lost else "USD"),
            },
            "by_month": [{"month": m, "count": by_month[m]} for m in sorted(by_month)],
            "active_since": active_since,
            "silent_since": silent_since,
            "min_orders": min_orders,
        }
        yield f"event: complete\ndata: {json.dumps(payload)}\n\n"

    async def generate_safe() -> AsyncGenerator[str, None]:
        try:
            async for event in generate():
                yield event
        except GeneratorExit:
            print("[SHOPIFY-ANALYTICS] Lost stream cancelled")
            return

    return StreamingResponse(
        generate_safe(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post("/api/shopify-analytics/customer-detail")
async def shopify_analytics_customer_detail(
    request: CustomerDetailRequest,
    db: Session = Depends(get_db),
):
    """Recent orders + line items for one customer, loaded on row click."""
    store = db.query(Store).filter(
        Store.id == request.store_id,
        Store.store_type == StoreType.shopify,
    ).first()
    if not store or not store.shopify_connection:
        raise HTTPException(status_code=404, detail="Shopify store not found")

    conn = store.shopify_connection
    result = await fetch_customer_recent_orders(
        shop_domain=conn.shop_domain,
        admin_api_key=conn.admin_api_key,
        customer_id=request.customer_id,
        api_version=conn.api_version,
        limit=request.limit or 5,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error") or "Shopify request failed")
    return {"store_name": store.name, "orders": result["orders"]}



# ============================================================================
# Lost Products — what was in the order customers left after
#
# Ranked by how many last orders a product appears in, NOT by quantity: one
# buyer taking 20 units must not outweigh 20 buyers taking one each.
#
# A raw frequency ranking reproduces the bestseller list, so every row also
# carries its share of a same-period baseline. Measured on live data, one
# product sat 3rd by count while being *under*-represented versus baseline
# (2.5% of last orders vs 3.0% of all orders) — without the comparison it
# would read as a churn signal.
# ============================================================================

# Baseline sampling. Exhaustive is not an option — one store has ~137,000
# orders in a two-year window — but a naive "first 250 of each month" is worse
# than it looks: on a 5,000-order month it covers only days 1-2, so every lift
# inherits whatever is special about the start of a month.
#
# Instead, size each window so a single 250-order page covers it ENTIRELY
# (unbiased within the window), and spread those windows evenly across the
# range. Small stores end up with contiguous windows, i.e. full coverage.
_BASELINE_PAGE_BUDGET = 100
_BASELINE_PAGE = 250
# Days used to measure the store's order rate. Short enough to stay under
# Shopify's 10,000 ordersCount saturation on the busiest store.
_RATE_PROBE_DAYS = 14
# Below this many last orders, a lift ratio is noise dressed up as a finding.
_LIFT_MIN_ORDERS = 5

# Below this many customers a loss rate is one or two people, not a trend.
_STATE_MIN_CUSTOMERS = 5


def _state_key(c: Dict[str, Any]) -> tuple:
    """(code, label). Province codes repeat across countries, so keep country."""
    code = c.get("state")
    country = c.get("country") or ""
    if not code:
        return ("__unknown__", "Unknown")
    label = c.get("state_name") or code
    if country and country != "US":
        return (f"{country}-{code}", f"{label} ({country})")
    return (code, label)


def _baseline_months(
    start_date: str, end_date: str, orders_per_day: float,
    page_budget: int = _BASELINE_PAGE_BUDGET,
) -> List[tuple]:
    """
    Complete calendar months, spread evenly across the range.

    Whole months matter: a partial slice inherits whatever is special about the
    days it lands on — paydays, weekends, promos, restocks. Each returned
    window is paginated in full, so within a month coverage is total.

    How many months fit depends on the store: a 5,000-order month costs ~20
    pages, a 30-order month costs one. The page budget decides how many months
    can be covered, and they are spread across the range rather than clustered.
    """
    from datetime import date

    try:
        s = date.fromisoformat(start_date)
        e = date.fromisoformat(end_date)
    except ValueError:
        return []
    if s >= e:
        return []

    months: List[tuple] = []
    y, m = s.year, s.month
    while date(y, m, 1) < e and len(months) < 120:
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        lo = max(date(y, m, 1), s)
        hi = min(date(ny, nm, 1), e)
        if lo < hi:
            months.append((lo.isoformat(), hi.isoformat()))
        y, m = ny, nm
    if not months:
        return []

    avg_days = ((e - s).days / len(months)) or 30
    per_month_pages = max(
        1, math.ceil((orders_per_day * avg_days) / _BASELINE_PAGE) if orders_per_day else 1
    )
    n = max(1, min(len(months), page_budget // per_month_pages))
    if n >= len(months):
        return months
    step = len(months) / n
    return [months[int(i * step)] for i in range(n)]


def _rate_probe_window(start_date: str, end_date: str) -> tuple:
    """A short window mid-range used to measure the store's orders/day."""
    from datetime import date, timedelta

    try:
        s = date.fromisoformat(start_date)
        e = date.fromisoformat(end_date)
    except ValueError:
        return (start_date, end_date, 1)
    total = (e - s).days
    if total <= _RATE_PROBE_DAYS:
        return (start_date, end_date, max(1, total))
    mid = s + timedelta(days=total // 2)
    return (mid.isoformat(), (mid + timedelta(days=_RATE_PROBE_DAYS)).isoformat(), _RATE_PROBE_DAYS)


# Add-ons and service lines are not products a customer chose to buy, and they
# ride along on a large share of orders — "Shipping Protection" sat 2nd by
# count. Excluded at source so they also drop out of the baskets and the
# baseline, keeping the percentages and lift consistent.
_EXCLUDED_PRODUCT_TERMS = ("shipping",)


def _is_excluded_product(item: Dict[str, Any]) -> bool:
    name = f"{item.get('product_title') or ''} {item.get('title') or ''}".lower()
    return any(term in name for term in _EXCLUDED_PRODUCT_TERMS)


def _product_key(item: Dict[str, Any]) -> tuple:
    """
    Group key and display title.

    Falls back to the line-item title when `product` is null (deleted product)
    rather than dropping the row — a discontinued item is exactly the kind of
    thing this report exists to surface.
    """
    pid = item.get("product_id")
    if pid:
        return (pid, item.get("product_title") or item.get("title") or "(untitled)", False)
    title = item.get("title") or "(untitled)"
    return (f"title:{title.lower()}", title, True)


def _count_orders(orders: List[Dict[str, Any]]) -> tuple:
    """
    Count how many ORDERS each product appears in, plus per-variant detail.

    A product is counted once per order even when it occupies several line
    items. Since each lost customer contributes exactly one last order, this is
    simultaneously a distinct-customer count.
    """
    per_product: Dict[Any, Dict[str, Any]] = {}
    excluded_lines = 0
    for order in orders:
        seen_products = set()
        seen_variants = set()
        for item in order.get("items") or []:
            if _is_excluded_product(item):
                excluded_lines += 1
                continue
            key, title, deleted = _product_key(item)
            entry = per_product.setdefault(key, {
                "key": key if isinstance(key, str) else str(key),
                "product_id": item.get("product_id"),
                "title": title,
                "deleted": deleted,
                "orders": 0,
                "quantity": 0,
                "variants": {},
            })
            entry["quantity"] += item.get("quantity") or 0
            if key not in seen_products:
                entry["orders"] += 1
                seen_products.add(key)

            vkey = item.get("sku") or item.get("variant_title") or "—"
            v = entry["variants"].setdefault(vkey, {
                "title": item.get("variant_title") or "",
                "sku": item.get("sku") or "",
                "orders": 0,
                "quantity": 0,
            })
            v["quantity"] += item.get("quantity") or 0
            if (key, vkey) not in seen_variants:
                v["orders"] += 1
                seen_variants.add((key, vkey))

    return per_product, len(orders), excluded_lines


@app.post("/api/shopify-analytics/lost-products/stream")
async def shopify_analytics_lost_products_stream(
    request: LostProductsRequest,
    db: Session = Depends(get_db),
):
    async def generate() -> AsyncGenerator[str, None]:
        selected = [s for s in (request.stores or []) if s.order_ids]
        if not selected:
            yield f"event: error\ndata: {json.dumps({'message': 'No last orders to analyse'})}\n\n"
            return

        stores = db.query(Store).filter(
            Store.id.in_([s.store_id for s in selected]),
            Store.store_type == StoreType.shopify,
            Store.is_active == True,
        ).all()
        by_id = {s.id: s for s in stores}

        work: List[Dict[str, Any]] = []
        for sel in selected:
            store = by_id.get(sel.store_id)
            if not store or not store.shopify_connection:
                continue
            conn = store.shopify_connection
            work.append({
                "id": store.id, "name": store.name,
                "shop_domain": conn.shop_domain,
                "admin_api_key": conn.admin_api_key,
                "api_version": conn.api_version,
                "order_ids": sel.order_ids,
            })
        if not work:
            yield f"event: error\ndata: {json.dumps({'message': 'No active Shopify stores found for the selected ids'})}\n\n"
            return
        work.sort(key=lambda w: w["id"])

        total_orders = sum(len(w["order_ids"]) for w in work)

        yield f"event: progress\ndata: {json.dumps({'phase': 'started', 'total_orders': total_orders, 'stores': [{'store_id': w['id'], 'store_name': w['name'], 'orders': len(w['order_ids'])} for w in work]})}\n\n"

        events: asyncio.Queue = asyncio.Queue()
        semaphore = asyncio.Semaphore(5)

        async def analyse_store(w: Dict[str, Any]) -> Dict[str, Any]:
            async with semaphore:
                def on_retry(attempt, max_attempts, reason, _w=w):
                    events.put_nowait(("retry", {
                        "store_id": _w["id"], "store_name": _w["name"],
                        "attempt": attempt, "max_attempts": max_attempts, "reason": reason,
                    }))

                def on_batch(done, total, _w=w, kind="last"):
                    events.put_nowait(("batch", {
                        "store_id": _w["id"], "store_name": _w["name"],
                        "kind": kind, "done": done, "total": total,
                    }))

                last = await fetch_orders_line_items(
                    shop_domain=w["shop_domain"], admin_api_key=w["admin_api_key"],
                    order_ids=w["order_ids"], api_version=w["api_version"],
                    on_batch=on_batch, on_retry=on_retry,
                )
                if not last.get("ok"):
                    return {"store": w, "ok": False, "error": last.get("error") or "Fetch failed",
                            "last": None, "baseline": None, "windows": []}

                # Measure this store's order rate so the baseline windows can be
                # sized to fit one page each. Stores differ by 100x in volume, so
                # a single fixed window size would over-sample one and bias another.
                pstart, pend, pdays = _rate_probe_window(
                    request.active_since, request.silent_since)
                rate = 0.0
                ok_c, _err_c, cnt = await count_orders(
                    shop_domain=w["shop_domain"], admin_api_key=w["admin_api_key"],
                    query=f"created_at:>={pstart} created_at:<{pend} {ORDER_STATUS_FILTER}",
                    api_version=w["api_version"],
                )
                if ok_c and cnt:
                    rate = cnt / max(1, pdays)
                windows = _baseline_months(
                    request.active_since, request.silent_since, rate)

                base = await fetch_baseline_order_items(
                    shop_domain=w["shop_domain"], admin_api_key=w["admin_api_key"],
                    windows=windows, api_version=w["api_version"],
                    on_batch=lambda d, t, _w=w: events.put_nowait(("batch", {
                        "store_id": _w["id"], "store_name": _w["name"],
                        "kind": "baseline", "done": d, "total": t,
                    })),
                    on_retry=on_retry,
                )
                return {"store": w, "ok": True, "error": None, "last": last,
                        "baseline": base, "windows": windows, "orders_per_day": round(rate, 1)}

        tasks = [asyncio.create_task(analyse_store(w)) for w in work]

        async def collect(t):
            try:
                res = await t
            except asyncio.CancelledError:
                raise
            except Exception as e:
                res = {"store": None, "ok": False, "error": f"Unexpected error: {e}",
                       "last": None, "baseline": None, "windows": []}
            await events.put(("done", res))

        collectors = [asyncio.create_task(collect(t)) for t in tasks]

        results: List[Dict[str, Any]] = []
        completed = 0
        last_heartbeat = asyncio.get_event_loop().time()

        try:
            while completed < len(work):
                try:
                    kind, payload = await asyncio.wait_for(events.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    last_heartbeat = asyncio.get_event_loop().time()
                    continue

                if kind in ("retry", "batch"):
                    yield f"event: progress\ndata: {json.dumps({'phase': kind, **payload})}\n\n"
                    continue

                completed += 1
                results.append(payload)
                st = payload.get("store") or {}
                yield f"event: progress\ndata: {json.dumps({'phase': 'store_done', 'store_id': st.get('id'), 'store_name': st.get('name'), 'ok': payload.get('ok'), 'error': payload.get('error'), 'completed': completed, 'total_stores': len(work)})}\n\n"

                now = asyncio.get_event_loop().time()
                if now - last_heartbeat > 15:
                    yield ": heartbeat\n\n"
                    last_heartbeat = now
        except GeneratorExit:
            print("[SHOPIFY-ANALYTICS] Lost-products client disconnected — cancelling")
            for t in list(tasks) + list(collectors):
                if not t.done():
                    t.cancel()
            raise

        # --- merge across stores, standardised per store ---
        #
        # Pooling raw counts across stores is Simpson's paradox waiting to
        # happen: merging a small store with a large one shifted one product
        # from 2.46x to 11.00x without a single order changing, because the
        # other store contributed baseline orders but no matching sales.
        #
        # So compare each store against ITS OWN baseline and sum the results
        # (indirect standardisation): expected = SUM_s n_lost_s * share_base_s.
        # Lift is then observed/expected, and store mix cannot distort it.
        per_store = []
        missing = 0
        truncated = 0
        excluded_lines_total = 0

        for res in results:
            if not res.get("ok"):
                continue
            last = res["last"]
            base = res.get("baseline") or {}
            missing += last.get("missing", 0)
            truncated += last.get("truncated", 0) + (base.get("truncated", 0) or 0)

            lost_products, n_lost_s, excl_lost = _count_orders(last.get("orders") or [])
            base_products, n_base_s, _excl_base = (
                _count_orders(base.get("orders") or []) if base.get("ok") else ({}, 0, 0)
            )
            excluded_lines_total += excl_lost
            slots_last = sum(e["orders"] for e in lost_products.values())
            slots_base = sum(e["orders"] for e in base_products.values())
            per_store.append({
                "store": res.get("store") or {},
                "lost_products": lost_products,
                "base_products": base_products,
                "n_lost": n_lost_s,
                "n_base": n_base_s,
                "avg_last": (slots_last / n_lost_s) if n_lost_s else 0.0,
                "avg_base": (slots_base / n_base_s) if n_base_s else 0.0,
            })

        n_last = sum(p["n_lost"] for p in per_store)
        n_base = sum(p["n_base"] for p in per_store)

        merged: Dict[Any, Dict[str, Any]] = {}
        for ps in per_store:
            for key, entry in ps["lost_products"].items():
                tgt = merged.setdefault(key, {
                    "key": entry["key"], "product_id": entry["product_id"],
                    "title": entry["title"], "deleted": entry["deleted"],
                    "orders": 0, "quantity": 0, "variants": {},
                })
                tgt["orders"] += entry["orders"]
                tgt["quantity"] += entry["quantity"]
                for vk, v in entry["variants"].items():
                    tv = tgt["variants"].setdefault(vk, {
                        "title": v["title"], "sku": v["sku"], "orders": 0, "quantity": 0,
                    })
                    tv["orders"] += v["orders"]
                    tv["quantity"] += v["quantity"]

        # Last orders hold fewer distinct products than ordinary orders, which
        # shrinks every product's share alike and would park the typical
        # product near 0.5x. Rescale per store so 1.0x means "typical".
        exp_raw_total = 0.0
        exp_adj_total = 0.0
        expected: Dict[Any, Dict[str, float]] = {}
        for key in merged:
            e_raw = 0.0
            e_adj = 0.0
            seen_base = 0
            for ps in per_store:
                if not ps["n_base"]:
                    continue
                share = (ps["base_products"].get(key, {}).get("orders", 0)) / ps["n_base"]
                seen_base += ps["base_products"].get(key, {}).get("orders", 0)
                e_raw += ps["n_lost"] * share
                ratio = (ps["avg_base"] / ps["avg_last"]) if ps["avg_last"] else 1.0
                e_adj += ps["n_lost"] * share / (ratio or 1.0)
            expected[key] = {"raw": e_raw, "adj": e_adj, "base_orders": seen_base}
            exp_raw_total += e_raw
            exp_adj_total += e_adj

        products = []
        for key, entry in merged.items():
            exp = expected.get(key) or {"raw": 0.0, "adj": 0.0, "base_orders": 0}
            pct_lost = (entry["orders"] / n_last * 100) if n_last else 0.0
            # The share this product WOULD have if lost customers behaved like
            # their own store's ordinary orders. Displayed so lift stays
            # checkable: lift_raw == pct_lost / pct_expected.
            pct_expected = (exp["raw"] / n_last * 100) if n_last else 0.0
            # Suppress rather than fabricate: a ratio built on 4 orders is
            # noise, and a zero expectation is not infinity.
            lift = None
            lift_raw = None
            if entry["orders"] >= _LIFT_MIN_ORDERS and exp["raw"] > 0 and exp["adj"] > 0:
                lift_raw = round(entry["orders"] / exp["raw"], 2)
                lift = round(entry["orders"] / exp["adj"], 2)
            products.append({
                "key": entry["key"],
                "product_id": entry["product_id"],
                "title": entry["title"],
                "deleted": entry["deleted"],
                "orders": entry["orders"],
                "pct_lost": round(pct_lost, 2),
                "quantity": entry["quantity"],
                "baseline_orders": exp["base_orders"],
                "pct_base": round(pct_expected, 2),
                "lift": lift,
                "lift_raw": lift_raw,
                "only_in_lost": exp["base_orders"] == 0 and n_base > 0,
                "variants": sorted(
                    entry["variants"].values(), key=lambda v: -v["orders"]
                )[:25],
            })

        avg_last = (
            sum(ps["avg_last"] * ps["n_lost"] for ps in per_store) / n_last
        ) if n_last else 0.0
        avg_base = (
            sum(ps["avg_base"] * ps["n_base"] for ps in per_store) / n_base
        ) if n_base else 0.0
        basket_ratio = (exp_raw_total / exp_adj_total) if exp_adj_total else 1.0

        products.sort(key=lambda p: (-p["orders"], p["title"].lower()))

        payload = {
            "products": products,
            "totals": {
                "last_orders_analysed": n_last,
                "baseline_orders_sampled": n_base,
                "orders_missing": missing,
                "orders_truncated": truncated,
                "distinct_products": len(products),
                "excluded_addon_lines": excluded_lines_total,
                "excluded_terms": list(_EXCLUDED_PRODUCT_TERMS),
                "lift_min_orders": _LIFT_MIN_ORDERS,
                "avg_products_last": round(avg_last, 2),
                "avg_products_baseline": round(avg_base, 2),
                "basket_ratio": round(basket_ratio, 2),
            },
            "stores": [{
                "store_id": (r.get("store") or {}).get("id"),
                "store_name": (r.get("store") or {}).get("name"),
                "ok": r.get("ok"),
                "error": r.get("error"),
                "analysed": len((r.get("last") or {}).get("orders") or []),
                "baseline": len((r.get("baseline") or {}).get("orders") or []),
            } for r in results],
        }
        yield f"event: complete\ndata: {json.dumps(payload)}\n\n"

    async def generate_safe() -> AsyncGenerator[str, None]:
        try:
            async for event in generate():
                yield event
        except GeneratorExit:
            print("[SHOPIFY-ANALYTICS] Lost-products stream cancelled")
            return

    return StreamingResponse(
        generate_safe(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )



if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
