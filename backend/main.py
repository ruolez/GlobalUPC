from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Union, AsyncGenerator, Optional, Dict, Any, Tuple, Set, Literal
from pydantic import BaseModel
from contextlib import asynccontextmanager
from datetime import datetime, date, timedelta, timezone
import uvicorn
import asyncio
import bisect
import time
import calendar
import json
import math
import statistics
import uuid
import os

from database import get_db, engine
from shopify_oauth_helper import fetch_client_credentials_token, apply_token
from models import Store, MSSQLConnection, ShopifyConnection, Setting, StoreType, StoreCategory, UPCUpdateHistory, UPCExclusion, ItemTrackerConfig, ItemTrackerExclusion, PriceUpdateHistory, StoreMirror, SalesConfig, SalesExclusion, BusinessOverviewConfig, BusinessOverviewShopifyExclusion, BusinessOverviewPoProductExclusion
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
    ShopifySyncRequest,
    CheckedOrderUser, CheckedOrdersUsersResponse,
    BOV_DEFAULT_QUOTATION_STATUSES,
    BusinessOverviewConfigCreate, BusinessOverviewConfigResponse, BusinessOverviewConfigOptions,
    BOVStoreOption, BOVPeriod, BOVBlockStatus, BOVSeriesPoint, BOVRangeTotals,
    BOVQuotationRow, BOVQuotationStatusCount, BOVQuotationsBlock, BOVQuotationsResponse,
    BOVInvoiceRow, BOVOpenInvoicesBlock, BOVOpenInvoicesResponse,
    BOVShippedInvoicesBlock, BOVShippedInvoicesResponse,
    BOVInvoiceLine, BOVInvoiceHeader, BOVInvoiceDetailResponse,
    BOVPurchaseOrderRow, BOVIncomingPurchasesBlock, BOVIncomingPurchasesResponse,
    BOVPurchasesRangeBlock, BOVPurchasesRangeResponse,
    BOVPurchaseOrderLine, BOVPurchaseOrderHeader, BOVPurchaseOrderDetailResponse,
    BOVPlacedPurchasesBlock, BOVPlacedPurchasesResponse,
    BOVSalesSourceTotals, BOVSalesBucket, BOVSalesSourceStatus, BOVSalesTrendResponse,
    BOVBreakdownRow, BOVSalesBreakdownResponse, BOVStoreStatus, BOVInvoicesPeriodResponse, BOVAlert, BOVAlertAction, BOVAlertsResponse, BOVShopifyOrderRow, BOVShopifyOrdersListResponse, BOVShopifyOrderLine, BOVShopifyOrderHeader, BOVShopifyOrderDetailResponse, BOVMissingCostRow, BOVMissingCostResponse, BOVProductRow, BOVProductsTotals, BOVProductsResponse, BOVShopifyExclusionCreate, BOVShopifyExclusion, BOVShopifyExclusionList, BOVPoExclusionCreate, BOVPoExclusion, BOVPoExclusionList, bov_merge_alert_rules, bov_validate_alert_rules, BOVShopifyStoreOrders, BOVShopifyOrdersResponse, BOVShopifyRefreshResult, BOVShopifyRefreshResponse,
    BOVShopifyStoreOpen, BOVShopifyOpenOrdersBlock, BOVSalesSummaryBlock,
    BusinessOverviewSummaryResponse,
    MonthEndRow, MonthEndTotals, MonthEndStoreStatus, MonthEndShipperStatus, MonthEndResponse,
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
    fetch_fulfilled_orders, fetch_variant_prices,
    fetch_orders_with_tag, fetch_customer_orders_after,
    count_fulfillment_buckets_for_store,
    fetch_customers_with_last_order, fetch_customer_recent_orders,
    fetch_orders_line_items, fetch_baseline_order_items, count_orders,
    fetch_customer_first_orders, fetch_customers_by_emails, normalize_email,
    fetch_customers_by_name, name_key, normalize_zip,
    fetch_shop_timezone, local_date, shop_today,
    fetch_earliest_customer_date, shopify_bucket_rate,
    ORDER_STATUS_FILTER, ANALYSIS_ORDER_FILTER, order_window_filter
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
    from shopify_oauth_helper import token_refresh_loop
    oauth_refresh_task = asyncio.create_task(token_refresh_loop())
    yield
    print("[SHUTDOWN] Cancelling Shopify OAuth token refresh loop...")
    oauth_refresh_task.cancel()
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
    print("[SHUTDOWN] Shutting down Shopify Sync thread pool...")
    from shopify_sync_helper import shutdown_sync_executor
    shutdown_sync_executor()
    print("[SHUTDOWN] Shutting down Business Overview thread pool...")
    from business_overview_helper import shutdown_bov_executor
    shutdown_bov_executor()
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
    auth_method: Literal["token", "client_credentials"] = "token"
    admin_api_key: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    api_version: str = "2025-01"
    store_id: Optional[int] = None  # edit mode: fall back to stored credentials

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
def test_shopify(connection: ShopifyConnectionTest, db: Session = Depends(get_db)):
    """Test Shopify store connection (Admin API token or OAuth client credentials)"""
    stored = None
    if connection.store_id is not None:
        store = db.query(Store).filter(Store.id == connection.store_id).first()
        stored = store.shopify_connection if store else None

    if connection.auth_method == "client_credentials":
        client_id = connection.client_id or (stored.client_id if stored else None)
        client_secret = connection.client_secret or (stored.client_secret if stored else None)
        if not client_id or not client_secret:
            return {"success": False, "message": "Client ID and client secret are required"}
        ok, error, token_data = fetch_client_credentials_token(
            connection.shop_domain, client_id, client_secret
        )
        if not ok:
            return {"success": False, "message": error or "OAuth token request failed"}
        access_token = token_data["access_token"]
        suffix = " OAuth token issued (valid ~24h)."
    else:
        access_token = connection.admin_api_key or (stored.admin_api_key if stored else None)
        if not access_token:
            return {"success": False, "message": "Admin API key is required"}
        suffix = ""

    success, error, shop_info = test_shopify_connection(
        shop_domain=connection.shop_domain,
        admin_api_key=access_token,
        api_version=connection.api_version
    )

    if success:
        return {
            "success": True,
            "message": f"Connection successful! Connected to: {shop_info.get('name', 'Unknown')}.{suffix}",
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

    # OAuth mode: validate credentials by fetching a token up front
    token_data = None
    if store_data.connection.auth_method == "client_credentials":
        ok, error, token_data = fetch_client_credentials_token(
            store_data.connection.shop_domain,
            store_data.connection.client_id,
            store_data.connection.client_secret,
        )
        if not ok:
            raise HTTPException(status_code=400, detail=f"OAuth token request failed: {error}")

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
        auth_method=store_data.connection.auth_method,
        admin_api_key=store_data.connection.admin_api_key,
        client_id=store_data.connection.client_id,
        client_secret=store_data.connection.client_secret,
        api_version=store_data.connection.api_version,
        update_sku_with_barcode=store_data.connection.update_sku_with_barcode
    )
    if token_data:
        apply_token(connection, token_data)
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
    prev_auth_method = conn.auth_method
    conn.shop_domain = store_data.connection.shop_domain
    conn.api_version = store_data.connection.api_version
    conn.update_sku_with_barcode = store_data.connection.update_sku_with_barcode
    conn.auth_method = store_data.connection.auth_method

    if store_data.connection.auth_method == "client_credentials":
        conn.client_id = store_data.connection.client_id
        if store_data.connection.client_secret:  # only overwrite when provided
            conn.client_secret = store_data.connection.client_secret
        if not conn.client_secret:
            raise HTTPException(status_code=400, detail="Client secret is required")
        ok, error, token_data = fetch_client_credentials_token(
            conn.shop_domain, conn.client_id, conn.client_secret
        )
        if not ok:
            raise HTTPException(status_code=400, detail=f"OAuth token request failed: {error}")
        apply_token(conn, token_data)  # ignore any admin_api_key in the payload: it's the cache
    else:
        if store_data.connection.admin_api_key:  # only overwrite when provided
            conn.admin_api_key = store_data.connection.admin_api_key
        elif prev_auth_method == "client_credentials":
            # blank key would silently keep the cached 24h OAuth token
            raise HTTPException(status_code=400, detail="Admin API key is required when switching to token auth")
        conn.client_id = None
        conn.client_secret = None
        conn.token_expires_at = None

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
                    "auth_method": store.shopify_connection.auth_method,
                    "admin_api_key": store.shopify_connection.admin_api_key,
                    "client_id": store.shopify_connection.client_id,
                    "client_secret": store.shopify_connection.client_secret,
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
                auth_method=store_data.connection.get("auth_method", "token"),
                admin_api_key=store_data.connection.get("admin_api_key"),
                client_id=store_data.connection.get("client_id"),
                client_secret=store_data.connection.get("client_secret"),
                api_version=store_data.connection.get("api_version", "2025-01"),
                update_sku_with_barcode=store_data.connection.get("update_sku_with_barcode", False)
            )
            # OAuth: best-effort token fetch now; the background refresh loop
            # picks up any failure (token_expires_at stays NULL => due).
            if connection.auth_method == "client_credentials" and connection.client_id and connection.client_secret:
                ok, _err, token_data = fetch_client_credentials_token(
                    connection.shop_domain, connection.client_id, connection.client_secret
                )
                if ok:
                    apply_token(connection, token_data)
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

        use_local = request.use_local_data
        data_source = "local" if use_local else "live"
        skipped_names = []
        if use_local:
            # Stores without a completed sync are skipped, never silently
            # routed to the live API — the checkbox means "no live order pull".
            synced_map = await asyncio.to_thread(shopify_sync.get_synced_stores)
            for sid in list(store_map):
                if sid not in synced_map:
                    skipped_names.append(store_map.pop(sid)["name"])

        all_line_items = []
        total_stores = len(store_map)

        yield f"event: progress\ndata: {json.dumps({'status': 'started', 'total_stores': total_stores, 'data_source': data_source})}\n\n"

        for name in skipped_names:
            yield f"event: progress\ndata: {json.dumps({'status': 'skipped_store', 'store_name': name, 'message': 'Not synced — skipped in local data mode'})}\n\n"

        for s in store_map.values():
            yield f"event: progress\ndata: {json.dumps({'status': 'searching_store', 'store_name': s['name'], 'data_source': data_source})}\n\n"

        async def fetch_store_orders(store_info):
            return store_info, await fetch_fulfilled_orders(
                shop_domain=store_info["shop_domain"],
                admin_api_key=store_info["admin_api_key"],
                start_date=start_date,
                end_date=end_date,
                api_version=store_info["api_version"]
            )

        async def fetch_store_orders_local(store_info):
            success, error, line_items = await shopify_sales_local.fetch_fulfilled_orders_local(
                store_info["id"], start_date, end_date
            )
            if success and line_items:
                # Today's Price is the one live value: the mirror has no
                # products table. A failed lookup leaves it None for this
                # store; the report itself still completes.
                variant_ids = {i["variant_shopify_id"] for i in line_items if i.get("variant_shopify_id")}
                ok, _, price_map = await fetch_variant_prices(
                    shop_domain=store_info["shop_domain"],
                    admin_api_key=store_info["admin_api_key"],
                    variant_ids=list(variant_ids),
                    api_version=store_info["api_version"],
                )
                if ok:
                    for item in line_items:
                        item["today_price"] = price_map.get(item.get("variant_shopify_id"))
            return store_info, (success, error, line_items)

        fetch_fn = fetch_store_orders_local if use_local else fetch_store_orders
        tasks = [asyncio.create_task(fetch_fn(s)) for s in store_map.values()]
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
                    "today_price": None,
                    "currency": currency
                }

            aggregated[key]["total_quantity"] += qty
            aggregated[key]["total_revenue"] += price * qty
            if not aggregated[key]["sku"] and item.get("sku"):
                aggregated[key]["sku"] = item["sku"]
            if not aggregated[key]["product_title"] and product_title:
                aggregated[key]["product_title"] = product_title
            if item.get("today_price") is not None:
                aggregated[key]["today_price"] = item["today_price"]

        results = []
        for entry in aggregated.values():
            qty = entry["total_quantity"]
            revenue = entry["total_revenue"]
            avg_price = f"{(revenue / qty):.2f}" if qty > 0 else "0.00"
            variant_display = "" if entry["variant_title"] == "Default Title" else entry["variant_title"]
            today_price = entry["today_price"]
            try:
                today_price = f"{float(today_price):.2f}" if today_price is not None else None
            except (TypeError, ValueError):
                today_price = None
            results.append({
                "store_name": entry["store_name"],
                "product_title": entry["product_title"],
                "variant_title": variant_display,
                "barcode": entry["barcode"],
                "sku": entry["sku"],
                "avg_price": avg_price,
                "today_price": today_price,
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
                                    real_cost_val = prices_map[bc].get("unit_cost")
                                    r["real_cost"] = f"{real_cost_val:.2f}" if real_cost_val is not None else None
                                else:
                                    r["cost"] = None
                                    r["real_cost"] = None
                        else:
                            for r in results:
                                r["cost"] = None
                                r["real_cost"] = None
                    else:
                        for r in results:
                            r["cost"] = None
                            r["real_cost"] = None
                else:
                    for r in results:
                        r["cost"] = None
                        r["real_cost"] = None
            except Exception:
                for r in results:
                    r["cost"] = None
                    r["real_cost"] = None
        else:
            for r in results:
                r["cost"] = None
                r["real_cost"] = None

        def markup_pct(price_str, cost_str):
            if price_str is None or cost_str is None:
                return None
            try:
                price_val = float(price_str)
                cost_val = float(cost_str)
            except (TypeError, ValueError):
                return None
            if cost_val <= 0:
                return None
            return f"{((price_val - cost_val) / cost_val * 100):.1f}"

        for r in results:
            r["profit_margin"] = markup_pct(r.get("today_price"), r.get("real_cost"))
            r["avg_margin"] = markup_pct(r.get("avg_price"), r.get("cost"))

        total_quantity = sum(r["total_quantity"] for r in results)
        total_revenue = sum(float(r["total_revenue"]) for r in results)

        yield f"event: complete\ndata: {json.dumps({'results': results, 'summary': {'total_items': len(results), 'total_quantity': total_quantity, 'total_revenue': f'{total_revenue:.2f}', 'total_shipping': f'{total_shipping:.2f}', 'stores_searched': len(store_map), 'date_range': {'start': start_date, 'end': end_date}, 'excluded_products': excluded_products, 'excluded_total_revenue': f'{excluded_total_revenue:.2f}', 'excluded_total_quantity': excluded_total_quantity, 'data_source': data_source, 'skipped_stores': skipped_names}})}\n\n"

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


def _shift_months(day: str, months: int) -> str:
    """
    `day` shifted by N calendar months — negative goes back.

    The day of month is clamped rather than allowed to overflow: one month
    before 2026-03-31 is 2026-02-28, not a ValueError. Output is always
    zero-padded ISO, which is load-bearing — every window decision in the lost
    customers report is a string comparison, so "2026-2-28" would sort after
    "2026-12-31" and compare wrong instead of failing.
    """
    y, m, d = int(day[0:4]), int(day[5:7]), int(day[8:10])
    # Month index from year 0, so the arithmetic works either direction without
    # a separate negative case.
    total = y * 12 + (m - 1) + months
    y2, m2 = divmod(total, 12)
    m2 += 1
    return f"{y2:04d}-{m2:02d}-{min(d, calendar.monthrange(y2, m2)[1]):02d}"


def _minus_months(day: str, months: int) -> str:
    return _shift_months(day, -months)


def _plus_months(day: str, months: int) -> str:
    return _shift_months(day, months)


def _month_end_exclusive(month_key: str) -> str:
    """First day of the month after `month_key` — an exclusive upper bound."""
    return _plus_months(f"{month_key}-01", 1)


def _days_between(start_day: str, end_day: str) -> Optional[int]:
    """Whole days from `start_day` to `end_day`, or None if either is unusable."""
    try:
        return (date.fromisoformat(end_day) - date.fromisoformat(start_day)).days
    except (ValueError, TypeError):
        return None


def _by_month_spine(lost_by_month: Dict[str, int], new_by_month: Dict[str, int],
                    through_month: str) -> List[str]:
    """
    Continuous month keys covering both series, extended to `through_month`.

    The extension matters: departures stop at the silence cutoff by definition,
    so without it a run whose arrivals series is empty or short would end the
    chart at the cutoff and the "too recent to judge" zone — the thing that
    explains why departures stop — would have no months to be drawn over.
    """
    keys = set(lost_by_month) | set(new_by_month)
    if not keys:
        return []
    return _month_spine(f"{min(keys)}-01", f"{max(max(keys), through_month)}-01")


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
                    # An order that was cancelled or fully refunded did not
                    # acquire anyone, so it must not count as a new customer.
                    exclude_cancelled=True,
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

# The scan is latency-bound, not rate-limited: a 250-customer page costs 57-90
# points against a 20,000 bucket refilling at 1,000/s, and takes ~1.5s. Wall
# clock is therefore (pages per cursor) x 1.5s, and the only lever is running
# more cursors — provided the slices do not overlap.
#
# Splitting the ORDER-date window does overlap, badly: a customer who ordered in
# several windows is fetched from each. Measured on a 17,732-customer store,
# duplication rose 1.97x -> 3.35x -> 5.15x at 3, 6 and 10 shards while pages per
# shard only fell 47 -> 40 -> 37. Adding shards there buys almost nothing.
#
# Splitting by CUSTOMER CREATION date partitions instead: every customer has
# exactly one, so nobody is fetched twice. Same store, same 17,732 customers:
# 8 shards ran 47.1s and 16 ran 24.5s at 1.01x duplication, against 78-195s for
# the old 3-way order-date split.
_LOST_MAX_CONCURRENCY = 16
_LOST_MIN_CONCURRENCY = 2
# Ranges outnumber cursors on purpose. Equal date spans do not match how a
# store grew, so with one range per cursor the deepest range decides the wall
# clock: measured, half the cursors finished in the first 27% of the time and
# one ground on alone for the rest. Cutting the same history into finer ranges
# and feeding them through a bounded pool splits the dense period across
# several cursors instead.
#
# Simulated against the measured distribution (concurrency 16): 16 ranges took
# 9.1s with a 15-page deepest range; 64 took 4.2s with 4 pages; 128 took 5.4s,
# where the per-range request cost starts to outweigh the parallelism.
#
# The count used to follow concurrency — `min(_LOST_MAX_RANGES, conc)` — which
# was one range per cursor, i.e. exactly the failure mode the paragraph above
# says was measured and rejected, and it made this ceiling unreachable. It is
# now driven by the store's history instead, because with the from-date optional
# the binding constraint is Shopify's 25,000-object pagination ceiling, which is
# a property of how many customers sit in a date slice rather than of how fast
# the shop's bucket refills. On the 200/s shop that costs some wall clock
# (measured 16.9s -> 20.5s going 16 -> 64 on a two-year window); truncating its
# history instead is not a trade worth making.
_RANGES_PER_CURSOR = 4
_LOST_MAX_RANGES = 256
# Target width of one range. Fine enough that a slice of a normal store's
# history stays well under the object cap, wide enough not to fragment.
_LOST_RANGE_TARGET_DAYS = 45
# Pages one cursor walks before handing the rest of its range back to be split.
# Low enough that a dense range is noticed early, high enough that a normal
# range finishes in one go and costs nothing extra.
_SCAN_PAGE_BUDGET = 4
# Splitting is bounded so a pathological range cannot recurse forever; at the
# limit the range is simply walked to the end.
#
# This — not the initial range count — is what actually defeats the object cap:
# a resumed child issues a NEW query over a narrower creation-date range, so it
# starts a fresh cursor chain with a fresh 25,000-object budget. At depth 4 with
# _RANGES_PER_CURSOR=4 that is 256x subdivision before any walk runs unbounded.
_SCAN_MAX_SPLIT_DEPTH = 4
# Balancing the ranges by volume would be better still, but is not possible:
# `customersCount` ignores its query filter and saturates at 10,000 AT_LEAST,
# so every range reports the same number.
#
# Below this a range is too thin to be worth its round trip, and a young store
# would otherwise fragment into one range per day.
_LOST_RANGE_MIN_DAYS = 3
# One page's cost, and how long it takes. Together these say how many cursors a
# shop's refill rate can sustain: rate * seconds / cost.
_SCAN_PAGE_COST = 90.0
_SCAN_PAGE_SECONDS = 1.5

# Departures per cross-store section. The email and name+ZIP passes used to run
# once over the whole departure list, which made their cost and their failures
# both unbounded: one failed probe disqualified the entire store's comparison,
# and the name pass was skipped outright above _ARRIVAL_NAME_MAX_CANDIDATES.
# Sectioning does not reduce the number of API calls — 25,000 emails is ~125
# batches of 200 either way — it bounds memory, localizes failure to one
# section, lets results stream as they are confirmed, and gives the
# departure-relative moved window a date range to bound its query by.
#
# Deliberately equal to _ARRIVAL_NAME_MAX_CANDIDATES: a section larger than the
# cap would still trip it, which is the thing being fixed.
_CROSS_SECTION_SIZE = 1500
# And no wider than this many months, whatever the volume. The section's date
# span becomes the bound on its in-window order query, and that query returns
# only the first _MOVED_WINDOW_ORDERS matches — so a wide section asks about
# orders from years before the departure it is judging.
#
# Measured: a store with 396 departures spread over three years fitted in ONE
# section, giving a 42-month window. For anyone still buying at a sister shop the
# five orders returned were all from the far end of that window, none inside the
# customer's own six-month test period, so the verdict came back "unknown" — for
# exactly the customers the check exists to find. A one-month span keeps the
# window tight enough that only a genuinely heavy concurrent buyer can saturate
# it, and that case is still reported rather than guessed.
_CROSS_SECTION_MAX_MONTHS = 1
# Sections in flight. Sections of the same store compete for the same shops'
# rate buckets, so this stays modest — the parallelism that matters is the
# per-shop fan-out inside a section. Raised with the span cap, which makes
# sections smaller and more numerous on a sparse store.
_CROSS_SECTION_CONCURRENCY = 4
# Rows per streamed `rows` event. Measured before this existed: a full-history
# run on one store produced a single 64.6 MB SSE line, which the browser has to
# buffer and JSON.parse in one go.
_ROWS_EVENT_CHUNK = 500

# Queue kinds that are their own SSE event rather than a `progress` phase.
# Everything else the workers publish is reported as progress; only "done"
# finishes a store. See the dispatcher for why this is a map and not a whitelist.
_LOST_EVENT_NAMES = {"rows": "rows"}

# Fields a departure row carries to the browser. The full record holds ~30 keys
# including the name parts, ZIPs and tracking URL that nothing renders; on a
# 65,000-departure run that padding was most of a 64 MB payload.
#
# Every field here is read by the UI, so removing one silently breaks a feature
# rather than erroring: last_order_id feeds the Top Products drill,
# orders_count_all/_exact the adjusted-count badge, state_name/country the
# per-month state column, shipping_method_raw the method tooltip, and
# days_to_fulfil/days_to_deliver both the table and the slow-order filter.
_LOST_ROW_FIELDS = (
    "customer_id", "name", "email", "state", "state_name", "country",
    "orders_count", "orders_count_all", "orders_count_exact",
    "amount_spent", "currency", "first_order_local", "last_order_local",
    "last_order_name", "last_order_id", "days_silent",
    "days_to_fulfil", "days_to_deliver", "shipping_method", "shipping_method_raw",
    "carrier",
)
# Only on the ones that moved, and only what the moved modal shows.
_MOVED_ROW_FIELDS = _LOST_ROW_FIELDS + (
    "moved_to_store", "moved_to_store_name", "moved_same_store",
    "moved_matched_by", "moved_last_order",
)


def _trim_row(c: Dict[str, Any], fields=_LOST_ROW_FIELDS) -> Dict[str, Any]:
    """One departure, reduced to what the browser actually renders."""
    return {k: c.get(k) for k in fields}


#: A move was proven, a move was ruled out, or the evidence ran out.
_MOVE_YES, _MOVE_NO, _MOVE_UNKNOWN = "yes", "no", "unknown"


def _judge_move(quiet_day: str, months: int, other_last: Optional[str],
                window_days: Optional[List[str]], saturated: bool) -> str:
    """
    Did this person buy at the other shop within `months` of going quiet here?

    Layered so that the cheap, exact signals decide almost every case and the
    only fallible one is consulted last:

    1. Their last-ever order at the other shop predates their departure here, so
       there can be nothing inside the window. Exact.
    2. That last order is itself inside the window. Exact.
    3. Otherwise they are still active there but later than the window, so the
       question is whether they ALSO bought during it. That is what the bounded
       in-window list answers — and if it saturated, the honest answer is
       "unknown", which the caller keeps as lost and reports.

    The lower bound is inclusive: an order elsewhere on the same day as their
    last order here is precisely the switch this is looking for.
    """
    if not other_last:
        return _MOVE_NO
    horizon = _plus_months(quiet_day, months)
    if other_last < quiet_day:
        return _MOVE_NO
    if other_last < horizon:
        return _MOVE_YES
    if any(quiet_day <= d < horizon for d in (window_days or ())):
        return _MOVE_YES
    return _MOVE_UNKNOWN if saturated else _MOVE_NO


def _departure_sections(rows: List[Dict[str, Any]], size: int = _CROSS_SECTION_SIZE,
                        newest_first: bool = True,
                        max_months: int = _CROSS_SECTION_MAX_MONTHS) -> List[Dict[str, Any]]:
    """
    Volume-sized, month-contiguous chunks of departures.

    Volume is what bounds cost — the cross-store passes scale with the number of
    departures, not with the calendar — while month contiguity is what lets one
    `created_at` bound serve a whole section. Whole months are never split across
    sections unless a single month is bigger than one section, in which case its
    parts share that month's window and the window stays as tight as possible.

    Newest first by default: the recent months are the actionable ones, so they
    should reach the screen first. Order is otherwise fixed, so cross-store
    attribution cannot vary between runs of the same report.

    Returns [{"rows": [...], "months": (lo_key, hi_key)}].
    """
    by_month: Dict[str, List[Dict[str, Any]]] = {}
    for c in rows:
        by_month.setdefault((c.get("last_order_local") or "")[:7], []).append(c)

    chunks: List[tuple] = []
    current: List[Dict[str, Any]] = []
    current_months: List[str] = []

    def flush():
        if current:
            chunks.append((list(current), list(current_months)))
            current.clear()
            current_months.clear()

    for m in sorted((k for k in by_month if k), reverse=newest_first):
        rows_m = by_month[m]
        if len(rows_m) >= size:
            # Big enough to be its own section (or several).
            flush()
            for i in range(0, len(rows_m), size):
                chunks.append((rows_m[i:i + size], [m]))
            continue
        # Cut on volume OR on span — whichever comes first. The span cap is what
        # keeps the in-window order query narrow enough to answer the question it
        # is asked; see _CROSS_SECTION_MAX_MONTHS.
        if current and (len(current) + len(rows_m) > size
                        or len(current_months) >= max_months):
            flush()
        current.extend(rows_m)
        current_months.append(m)
    flush()

    out = [{"rows": rws, "months": (min(ms), max(ms))} for rws, ms in chunks]
    # Unreachable for a departure — classification needs last_order_local — but a
    # row without one must not be silently dropped from the check.
    undated = by_month.get("")
    if undated:
        out.append({"rows": undated, "months": None})
    return out


def _scan_concurrency_for_rate(restore_rate: Optional[float]) -> int:
    """
    How many cursors this shop's refill rate can feed at once.

    Rate-limit budgets differ five-fold across shops here (1,000/s on most,
    200/s on one), so a constant would either throttle the small shop or waste
    the large ones. Unknown rate falls back to the floor.
    """
    if not restore_rate or restore_rate <= 0:
        return _LOST_MIN_CONCURRENCY
    sustainable = int(restore_rate * _SCAN_PAGE_SECONDS / _SCAN_PAGE_COST)
    return max(_LOST_MIN_CONCURRENCY, min(_LOST_MAX_CONCURRENCY, sustainable))


def _lost_shards(earliest_customer: Optional[str], upper: str,
                 max_ranges: int = _LOST_MAX_RANGES) -> List[tuple]:
    """
    Partition [earliest_customer, upper] into contiguous CREATION-date ranges.

    Returns (created_start, created_end) pairs. Both ends are deliberately
    open: the last range has no upper bound so a record created today is still
    caught, and the FIRST has no lower bound so nothing older than the floor can
    be missed. That matters because the floor is a UTC date while
    `customer_date:` filters on the shop's local date — a shop whose oldest
    record was created between midnight and dawn UTC would otherwise have that
    record, and everyone else created that local day, silently excluded.

    Without an earliest date the caller gets one unbounded walk; guessing a
    floor would drop every customer created before it.
    """
    from datetime import date, timedelta

    if not earliest_customer:
        return [(None, None)]
    try:
        start = date.fromisoformat(earliest_customer)
        end = date.fromisoformat(upper)
    except ValueError:
        return [(None, None)]

    span = (end - start).days
    if span < _LOST_RANGE_MIN_DAYS * 2:
        return [(None, None)]

    # Driven by the store's own history, not by how many cursors the shop's rate
    # can feed: the range count exists to keep each cursor walk under Shopify's
    # object cap, and that depends on how many customers sit in a date slice.
    # `max_ranges` is a ceiling, `_LOST_RANGE_MIN_DAYS` a floor on width.
    n = max(2, min(max_ranges,
                   span // _LOST_RANGE_MIN_DAYS,
                   math.ceil(span / _LOST_RANGE_TARGET_DAYS)))
    step = span // n
    bounds = [start + timedelta(days=step * i) for i in range(n)] + [end]
    return [
        (
            bounds[i].isoformat() if i > 0 else None,
            bounds[i + 1].isoformat() if i < n - 1 else None,
        )
        for i in range(n)
    ]


def _split_dates(lo: str, hi: Optional[str], upper: str, parts: int) -> List[tuple]:
    """
    Cut [lo, hi) into `parts` contiguous ranges, preserving an open upper end.

    `upper` stands in for `hi` when the range is open-ended, so the tail of the
    store's history can still be divided; the final part keeps `hi` verbatim so
    records created after `upper` are never fenced out.
    """
    from datetime import date, timedelta

    try:
        start = date.fromisoformat(lo)
        end = date.fromisoformat(hi or upper)
    except ValueError:
        return []
    span = (end - start).days
    if span < _LOST_RANGE_MIN_DAYS * 2:
        return []
    n = max(2, min(parts, span // _LOST_RANGE_MIN_DAYS))
    step = span // n
    bounds = [start + timedelta(days=step * i) for i in range(n)] + [end]
    return [
        (bounds[i].isoformat(), bounds[i + 1].isoformat() if i < n - 1 else hi)
        for i in range(n)
    ]


def _bump_moved(breakdown: Dict[Any, Dict[str, Any]], key: Any, label: str) -> None:
    """
    Tally one customer against the shop they moved to, keyed by shop rather
    than by display name — two shops can share a name, and merging them would
    misattribute the move. The label rides along for display.
    """
    entry = breakdown.setdefault(key, {"label": label, "count": 0})
    entry["count"] += 1


def _record_move(c: Dict[str, Any], store_id: Any, label: str, store_name: str,
                 dest_last_order: Optional[str], matched_by: str,
                 same_store: bool = False) -> None:
    """
    Stamp a customer with where they went, so the move can be listed and not
    merely counted. Both dates are shop-local, but each in its OWN shop's
    calendar — they are events at different businesses.

    `label` is the display string (which may say "another account");
    `store_name` is the bare shop name, so a table column does not have to
    parse a suffix back out of the label to stay narrow.
    """
    c["moved_to_store"] = label
    c["moved_to_store_name"] = store_name
    c["moved_to_store_id"] = store_id
    c["moved_same_store"] = same_store
    c["moved_last_order"] = dest_last_order
    c["moved_matched_by"] = matched_by


# --- arrivals: where the newly-acquired customers came from -----------------
#
# The mirror of the moved-away check. "New" in this report means first COMPLETED
# order inside the window at this shop, which says nothing about whether the
# person was already a customer of the business somewhere else. Measured on one
# live store, only half of a 208-strong arrival cohort was new to the business.
#
# Verdicts are mutually exclusive and ordered by how much they matter:
_ARR_SWITCHED = "switched from another store"
_ARR_BOTH = "shops here and there"
_ARR_PRIOR_HERE = "already bought here under an earlier account"
_ARR_ACCOUNT_ONLY = "had an account, never bought there"
_ARR_EXPANDED = "started here, joined another store later"
_ARR_NEW = "new to the business"

# The name+ZIP pass costs up to _NAME_MAX_PAGES pages per 100-name batch at
# EVERY shop, so its cost is quadratic in a way the email pass is not. On a
# lost list of a few hundred that is fine; on an arrival cohort of tens of
# thousands it would be thousands of requests. Past this many unresolved
# people the pass is skipped and said so, rather than silently hanging.
_ARRIVAL_NAME_MAX_CANDIDATES = 1500

# The cohort can run to tens of thousands; only the ones that were not new are
# listed, and the browser renders a table of them, so the list is capped and the
# remainder reported as a count rather than quietly dropped.
_ARRIVAL_MAX_ROWS = 3000


def _classify_arrival(here: str, matches: List[Dict[str, Any]]) -> tuple:
    """
    Decide what one arrival really was, from their records at other shops.

    `here` is the shop-local day of their first completed order at this shop.
    Each match carries that other shop's own local `first`/`last` order days
    and its name. Returns (verdict, origin store name or None).
    """
    prior = [m for m in matches if m["first"] and m["first"] < here]
    if prior:
        # Where were they shopping immediately before turning up here? Only two
        # anchors per shop are fetched, so the best available answer is the
        # last order when that itself predates the arrival, and otherwise the
        # first order as a lower bound on their activity there.
        def anchor(m):
            return m["last"] if (m["last"] and m["last"] < here) else m["first"]
        origin = max(prior, key=lambda m: (anchor(m), m["store_name"]))
        if origin["same_store"]:
            # Not a move between stores at all: they were already buying here,
            # then re-registered, which is what made them look new.
            return _ARR_PRIOR_HERE, origin["store_name"]
        # Still buying there afterwards means they added us, not left them.
        kept_buying = any(m["last"] and m["last"] >= here for m in prior)
        return (_ARR_BOTH if kept_buying else _ARR_SWITCHED), origin["store_name"]
    # Past this point nothing predates their first purchase here, so a second
    # account at THIS store is not evidence of an earlier relationship — it was
    # opened later, or never used, and their first purchase anywhere really was
    # this one. Counting it would understate how many customers are genuinely
    # new, which is the number the whole modal exists to report.
    cross = [m for m in matches if not m["same_store"]]
    later = [m for m in cross if m["first"] and m["first"] >= here]
    if later:
        return _ARR_EXPANDED, min(later, key=lambda m: m["first"])["store_name"]
    if cross:
        # An account exists but has never completed an order there. Credit the
        # oldest one — that is the relationship that predates us.
        dated = [m for m in cross if m.get("account")] or cross
        return _ARR_ACCOUNT_ONLY, min(
            dated, key=lambda m: (m.get("account") or "", m["store_name"]))["store_name"]
    return _ARR_NEW, None


def _merge_arrivals(parts) -> Dict[str, Any]:
    """
    Collapse per-store arrival results into one. Empty when no store ran the
    check, which is how the client decides whether to offer the button at all.
    """
    live = [p for p in parts if p]
    if not live:
        return {}
    out: Dict[str, Any] = {
        "total": sum(p.get("total", 0) for p in live),
        "verdicts": {},
        "origins": {},
        "by_month": {},
        "prior_account": sum(p.get("prior_account", 0) for p in live),
        "no_email": sum(p.get("no_email", 0) for p in live),
        "rows": [],
        "rows_truncated": sum(p.get("rows_truncated", 0) for p in live),
        "errors": [e for p in live for e in (p.get("errors") or [])][:3],
    }
    for p in live:
        for k, v in (p.get("verdicts") or {}).items():
            out["verdicts"][k] = out["verdicts"].get(k, 0) + v
        for k, v in (p.get("origins") or {}).items():
            out["origins"][k] = out["origins"].get(k, 0) + v
        # Same merge, one level down. Stores share months, so a month's tallies
        # accumulate across every store that reported it.
        for month, e in (p.get("by_month") or {}).items():
            tgt = out["by_month"].setdefault(month, {"total": 0, "verdicts": {}, "origins": {}})
            tgt["total"] += e.get("total", 0)
            for k, v in (e.get("verdicts") or {}).items():
                tgt["verdicts"][k] = tgt["verdicts"].get(k, 0) + v
            for k, v in (e.get("origins") or {}).items():
                tgt["origins"][k] = tgt["origins"].get(k, 0) + v
        out["rows"].extend(p.get("rows") or [])
    out["rows"].sort(key=lambda r: r.get("amount_spent") or 0, reverse=True)
    if len(out["rows"]) > _ARRIVAL_MAX_ROWS:
        out["rows_truncated"] += len(out["rows"]) - _ARRIVAL_MAX_ROWS
        out["rows"] = out["rows"][:_ARRIVAL_MAX_ROWS]
    return out


def _merge_moved(breakdowns) -> Dict[str, int]:
    """Collapse per-store breakdowns to {label: count} for the client."""
    totals: Dict[Any, Dict[str, Any]] = {}
    for b in breakdowns:
        for key, entry in (b or {}).items():
            tgt = totals.setdefault(key, {"label": entry["label"], "count": 0})
            tgt["count"] += entry["count"]
    out: Dict[str, int] = {}
    for entry in totals.values():
        out[entry["label"]] = out.get(entry["label"], 0) + entry["count"]
    return out


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
        # Snapped to the first of its month, because this report is monthly and a
        # mid-month floor makes the first bar a fraction of a month drawn as a
        # whole one. With a floor of 2024-07-31 the July departure bar counted a
        # single day against its neighbours' 31 — measured, 29 against 711 — so
        # the month-over-month figure beside it read +2,352%.
        #
        # It also removes a units mismatch: departures were filtered by DAY while
        # the arrivals series bucketed by MONTH KEY, so the floor month's "new"
        # bar included the thirty pre-floor days that the arrivals cohort itself
        # excluded, and the two disagreed about the month they both described.
        history_from = request.history_from            # None = all history
        if history_from:
            history_from = f"{history_from[:7]}-01"
        silent_months = int(request.silent_months)
        moved_months = int(request.moved_within_months or silent_months)
        require_acquired = bool(request.require_acquired_in_window)
        min_orders = max(1, int(request.min_orders or 1))

        # There is no second date to order this against any more; the cutoff is
        # derived per shop below. What can still be contradictory is asking for
        # an acquisition window without giving it a floor.
        if require_acquired and not history_from:
            msg = ("Set a history start date, or turn off \"only customers acquired "
                   "in this window\" — the filter has no floor without one")
            yield f"event: error\ndata: {json.dumps({'message': msg})}\n\n"
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
        # Fixed order so that when two shops both match a customer, the one
        # credited with the move is the same on every run.
        all_shopify.sort(key=lambda s: s["id"])
        cross_store = bool(request.exclude_cross_store) and len(all_shopify) > 1
        # A single shop has nowhere for anyone to have come from by email, but
        # it can still hold an earlier account for the same person, so the
        # arrivals check is worth running even then.
        check_arrivals = bool(request.check_arrivals)

        # Shopify filters on each shop's local date, so every window comparison
        # has to be made in that shop's calendar — including the cross-store
        # ones, where the date being judged belongs to a different shop.
        # Resolved once here (and cached in the helper) rather than per store.
        # Concurrent: these are independent one-shot queries against different
        # shops, and serialising them added a second to every cold run.
        # Optional pre-run catch-up: every synced store pulls its Shopify
        # delta first, so the classification below runs on current data. Runs
        # BEFORE coverage is loaded — the refreshed mirror is what routes.
        # A store that fails or is mid-sync is noted and the report continues
        # on its last-synced data; freshness must not cost availability.
        if request.refresh_local_data:
            refresh_candidates = await asyncio.to_thread(shopify_sync.get_synced_stores)
            by_id_all = {s["id"]: s for s in (store_list + all_shopify)}
            refresh_ids = [sid for sid in by_id_all if sid in refresh_candidates]
            anchors: Dict[int, Any] = {}
            if refresh_ids:
                for r in db.execute(sa_text(
                    "SELECT store_id, last_sync_started_at FROM shopify_sync_state "
                    "WHERE store_id = ANY(:ids)"), {"ids": refresh_ids},
                ).mappings():
                    anchors[r["store_id"]] = r["last_sync_started_at"]
            refresh_targets = [by_id_all[sid] for sid in refresh_ids
                               if anchors.get(sid) is not None]

            async def refresh_one(sh: Dict[str, Any]) -> str:
                token = await asyncio.to_thread(
                    shopify_sync.claim_sync, sh["id"], "incremental")
                if token is None:
                    return f"{sh['name']}: skipped — a sync is already running"

                async def _quiet_emit(kind, payload):
                    return None

                try:
                    summary = await shopify_sync.run_store_sync(
                        dict(sh), "incremental", anchors[sh["id"]], _quiet_emit,
                        claim_token=token)
                    await asyncio.to_thread(
                        shopify_sync.release_sync, sh["id"],
                        counts=summary["totals"],
                        run_started=summary["run_started"], claim_token=token)
                    d = summary["synced"]
                    return (f"{sh['name']}: {d['orders']:,} order(s), "
                            f"{d['customers']:,} customer(s) updated")
                except asyncio.CancelledError:
                    asyncio.create_task(asyncio.to_thread(
                        shopify_sync.release_sync, sh["id"],
                        error="cancelled", claim_token=token))
                    raise
                except Exception as e:
                    await asyncio.to_thread(
                        shopify_sync.release_sync, sh["id"],
                        error=str(e)[:500], claim_token=token)
                    return (f"{sh['name']}: refresh failed "
                            f"({str(e)[:120]}) — using last synced data")

            if refresh_targets:
                yield f"event: progress\ndata: {json.dumps({'phase': 'refresh', 'detail': f'Syncing latest Shopify data for {len(refresh_targets)} store(s)…', 'done': 0, 'total': len(refresh_targets)})}\n\n"
                refresh_pending = {asyncio.create_task(refresh_one(sh))
                                   for sh in refresh_targets}
                refresh_done = 0
                try:
                    while refresh_pending:
                        done_set, refresh_pending = await asyncio.wait(
                            refresh_pending, timeout=10)
                        if not done_set:
                            yield ": heartbeat\n\n"
                            continue
                        for t in done_set:
                            refresh_done += 1
                            try:
                                note = t.result()
                            except Exception as e:
                                note = f"refresh failed: {str(e)[:120]}"
                            yield f"event: progress\ndata: {json.dumps({'phase': 'refresh', 'detail': note, 'done': refresh_done, 'total': len(refresh_targets)})}\n\n"
                except (GeneratorExit, asyncio.CancelledError):
                    for t in refresh_pending:
                        t.cancel()
                    raise

        # Which stores have a completed local sync. Those are served from
        # PostgreSQL (scan, first orders, cross-store probes); the rest use the
        # live API exactly as before, so partial coverage degrades per store
        # rather than per report.
        synced_map = await asyncio.to_thread(shopify_sync.get_synced_stores)
        local_ids = {sid for sid in synced_map}

        tz_shops = list({s["id"]: s for s in (store_list + all_shopify)}.values())
        # Synced shops carry the timezone captured at sync time, so a local run
        # does not depend on the Shopify API being reachable at all.
        tz_by_shop: Dict[int, Optional[str]] = {
            sid: info.get("shop_timezone")
            for sid, info in synced_map.items() if info.get("shop_timezone")
        }
        tz_need = [sh for sh in tz_shops if not tz_by_shop.get(sh["id"])]
        tz_values = await asyncio.gather(*[
            fetch_shop_timezone(
                shop_domain=sh["shop_domain"],
                admin_api_key=sh["admin_api_key"],
                api_version=sh["api_version"],
            ) for sh in tz_need
        ], return_exceptions=True)
        for sh, tz_val in zip(tz_need, tz_values):
            tz_by_shop[sh["id"]] = tz_val if isinstance(tz_val, str) else None
        for sh in tz_shops:
            tz_by_shop.setdefault(sh["id"], None)

        # The silence cutoff, per shop, in that shop's own calendar. Shops in
        # different timezones are not on the same day — measured live, a US shop
        # and a Tokyo shop disagree for part of every day — and a cutoff one day
        # out moves customers across the line.
        cutoff_by_store: Dict[int, str] = {
            s["id"]: _minus_months(shop_today(tz_by_shop.get(s["id"])), silent_months)
            for s in store_list
        }
        # A month can only be called fully judged when it is judged at EVERY
        # store, so the report-wide boundary is the latest of the cutoffs — one
        # day's disagreement is enough to straddle a month boundary.
        report_cutoff = max(cutoff_by_store.values())
        cutoff_month = report_cutoff[:7]

        # Server-local, and only ever used as the open upper end of the last
        # creation-date range — the shop's own today is what classification uses.
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        # The partition is per shop: it spans that shop's own customer history.
        # Both probes are one cheap query each, run together. Locally-served
        # stores skip them — a single SQL query needs no creation-date shards.
        probe_stores = [s for s in store_list if s["id"] not in local_ids]
        earliest_values = await asyncio.gather(*[
            fetch_earliest_customer_date(
                shop_domain=s["shop_domain"],
                admin_api_key=s["admin_api_key"],
                api_version=s["api_version"],
            ) for s in probe_stores
        ], return_exceptions=True)
        shards_by_store: Dict[int, List[tuple]] = {}
        concurrency_by_store: Dict[int, int] = {}
        unpartitioned: List[str] = []
        for s in store_list:
            if s["id"] in local_ids:
                shards_by_store[s["id"]] = [(None, None)]
                concurrency_by_store[s["id"]] = 1
        for s, earliest in zip(probe_stores, earliest_values):
            first = earliest if isinstance(earliest, str) else None
            conc = _scan_concurrency_for_rate(shopify_bucket_rate(s["shop_domain"]))
            concurrency_by_store[s["id"]] = conc
            # Not bounded by `conc`: that would be one range per cursor, which is
            # the arrangement _RANGES_PER_CURSOR exists to avoid. `conc` still
            # sizes the pool that walks these ranges, below.
            shards_by_store[s["id"]] = _lost_shards(first, tomorrow)
            # A failed probe silently collapses the scan to a single cursor,
            # which is correct but many times slower. Say so rather than let the
            # run look mysteriously slow.
            if not first:
                unpartitioned.append(s["name"])
        total_units = sum(len(v) for v in shards_by_store.values())

        # What the run actually resolved to, as opposed to what was asked for.
        # Echoed here as well as in `complete` because the notes and scope lines
        # render on every store event, long before the run finishes — without an
        # early echo they would have nothing to interpolate.
        window = {
            "history_from": history_from,
            "all_history": history_from is None,
            "silent_months": silent_months,
            "moved_within_months": moved_months,
            "require_acquired_in_window": require_acquired,
            "min_orders": min_orders,
            "cutoff": report_cutoff,
            "judgeable_through": cutoff_month,
            "cutoffs_by_store": {str(k): v for k, v in cutoff_by_store.items()},
        }

        yield f"event: progress\ndata: {json.dumps({'phase': 'started', 'window': window, 'min_orders': min_orders, 'shards': max((len(v) for v in shards_by_store.values()), default=1), 'total_units': total_units, 'stores': [{'store_id': s['id'], 'store_name': s['name'], 'shards': len(shards_by_store[s['id']])} for s in store_list]})}\n\n"

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

                shards = shards_by_store.get(s["id"]) or [(None, None)]
                data_source = "local" if s["id"] in local_ids else "live"
                events.put_nowait(("store_start", {
                    "store_id": s["id"], "store_name": s["name"], "shards": len(shards),
                    "data_source": data_source,
                }))

                store_tz = tz_by_shop.get(s["id"])
                collected: List[Dict[str, Any]] = []
                # Distinct customers seen so far, so progress reports customers
                # and not records. Ranges overlap by a day at their boundaries,
                # which made the counter read ~900 high on a 17,700-customer
                # store and disagree with every figure that followed it.
                seen_ids: set = set()
                # Every walk needs its own id. The client keys per-walk page and
                # customer counts by this and sums them, so two walks sharing an
                # id overwrite each other — a split child reporting its first
                # page would wipe out its parent's total and the counter would
                # visibly drop, climb, and drop again.
                next_walk = [len(shards)]

                def new_walk_id() -> int:
                    wid = next_walk[0]
                    next_walk[0] += 1
                    return wid

                async def run_shard(index: int, lo: Optional[str], hi: Optional[str],
                                    depth: int = 0):
                    # Page callbacks are what prove the run is alive during a
                    # long cursor walk — a store can spend minutes on one shard.
                    pages = 0

                    def on_page(scanned: int, ids: List[str], _i=index):
                        nonlocal pages
                        pages += 1
                        seen_ids.update(ids)
                        events.put_nowait(("page", {
                            "store_id": s["id"], "store_name": s["name"],
                            "shard": _i, "pages": pages, "scanned": scanned,
                            "distinct": len(seen_ids),
                        }))

                    async with scan_pool:
                        res = await fetch_customers_with_last_order(
                            shop_domain=s["shop_domain"],
                            admin_api_key=s["admin_api_key"],
                            order_floor=history_from,
                            api_version=s["api_version"],
                            created_start=lo,
                            created_end=hi,
                            page_budget=(_SCAN_PAGE_BUDGET
                                         if depth < _SCAN_MAX_SPLIT_DEPTH else None),
                            on_retry=on_retry,
                            on_page=on_page,
                        )
                    collected.append(res)
                    events.put_nowait(("shard_done", {
                        "store_id": s["id"], "store_name": s["name"], "shard": index,
                        "ok": bool(res.get("ok")), "pages": res.get("pages", 0),
                        "scanned": len(res.get("customers") or []),
                        "distinct": len(seen_ids),
                    }))

                    # This range turned out denser than its neighbours. Hand the
                    # remainder to several cursors rather than let one finish it
                    # while the others idle — the tail of a single deep range was
                    # 73% of the scan's wall clock.
                    resume = res.get("resume_from")
                    if not resume:
                        return
                    nxt = local_date(resume, store_tz)
                    parts = _split_dates(nxt, hi, tomorrow, _RANGES_PER_CURSOR) if nxt else []
                    if not parts or (lo and parts[0][0] <= lo):
                        # No room to divide (or no forward progress): finish the
                        # remainder in one uninterrupted walk. Still announced,
                        # because it is one more shard_done than we promised and
                        # an unannounced one pushes the progress bar past 100%.
                        events.put_nowait(("shard_split", {
                            "store_id": s["id"], "store_name": s["name"], "added": 1,
                        }))
                        await run_shard(new_walk_id(), nxt or lo, hi,
                                        depth=_SCAN_MAX_SPLIT_DEPTH)
                        return
                    events.put_nowait(("shard_split", {
                        "store_id": s["id"], "store_name": s["name"], "added": len(parts),
                    }))
                    await asyncio.gather(*[
                        run_shard(new_walk_id(), a, b, depth + 1) for a, b in parts
                    ], return_exceptions=True)

                if data_source == "local":
                    # One SQL query replaces the whole sharded cursor walk: the
                    # 25k pagination cap, page budgets and adaptive splitting
                    # exist only to cope with the live API.
                    events.put_nowait(("phase", {
                        "store_id": s["id"], "store_name": s["name"],
                        "label": "reading synced local data",
                    }))
                    try:
                        local_res = await lost_customers_local.scan_store(
                            s["id"], tz_by_shop.get(s["id"]), history_from)
                    except Exception as e:
                        local_res = {
                            "ok": False, "complete": False, "incomplete_reason": None,
                            "error": f"Local data read failed: {e}",
                            "customers": [], "warnings": [], "pages": 0,
                            "resume_from": None,
                        }
                    collected.append(local_res)
                    seen_ids.update(
                        c["customer_id"] for c in local_res.get("customers") or []
                        if c.get("customer_id"))
                    events.put_nowait(("shard_done", {
                        "store_id": s["id"], "store_name": s["name"], "shard": 0,
                        "ok": bool(local_res.get("ok")), "pages": 0,
                        "scanned": len(local_res.get("customers") or []),
                        "distinct": len(seen_ids),
                    }))
                else:
                    # Ranges are equal in date span but not in customer volume, so
                    # each cursor stops after a page budget and whatever is left of a
                    # dense range is split across cursors that have gone idle.
                    scan_pool = asyncio.Semaphore(concurrency_by_store.get(s["id"], 4))
                    await asyncio.gather(*[
                        run_shard(i, lo, hi) for i, (lo, hi) in enumerate(shards)
                    ], return_exceptions=True)
                shard_results = collected

                by_id: Dict[str, Dict[str, Any]] = {}
                warnings: List[str] = []
                if s["name"] in unpartitioned:
                    # Correct, just slow, so it is a warning rather than a
                    # partial-data flag — but it must not pass unremarked.
                    warnings.append(
                        "Could not read this shop's customer history, so the scan ran "
                        "as a single pass instead of in parallel — slower than usual.")
                failed_shards = 0
                incomplete_reasons: List[str] = []
                # Two different kinds of "incomplete", and conflating them threw
                # away a whole store's comparison over four customers' order
                # counts. `incomplete_reasons` is everything worth telling the
                # user. `bias_reasons` is the subset that makes the customers we
                # DID get an unrepresentative sample — a missing date range, an
                # unhonoured acquisition filter, an undetected mover. Only those
                # may disqualify the store from the lost-vs-active comparison;
                # a figure being imprecise for named customers is fixed by
                # dropping those customers, not the store.
                bias_reasons: List[str] = []

                for res in shard_results:
                    if isinstance(res, BaseException):
                        failed_shards += 1
                        incomplete_reasons.append(str(res)[:200])
                        bias_reasons.append(str(res)[:200])
                        continue
                    if not res.get("ok"):
                        failed_shards += 1
                        if res.get("error"):
                            incomplete_reasons.append(res["error"][:200])
                            bias_reasons.append(res["error"][:200])
                    if res.get("incomplete_reason"):
                        incomplete_reasons.append(res["incomplete_reason"])
                        bias_reasons.append(res["incomplete_reason"])
                    warnings.extend(res.get("warnings") or [])
                    # A customer with orders in several shards appears in each;
                    # the record is identical, so first write wins.
                    for c in res.get("customers") or []:
                        if c.get("customer_id"):
                            by_id.setdefault(c["customer_id"], c)

                if not collected or failed_shards >= len(collected):
                    return {
                        "store": s, "ok": False, "complete": False,
                        "error": incomplete_reasons[0] if incomplete_reasons else "Fetch failed",
                        "lost": [], "active": [],
                        "data_source": data_source,
                    }

                tz = tz_by_shop.get(s["id"])
                if not tz:
                    incomplete_reasons.append(
                        "Could not read this shop's timezone, so dates near the "
                        "window edges are judged in UTC and may be off by a day.")
                    bias_reasons.append("timezone unavailable")

                cutoff = cutoff_by_store[s["id"]]
                store_today = shop_today(tz)
                lost, active = [], []
                never_purchased = 0
                ordered_before_window = 0
                for c in by_id.values():
                    last = c.get("last_order_created_at")
                    if not last:
                        # Every order they placed was cancelled or refunded, so
                        # there is no purchase here to have lost.
                        never_purchased += 1
                        continue
                    # The shop's own calendar day, matching what Shopify filtered
                    # on. Carried on the row so the table shows the same date the
                    # classification used and can never appear to contradict it.
                    c["last_order_local"] = local_date(last, tz)
                    # Days quiet, in the shop's calendar. Computed here because
                    # this is the only place that holds both the shop's timezone
                    # and its today; the browser used to derive it from the raw
                    # UTC stamp against the viewer's own clock.
                    c["days_silent"] = _days_between(c["last_order_local"], store_today)
                    if c["last_order_local"] >= cutoff:
                        active.append(c)
                    elif history_from and c["last_order_local"] < history_from:
                        # Only reachable when a floor was given: their in-window
                        # orders were all cancelled or refunded, leaving an older
                        # real purchase as their last. Correctly excluded, but
                        # counted, so the reconciliation adds up instead of
                        # losing people.
                        ordered_before_window += 1
                    else:
                        lost.append(c)

                # "Was ordering since" means the customer STARTED here. Shopify's
                # order_date filter only proves they ordered at some point in the
                # window, so anyone already buying beforehand is still in `lost`
                # at this stage. Look up each candidate's oldest order and drop
                # the pre-existing ones outright — they must not reach the rows,
                # the totals, the KPIs or the benchmark.
                # Pre-filtered on Shopify's inflated lifetime count before the
                # lookup, so we stop paying for customers we are about to
                # discard. Safe in one direction only, which is the one we need:
                # the inflated count is always >= the true one, so nobody who
                # would qualify on the true count can be dropped here. The real
                # filter runs again below on the corrected number.
                lost_pre = [c for c in lost if c["orders_count"] >= min_orders]
                active_pre = [c for c in active if c["orders_count"] >= min_orders]
                candidates = [c["customer_id"] for c in (lost_pre + active_pre)
                              if c.get("customer_id")]
                first_map: Dict[str, Any] = {}
                count_map: Dict[str, Any] = {}
                undercounted = 0
                undercounted_ids: set = set()
                first_err = None
                unknown_first = 0
                if candidates:
                    events.put_nowait(("phase", {
                        "store_id": s["id"], "store_name": s["name"],
                        "label": "checking when each customer started",
                    }))
                    if data_source == "local":
                        fo = await lost_customers_local.first_orders(s["id"], candidates)
                    else:
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
                        count_map = fo.get("order_counts") or {}
                        undercounted = fo.get("undercounted", 0)
                        undercounted_ids = set(fo.get("undercounted_ids") or ())
                    else:
                        first_err = fo.get("error")

                # Replace Shopify's lifetime count with the completed one. The
                # raw value is kept so the cell can show what was subtracted.
                for c in lost_pre + active_pre:
                    completed, lifetime = count_map.get(c.get("customer_id"), (None, None))
                    c["orders_count_all"] = lifetime if lifetime is not None else c["orders_count"]
                    if completed is not None:
                        c["orders_count"] = completed
                    # Stamped per customer so the badge marks the four people it
                    # actually applies to, rather than every row of their store.
                    c["orders_count_exact"] = c.get("customer_id") not in undercounted_ids
                if undercounted:
                    # The completed count is lifetime minus the cancelled and
                    # refunded orders we could see, and that page caps out — so
                    # too little is subtracted and the result is an over-count,
                    # not an under-count. Said backwards until 2026-07-30.
                    incomplete_reasons.append(
                        f"{undercounted} customer(s) have more cancelled or refunded orders "
                        f"than one page holds, so their order count is an upper bound and "
                        f"may be overstated")
                    # Deliberately NOT a bias reason. It touches orders_count,
                    # and nothing the comparison reads — that is fulfilment and
                    # delivery timing — depends on it.

                # Stamping is separate from filtering on purpose. The acquisition
                # date is read by the chart's "new" series and by the arrivals
                # classifier whether or not the cohort filter is on, so the two
                # used to be one function only because the filter was mandatory.
                def stamp_first_order(c) -> bool:
                    """Stamp the acquisition date. False when it is unknown."""
                    first = first_map.get(c.get("customer_id"))
                    c["first_order_created_at"] = first
                    c["first_order_local"] = local_date(first, tz) if first else None
                    return bool(first)

                for c in lost_pre + active_pre:
                    stamp_first_order(c)

                if require_acquired:
                    if first_err:
                        # Without first-order data the acquisition filter cannot
                        # be honoured, so report the store as partial instead of
                        # silently falling back to the old, wider meaning.
                        incomplete_reasons.append(
                            f"Could not determine when customers started ordering: {first_err}")
                        bias_reasons.append("acquisition window not applied")
                        lost_in, active_in = lost_pre, active_pre
                    else:
                        # No first order resolved: excluded rather than assumed
                        # in, so a lookup gap can never inflate the cohort.
                        def acquired(c):
                            return bool(c["first_order_local"]) and \
                                c["first_order_local"] >= history_from
                        lost_in = [c for c in lost_pre if acquired(c)]
                        active_in = [c for c in active_pre if acquired(c)]
                else:
                    if first_err:
                        # Still worth saying — the "new" bars undercount without
                        # it — but no longer a bias: no filter was applied, so
                        # the cohort is not a skewed sample of anything.
                        incomplete_reasons.append(
                            f"Could not determine when customers started ordering, so the "
                            f"'new customers' bars are incomplete: {first_err}")
                    lost_in, active_in = lost_pre, active_pre

                # Measured against the pre-filtered sets, so a customer dropped
                # for too few orders is never miscounted as "already ordering".
                # None rather than 0 when the filter is off, so the client can
                # tell "nobody was excluded" from "nothing was being excluded"
                # and suppress the note instead of reporting zero exclusions.
                excluded_pre_existing = (
                    ((len(lost_pre) - len(lost_in)) + (len(active_pre) - len(active_in)))
                    if require_acquired else None)

                # Second application, now on the corrected count.
                lost_kept = [c for c in lost_in if c["orders_count"] >= min_orders]
                lost_kept.sort(key=lambda c: c["amount_spent"], reverse=True)
                # The comparison group must be filtered identically. Applying
                # min_orders — or the acquisition window — to only one side
                # would compare newly-acquired leavers against a control drawn
                # from a different population.
                active_kept = [c for c in active_in if c["orders_count"] >= min_orders]

                # Cross-store check runs last, on the smallest possible list, and
                # in volume-sized sections. Sectioning does not reduce the number
                # of requests — the same emails are looked up either way — but it
                # bounds memory, keeps a failure inside one section instead of
                # disqualifying the whole store, and gives each batch a date range
                # to bound the in-window query by.
                moved_breakdown: Dict[Any, Dict[str, Any]] = {}
                moved_rows: List[Dict[str, Any]] = []
                matched_by_name = 0
                no_email = 0
                moved_unresolved = 0
                cross_errors: List[str] = []
                sections_total = 0
                sections_biased = 0

                async def emit_rows(kind_name: str, source: List[Dict[str, Any]],
                                    fields=_LOST_ROW_FIELDS):
                    """
                    Stream departures to the client in chunks.

                    Chunked because a single event carrying a whole store's
                    departures was measured at 64.6 MB on a full-history run,
                    which the browser must buffer and parse in one go.
                    """
                    for i in range(0, len(source), _ROWS_EVENT_CHUNK):
                        await events.put(("rows", {
                            "store_id": s["id"], "store_name": s["name"],
                            "kind": kind_name,
                            "rows": [_trim_row(c, fields)
                                     for c in source[i:i + _ROWS_EVENT_CHUNK]],
                        }))

                async def flush_section(out: Dict[str, Any]):
                    """
                    Send a finished section's rows immediately.

                    Called from inside the section rather than from the merge loop
                    below, because that loop runs after `gather` — a barrier — so
                    emitting there would hold every row back until the slowest
                    section finished, which is the delay sectioning exists to
                    avoid. Arrival order does not matter: the client sorts rows
                    itself, and the order-sensitive part (the moved breakdown) is
                    still merged in section order.
                    """
                    await emit_rows("lost", out["kept"])
                    await emit_rows("moved", out["moved"], _MOVED_ROW_FIELDS)
                # Ids in sections whose check was incomplete. Those departures are
                # real, so they stay in the table — but they cannot be trusted in
                # the lost-vs-active comparison, which is what the user acts on.
                biased_ids: set = set()

                if cross_store and lost_kept:
                    # The customer's own shop is skipped in pass 1: Shopify
                    # enforces one customer record per email, so an email lookup
                    # against the shop they are already lost at can only ever
                    # return their own pre-departure order. Pass 2 keeps the own
                    # shop — matching on name and ZIP is what catches a
                    # re-registration, which is forced onto a different address by
                    # that same rule.
                    others = [o for o in all_shopify if o["id"] != s["id"]]
                    name_shops = list(all_shopify)
                    sections = _departure_sections(lost_kept)
                    sections_total = len(sections)
                    section_pool = asyncio.Semaphore(_CROSS_SECTION_CONCURRENCY)

                    async def run_section(index: int, section: Dict[str, Any]) -> Dict[str, Any]:
                        rows_in = section["rows"]
                        months = section["months"]
                        # One bound for the whole section: from the start of its
                        # earliest departure month to `moved_months` past the end
                        # of its latest, which covers every member's own window.
                        win = None
                        if months:
                            win = (f"{months[0]}-01",
                                   _plus_months(_month_end_exclusive(months[1]), moved_months))
                        out = {
                            "kept": [], "moved": [], "errors": [], "matched_by_name": 0,
                            "no_email": 0, "unresolved": 0,
                            "breakdown": {},
                        }
                        async with section_pool:
                            events.put_nowait(("section_start", {
                                "store_id": s["id"], "store_name": s["name"],
                                "section": index, "sections_total": sections_total,
                                "months": list(months) if months else None,
                                "size": len(rows_in),
                            }))

                            out["no_email"] = sum(
                                1 for c in rows_in if not normalize_email(c.get("email")))
                            lookup = sorted({e for e in (
                                normalize_email(c.get("email")) for c in rows_in) if e})

                            # Shops are independent lookups against different
                            # hosts, so they run together — this phase was 35% of
                            # the run when serialised. Each shop's own rate-limit
                            # bucket still paces it, and results are merged in a
                            # fixed shop order so attribution cannot vary.
                            async def email_probe(other):
                                if other["id"] in local_ids:
                                    return other, await lost_customers_local.emails_probe(
                                        other["id"], tz_by_shop.get(other["id"]),
                                        lookup, window=win)
                                return other, await fetch_customers_by_emails(
                                    shop_domain=other["shop_domain"],
                                    admin_api_key=other["admin_api_key"],
                                    emails=lookup,
                                    api_version=other["api_version"],
                                    window=win,
                                    on_batch=lambda d, t, _s=s, _o=other: events.put_nowait(
                                        ("cross_store", {
                                            "store_id": _s["id"], "store_name": _s["name"],
                                            "other": _o["name"], "done": d, "total": t,
                                        })),
                                    on_retry=on_retry,
                                )

                            email_results = []
                            if lookup and others:
                                email_results = await asyncio.gather(
                                    *[email_probe(o) for o in others], return_exceptions=True)

                            # email -> the shop they moved to, plus the evidence
                            moved_to: Dict[str, Dict[str, Any]] = {}
                            unknown_at: Dict[str, bool] = {}
                            quiet_of = {normalize_email(c.get("email")): c["last_order_local"]
                                        for c in rows_in if normalize_email(c.get("email"))}
                            for item in email_results:
                                if isinstance(item, BaseException):
                                    out["errors"].append(str(item)[:200])
                                    continue
                                other, res = item
                                if not res.get("ok"):
                                    # Never silently keep a customer we failed to check.
                                    out["errors"].append(f"{other['name']}: {res.get('error')}")
                                    continue
                                if res.get("malformed"):
                                    out["errors"].append(
                                        f"{other['name']}: {res['malformed']} address(es) were "
                                        f"too malformed to search")
                                other_tz = tz_by_shop.get(other["id"])
                                wins = res.get("window_orders") or {}
                                sat = set(res.get("window_saturated") or ())
                                for em, last in (res.get("last_orders") or {}).items():
                                    quiet = quiet_of.get(em)
                                    if not quiet or em in moved_to:
                                        continue
                                    # Every date is judged in the calendar of the
                                    # shop the order was placed at.
                                    last_local = local_date(last, other_tz) if last else None
                                    verdict = _judge_move(
                                        quiet, moved_months, last_local,
                                        [local_date(d, other_tz) for d in wins.get(em, ())],
                                        em in sat)
                                    if verdict == _MOVE_YES:
                                        # Keyed by id: two shops can share a
                                        # display name, and merging them would
                                        # misattribute the move.
                                        moved_to[em] = {
                                            "id": other["id"], "name": other["name"],
                                            "last_order": last_local,
                                        }
                                        unknown_at.pop(em, None)
                                    elif verdict == _MOVE_UNKNOWN:
                                        unknown_at[em] = True

                            after_email = []
                            for c in rows_in:
                                em = normalize_email(c.get("email"))
                                dest = moved_to.get(em) if em else None
                                if dest:
                                    _record_move(c, dest["id"], dest["name"], dest["name"],
                                                 dest["last_order"], "email")
                                    _bump_moved(out["breakdown"], dest["id"], dest["name"])
                                    out["moved"].append(c)
                                    continue
                                if em and unknown_at.get(em):
                                    # Active at another shop, but we could not see
                                    # far enough back to say whether that started
                                    # inside their window. Kept as lost — the
                                    # conservative direction — and counted.
                                    c["moved_unresolved"] = True
                                    out["unresolved"] += 1
                                after_email.append(c)

                            # --- second pass: name + ZIP ---
                            # Shopify allows only one record per email, so anyone
                            # who re-registered is invisible to pass 1.
                            people = [
                                c for c in after_email
                                if name_key(c.get("first_name"), c.get("last_name"))
                                and c.get("zips")
                            ]
                            if not people:
                                out["kept"] = after_email
                                await flush_section(out)
                                return out

                            wanted = sorted({(c["first_name"], c["last_name"]) for c in people})
                            by_name: Dict[str, List[Dict[str, Any]]] = {}

                            async def name_probe(other):
                                if other["id"] in local_ids:
                                    return other, await lost_customers_local.names_probe(
                                        other["id"], tz_by_shop.get(other["id"]),
                                        wanted, window=win)
                                return other, await fetch_customers_by_name(
                                    shop_domain=other["shop_domain"],
                                    admin_api_key=other["admin_api_key"],
                                    names=wanted,
                                    api_version=other["api_version"],
                                    window=win,
                                    on_batch=lambda d, t, _s=s, _o=other: events.put_nowait(
                                        ("cross_store", {
                                            "store_id": _s["id"], "store_name": _s["name"],
                                            "other": _o["name"], "done": d, "total": t,
                                        })),
                                    on_retry=on_retry,
                                )

                            name_results = await asyncio.gather(
                                *[name_probe(o) for o in name_shops], return_exceptions=True)

                            for item in name_results:
                                if isinstance(item, BaseException):
                                    out["errors"].append(str(item)[:200])
                                    continue
                                other, res2 = item
                                if not res2.get("ok"):
                                    out["errors"].append(
                                        f"{other['name']} (by name): {res2.get('error')}")
                                    continue
                                if res2.get("truncated"):
                                    out["errors"].append(
                                        f"{other['name']}: too many customers share these "
                                        f"names to check them all")
                                other_tz2 = tz_by_shop.get(other["id"])
                                for cand in res2.get("candidates") or []:
                                    cand["store_id"] = other["id"]
                                    cand["store_name"] = other["name"]
                                    cand["same_store"] = other["id"] == s["id"]
                                    cand["_tz"] = other_tz2
                                    by_name.setdefault(cand["name_key"], []).append(cand)

                            kept2 = []
                            for c in after_email:
                                k = name_key(c.get("first_name"), c.get("last_name"))
                                zips = set(c.get("zips") or ())
                                hit = None
                                hit_unknown = False
                                for cand in by_name.get(k, ()) if k else ():
                                    # A different record, same household. The ZIP
                                    # separates a genuine duplicate from two
                                    # unrelated people sharing a common name.
                                    if cand["id"] == c.get("customer_id"):
                                        continue
                                    if not zips.intersection(cand["zips"]):
                                        continue
                                    tz2 = cand["_tz"]
                                    verdict = _judge_move(
                                        c["last_order_local"], moved_months,
                                        local_date(cand["last_order"], tz2)
                                        if cand.get("last_order") else None,
                                        [local_date(d, tz2)
                                         for d in (cand.get("window_orders") or ())],
                                        bool(cand.get("window_saturated")))
                                    if verdict == _MOVE_YES:
                                        hit = cand
                                        break
                                    if verdict == _MOVE_UNKNOWN:
                                        hit_unknown = True
                                if hit:
                                    # The email pass may already have counted this
                                    # person as unresolved. Now that a move is
                                    # proven, take that back — otherwise they are
                                    # reported both as having moved and as a
                                    # departure whose move could not be determined,
                                    # and the store wears a partial-data flag for a
                                    # customer it resolved.
                                    if c.pop("moved_unresolved", None):
                                        out["unresolved"] -= 1
                                    label = (f"{hit['store_name']} (another account)"
                                             if hit["same_store"] else hit["store_name"])
                                    _record_move(
                                        c, hit["store_id"], label, hit["store_name"],
                                        local_date(hit["last_order"], hit["_tz"]),
                                        "name + ZIP", same_store=hit["same_store"])
                                    # Same-store matches are a distinct destination
                                    # from cross-store ones at that shop, so they
                                    # get their own key rather than merging.
                                    _bump_moved(
                                        out["breakdown"],
                                        f"{hit['store_id']}{':self' if hit['same_store'] else ''}",
                                        label)
                                    out["matched_by_name"] += 1
                                    out["moved"].append(c)
                                    continue
                                if hit_unknown and not c.get("moved_unresolved"):
                                    c["moved_unresolved"] = True
                                    out["unresolved"] += 1
                                kept2.append(c)
                            out["kept"] = kept2
                            await flush_section(out)
                            return out

                    # Ordered, not completion-ordered: a section's contribution to
                    # the breakdown must not depend on which finished first.
                    section_results = await asyncio.gather(
                        *[run_section(i, sec) for i, sec in enumerate(sections)],
                        return_exceptions=True)

                    survivors: List[Dict[str, Any]] = []
                    for index, (sec, res) in enumerate(zip(sections, section_results)):
                        if isinstance(res, BaseException):
                            # The whole section went unchecked. Its departures are
                            # still departures, so they stay — flagged.
                            cross_errors.append(str(res)[:200])
                            sections_biased += 1
                            survivors.extend(sec["rows"])
                            biased_ids.update(
                                c["customer_id"] for c in sec["rows"] if c.get("customer_id"))
                            await emit_rows("lost", sec["rows"])
                            continue
                        # Rows already went out from inside the section — see
                        # flush_section. This loop only merges the tallies, in
                        # section order so attribution cannot vary between runs.
                        survivors.extend(res["kept"])
                        moved_rows.extend(res["moved"])
                        matched_by_name += res["matched_by_name"]
                        # Summed, not assigned: each section counts only its own.
                        no_email += res["no_email"]
                        moved_unresolved += res["unresolved"]
                        for key, entry in res["breakdown"].items():
                            _bump_moved(moved_breakdown, key, entry["label"])
                            # _bump_moved adds one; carry the rest of the count.
                            moved_breakdown[key]["count"] += entry["count"] - 1
                        if res["errors"]:
                            cross_errors.extend(res["errors"])
                            sections_biased += 1
                            biased_ids.update(
                                c["customer_id"] for c in res["kept"] if c.get("customer_id"))
                        events.put_nowait(("section_done", {
                            "store_id": s["id"], "store_name": s["name"],
                            "section": index, "sections_total": sections_total,
                            "kept": len(res["kept"]), "moved": len(res["moved"]),
                            "biased": bool(res["errors"]),
                        }))
                    lost_kept = survivors

                    if cross_errors:
                        incomplete_reasons.append(
                            f"Could not check every store for duplicate accounts in "
                            f"{sections_biased} of {sections_total} batch(es) of departures: "
                            + "; ".join(cross_errors[:2]))
                        # Deliberately NOT a whole-store bias reason any more. The
                        # failure belongs to the sections that hit it, so only
                        # their departures leave the comparison — see biased_ids.
                        # Before sectioning this disqualified the entire store.
                    # Deliberately NOT an incomplete_reason: it is a precision
                    # caveat about a handful of named customers, and putting it
                    # there flagged the whole store as partial data — the same
                    # mistake the order-count caveat above documents. The count is
                    # reported on its own and the client renders it as a note.

                # --- where the arrivals came from ---------------------------
                # Deliberately placed after the moved check, so it runs on
                # exactly the population the chart's "new" bars count: the kept
                # lost list plus the kept active one.
                arrival: Dict[str, Any] = {}
                if check_arrivals:
                    # Exactly the population the chart's "new" bars count, which is
                    # why it is also clamped to the history floor. Without the
                    # clamp the cohort is everyone the scan touched — measured on
                    # one store, 15,674 people reaching back to 2020 — and the
                    # modal would report them as customers acquired in the window
                    # while the bars above it counted a fraction of that.
                    cohort = [c for c in (lost_kept + active_kept)
                              if c.get("first_order_local")
                              and (not history_from
                                   or c["first_order_local"] >= history_from)]
                    others = [o for o in all_shopify if o["id"] != s["id"]]
                    arr_errors: List[str] = []
                    # customer_id -> that person's records at other shops
                    matches: Dict[str, List[Dict[str, Any]]] = {}

                    # Sectioned by volume only. Unlike the moved check there is no
                    # date bound to align to — these passes want each candidate's
                    # first and last order over all time — so plain slices will do.
                    #
                    # The reason to section here is the candidate cap below: it
                    # used to be measured against the WHOLE cohort, so on any large
                    # run the name+ZIP pass was skipped outright and the check
                    # silently degraded to email-only. Per section it applies to at
                    # most one section's worth of unmatched customers.
                    arr_sections = [cohort[i:i + _CROSS_SECTION_SIZE]
                                    for i in range(0, len(cohort), _CROSS_SECTION_SIZE)]
                    arr_pool = asyncio.Semaphore(_CROSS_SECTION_CONCURRENCY)

                    async def trace_section(chunk: List[Dict[str, Any]]):
                        async with arr_pool:
                            emails = sorted({normalize_email(c.get("email"))
                                             for c in chunk if normalize_email(c.get("email"))})
                            if emails and others:
                                events.put_nowait(("phase", {
                                    "store_id": s["id"], "store_name": s["name"],
                                    "label": f"tracing {len(chunk)} new customer(s) "
                                             f"across {len(others)} store(s)",
                                }))

                                async def origin_probe(other):
                                    if other["id"] in local_ids:
                                        return other, await lost_customers_local.emails_probe(
                                            other["id"], tz_by_shop.get(other["id"]),
                                            emails, want_origin=True)
                                    return other, await fetch_customers_by_emails(
                                        shop_domain=other["shop_domain"],
                                        admin_api_key=other["admin_api_key"],
                                        emails=emails,
                                        api_version=other["api_version"],
                                        want_origin=True,
                                        on_batch=lambda d, t, _s=s, _o=other: events.put_nowait(
                                            ("cross_store", {
                                                "store_id": _s["id"], "store_name": _s["name"],
                                                "other": _o["name"], "done": d, "total": t,
                                            })),
                                        on_retry=on_retry,
                                    )

                                for item in await asyncio.gather(
                                        *[origin_probe(o) for o in others],
                                        return_exceptions=True):
                                    if isinstance(item, BaseException):
                                        arr_errors.append(str(item)[:200])
                                        continue
                                    other, res = item
                                    if not res.get("ok"):
                                        arr_errors.append(f"{other['name']}: {res.get('error')}")
                                        continue
                                    otz = tz_by_shop.get(other["id"])
                                    by_email = {}
                                    for em, acct in (res.get("accounts") or {}).items():
                                        f = (res.get("first_orders") or {}).get(em)
                                        l = (res.get("last_orders") or {}).get(em)
                                        by_email[em] = {
                                            "store_id": other["id"],
                                            "store_name": other["name"],
                                            "same_store": False,
                                            "matched_by": "email",
                                            # Each shop's own calendar, as
                                            # everywhere else — events elsewhere.
                                            "first": local_date(f, otz) if f else None,
                                            "last": local_date(l, otz) if l else None,
                                            "account": local_date(acct, otz) if acct else None,
                                        }
                                    for c in chunk:
                                        em = normalize_email(c.get("email"))
                                        hit = by_email.get(em) if em else None
                                        if hit:
                                            matches.setdefault(c["customer_id"], []).append(hit)

                            # Second pass, same reasoning as the lost side: one
                            # record per email means a re-registration is invisible
                            # above. The own shop is in scope here — that is where
                            # a second account for the same person most often sits.
                            unresolved = [c for c in chunk if c["customer_id"] not in matches]
                            people = [c for c in unresolved
                                      if name_key(c.get("first_name"), c.get("last_name"))
                                      and c.get("zips")]
                            if len(people) > _ARRIVAL_NAME_MAX_CANDIDATES:
                                arr_errors.append(
                                    f"{len(people):,} new customers in one batch had no match "
                                    f"by email — too many to also check for earlier accounts "
                                    f"under a different address, so that check was skipped "
                                    f"for them")
                                people = []
                            if not people:
                                return
                            events.put_nowait(("phase", {
                                "store_id": s["id"], "store_name": s["name"],
                                "label": f"checking {len(people)} new customer(s) for "
                                         f"earlier accounts by name and ZIP",
                            }))
                            wanted = sorted({(c["first_name"], c["last_name"]) for c in people})

                            async def origin_name_probe(other):
                                if other["id"] in local_ids:
                                    return other, await lost_customers_local.names_probe(
                                        other["id"], tz_by_shop.get(other["id"]),
                                        wanted, want_origin=True)
                                return other, await fetch_customers_by_name(
                                    shop_domain=other["shop_domain"],
                                    admin_api_key=other["admin_api_key"],
                                    names=wanted,
                                    api_version=other["api_version"],
                                    want_origin=True,
                                    on_batch=lambda d, t, _s=s, _o=other: events.put_nowait(
                                        ("cross_store", {
                                            "store_id": _s["id"], "store_name": _s["name"],
                                            "other": _o["name"], "done": d, "total": t,
                                        })),
                                    on_retry=on_retry,
                                )

                            cands_by_name: Dict[str, List[Dict[str, Any]]] = {}
                            for item in await asyncio.gather(
                                    *[origin_name_probe(o) for o in all_shopify],
                                    return_exceptions=True):
                                if isinstance(item, BaseException):
                                    arr_errors.append(str(item)[:200])
                                    continue
                                other, res2 = item
                                if not res2.get("ok"):
                                    arr_errors.append(
                                        f"{other['name']} (by name): {res2.get('error')}")
                                    continue
                                if res2.get("truncated"):
                                    arr_errors.append(
                                        f"{other['name']}: too many customers share these "
                                        f"names to check them all")
                                otz2 = tz_by_shop.get(other["id"])
                                for cand in res2.get("candidates") or []:
                                    cand["store_id"] = other["id"]
                                    cand["store_name"] = other["name"]
                                    cand["same_store"] = other["id"] == s["id"]
                                    cand["_tz"] = otz2
                                    cands_by_name.setdefault(cand["name_key"], []).append(cand)

                            for c in people:
                                k = name_key(c.get("first_name"), c.get("last_name"))
                                zips = set(c.get("zips") or ())
                                for cand in cands_by_name.get(k, ()) if k else ():
                                    # The person's own record is not evidence of an
                                    # earlier relationship with them.
                                    if cand["id"] == c.get("customer_id"):
                                        continue
                                    if not zips.intersection(cand["zips"]):
                                        continue
                                    f, l = cand.get("first_order"), cand.get("last_order")
                                    a = cand.get("account_created")
                                    matches.setdefault(c["customer_id"], []).append({
                                        "store_id": cand["store_id"],
                                        "store_name": (
                                            f"{cand['store_name']} (another account)"
                                            if cand["same_store"] else cand["store_name"]),
                                        "same_store": cand["same_store"],
                                        "matched_by": "name + ZIP",
                                        "first": local_date(f, cand["_tz"]) if f else None,
                                        "last": local_date(l, cand["_tz"]) if l else None,
                                        "account": local_date(a, cand["_tz"]) if a else None,
                                    })
                                    break

                    for item in await asyncio.gather(
                            *[trace_section(ch) for ch in arr_sections],
                            return_exceptions=True):
                        if isinstance(item, BaseException):
                            arr_errors.append(str(item)[:200])

                    verdicts: Dict[str, int] = {}
                    origins: Dict[Any, Dict[str, Any]] = {}
                    rows: List[Dict[str, Any]] = []
                    prior_account = 0
                    # The same tallies per arrival month, so the modal can follow a
                    # month selection on the chart. Aggregates only: the row table
                    # below is capped at the highest-spending _ARRIVAL_MAX_ROWS, so
                    # deriving per-month figures from it would disagree with the
                    # month's own "new" bar.
                    by_month_arr: Dict[str, Dict[str, Any]] = {}
                    for c in cohort:
                        here = c["first_order_local"]
                        mine = matches.get(c["customer_id"]) or []
                        verdict, origin = _classify_arrival(here, mine)
                        verdicts[verdict] = verdicts.get(verdict, 0) + 1
                        bucket = by_month_arr.setdefault(
                            here[:7], {"total": 0, "verdicts": {}, "origins": {}})
                        bucket["total"] += 1
                        bucket["verdicts"][verdict] = bucket["verdicts"].get(verdict, 0) + 1
                        # Free signal, no extra request: the account was opened
                        # before the purchase that made them look new.
                        made = c.get("customer_since")
                        if made and local_date(made, tz) < here:
                            prior_account += 1
                        if verdict == _ARR_NEW:
                            continue
                        best = next((m for m in mine if m["store_name"] == origin), None)
                        origin_key = (f"{(best or {}).get('store_id')}"
                                      f"{':self' if (best or {}).get('same_store') else ''}")
                        _bump_moved(origins, origin_key, origin)
                        _bump_moved(bucket["origins"], origin_key, origin)
                        rows.append({
                            "customer_id": c["customer_id"],
                            "name": c.get("name"),
                            "email": c.get("email"),
                            "arrived": here,
                            "orders_count": c.get("orders_count"),
                            "amount_spent": c.get("amount_spent"),
                            "currency": c.get("currency"),
                            "verdict": verdict,
                            "origin_store": origin,
                            "origin_first_order": (best or {}).get("first"),
                            "origin_last_order": (best or {}).get("last"),
                            "origin_account": (best or {}).get("account"),
                            "matched_by": (best or {}).get("matched_by"),
                            "account_created": (local_date(made, tz) if made else None),
                        })
                    rows.sort(key=lambda r: r.get("amount_spent") or 0, reverse=True)
                    if arr_errors:
                        incomplete_reasons.append(
                            "Could not fully trace where new customers came from: "
                            + "; ".join(arr_errors[:2]))
                        # Not a bias reason: this feeds only the arrivals modal.
                    arrival = {
                        "total": len(cohort),
                        "verdicts": verdicts,
                        "origins": _merge_moved([origins]),
                        # Origin keys collapse to labels here, exactly as the
                        # run-wide breakdown does at the boundary.
                        "by_month": {
                            m: {"total": e["total"], "verdicts": e["verdicts"],
                                "origins": _merge_moved([e["origins"]])}
                            for m, e in by_month_arr.items()
                        },
                        "prior_account": prior_account,
                        "no_email": sum(1 for c in cohort
                                        if not normalize_email(c.get("email"))),
                        # Capped: the cohort can run to tens of thousands and
                        # the browser only ever renders a table of them.
                        "rows": rows[:_ARRIVAL_MAX_ROWS],
                        "rows_truncated": max(0, len(rows) - _ARRIVAL_MAX_ROWS),
                        "errors": arr_errors[:3],
                    }

                # Lost and still-active counted the same way, so the share of a
                # state's customers that went quiet is comparable between
                # states — a raw count would only rank population size.
                #
                # Aggregated BEFORE the rows are trimmed: _state_key reads
                # state_name and country, and _timing_summary reads days_total,
                # none of which survive the trim.
                states: Dict[str, Dict[str, Any]] = {}
                for c in lost_kept:
                    k, label = _state_key(c)
                    e = states.setdefault(k, {"code": k, "label": label, "lost": 0, "active": 0})
                    e["lost"] += 1
                for c in active_kept:
                    k, label = _state_key(c)
                    e = states.setdefault(k, {"code": k, "label": label, "lost": 0, "active": 0})
                    e["active"] += 1
                lost_timing = _timing_summary(lost_kept)
                active_timing = _timing_summary(active_kept)

                # With the cross-store check off there are no sections to stream
                # from, so the rows go out here instead. The queue is FIFO either
                # way, so the client can treat this store's `done` as "all of its
                # rows have arrived".
                if not sections_total:
                    await emit_rows("lost", lost_kept)

                return {
                    "store": s,
                    "ok": True,
                    # A failed shard removes a contiguous date range, so what
                    # survives is a biased sample — flag it rather than pretend.
                    "complete": failed_shards == 0 and not incomplete_reasons,
                    # What the comparison gates on — see bias_reasons above.
                    "cohort_complete": failed_shards == 0 and not bias_reasons,
                    "incomplete_reason": incomplete_reasons[0] if incomplete_reasons else None,
                    "error": None,
                    "warnings": warnings[:3],
                    "lost": lost_kept,
                    "active": active_kept,
                    "excluded_pre_existing": excluded_pre_existing,
                    "unknown_first_order": unknown_first,
                    "never_purchased": never_purchased,
                    "ordered_before_window": ordered_before_window,
                    "states": states,
                    "lost_timing": lost_timing,
                    "active_timing": active_timing,
                    # Collapsed to {label: count} at the boundary; the shop-id
                    # keying exists to keep the tally correct, not to be sent.
                    "moved_breakdown": _merge_moved([moved_breakdown]),
                    "moved_total": sum(e["count"] for e in moved_breakdown.values()),
                    "matched_by_name": matched_by_name,
                    "no_email": no_email,
                    "arrival": arrival,
                    "sections_total": sections_total,
                    "sections_biased": sections_biased,
                    "moved_unresolved": moved_unresolved,
                    "cutoff": cutoff,
                    "shop_timezone": tz,
                    "data_source": data_source,
                    # The departures whose cross-store check was incomplete. They
                    # belong in the table but not in the comparison, so the
                    # benchmark filters on this rather than dropping the store.
                    "biased_ids": biased_ids,
                    "departures_excluded_from_benchmark": sum(
                        1 for c in lost_kept if c.get("customer_id") in biased_ids),
                }

        tasks = [asyncio.create_task(fetch_for_store(s)) for s in store_list]

        async def collect(t, store):
            try:
                res = await t
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # The store must travel with the failure. Without it the event
                # carries store_id: null, the client's lookup by id finds nothing,
                # and the store keeps its "still scanning" state — so the run
                # reports "1 of 1 stores complete" with no error anywhere, while
                # any rows already streamed sit on screen looking like a finished
                # result. Harmless before rows streamed; not any more.
                res = {"store": store, "ok": False, "complete": False,
                       "cohort_complete": False,
                       "error": f"Unexpected error: {e}", "lost": [], "active": [],
                       "data_source": "local" if store["id"] in local_ids else "live"}
            await events.put(("done", res))

        collectors = [asyncio.create_task(collect(t, s))
                      for t, s in zip(tasks, store_list)]

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

                # Only "done" advances the completed-store counter; everything
                # else is reporting.
                #
                # Inverted deliberately. This used to be a whitelist of progress
                # kinds, with anything unlisted treated as a finished store — so
                # adding a new progress event and forgetting to list it ended the
                # run early and truncated the scan, silently. Now an unrecognised
                # kind is merely reported as progress.
                if kind != "done":
                    name = _LOST_EVENT_NAMES.get(kind, "progress")
                    body = payload if name != "progress" else {"phase": kind, **payload}
                    yield f"event: {name}\ndata: {json.dumps(body)}\n\n"
                    continue

                completed += 1
                results.append(payload)
                st = payload.get("store") or {}
                lost = payload.get("lost") or []
                # Summary only. The rows themselves already went out as `rows`
                # events, chunked — this used to carry the entire departure list
                # inline, which on a full-history run was a single 64 MB SSE line.
                store_event = {
                    "store_id": st.get("id"), "store_name": st.get("name"),
                    "ok": payload.get("ok"),
                    "data_source": payload.get("data_source"),
                    "complete": payload.get("complete"),
                    "cohort_complete": payload.get("cohort_complete"),
                    "incomplete_reason": payload.get("incomplete_reason"),
                    "error": payload.get("error"),
                    "warnings": payload.get("warnings") or [],
                    "excluded_pre_existing": payload.get("excluded_pre_existing"),
                    "unknown_first_order": payload.get("unknown_first_order", 0),
                    "never_purchased": payload.get("never_purchased", 0),
                    "ordered_before_window": payload.get("ordered_before_window", 0),
                    "moved_total": payload.get("moved_total", 0),
                    "moved_breakdown": payload.get("moved_breakdown", {}),
                    "matched_by_name": payload.get("matched_by_name", 0),
                    "no_email": payload.get("no_email", 0),
                    # `arrival` deliberately omitted: it is the full per-store
                    # arrivals blob including up to _ARRIVAL_MAX_ROWS rows, and it
                    # is sent again merged in `complete`, which is the only copy
                    # anything reads. Including it here doubled the largest
                    # remaining payload on an arrivals run.
                    "lost_count": len(lost),
                    "active_count": len(payload.get("active") or []),
                    "lost_timing": payload.get("lost_timing") or _timing_summary(lost),
                    "active_timing": (payload.get("active_timing")
                                      or _timing_summary(payload.get("active") or [])),
                    "sections_total": payload.get("sections_total", 0),
                    "sections_biased": payload.get("sections_biased", 0),
                    "departures_excluded_from_benchmark": payload.get(
                        "departures_excluded_from_benchmark", 0),
                    "moved_unresolved": payload.get("moved_unresolved", 0),
                    "cutoff": payload.get("cutoff"),
                    "shop_timezone": payload.get("shop_timezone"),
                    "completed": completed,
                    "total_stores": len(store_list),
                }
                yield f"event: store\ndata: {json.dumps(store_event)}\n\n"

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

        # Two different scopes, deliberately.
        #
        # Counts describe the rows on screen: every store that returned any, so
        # the chart, the KPI strip and the table can never disagree about how
        # many customers there are. A partial store is flagged in the banner.
        #
        # The benchmark keeps the stricter scope. It compares lost against
        # still-active, and a store missing a contiguous date range contributes
        # a biased sample to both sides — that is a different kind of wrong from
        # an undercount, and it is the number the user acts on.
        shown = [r for r in results if r.get("ok")]
        # The comparison gates on cohort_complete, not on complete: a store
        # whose only fault is an imprecise order count for four named customers
        # still yields a representative sample of fulfilment timing, which is
        # all this compares. Gating on `complete` discarded the entire store.
        complete = [r for r in shown if r.get("cohort_complete")]
        all_lost = [c for r in shown for c in (r.get("lost") or [])]
        # Departures whose own section failed its cross-store check drop out of
        # the comparison; the rest of the store stays in. Previously one failed
        # probe took the whole store's sample with it.
        bench_lost = [c for r in complete for c in (r.get("lost") or [])
                      if c.get("customer_id") not in (r.get("biased_ids") or ())]
        bench_active = [c for r in complete for c in (r.get("active") or [])]

        # Arrivals against departures, by month. Both dates are the shop's own
        # calendar day, so an order placed late on the last evening of a month
        # is not bucketed into the next one. Both come from status-filtered
        # queries, so a cancelled or refunded order can neither make someone look
        # newly acquired nor stand in as their last purchase.
        #
        # Both series are complete for every month from the history floor
        # onwards, and NEITHER is complete before it. The scan selects customers
        # who ordered on or after the floor, so:
        #   - a departure needs its last order on or after the floor to be seen
        #     at all, which the classification already enforces; and
        #   - an arrival in a month on or after the floor necessarily ordered in
        #     the window, so it cannot be missed.
        # Before the floor the arrivals side would still find people — anyone
        # acquired years ago who is *still* ordering — but only the survivors.
        # Measured on one store with a 2025-06 floor: 63 months of green-only
        # bars back to 2020 built from 9,541 survivors, while everyone who
        # arrived and left inside those years was invisible. Plotting that
        # against a departures series that is structurally zero there invites
        # exactly the wrong reading, so those arrivals are counted out loud
        # instead of drawn.
        floor_month = history_from[:7] if history_from else None
        lost_by_month: Dict[str, int] = {}
        new_by_month: Dict[str, int] = {}
        arrivals_before_window = 0
        for c in all_lost:
            key = (c.get("last_order_local") or c.get("last_order_created_at") or "")[:7]
            if key:
                lost_by_month[key] = lost_by_month.get(key, 0) + 1
        for r in shown:
            for c in (r.get("lost") or []) + (r.get("active") or []):
                key = (c.get("first_order_local") or c.get("first_order_created_at") or "")[:7]
                if not key:
                    continue
                if floor_month and key < floor_month:
                    arrivals_before_window += 1
                    continue
                new_by_month[key] = new_by_month.get(key, 0) + 1

        # Same scope as the rows: a state breakdown that omitted a partial
        # store's customers would not add up to the table beneath it.
        merged_states: Dict[str, Dict[str, Any]] = {}
        for r in shown:
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
                "cohort_complete": r.get("cohort_complete"),
                "incomplete_reason": r.get("incomplete_reason"),
                "error": r.get("error"),
                "warnings": r.get("warnings") or [],
                "lost_count": len(r.get("lost") or []),
                "active_count": len(r.get("active") or []),
                "excluded_pre_existing": r.get("excluded_pre_existing"),
                "unknown_first_order": r.get("unknown_first_order", 0),
                "never_purchased": r.get("never_purchased", 0),
                "ordered_before_window": r.get("ordered_before_window", 0),
                "moved_total": r.get("moved_total", 0),
                "moved_breakdown": r.get("moved_breakdown", {}),
                "matched_by_name": r.get("matched_by_name", 0),
                "no_email": r.get("no_email", 0),
                "lost_timing": r.get("lost_timing") or _timing_summary(r.get("lost") or []),
                "active_timing": (r.get("active_timing")
                                  or _timing_summary(r.get("active") or [])),
                "sections_total": r.get("sections_total", 0),
                "sections_biased": r.get("sections_biased", 0),
                "departures_excluded_from_benchmark": r.get(
                    "departures_excluded_from_benchmark", 0),
                "moved_unresolved": r.get("moved_unresolved", 0),
                "cutoff": r.get("cutoff"),
                "shop_timezone": r.get("shop_timezone"),
            } for r in results],
            "benchmark": {
                "lost": _timing_summary(bench_lost),
                "active": _timing_summary(bench_active),
                "stores_included": len(complete),
                "stores_total": len(store_list),
                # Departures dropped from the lost side because their own
                # cross-store section failed. Named so the card can say what the
                # comparison excludes instead of quietly narrowing.
                "departures_excluded": sum(
                    r.get("departures_excluded_from_benchmark", 0) for r in complete),
            },
            "totals": {
                # None all the way through when the acquisition filter is off,
                # so the client suppresses the note rather than claiming that
                # zero customers were excluded by a filter that never ran.
                "excluded_pre_existing": (
                    sum(r.get("excluded_pre_existing") or 0 for r in shown)
                    if require_acquired else None),
                "moved_to_other_store": sum(r.get("moved_total", 0) for r in shown),
                "matched_by_name": sum(r.get("matched_by_name", 0) for r in shown),
                "never_purchased": sum(r.get("never_purchased", 0) for r in shown),
                "ordered_before_window": sum(r.get("ordered_before_window", 0) for r in shown),
                "no_email": sum(r.get("no_email", 0) for r in shown),
                "unknown_first_order": sum(r.get("unknown_first_order", 0) for r in shown),
                # Kept in the report but left off the chart — see by_month above.
                "arrivals_before_window": arrivals_before_window,
                "lost_customers": len(all_lost),
                # No revenue total. It summed Shopify's LIFETIME amountSpent, so it
                # answered "what have these people ever spent with us", not "what
                # did we lose" — every order they placed before the window was in
                # it. There is no honest reading of the number, so it is gone
                # rather than relabelled.
                # The handful of customers whose count is an upper bound are
                # dropped rather than allowed to drag the median up.
                "median_orders": _median([
                    float(c["orders_count"]) for c in all_lost
                    if c.get("orders_count_exact", True)]),
                "currency": (all_lost[0]["currency"] if all_lost else "USD"),
            },
            # Same scope as the rows and the chart's "new" series, so the modal
            # and the bars above it can never disagree about the cohort.
            "arrivals": _merge_arrivals([r.get("arrival") for r in shown]),
            # A continuous spine, not just the months that happen to have a
            # figure: over a long history a month with neither arrivals nor
            # departures would otherwise vanish from the series and the x-axis
            # would silently compress, putting non-adjacent months side by side.
            #
            # `judgeable` says whether a month has been measured at all. Nobody
            # counts as lost until they have been silent for the full period, so
            # the months AFTER the cutoff month are structurally empty — not a
            # collapse in churn — and are flagged false.
            #
            # The cutoff's own month is judgeable but `partial`: someone who went
            # quiet early in it has already been silent long enough, someone late
            # in it has not. So it holds real departures and its count will still
            # rise. Marking it unjudgeable would hide those departures and make the
            # chart claim nobody left that month, which is measurably false.
            "by_month": [
                {
                    "month": m,
                    "count": lost_by_month.get(m, 0),
                    "new": new_by_month.get(m, 0),
                    "judgeable": m <= cutoff_month,
                    "partial": m == cutoff_month,
                }
                for m in _by_month_spine(
                    lost_by_month, new_by_month,
                    # The cutoff plus the silence period is, by construction,
                    # the latest shop's current month.
                    _plus_months(report_cutoff, silent_months)[:7])
            ],
            "window": window,
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
    result = None
    synced_map = await asyncio.to_thread(shopify_sync.get_synced_stores)
    if store.id in synced_map:
        # A local read failing is a code/data problem; the live API still
        # works — which is only true if an EXCEPTION also falls through, not
        # just an ok:False result.
        try:
            result = await lost_customers_local.recent_orders(
                store.id, request.customer_id, request.limit or 5)
        except Exception as e:
            print(f"[SHOPIFY-ANALYTICS] local customer-detail failed, using live: {e}")
            result = None
        if result is not None and not result.get("ok"):
            result = None
    if result is None:
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

    A one-month range — which is what a month drill-down sends — returns that
    single month, and the `max(1, ...)` floor below means the page budget cannot
    drop it however busy the store is. The real ceiling then becomes
    _BASELINE_MAX_PAGES_PER_WINDOW inside fetch_baseline_order_items, i.e. up to
    15,000 orders of full within-month coverage, which is exactly the unbiased
    comparison this function exists to produce.
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
    # Clamped to the range. For any span of 15-27 days — a partial-month drill —
    # mid + _RATE_PROBE_DAYS overshoots the end, so the rate would be measured
    # partly outside the period it is meant to describe.
    probe_end = min(mid + timedelta(days=_RATE_PROBE_DAYS), e)
    return (mid.isoformat(), probe_end.isoformat(), max(1, (probe_end - mid).days))


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
                "barcodes": set(),
                "variants": {},
            })
            if item.get("barcode"):
                entry["barcodes"].add(item["barcode"])
            entry["quantity"] += item.get("quantity") or 0
            if key not in seen_products:
                entry["orders"] += 1
                seen_products.add(key)

            # Barcode first so a variant also matches across stores.
            vkey = item.get("barcode") or item.get("sku") or item.get("variant_title") or "—"
            v = entry["variants"].setdefault(vkey, {
                "title": item.get("variant_title") or "",
                "sku": item.get("sku") or "",
                "barcode": item.get("barcode") or "",
                "orders": 0,
                "quantity": 0,
            })
            v["quantity"] += item.get("quantity") or 0
            if (key, vkey) not in seen_variants:
                v["orders"] += 1
                seen_variants.add((key, vkey))

    return per_product, len(orders), excluded_lines


def _link_products_across_stores(per_store: List[Dict[str, Any]]) -> tuple:
    """
    Decide which per-store products are the same product.

    Shopify product ids are per-store, and the same item is frequently titled
    differently in each shop ("Kentucky Select Red" vs "Kentucky Select Full
    Flavor"), so neither id nor title can match across stores. The variant
    barcode is the only shared identifier — measured at 91% coverage on line
    items, with over a thousand barcodes common to a single pair of stores.

    Products are joined through the barcodes they share, so a product still
    merges when its stores list only partly overlapping variants. Returns
    (local key -> canonical key, canonical key -> display title).
    """
    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    def node(store_id, key) -> str:
        return f"p|{store_id}|{key}"

    for ps in per_store:
        sid = (ps.get("store") or {}).get("id")
        for bucket in ("lost_products", "base_products"):
            for key, entry in (ps.get(bucket) or {}).items():
                n = node(sid, key)
                find(n)
                for bc in entry.get("barcodes") or ():
                    union(n, f"bc|{bc}")

    mapping: Dict[tuple, str] = {}
    # Title chosen by order weight so the merged row carries the name attached
    # to the most real purchases rather than whichever store sorted first.
    titles: Dict[str, Dict[str, int]] = {}
    for ps in per_store:
        sid = (ps.get("store") or {}).get("id")
        for bucket, weighted in (("lost_products", True), ("base_products", False)):
            for key, entry in (ps.get(bucket) or {}).items():
                canon = find(node(sid, key))
                mapping[(sid, key)] = canon
                if weighted:
                    t = titles.setdefault(canon, {})
                    t[entry["title"]] = t.get(entry["title"], 0) + entry["orders"]

    labels = {
        canon: max(sorted(counts), key=lambda t: counts[t])
        for canon, counts in titles.items() if counts
    }
    return mapping, labels


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
        # An inverted or empty baseline window is not a harmless no-op here: it
        # makes _baseline_months return nothing, so no ordinary orders are
        # sampled and EVERY product comes back flagged "only in lost customers'
        # orders" — the strongest churn signal this report can emit, produced
        # entirely by a bad date pair.
        if request.active_since >= request.silent_since:
            yield f"event: error\ndata: {json.dumps({'message': 'Baseline window start must be earlier than its end'})}\n\n"
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

        # Same routing rule as the report itself: a synced store is analysed
        # from local line items, everything else from the live API.
        lp_synced = await asyncio.to_thread(shopify_sync.get_synced_stores)

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

                is_local = w["id"] in lp_synced
                local_tz = (lp_synced.get(w["id"]) or {}).get("shop_timezone")

                if is_local:
                    last = await lost_customers_local.orders_line_items(
                        w["id"], w["order_ids"])
                else:
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
                if is_local:
                    cnt = await lost_customers_local.count_completed_orders(
                        w["id"], local_tz, pstart, pend)
                    if cnt:
                        rate = cnt / max(1, pdays)
                else:
                    ok_c, _err_c, cnt = await count_orders(
                        shop_domain=w["shop_domain"], admin_api_key=w["admin_api_key"],
                        query=f"created_at:>={pstart} created_at:<{pend} {ANALYSIS_ORDER_FILTER}",
                        api_version=w["api_version"],
                    )
                    if ok_c and cnt:
                        rate = cnt / max(1, pdays)
                windows = _baseline_months(
                    request.active_since, request.silent_since, rate)

                if is_local:
                    base = await lost_customers_local.baseline_order_items(
                        w["id"], local_tz, windows)
                else:
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

        canon_of, canon_titles = _link_products_across_stores(per_store)

        merged: Dict[Any, Dict[str, Any]] = {}
        for ps in per_store:
            sid = (ps.get("store") or {}).get("id")
            for key, entry in ps["lost_products"].items():
                ckey = canon_of.get((sid, key), key)
                tgt = merged.setdefault(ckey, {
                    "key": str(ckey),
                    # Ids are per-store, so a merged row has no single one.
                    "product_id": entry["product_id"],
                    "title": canon_titles.get(ckey) or entry["title"],
                    "deleted": entry["deleted"],
                    "orders": 0, "quantity": 0, "variants": {},
                })
                tgt["orders"] += entry["orders"]
                tgt["quantity"] += entry["quantity"]
                for vk, v in entry["variants"].items():
                    tv = tgt["variants"].setdefault(vk, {
                        "title": v["title"], "sku": v["sku"],
                        "barcode": v.get("barcode", ""), "orders": 0, "quantity": 0,
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
                sid = (ps.get("store") or {}).get("id")
                # Sum every local product that maps to this canonical one, or a
                # store whose title differs would contribute nothing.
                b_orders_s = sum(
                    e["orders"] for lk, e in ps["base_products"].items()
                    if canon_of.get((sid, lk), lk) == key
                )
                share = b_orders_s / ps["n_base"]
                seen_base += b_orders_s
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
            # A zero expectation is not infinity, so it stays withheld and is
            # shown as "only here". No minimum order count: a comparison built
            # on few orders is shakier, but hiding it hid real products too.
            lift = None
            lift_raw = None
            if exp["raw"] > 0 and exp["adj"] > 0:
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



# ============================================================================
# Shopify Local Data Sync
#
# Downloads each Shopify store's full customer + order history (line items,
# fulfillments, tags, notes included) into PostgreSQL so reports can run from
# local SQL instead of live GraphQL. Full syncs go through the Bulk Operations
# API; repeat syncs paginate an updated_at delta. See shopify_sync_helper.py.
# ============================================================================

import shopify_sync_helper as shopify_sync
import lost_customers_local
import shopify_sales_local
from sqlalchemy import text as sa_text


def _load_sync_store(db: Session, store_id: int) -> Dict[str, Any]:
    store = db.query(Store).filter(
        Store.id == store_id, Store.store_type == StoreType.shopify,
    ).first()
    if not store or not store.shopify_connection:
        raise HTTPException(status_code=404, detail="Shopify store not found")
    conn = store.shopify_connection
    return {
        "id": store.id, "name": store.name,
        "shop_domain": conn.shop_domain,
        "admin_api_key": conn.admin_api_key,
        "api_version": conn.api_version,
    }


@app.get("/api/shopify-sync/status")
async def shopify_sync_status():
    return {"stores": await asyncio.to_thread(shopify_sync.get_sync_states)}


@app.post("/api/shopify-sync/{store_id}/stream")
async def shopify_sync_stream(
    store_id: int,
    request: ShopifySyncRequest,
    db: Session = Depends(get_db),
):
    store = _load_sync_store(db, store_id)

    # The anchor for an incremental run is the start of the last successful one.
    # No successful run yet -> the store has never fully synced -> force full.
    state_row = db.execute(
        sa_text(
            "SELECT last_completed_at, last_sync_started_at, status, heartbeat_at "
            "FROM shopify_sync_state WHERE store_id = :sid"
        ),
        {"sid": store_id},
    ).mappings().first()
    anchor = state_row["last_sync_started_at"] if state_row else None
    mode = request.mode
    if not state_row or state_row["last_completed_at"] is None or anchor is None:
        mode = "full"

    # Read-only pre-check so the common already-running case still gets a clean
    # 409. The authoritative claim happens INSIDE the stream: a claim taken
    # here would leak until the staleness takeover if the client vanished
    # before the response ever started, because a generator that is never
    # iterated never runs its finally.
    if (
        state_row and state_row["status"] == "running"
        and state_row["heartbeat_at"] is not None
        and (datetime.now(state_row["heartbeat_at"].tzinfo) - state_row["heartbeat_at"]).total_seconds() < 180
    ):
        raise HTTPException(status_code=409, detail="A sync is already running for this store")

    events: asyncio.Queue = asyncio.Queue()
    tracker = shopify_sync._BulkTracker()

    async def emit(kind: str, payload: Dict[str, Any]):
        events.put_nowait((kind, payload))

    async def worker(claim_token):
        try:
            summary = await shopify_sync.run_store_sync(
                store, mode, anchor, emit, tracker=tracker, claim_token=claim_token
            )
            await asyncio.to_thread(
                shopify_sync.release_sync, store_id,
                counts=summary["totals"], run_started=summary["run_started"],
                claim_token=claim_token,
            )
            events.put_nowait(("complete", {
                "mode": summary["mode"],
                "seconds": summary["seconds"],
                "synced": summary["synced"],
                "totals": summary["totals"],
            }))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            message = str(e)
            print(f"[SHOPIFY-SYNC] store {store_id} failed: {message}")
            try:
                await asyncio.to_thread(
                    shopify_sync.release_sync, store_id,
                    error=message[:500], claim_token=claim_token,
                )
            finally:
                events.put_nowait(("error", {"message": message}))

    async def generate() -> AsyncGenerator[str, None]:
        finished = False
        task = None
        claim_token = None
        try:
            claim_token = await asyncio.to_thread(shopify_sync.claim_sync, store_id, mode)
            if claim_token is None:
                # Lost the race between the pre-check and here.
                finished = True
                yield f"event: error\ndata: {json.dumps({'message': 'A sync is already running for this store'})}\n\n"
                return
            task = asyncio.create_task(worker(claim_token))
            yield f"event: progress\ndata: {json.dumps({'phase': 'starting', 'mode': mode, 'store_id': store_id, 'store_name': store['name']})}\n\n"
            while True:
                try:
                    kind, payload = await asyncio.wait_for(events.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                yield f"event: {kind}\ndata: {json.dumps(payload)}\n\n"
                if kind in ("complete", "error"):
                    finished = True
                    break
        finally:
            # A client disconnect surfaces as CancelledError inside the awaits
            # (uvicorn cancels the response task), NOT only as GeneratorExit —
            # so the cleanup lives in finally, keyed on whether the run ended
            # normally. Without this the claim stays "running" until the stale
            # heartbeat takeover, and the bulk op keeps exporting shop-side.
            if not finished and claim_token is not None:
                if task is not None:
                    task.cancel()
                if tracker.current_id:
                    asyncio.create_task(
                        shopify_sync.cancel_bulk_operation(store, tracker.current_id)
                    )
                asyncio.create_task(
                    asyncio.to_thread(
                        shopify_sync.release_sync, store_id,
                        error="cancelled", claim_token=claim_token,
                    )
                )
                print(f"[SHOPIFY-SYNC] store {store_id} sync cancelled by client")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ============================================================================
# Business Overview
#
# Executive dashboard: quotations in progress (DB_ADMIN), open / shipped
# invoices and revenue-cost-profit trends (configured "sales" MSSQL store),
# purchase orders (configured "purchases" MSSQL store) and Shopify revenue
# from the local mirror. Config lives in business_overview_config; DB_ADMIN
# still comes from settings.admin_store_id. Every resolver here is SOFT so a
# missing source degrades a widget (configured=False) instead of the page.
# ============================================================================
import business_overview_helper as bov
from zoneinfo import ZoneInfo as _BovZoneInfo


def _bov_config(db: Session) -> Optional[BusinessOverviewConfig]:
    return db.query(BusinessOverviewConfig).first()


def _bov_mssql_store(db: Session, store_id: Optional[int]) -> Optional[Store]:
    if not store_id:
        return None
    store = db.query(Store).filter(
        Store.id == store_id,
        Store.store_type == StoreType.mssql,
        Store.is_active == True,
    ).first()
    if not store or not store.mssql_connection:
        return None
    return store


def _bov_conn_kwargs(store: Store) -> Dict[str, Any]:
    c = store.mssql_connection
    return {"host": c.host, "port": c.port, "database": c.database_name,
            "username": c.username, "password": c.password}


def _bov_sales_store_ids(cfg: Optional[BusinessOverviewConfig]) -> List[int]:
    if not cfg:
        return []
    ids = list(cfg.sales_store_ids or [])
    if not ids and cfg.sales_store_id:          # legacy single-store rows
        ids = [cfg.sales_store_id]
    out: List[int] = []
    for i in ids:
        try:
            i = int(i)
        except (TypeError, ValueError):
            continue
        if i not in out:
            out.append(i)
    return out


def _bov_sales_stores(db: Session, cfg: Optional[BusinessOverviewConfig],
                      only_ids: Optional[Set[int]] = None) -> List[Store]:
    """Active MSSQL stores selected as sales/invoice sources (order preserved), optionally filtered."""
    out: List[Store] = []
    for sid in _bov_sales_store_ids(cfg):
        if only_ids is not None and sid not in only_ids:
            continue
        st = _bov_mssql_store(db, sid)
        if st is not None:
            out.append(st)
    return out


def _bov_parse_store_ids(store_ids: Optional[str]) -> Optional[Set[int]]:
    """CSV store-id filter from the query string. None = no filter."""
    if store_ids is None or not str(store_ids).strip():
        return None
    out: Set[int] = set()
    for part in str(store_ids).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"store_ids must be a comma-separated list of ids (got '{part}')")
    return out


def _bov_quotation_source_dbs(db: Session, only_ids: Optional[Set[int]]) -> Optional[List[str]]:
    """
    QuotationsInProgress.SourceDB holds the originating BackOffice database
    name, so a store filter maps to the database_name of every selected
    active MSSQL store. None = no filter; [] = filter selects no MSSQL store.
    """
    if only_ids is None:
        return None
    names: List[str] = []
    for st in db.query(Store).filter(Store.id.in_(list(only_ids)), Store.store_type == StoreType.mssql,
                                     Store.is_active == True).all():
        if st.mssql_connection and st.mssql_connection.database_name:
            names.append(st.mssql_connection.database_name)
    return names


def _bov_purchases_store(db: Session, cfg: Optional[BusinessOverviewConfig],
                         only_ids: Optional[Set[int]] = None) -> Tuple[Optional[Store], bool]:
    """(store, filtered_out) — filtered_out when the store exists but is outside the filter."""
    store = _bov_mssql_store(db, cfg.purchases_store_id if cfg else None)
    if store is None:
        return None, False
    if only_ids is not None and store.id not in only_ids:
        return store, True
    return store, False


def _bov_cost_conn(db: Session, cfg: Optional[BusinessOverviewConfig]):
    """
    The S2S cost source = the Item Tracker S2S store (master items DB).
    Shopify lines are always costed from it (Items_tbl.UnitPriceC by default,
    UnitCost in "S2S cost" mode); in S2S mode BackOffice lines use it too.
    """
    return _resolve_item_tracker_s2s_conn(db)


BOV_COST_MODES = ("default", "s2s")


def _bov_cost_mode(cost_mode: Optional[str]) -> str:
    m = (cost_mode or "default").strip().lower()
    if m not in BOV_COST_MODES:
        raise HTTPException(status_code=400, detail="cost_mode must be default or s2s")
    return m


def _bov_shopify_cost_field(cost_mode: str) -> str:
    """Items_tbl column used for Shopify unit cost: UnitPriceC by default, UnitCost in S2S mode."""
    return "unit_cost" if cost_mode == "s2s" else "unit_delivery_b"


async def _bov_fanout(stores: List[Store], make_coro) -> List[Tuple[Store, bool, Optional[str], Dict[str, Any]]]:
    """Run make_coro(store) for every store in parallel; exceptions become (ok=False, err)."""
    results = await asyncio.gather(*[make_coro(st) for st in stores], return_exceptions=True)
    out: List[Tuple[Store, bool, Optional[str], Dict[str, Any]]] = []
    for st, res in zip(stores, results):
        if isinstance(res, Exception):
            out.append((st, False, str(res), {}))
        else:
            ok, err, payload = res
            out.append((st, bool(ok), err, payload or {}))
    return out


def _bov_store_statuses(results, count_of=None, amount_of=None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for st, ok, err, p in results:
        row: Dict[str, Any] = {"store_id": st.id, "store_name": st.name, "error": (None if ok else (err or "failed"))}
        if ok and count_of is not None:
            try:
                row["count"] = int(count_of(p) or 0)
            except Exception:
                row["count"] = None
        if ok and amount_of is not None:
            try:
                row["amount"] = round(float(amount_of(p) or 0), 2)
            except Exception:
                row["amount"] = None
        out.append(row)
    return out


def _bov_merge_daily(dicts: List[Dict[Any, Dict[str, float]]]) -> Dict[Any, Dict[str, float]]:
    merged: Dict[Any, Dict[str, float]] = {}
    for d in dicts:
        for k, vals in (d or {}).items():
            slot = merged.setdefault(k, {})
            for f, v in vals.items():
                slot[f] = slot.get(f, 0.0) + float(v or 0)
    return merged


def _bov_shopify_stores(db: Session, cfg: Optional[BusinessOverviewConfig],
                        only_ids: Optional[Set[int]] = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for sid in (cfg.shopify_store_ids if cfg else []) or []:
        if only_ids is not None and int(sid) not in only_ids:
            continue
        st = db.query(Store).filter(
            Store.id == sid, Store.store_type == StoreType.shopify, Store.is_active == True
        ).first()
        if st and st.shopify_connection:
            sc = st.shopify_connection
            out.append({"id": st.id, "name": st.name, "shop_domain": sc.shop_domain,
                        "admin_api_key": sc.admin_api_key, "api_version": sc.api_version or "2025-01"})
    return out


def _bov_excluded_names(db: Session) -> Tuple[List[str], List[str]]:
    """(excluded_sales_names, excluded_return_names) — same semantics as the Sales report."""
    sales_names: List[str] = []
    return_names: List[str] = []
    for excl in db.query(SalesExclusion).all():
        if excl.void_status is None or excl.void_status == 0:
            sales_names.append(excl.business_name)
        if excl.void_status is None:
            return_names.append(excl.business_name)
    return sales_names, return_names


def _bov_shopify_exclusions(db: Session) -> List[Dict[str, Any]]:
    """Excluded Shopify products (store_id None = every store) for the helper queries."""
    return [{"id": e.id, "store_id": e.store_id, "variant_shopify_id": e.variant_shopify_id,
             "product_shopify_id": e.product_shopify_id, "barcode": e.barcode}
            for e in db.query(BusinessOverviewShopifyExclusion).all()]


def _bov_po_exclusions(db: Session, store_id: int) -> List[BusinessOverviewPoProductExclusion]:
    """Excluded PO products (non-merchandise lines like shipping/discounts) for one purchases store."""
    return db.query(BusinessOverviewPoProductExclusion).filter(
        BusinessOverviewPoProductExclusion.store_id == store_id).all()


def _bov_po_exclusion_ids(db: Session, store_id: int) -> List[int]:
    return [e.product_id for e in _bov_po_exclusions(db, store_id)]


def _bov_tz(cfg: Optional[BusinessOverviewConfig]) -> str:
    return (cfg.timezone if cfg and cfg.timezone else "America/Chicago")


def _bov_period(cfg: Optional[BusinessOverviewConfig], preset: Optional[str],
                date_from: Optional[str], date_to: Optional[str]) -> bov.Period:
    try:
        return bov.resolve_period(date_from, date_to, preset, _bov_tz(cfg))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _bov_check_bucket(bucket: Optional[str]) -> str:
    b = (bucket or "day").strip().lower()
    if b not in bov.BUCKETS:
        raise HTTPException(status_code=400, detail="bucket must be day, week or month")
    return b


def _bov_series_points(rows: List[Dict[str, Any]]) -> List[BOVSeriesPoint]:
    return [BOVSeriesPoint(**r) for r in rows]


def _bov_config_response(db: Session, cfg: Optional[BusinessOverviewConfig]) -> BusinessOverviewConfigResponse:
    sales_stores = _bov_sales_stores(db, cfg)
    purchases_store = _bov_mssql_store(db, cfg.purchases_store_id if cfg else None)
    shopify_ids = list((cfg.shopify_store_ids if cfg else []) or [])
    shopify_names: List[str] = []
    for sid in shopify_ids:
        st = db.query(Store).filter(Store.id == sid).first()
        if st:
            shopify_names.append(st.name)
    admin_store = _resolve_admin_store_soft(db)
    cost_conn = _bov_cost_conn(db, cfg)
    cost_store = db.query(Store).filter(Store.id == cost_conn.store_id).first() if cost_conn else None
    return BusinessOverviewConfigResponse(
        id=cfg.id if cfg else 0,
        configured=bool(sales_stores or purchases_store or shopify_ids),
        sales_store_ids=[st.id for st in sales_stores],
        sales_store_names=[st.name for st in sales_stores],
        sales_store_id=(sales_stores[0].id if sales_stores else None),
        sales_store_name=(sales_stores[0].name if sales_stores else None),
        purchases_store_id=cfg.purchases_store_id if cfg else None,
        purchases_store_name=purchases_store.name if purchases_store else None,
        shopify_store_ids=shopify_ids,
        shopify_store_names=shopify_names,
        quotation_statuses=list((cfg.quotation_statuses if cfg else BOV_DEFAULT_QUOTATION_STATUSES) or []),
        timezone=_bov_tz(cfg),
        alert_rules=bov_merge_alert_rules(cfg.alert_rules if cfg else None),
        admin_store_id=admin_store.id if admin_store else None,
        admin_store_name=admin_store.name if admin_store else None,
        cost_store_id=cost_store.id if cost_store else None,
        cost_store_name=cost_store.name if cost_store else None,
        sales_exclusions_count=db.query(SalesExclusion).count(),
        created_at=cfg.created_at if cfg else None,
        updated_at=cfg.updated_at if cfg else None,
    )


@app.get("/api/business-overview/config", response_model=BusinessOverviewConfigResponse)
def get_business_overview_config(db: Session = Depends(get_db)):
    return _bov_config_response(db, _bov_config(db))


@app.post("/api/business-overview/config", response_model=BusinessOverviewConfigResponse)
def save_business_overview_config(data: BusinessOverviewConfigCreate, db: Session = Depends(get_db)):
    sales_ids: List[int] = []
    for sid in list(data.sales_store_ids or []) + ([data.sales_store_id] if data.sales_store_id else []):
        if sid and sid not in sales_ids:
            sales_ids.append(sid)
    for sid, label in [(i, "sales") for i in sales_ids] + [(data.purchases_store_id, "purchases")]:
        if sid and not db.query(Store).filter(Store.id == sid, Store.store_type == StoreType.mssql).first():
            raise HTTPException(status_code=400, detail=f"Invalid {label} store ID: {sid} (must be an MSSQL store)")
    for sid in data.shopify_store_ids:
        if not db.query(Store).filter(Store.id == sid, Store.store_type == StoreType.shopify).first():
            raise HTTPException(status_code=400, detail=f"Invalid Shopify store ID: {sid}")
    tz = (data.timezone or "").strip() or "America/Chicago"
    try:
        _BovZoneInfo(tz)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Unknown timezone: {tz}")
    statuses: List[str] = []
    for s in data.quotation_statuses or []:
        s2 = (s or "").strip()
        if s2 and s2.lower() not in {x.lower() for x in statuses}:
            statuses.append(s2)
    cfg = _bov_config(db)
    # Alert rules: partial overrides are merged over the current (or default)
    # rules, validated, and stored merged so the row is always complete.
    if data.alert_rules is not None:
        base_rules = bov_merge_alert_rules(cfg.alert_rules if cfg else None)
        for k, v in (data.alert_rules or {}).items():
            if k in base_rules and isinstance(v, dict):
                for kk, vv in v.items():
                    if kk == "stores":
                        continue
                    if kk in base_rules[k]:
                        base_rules[k][kk] = vv
                if "stores" in v:
                    # per-store overrides replace the stored set for that rule
                    if isinstance(v["stores"], dict) and v["stores"]:
                        base_rules[k]["stores"] = v["stores"]
                    else:
                        base_rules[k].pop("stores", None)
        base_rules = bov_merge_alert_rules(base_rules)
        err = bov_validate_alert_rules(base_rules)
        if err:
            raise HTTPException(status_code=400, detail=f"Invalid alert rules — {err}")
        new_rules = base_rules
    else:
        new_rules = None

    if cfg:
        cfg.sales_store_ids = sales_ids
        cfg.sales_store_id = sales_ids[0] if sales_ids else None
        cfg.purchases_store_id = data.purchases_store_id
        cfg.shopify_store_ids = list(dict.fromkeys(data.shopify_store_ids))
        cfg.quotation_statuses = statuses
        cfg.timezone = tz
        if new_rules is not None:
            cfg.alert_rules = new_rules
    else:
        cfg = BusinessOverviewConfig(
            sales_store_ids=sales_ids,
            sales_store_id=sales_ids[0] if sales_ids else None,
            purchases_store_id=data.purchases_store_id,
            shopify_store_ids=list(dict.fromkeys(data.shopify_store_ids)),
            quotation_statuses=statuses,
            timezone=tz,
            alert_rules=new_rules or {},
        )
        db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return _bov_config_response(db, cfg)


@app.get("/api/business-overview/config/options", response_model=BusinessOverviewConfigOptions)
async def get_business_overview_config_options(db: Session = Depends(get_db)):
    synced = await asyncio.to_thread(shopify_sync.get_synced_stores)
    mssql: List[BOVStoreOption] = []
    shopify: List[BOVStoreOption] = []
    for st in db.query(Store).order_by(Store.name).all():
        if st.store_type == StoreType.mssql and st.mssql_connection:
            mssql.append(BOVStoreOption(id=st.id, name=st.name, store_type="mssql", is_active=bool(st.is_active),
                                        database_name=st.mssql_connection.database_name))
        elif st.store_type == StoreType.shopify and st.shopify_connection:
            info = synced.get(st.id) or {}
            last = info.get("last_completed_at")
            shopify.append(BOVStoreOption(
                id=st.id, name=st.name, store_type="shopify", is_active=bool(st.is_active),
                synced=bool(info),
                last_synced_at=(last.isoformat() if hasattr(last, "isoformat") else (str(last) if last else None)),
                shop_timezone=info.get("shop_timezone"),
            ))
    statuses: List[str] = []
    admin_store = _resolve_admin_store_soft(db)
    if admin_store is not None:
        ok, _err, vals = await bov.quotation_status_options_async(**_bov_conn_kwargs(admin_store))
        if ok:
            statuses = vals
    return BusinessOverviewConfigOptions(
        mssql_stores=mssql, shopify_stores=shopify, quotation_statuses=statuses,
        admin_configured=admin_store is not None,
        admin_store_name=admin_store.name if admin_store else None,
    )


# ---- building blocks shared by /summary and the per-widget endpoints -------

async def _bov_quotations_block(db: Session, cfg, include_list: bool, limit: int = 500,
                                sort_by: str = "start_date", sort_order: str = "desc",
                                only_ids: Optional[Set[int]] = None, cost_mode: str = "default") -> Dict[str, Any]:
    admin_store = _resolve_admin_store_soft(db)
    statuses = list((cfg.quotation_statuses if cfg else BOV_DEFAULT_QUOTATION_STATUSES) or [])
    if admin_store is None:
        return {"configured": False, "statuses": statuses}
    base = {"configured": True, "store_id": admin_store.id, "store_name": admin_store.name, "statuses": statuses}
    source_dbs = _bov_quotation_source_dbs(db, only_ids)
    if source_dbs is not None and not source_dbs:
        base.update({"filtered_out": True, "count": 0, "total_amount": 0.0, "total_qty": 0.0,
                     "quotations": [], "limit": limit, "truncated": False})
        return base
    excl_names, _ = _bov_excluded_names(db)
    ok, err, payload = await bov.quotations_in_progress_async(
        **_bov_conn_kwargs(admin_store), statuses=statuses, limit=limit,
        sort_by=sort_by, sort_order=sort_order, include_list=include_list, source_dbs=source_dbs,
        excluded_names=excl_names, include_units=include_list)
    if not ok:
        base["error"] = err
        return base
    if include_list:
        try:
            await _bov_cost_quotations(db, cfg, payload.get("quotations") or [], payload.get("units_by_upc") or {}, cost_mode)
        except Exception as e:
            print(f"[BOV] quotation costing failed: {e}")
    payload.pop("units_by_upc", None)
    base.update(payload)
    return base


async def _bov_recost_invoice_results(db: Session, cfg, results) -> None:
    """S2S-cost every listed invoice across fanned-out store payloads (one S2S lookup)."""
    lookup = _bov_make_cost_lookup(db, cfg, "unit_cost")
    upcs: Set[str] = set()
    for _st, ok, _err, p in results:
        if ok:
            for lines in (p.get("units_by_upc") or {}).values():
                upcs.update(u for (u, _n) in lines if u)
    unit_costs = await lookup(sorted(upcs)) if (upcs and getattr(lookup, "configured", False)) else {}
    for _st, ok, _err, p in results:
        if ok:
            bov.recost_rows_s2s(list(p.get("invoices") or []), p.get("units_by_upc") or {}, "invoice_id", unit_costs)


async def _bov_recost_list_s2s(db: Session, cfg, rows: List[Dict[str, Any]],
                               units_by_key: Dict[Any, List[Tuple[str, float]]], key_field: str) -> None:
    """S2S cost mode for list rows: Σ units × S2S Items_tbl.UnitCost by UPC."""
    lookup = _bov_make_cost_lookup(db, cfg, "unit_cost")
    upcs = sorted({u for lines in units_by_key.values() for (u, _n) in lines if u})
    unit_costs = await lookup(upcs) if (upcs and getattr(lookup, "configured", False)) else {}
    bov.recost_rows_s2s(rows, units_by_key, key_field, unit_costs)


async def _bov_cost_quotations(db: Session, cfg, quotations: List[Dict[str, Any]],
                               units_by_qn: Dict[str, List[Tuple[str, float]]], cost_mode: str) -> None:
    """
    Quotation cost: default = the originating store's own Items_tbl.UnitCost
    (SourceDB → sales store by database_name); s2s = S2S Items_tbl.UnitCost.
    Revenue = QuotationTotal.
    """
    if not quotations:
        return
    if cost_mode == "s2s":
        await _bov_recost_list_s2s(db, cfg, quotations, units_by_qn, "quotation_number")
        return
    by_db: Dict[str, Any] = {}
    for st in db.query(Store).filter(Store.store_type == StoreType.mssql, Store.is_active == True).all():
        if st.mssql_connection and st.mssql_connection.database_name:
            by_db[st.mssql_connection.database_name.strip().lower()] = st.mssql_connection
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for q in quotations:
        groups.setdefault((q.get("source_db") or "").strip().lower(), []).append(q)

    async def _one(src: str, rows: List[Dict[str, Any]]):
        conn = by_db.get(src)
        sub_units = {r["quotation_number"]: units_by_qn.get(r["quotation_number"], []) for r in rows}
        if conn is None:
            bov.recost_rows_s2s(rows, sub_units, "quotation_number", {})
            return
        lookup = _bov_make_conn_cost_lookup(conn, "unit_cost")
        upcs = sorted({u for lines in sub_units.values() for (u, _n) in lines if u})
        unit_costs = await lookup(upcs) if upcs else {}
        bov.recost_rows_s2s(rows, sub_units, "quotation_number", unit_costs)

    await asyncio.gather(*[_one(src, rows) for src, rows in groups.items()], return_exceptions=True)


def _bov_tag_rows(rows: List[Dict[str, Any]], store: Store) -> List[Dict[str, Any]]:
    for r in rows:
        r["store_id"] = store.id
        r["store_name"] = store.name
    return rows


def _bov_multi_base(stores: List[Store], results, extra: Optional[Dict[str, Any]] = None,
                    count_of=None, amount_of=None) -> Dict[str, Any]:
    """Common block header for fanned-out sales-store blocks."""
    base: Dict[str, Any] = {"configured": True, "stores": _bov_store_statuses(results, count_of, amount_of)}
    if len(stores) == 1:
        base["store_id"] = stores[0].id
        base["store_name"] = stores[0].name
    else:
        base["store_name"] = ", ".join(st.name for st in stores)
    failures = [f"{st.name}: {err}" for st, ok, err, _p in results if not ok]
    if failures and len(failures) == len(results):
        base["error"] = "; ".join(failures)
    if extra:
        base.update(extra)
    return base


async def _bov_open_invoices_block(db: Session, cfg, include_list: bool, date_from=None, date_to=None,
                                   limit: int = 500, sort_by: str = "invoice_date", sort_order: str = "desc",
                                   only_ids: Optional[Set[int]] = None, cost_mode: str = "default") -> Dict[str, Any]:
    if not _bov_sales_stores(db, cfg):
        return {"configured": False}
    stores = _bov_sales_stores(db, cfg, only_ids)
    if not stores:
        return {"configured": True, "filtered_out": True, "invoices": [], "limit": limit}
    today = bov.today_in_tz(_bov_tz(cfg))
    date_to_excl = bov.upper_bound(bov.parse_ymd(date_to)) if date_to else None
    excl_names, _ = _bov_excluded_names(db)
    results = await _bov_fanout(stores, lambda st: bov.open_invoices_async(
        **_bov_conn_kwargs(st), date_from=date_from, date_to_excl=date_to_excl,
        limit=limit, sort_by=sort_by, sort_order=sort_order, include_list=include_list, today=today,
        excluded_names=excl_names, cost_mode=cost_mode))
    base = _bov_multi_base(stores, results, None,
                           count_of=lambda p: p.get("count"), amount_of=lambda p: p.get("total_amount"))
    if base.get("error"):
        return base
    if include_list and cost_mode == "s2s":
        await _bov_recost_invoice_results(db, cfg, results)
    invoices: List[Dict[str, Any]] = []
    count = 0
    total_amount = 0.0
    total_qty = 0.0
    aging = {"0-1": 0, "2-3": 0, "4+": 0}
    oldest: Optional[str] = None
    oldest_age: Optional[int] = None
    truncated = False
    for st, ok, _err, p in results:
        if not ok:
            continue
        invoices.extend(_bov_tag_rows(list(p.get("invoices") or []), st))
        count += int(p.get("count") or 0)
        total_amount += float(p.get("total_amount") or 0)
        total_qty += float(p.get("total_qty") or 0)
        for k, v in (p.get("aging") or {}).items():
            aging[k] = aging.get(k, 0) + int(v or 0)
        od = p.get("oldest_invoice_date")
        if od and (oldest is None or od < oldest):
            oldest = od
            oldest_age = p.get("oldest_age_days")
        truncated = truncated or bool(p.get("truncated"))
    base.update({
        "invoices": invoices, "count": count, "total_amount": round(total_amount, 2),
        "total_qty": total_qty, "oldest_invoice_date": oldest, "oldest_age_days": oldest_age,
        "aging": aging, "limit": limit, "truncated": truncated,
    })
    return base


def _bov_range_block_from_daily(daily: Dict[Any, Dict[str, float]], period: bov.Period, bucket: str,
                                fields: List[str]) -> Dict[str, Any]:
    cur = bov.sum_daily(daily, period.start, period.end, fields)
    prev = bov.sum_daily(daily, period.prev_start, period.prev_end, fields)
    return {
        "period": period.as_dict(),
        "totals": bov.range_totals(cur, prev),
        "bucket": bucket,
        "series": bov.rollup_daily(daily, period.start, period.end, bucket, fields),
        "previous_series": bov.rollup_daily(daily, period.prev_start, period.prev_end, bucket, fields),
    }


async def _bov_shipped_block(db: Session, cfg, period: bov.Period, bucket: str, include_list: bool,
                             limit: int = 500, sort_by: str = "ship_date", sort_order: str = "desc",
                             only_ids: Optional[Set[int]] = None, cost_mode: str = "default") -> Dict[str, Any]:
    if not _bov_sales_stores(db, cfg):
        return {"configured": False, "period": period.as_dict()}
    stores = _bov_sales_stores(db, cfg, only_ids)
    if not stores:
        return {"configured": True, "filtered_out": True, "period": period.as_dict(), "bucket": bucket,
                "invoices": [], "limit": limit}
    excl_names, _ = _bov_excluded_names(db)
    results = await _bov_fanout(stores, lambda st: bov.shipped_invoices_async(
        **_bov_conn_kwargs(st),
        date_from=period.start.isoformat(), date_to_excl=period.end_excl,
        series_from=period.prev_start.isoformat(),
        limit=limit, sort_by=sort_by, sort_order=sort_order, include_list=include_list,
        excluded_names=excl_names, cost_mode=cost_mode))
    if include_list and cost_mode == "s2s":
        await _bov_recost_invoice_results(db, cfg, results)
    def _cur_sum(p, field):
        return bov.sum_daily(p.get("daily") or {}, period.start, period.end, [field])[field]
    base = _bov_multi_base(stores, results, {"period": period.as_dict(), "bucket": bucket},
                           count_of=lambda p: _cur_sum(p, "invoices"), amount_of=lambda p: _cur_sum(p, "total_amount"))
    if base.get("error"):
        return base
    daily = _bov_merge_daily([p.get("daily") or {} for _st, ok, _e, p in results if ok])
    base.update(_bov_range_block_from_daily(daily, period, bucket,
                                            ["invoices", "total_amount", "total_qty", "boxes"]))
    invoices: List[Dict[str, Any]] = []
    truncated = False
    for st, ok, _err, p in results:
        if not ok:
            continue
        rows = _bov_tag_rows(list(p.get("invoices") or []), st)
        invoices.extend(rows)
        truncated = truncated or (include_list and len(rows) >= int(p.get("limit", limit)))
    base["invoices"] = invoices
    base["limit"] = limit
    base["truncated"] = truncated
    return base


async def _bov_incoming_block(db: Session, cfg, include_list: bool, limit: int = 500,
                              sort_by: str = "po_date", sort_order: str = "desc",
                              only_ids: Optional[Set[int]] = None) -> Dict[str, Any]:
    store, filtered_out = _bov_purchases_store(db, cfg, only_ids)
    if store is None:
        return {"configured": False}
    if filtered_out:
        return {"configured": True, "filtered_out": True, "store_id": store.id, "store_name": store.name,
                "purchase_orders": [], "limit": limit}
    ok, err, payload = await bov.incoming_purchases_async(
        **_bov_conn_kwargs(store), limit=limit, sort_by=sort_by, sort_order=sort_order, include_list=include_list,
        excluded_product_ids=_bov_po_exclusion_ids(db, store.id) or None)
    base = {"configured": True, "store_id": store.id, "store_name": store.name}
    if not ok:
        base["error"] = err
        return base
    base.update(payload)
    return base


async def _bov_placed_block(db: Session, cfg, include_list: bool,
                            limit: int = 500, sort_by: str = "po_date", sort_order: str = "desc",
                            only_ids: Optional[Set[int]] = None) -> Dict[str, Any]:
    """POs placed but not yet vendor-confirmed (Status 0, blank PoHeader) — snapshot, no date filter."""
    store, filtered_out = _bov_purchases_store(db, cfg, only_ids)
    if store is None:
        return {"configured": False}
    if filtered_out:
        return {"configured": True, "filtered_out": True, "store_id": store.id, "store_name": store.name,
                "purchase_orders": [], "limit": limit}
    ok, err, payload = await bov.placed_unconfirmed_async(
        **_bov_conn_kwargs(store), limit=limit, sort_by=sort_by, sort_order=sort_order, include_list=include_list,
        excluded_product_ids=_bov_po_exclusion_ids(db, store.id) or None)
    base = {"configured": True, "store_id": store.id, "store_name": store.name}
    if not ok:
        base["error"] = err
        return base
    base.update(payload)
    return base


async def _bov_received_block(db: Session, cfg, period: bov.Period, bucket: str, include_list: bool,
                              limit: int = 500, only_ids: Optional[Set[int]] = None) -> Dict[str, Any]:
    store, filtered_out = _bov_purchases_store(db, cfg, only_ids)
    if store is None:
        return {"configured": False, "period": period.as_dict()}
    if filtered_out:
        return {"configured": True, "filtered_out": True, "store_id": store.id, "store_name": store.name,
                "period": period.as_dict(), "bucket": bucket, "purchase_orders": [], "limit": limit}
    ok, err, payload = await bov.received_in_range_async(
        **_bov_conn_kwargs(store),
        date_from=period.start.isoformat(), date_to_excl=period.end_excl,
        series_from=period.prev_start.isoformat(),
        limit=limit, include_list=include_list,
        excluded_product_ids=_bov_po_exclusion_ids(db, store.id) or None)
    base = {"configured": True, "store_id": store.id, "store_name": store.name, "period": period.as_dict(), "bucket": bucket}
    if not ok:
        base["error"] = err
        return base
    base.update(_bov_range_block_from_daily(payload.get("daily") or {}, period, bucket,
                                            ["purchase_orders", "qty", "value"]))
    pos = payload.get("purchase_orders") or []
    base["purchase_orders"] = pos
    base["limit"] = payload.get("limit", limit)
    base["truncated"] = include_list and len(pos) >= int(payload.get("limit", limit))
    return base


def _bov_make_cost_lookup(db: Session, cfg, field: str = "unit_delivery_b"):
    """
    Memoised async barcode -> unit cost lookup against the S2S store.
    `field` picks the Items_tbl column: 'unit_delivery_b' = UnitPriceC (Shopify default),
    'unit_cost' = UnitCost (S2S cost mode).
    """
    return _bov_make_conn_cost_lookup(_bov_cost_conn(db, cfg), field)


def _bov_make_conn_cost_lookup(conn, field: str = "unit_cost"):
    """Memoised async UPC -> Items_tbl.<field> lookup against one MSSQL connection (None = unconfigured)."""
    cache: Dict[str, Optional[float]] = {}

    async def lookup(barcodes: List[str]) -> Dict[str, float]:
        if conn is None:
            return {}
        missing = [b for b in barcodes if b not in cache]
        if missing:
            ok, _err, by_upc = await get_item_prices_batch_async(
                host=conn.host, port=conn.port, database=conn.database_name,
                username=conn.username, password=conn.password,
                upcs=missing, include_discontinued=True)
            if ok and isinstance(by_upc, dict):
                for b in missing:
                    entry = by_upc.get(b)
                    c = entry.get(field) if entry else None
                    cache[b] = float(c) if c is not None else None
            else:
                lookup.failed = _err or "cost lookup failed"  # type: ignore[attr-defined]
                for b in missing:
                    cache[b] = None
        return {b: cache[b] for b in barcodes if cache.get(b) is not None}

    lookup.configured = conn is not None  # type: ignore[attr-defined]
    lookup.failed = None  # type: ignore[attr-defined]
    return lookup


async def _bov_sales_trend(db: Session, cfg, period: bov.Period, bucket: str,
                           sources: List[str], only_ids: Optional[Set[int]] = None,
                           cost_mode: str = "default") -> Dict[str, Any]:
    """
    Shared by /summary (sales block) and /sales/trend.
    cost_mode 'default': BackOffice = each store's own Items_tbl.UnitCost, Shopify = S2S Items_tbl.UnitPriceC.
    cost_mode 's2s': everything = S2S Items_tbl.UnitCost.
    """
    warnings: List[str] = []
    src_status: Dict[str, Dict[str, Any]] = {}
    tasks: Dict[str, Any] = {}
    s2s_lookup = _bov_make_cost_lookup(db, cfg, "unit_cost") if cost_mode == "s2s" else None
    if cost_mode == "s2s" and not getattr(s2s_lookup, "configured", False):
        warnings.append("S2S cost: Item Tracker S2S store is not configured — cost/margin unavailable")

    sales_stores = _bov_sales_stores(db, cfg, only_ids)
    bo_names_by_key: Dict[str, str] = {}
    if "backoffice" in sources:
        if not _bov_sales_stores(db, cfg):
            src_status["backoffice"] = {"configured": False}
        elif not sales_stores:
            src_status["backoffice"] = {"configured": True, "store_ids": [], "store_names": []}
        else:
            src_status["backoffice"] = {"configured": True, "store_ids": [st.id for st in sales_stores],
                                        "store_names": [st.name for st in sales_stores], "failed_stores": []}
            excl_sales, excl_returns = _bov_excluded_names(db)
            for st in sales_stores:
                key = f"backoffice:{st.id}"
                bo_names_by_key[key] = st.name
                tasks[key] = bov.backoffice_daily_sales_async(
                    **_bov_conn_kwargs(st),
                    date_from=period.prev_start.isoformat(), date_to_excl=period.end_excl,
                    excluded_sales_names=excl_sales, excluded_return_names=excl_returns,
                    cost_mode=cost_mode)

    shopify_stores = _bov_shopify_stores(db, cfg, only_ids) if "shopify" in sources else []
    if "shopify" in sources:
        if not _bov_shopify_stores(db, cfg):
            src_status["shopify"] = {"configured": False}
        elif not shopify_stores:
            src_status["shopify"] = {"configured": True, "store_ids": [], "store_names": []}
        else:
            synced = await asyncio.to_thread(shopify_sync.get_synced_stores)
            cost_lookup = s2s_lookup or _bov_make_cost_lookup(db, cfg, _bov_shopify_cost_field(cost_mode))
            if not getattr(cost_lookup, "configured", False):
                warnings.append("Item Tracker S2S store not configured — Shopify cost/margin unavailable")
            usable: List[Dict[str, Any]] = []
            skipped: List[str] = []
            sh_excl = _bov_shopify_exclusions(db)
            for st in shopify_stores:
                info = synced.get(st["id"])
                if not info:
                    skipped.append(st["name"])
                    warnings.append(f"{st['name']}: not synced — skipped (run Data Sync)")
                    continue
                st["_tz"] = info.get("shop_timezone") or _bov_tz(cfg)
                st["_exclusions"] = sh_excl
                usable.append(st)
            src_status["shopify"] = {"configured": True, "store_ids": [s["id"] for s in shopify_stores],
                                     "store_names": [s["name"] for s in shopify_stores], "skipped_stores": skipped}
            for st in usable:
                tasks[f"shopify:{st['id']}"] = bov.compute_shopify_series(st, st["_tz"], period, bucket, cost_lookup)

    keys = list(tasks.keys())
    results = await asyncio.gather(*[tasks[k] for k in keys], return_exceptions=True) if keys else []
    if "shopify" in sources and shopify_stores:
        failed = getattr(cost_lookup, "failed", None)
        if failed:
            warnings.append(f"Shopify cost lookup failed — margin unavailable: {failed}")
    if s2s_lookup is not None:
        # S2S mode: re-cost every BackOffice day from units × S2S Items_tbl.UnitCost by UPC.
        upcs: Set[str] = set()
        for k, res in zip(keys, results):
            if k.startswith("backoffice:") and not isinstance(res, Exception) and res[0]:
                upcs.update(u for (_d, u, _n) in (res[2].get("units_by_upc") or []) if u)
        unit_costs = await s2s_lookup(sorted(upcs)) if (upcs and getattr(s2s_lookup, "configured", False)) else {}
        failed = getattr(s2s_lookup, "failed", None)
        if failed:
            warnings.append(f"S2S cost lookup failed — margin unavailable: {failed}")
        for k, res in zip(keys, results):
            if k.startswith("backoffice:") and not isinstance(res, Exception) and res[0]:
                bov.recost_backoffice_days(res[2], unit_costs)

    empty = bov.empty_totals()
    per_source: Dict[str, Dict[str, Any]] = {}
    per_store: List[Dict[str, Any]] = []
    bo_days: List[Dict[Any, Dict[str, float]]] = []
    bo_returns: List[Dict[Any, Dict[str, float]]] = []
    bo_ok = 0
    sh_name_by_id = {st["id"]: st["name"] for st in shopify_stores}

    def _store_row(name: str, sid: int, source: str, totals: Optional[Dict[str, Any]], error: Optional[str] = None) -> Dict[str, Any]:
        t = totals or {}
        return {"store_id": sid, "store_name": name, "source": source,
                "revenue": round(float(t.get("revenue") or 0), 2), "cost": round(float(t.get("cost") or 0), 2),
                "profit": round(float(t.get("profit") or 0), 2),
                "shipping_cost": round(float(t.get("shipping_cost") or 0), 2), "margin_pct": t.get("margin_pct"),
                "orders": int(t.get("orders") or 0), "units": float(t.get("units") or 0),
                "cost_coverage": t.get("cost_coverage"), "error": error}

    for k, res in zip(keys, results):
        name = k.split(":", 1)[0]
        sid = int(k.split(":", 1)[1]) if ":" in k else 0
        if isinstance(res, Exception):
            if name == "backoffice":
                src_status["backoffice"].setdefault("failed_stores", []).append(f"{bo_names_by_key.get(k, k)}: {res}")
                per_store.append(_store_row(bo_names_by_key.get(k, k), sid, "backoffice", None, str(res)))
            else:
                src_status.setdefault(name, {"configured": True})["error"] = str(res)
                per_store.append(_store_row(sh_name_by_id.get(sid, k), sid, "shopify", None, str(res)))
            warnings.append(f"{bo_names_by_key.get(k, k)}: {res}")
            continue
        if name == "backoffice":
            ok, err, payload = res
            if not ok:
                src_status["backoffice"].setdefault("failed_stores", []).append(f"{bo_names_by_key.get(k, k)}: {err}")
                warnings.append(f"{bo_names_by_key.get(k, k)}: {err}")
                per_store.append(_store_row(bo_names_by_key.get(k, k), sid, "backoffice", None, err))
                continue
            bo_ok += 1
            bo_days.append(payload.get("days") or {})
            bo_returns.append(payload.get("returns") or {})
            per_store.append(_store_row(bo_names_by_key.get(k, k), sid, "backoffice",
                                        bov.compute_backoffice_series(payload, period, bucket)["totals"]))
        else:
            per_store.append(_store_row(sh_name_by_id.get(sid, k), sid, "shopify", res.get("totals")))
            sh = per_source.get("shopify")
            if sh is None:
                per_source["shopify"] = {"current": res["current"], "previous": res["previous"],
                                         "totals": res["totals"], "previous_totals": res["previous_totals"]}
            else:
                sh["current"] = bov.merge_bucket_lists([sh["current"], res["current"]])
                sh["previous"] = bov.merge_bucket_lists([sh["previous"], res["previous"]])
                sh["totals"] = bov.add_totals(sh["totals"], res["totals"])
                sh["previous_totals"] = bov.add_totals(sh["previous_totals"], res["previous_totals"])

    if "backoffice" in src_status and src_status["backoffice"].get("configured"):
        if bo_ok:
            per_source["backoffice"] = bov.compute_backoffice_series(
                {"days": _bov_merge_daily(bo_days), "returns": _bov_merge_daily(bo_returns),
                 "recosted": s2s_lookup is not None}, period, bucket)
        elif src_status["backoffice"].get("failed_stores"):
            src_status["backoffice"]["error"] = "; ".join(src_status["backoffice"]["failed_stores"])

    def _build_buckets(which: str) -> List[Dict[str, Any]]:
        skel = bov.iter_buckets(period.start if which == "current" else period.prev_start,
                                period.end if which == "current" else period.prev_end, bucket)
        out: List[Dict[str, Any]] = []
        for i, (k, cs, ce) in enumerate(skel):
            b: Dict[str, Any] = {"key": k.isoformat(), "start": cs.isoformat(), "end": ce.isoformat(),
                                 "label": bov.bucket_label(k, bucket), "backoffice": None, "shopify": None}
            total = dict(empty)
            for src in ("backoffice", "shopify"):
                lst = (per_source.get(src) or {}).get(which)
                if lst is not None and i < len(lst):
                    b[src] = lst[i]["totals"]
                    total = bov.add_totals(total, lst[i]["totals"])
            b["total"] = total
            out.append(b)
        return out

    totals: Dict[str, Any] = {}
    prev_totals: Dict[str, Any] = {}
    grand = dict(empty)
    grand_prev = dict(empty)
    for src in ("backoffice", "shopify"):
        ps = per_source.get(src)
        if ps:
            totals[src] = ps["totals"]
            prev_totals[src] = ps["previous_totals"]
            grand = bov.add_totals(grand, ps["totals"])
            grand_prev = bov.add_totals(grand_prev, ps["previous_totals"])
    totals["total"] = grand
    prev_totals["total"] = grand_prev
    change = {k: bov.totals_change(totals[k], prev_totals[k]) for k in totals}

    return {
        "period": period.as_dict(),
        "bucket": bucket,
        "sources": src_status,
        "buckets": _build_buckets("current"),
        "previous_buckets": _build_buckets("previous"),
        "totals": totals,
        "previous_totals": prev_totals,
        "change_pct": change,
        "warnings": warnings,
        "cost_mode": cost_mode,
        "configured": any(v.get("configured") for v in src_status.values()),
        "store_ids": sorted(only_ids) if only_ids is not None else [],
        "per_store": per_store,
    }


async def _bov_shopify_open_orders_block(db: Session, cfg, only_ids: Optional[Set[int]] = None) -> Dict[str, Any]:
    if not _bov_shopify_stores(db, cfg):
        return {"configured": False}
    stores = _bov_shopify_stores(db, cfg, only_ids)
    if not stores:
        return {"configured": True, "filtered_out": True, "count": 0, "per_store": []}

    async def _one(st: Dict[str, Any]) -> Dict[str, Any]:
        row = {"store_id": st["id"], "store_name": st["name"], "count": None, "open_value": None,
               "source": None, "error": None}
        try:
            ok, err, cnt = await count_orders(st["shop_domain"], st["admin_api_key"],
                                              "fulfillment_status:unshipped status:open", st.get("api_version") or "2025-01")
        except Exception as e:
            ok, err, cnt = False, str(e), None
        if ok and cnt is not None:
            row["count"] = int(cnt)
            row["source"] = "live"
            return row
        try:
            local = await bov.shopify_open_orders_local(st["id"])
            row["count"] = int(local.get("open_orders") or 0)
            row["open_value"] = round(float(local.get("open_value") or 0), 2)
            row["source"] = "local"
            row["error"] = f"live count failed ({err}); showing mirror" if err else None
        except Exception as e:
            row["error"] = f"{err or ''} / mirror: {e}".strip(" /")
        return row

    per_store = await asyncio.gather(*[_one(s) for s in stores])
    total = sum((r["count"] or 0) for r in per_store)
    values = [r["open_value"] for r in per_store if r["open_value"] is not None]
    return {
        "configured": True,
        "count": total,
        "open_value": (round(sum(values), 2) if values else None),
        "per_store": list(per_store),
    }


def _bov_result(res: Any, period: Optional[bov.Period] = None) -> Dict[str, Any]:
    if isinstance(res, Exception):
        d: Dict[str, Any] = {"configured": True, "error": str(res)}
        if period is not None:
            d["period"] = period.as_dict()
        return d
    return res


@app.get("/api/business-overview/summary", response_model=BusinessOverviewSummaryResponse)
async def get_business_overview_summary(
    preset: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    store_ids: Optional[str] = None,
    open_scope: str = "range",
    cost_mode: str = "default",
    db: Session = Depends(get_db),
):
    cfg = _bov_config(db)
    period = _bov_period(cfg, preset, date_from, date_to)
    only = _bov_parse_store_ids(store_ids)
    cmode = _bov_cost_mode(cost_mode)
    # Open (unshipped) invoices: "range" = invoiced within the selected period
    # (default — the whole historical backlog is rarely what the owner wants);
    # "all" = every unshipped invoice regardless of date.
    scope = (open_scope or "range").strip().lower()
    if scope not in ("range", "all"):
        raise HTTPException(status_code=400, detail="open_scope must be range or all")
    open_kwargs = ({"date_from": period.start.isoformat(), "date_to": period.end.isoformat()}
                   if scope == "range" else {})
    (quotations, invoices_open, invoices_shipped, incoming, purchased, received,
     sales, shopify_open) = await asyncio.gather(
        _bov_quotations_block(db, cfg, include_list=False, only_ids=only),
        _bov_open_invoices_block(db, cfg, include_list=False, only_ids=only, **open_kwargs),
        _bov_shipped_block(db, cfg, period, "day", include_list=False, only_ids=only),
        _bov_incoming_block(db, cfg, include_list=False, only_ids=only),
        _bov_placed_block(db, cfg, include_list=False, only_ids=only),
        _bov_received_block(db, cfg, period, "day", include_list=False, only_ids=only),
        _bov_sales_trend(db, cfg, period, "day", ["backoffice", "shopify"], only_ids=only, cost_mode=cmode),
        _bov_shopify_open_orders_block(db, cfg, only_ids=only),
        return_exceptions=True,
    )
    sales = _bov_result(sales, period)
    sales_block = {
        "configured": bool(sales.get("configured")),
        "cost_mode": cmode,
        "per_store": sales.get("per_store") or [],
        "sources": sales.get("sources") or {},
        "totals": sales.get("totals") or {},
        "previous_totals": sales.get("previous_totals") or {},
        "change_pct": sales.get("change_pct") or {},
        "sparkline": [{"key": b["key"], "start": b["start"], "end": b["end"], "label": b["label"],
                       "values": {"revenue": b["total"]["revenue"], "profit": b["total"]["profit"],
                                  "cost": b["total"]["cost"]}}
                      for b in (sales.get("buckets") or [])],
        "previous_sparkline": [{"key": b["key"], "start": b["start"], "end": b["end"], "label": b["label"],
                                "values": {"revenue": b["total"]["revenue"], "profit": b["total"]["profit"],
                                           "cost": b["total"]["cost"]}}
                               for b in (sales.get("previous_buckets") or [])],
        "warnings": list(sales.get("warnings") or []) + ([sales["error"]] if sales.get("error") else []),
    }
    return BusinessOverviewSummaryResponse(
        period=BOVPeriod(**period.as_dict()),
        quotations=BOVQuotationsBlock(**_bov_result(quotations)),
        invoices_open=BOVOpenInvoicesBlock(**_bov_result(invoices_open)),
        invoices_shipped=BOVShippedInvoicesBlock(**_bov_result(invoices_shipped, period)),
        purchases_incoming=BOVIncomingPurchasesBlock(**_bov_result(incoming)),
        purchases_purchased=BOVPlacedPurchasesBlock(**_bov_result(purchased)),
        purchases_received=BOVPurchasesRangeBlock(**_bov_result(received, period)),
        sales=BOVSalesSummaryBlock(**sales_block),
        shopify_open_orders=BOVShopifyOpenOrdersBlock(**_bov_result(shopify_open)),
        store_ids=sorted(only) if only is not None else [],
        generated_at=datetime.utcnow(),
    )


@app.get("/api/business-overview/quotations", response_model=BOVQuotationsResponse)
async def get_business_overview_quotations(
    limit: int = 500, sort_by: str = "start_date", sort_order: str = "desc",
    store_ids: Optional[str] = None, cost_mode: str = "default",
    db: Session = Depends(get_db),
):
    cfg = _bov_config(db)
    block = await _bov_quotations_block(db, cfg, include_list=True, limit=limit, sort_by=sort_by, sort_order=sort_order,
                                        only_ids=_bov_parse_store_ids(store_ids), cost_mode=_bov_cost_mode(cost_mode))
    return BOVQuotationsResponse(**block)


@app.get("/api/business-overview/invoices/open", response_model=BOVOpenInvoicesResponse)
async def get_business_overview_open_invoices(
    date_from: Optional[str] = None, date_to: Optional[str] = None,
    limit: int = 500, sort_by: str = "invoice_date", sort_order: str = "desc",
    store_ids: Optional[str] = None, cost_mode: str = "default",
    db: Session = Depends(get_db),
):
    if (date_from and not date_to) or (date_to and not date_from):
        raise HTTPException(status_code=400, detail="date_from and date_to must be given together")
    if date_from:
        try:
            bov.parse_ymd(date_from); bov.parse_ymd(date_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD")
    cfg = _bov_config(db)
    block = await _bov_open_invoices_block(db, cfg, include_list=True, date_from=date_from, date_to=date_to,
                                          limit=limit, sort_by=sort_by, sort_order=sort_order,
                                          only_ids=_bov_parse_store_ids(store_ids), cost_mode=_bov_cost_mode(cost_mode))
    return BOVOpenInvoicesResponse(**block)


@app.get("/api/business-overview/invoices/period", response_model=BOVInvoicesPeriodResponse)
async def get_business_overview_invoices_period(
    preset: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
    limit: int = 500, sort_by: str = "invoice_date", sort_order: str = "desc",
    store_ids: Optional[str] = None, cost_mode: str = "default",
    db: Session = Depends(get_db),
):
    """
    Every non-void invoice dated in the period across the selected sales stores,
    each flagged is_shipped (TrackingNo present) — the card's All/Open/Shipped view.
    """
    cfg = _bov_config(db)
    period = _bov_period(cfg, preset, date_from, date_to)
    only = _bov_parse_store_ids(store_ids)
    if not _bov_sales_stores(db, cfg):
        return BOVInvoicesPeriodResponse(configured=False, period=BOVPeriod(**period.as_dict()))
    stores = _bov_sales_stores(db, cfg, only)
    if not stores:
        return BOVInvoicesPeriodResponse(configured=True, filtered_out=True, period=BOVPeriod(**period.as_dict()))
    today = bov.today_in_tz(_bov_tz(cfg))
    excl_names, _ = _bov_excluded_names(db)
    cmode = _bov_cost_mode(cost_mode)
    results = await _bov_fanout(stores, lambda st: bov.invoices_in_period_async(
        **_bov_conn_kwargs(st), date_from=period.start.isoformat(), date_to_excl=period.end_excl,
        limit=limit, sort_by=sort_by, sort_order=sort_order, include_list=True, today=today,
        excluded_names=excl_names, cost_mode=cmode))
    base = _bov_multi_base(stores, results, {"period": period.as_dict()},
                           count_of=lambda p: p.get("count"), amount_of=lambda p: p.get("total_amount"))
    if base.get("error"):
        return BOVInvoicesPeriodResponse(**base)
    if cmode == "s2s":
        await _bov_recost_invoice_results(db, cfg, results)
    invoices: List[Dict[str, Any]] = []
    sums = {"count": 0, "open_count": 0, "shipped_count": 0, "total_amount": 0.0,
            "open_amount": 0.0, "shipped_amount": 0.0, "total_qty": 0.0}
    truncated = False
    for st, ok, _err, p in results:
        if not ok:
            continue
        invoices.extend(_bov_tag_rows(list(p.get("invoices") or []), st))
        for k in sums:
            sums[k] += (p.get(k) or 0)
        truncated = truncated or bool(p.get("truncated"))
    for k in ("total_amount", "open_amount", "shipped_amount"):
        sums[k] = round(sums[k], 2)
    base.update(sums)
    base.update({"invoices": invoices, "limit": limit, "truncated": truncated})
    return BOVInvoicesPeriodResponse(**base)


@app.get("/api/business-overview/invoices/shipped", response_model=BOVShippedInvoicesResponse)
async def get_business_overview_shipped_invoices(
    preset: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
    bucket: str = "day", limit: int = 500, sort_by: str = "ship_date", sort_order: str = "desc",
    store_ids: Optional[str] = None, cost_mode: str = "default",
    db: Session = Depends(get_db),
):
    cfg = _bov_config(db)
    period = _bov_period(cfg, preset, date_from, date_to)
    b = _bov_check_bucket(bucket)
    block = await _bov_shipped_block(db, cfg, period, b, include_list=True, limit=limit, sort_by=sort_by, sort_order=sort_order,
                                     only_ids=_bov_parse_store_ids(store_ids), cost_mode=_bov_cost_mode(cost_mode))
    return BOVShippedInvoicesResponse(**block)


@app.get("/api/business-overview/invoices/{invoice_id}", response_model=BOVInvoiceDetailResponse)
async def get_business_overview_invoice_detail(invoice_id: int, store_id: Optional[int] = None,
                                               cost_mode: str = "default",
                                               db: Session = Depends(get_db)):
    cfg = _bov_config(db)
    cmode = _bov_cost_mode(cost_mode)
    stores = _bov_sales_stores(db, cfg)
    if not stores:
        raise HTTPException(status_code=400, detail="Business Overview sales store is not configured.")
    if store_id is not None:
        store = next((st for st in stores if st.id == store_id), None)
        if store is None:
            raise HTTPException(status_code=400, detail=f"Store {store_id} is not a selected sales store.")
    elif len(stores) == 1:
        store = stores[0]
    else:
        raise HTTPException(status_code=400, detail="store_id is required when several sales stores are selected.")
    ok, err, payload = await bov.invoice_detail_async(**_bov_conn_kwargs(store), invoice_id=invoice_id, cost_mode=cmode)
    if not ok:
        raise HTTPException(status_code=502, detail=err or "Invoice lookup failed")
    if not payload.get("header"):
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
    lines = payload.get("lines") or []
    cost_basis = "local"
    if cmode == "s2s":
        cost_basis = "s2s"
        lookup = _bov_make_cost_lookup(db, cfg, "unit_cost")
        upcs = sorted({(l.get("product_upc") or "").strip() for l in lines if (l.get("product_upc") or "").strip()})
        unit_costs = await lookup(upcs) if (upcs and getattr(lookup, "configured", False)) else {}
        for l in lines:
            uc = unit_costs.get((l.get("product_upc") or "").strip())
            qty = float(l.get("qty_shipped") or 0)
            ext = float(l.get("extended_price") or 0)
            l["unit_cost"] = float(uc) if uc is not None else None
            l["line_cost"] = round(qty * float(uc), 4) if uc is not None else 0.0
            l["line_profit"] = (round(ext - qty * float(uc), 4) if uc is not None else None)
            l["margin_pct"] = (bov.margin_pct(ext, qty * float(uc)) if (uc is not None and ext) else None)
        revenue = sum(float(l.get("extended_price") or 0) for l in lines)
        cost = sum(float(l.get("line_cost") or 0) for l in lines)
        payload["header"].update({"revenue": round(revenue, 2), "cost": round(cost, 2),
                                  "profit": round(revenue - cost, 2), "margin_pct": bov.margin_pct(revenue, cost)})
        payload["header"]["net_profit"] = bov.invoice_net_profit(payload["header"])
    return BOVInvoiceDetailResponse(header=BOVInvoiceHeader(**payload["header"]),
                                    lines=[BOVInvoiceLine(**l) for l in lines],
                                    store_name=store.name, cost_basis=cost_basis)


@app.get("/api/business-overview/purchases/incoming", response_model=BOVIncomingPurchasesResponse)
async def get_business_overview_incoming_purchases(
    limit: int = 500, sort_by: str = "po_date", sort_order: str = "desc",
    store_ids: Optional[str] = None,
    db: Session = Depends(get_db),
):
    cfg = _bov_config(db)
    block = await _bov_incoming_block(db, cfg, include_list=True, limit=limit, sort_by=sort_by, sort_order=sort_order,
                                      only_ids=_bov_parse_store_ids(store_ids))
    return BOVIncomingPurchasesResponse(**block)


@app.get("/api/business-overview/purchases/purchased", response_model=BOVPlacedPurchasesResponse)
async def get_business_overview_purchased(
    limit: int = 500, sort_by: str = "po_date", sort_order: str = "desc",
    store_ids: Optional[str] = None,
    db: Session = Depends(get_db),
):
    cfg = _bov_config(db)
    block = await _bov_placed_block(db, cfg, include_list=True, limit=limit, sort_by=sort_by, sort_order=sort_order,
                                    only_ids=_bov_parse_store_ids(store_ids))
    return BOVPlacedPurchasesResponse(**block)


@app.get("/api/business-overview/purchases/received", response_model=BOVPurchasesRangeResponse)
async def get_business_overview_received(
    preset: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
    bucket: str = "day", limit: int = 500,
    store_ids: Optional[str] = None,
    db: Session = Depends(get_db),
):
    cfg = _bov_config(db)
    period = _bov_period(cfg, preset, date_from, date_to)
    b = _bov_check_bucket(bucket)
    block = await _bov_received_block(db, cfg, period, b, include_list=True, limit=limit,
                                      only_ids=_bov_parse_store_ids(store_ids))
    return BOVPurchasesRangeResponse(**block)


# NOTE: the /purchases/exclusions routes must stay declared before /purchases/{po_id},
# otherwise the int path parameter swallows them with a 422.
@app.get("/api/business-overview/purchases/exclusions", response_model=BOVPoExclusionList)
def list_business_overview_po_exclusions(db: Session = Depends(get_db)):
    rows = db.query(BusinessOverviewPoProductExclusion).order_by(BusinessOverviewPoProductExclusion.created_at.desc()).all()
    out = []
    for e in rows:
        d = BOVPoExclusion.model_validate(e)
        d.store_name = e.store.name if e.store else None
        out.append(d)
    return BOVPoExclusionList(exclusions=out, total=len(out))


@app.post("/api/business-overview/purchases/exclusions", response_model=BOVPoExclusion)
def add_business_overview_po_exclusion(data: BOVPoExclusionCreate, db: Session = Depends(get_db)):
    cfg = _bov_config(db)
    store = _bov_mssql_store(db, cfg.purchases_store_id if cfg else None)
    if store is None:
        raise HTTPException(status_code=400, detail="Business Overview purchases store is not configured.")
    row = db.query(BusinessOverviewPoProductExclusion).filter(
        BusinessOverviewPoProductExclusion.store_id == store.id,
        BusinessOverviewPoProductExclusion.product_id == data.product_id).first()
    if not row:
        row = BusinessOverviewPoProductExclusion(store_id=store.id, product_id=data.product_id,
                                                 product_sku=data.product_sku, product_upc=data.product_upc,
                                                 description=data.description, note=data.note)
        db.add(row)
        db.commit()
        db.refresh(row)
    d = BOVPoExclusion.model_validate(row)
    d.store_name = row.store.name if row.store else None
    return d


@app.delete("/api/business-overview/purchases/exclusions/{exclusion_id}")
def delete_business_overview_po_exclusion(exclusion_id: int, db: Session = Depends(get_db)):
    row = db.query(BusinessOverviewPoProductExclusion).filter(BusinessOverviewPoProductExclusion.id == exclusion_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Exclusion not found")
    db.delete(row)
    db.commit()
    return {"deleted": exclusion_id}


@app.get("/api/business-overview/purchases/{po_id}", response_model=BOVPurchaseOrderDetailResponse)
async def get_business_overview_purchase_order_detail(po_id: int, db: Session = Depends(get_db)):
    cfg = _bov_config(db)
    store = _bov_mssql_store(db, cfg.purchases_store_id if cfg else None)
    if store is None:
        raise HTTPException(status_code=400, detail="Business Overview purchases store is not configured.")
    excl_rows = _bov_po_exclusions(db, store.id)
    excl_id_by_product = {e.product_id: e.id for e in excl_rows}
    ok, err, payload = await bov.purchase_order_detail_async(
        **_bov_conn_kwargs(store), po_id=po_id,
        excluded_product_ids=list(excl_id_by_product.keys()) or None)
    if not ok:
        raise HTTPException(status_code=502, detail=err or "Purchase order lookup failed")
    if not payload.get("header"):
        raise HTTPException(status_code=404, detail=f"Purchase order {po_id} not found")
    lines = payload.get("lines") or []
    for l in lines:
        if l.get("excluded"):
            l["exclusion_id"] = excl_id_by_product.get(l.get("product_id"))
    return BOVPurchaseOrderDetailResponse(header=BOVPurchaseOrderHeader(**payload["header"]),
                                          lines=[BOVPurchaseOrderLine(**l) for l in lines],
                                          store_name=store.name,
                                          excluded_lines=sum(1 for l in lines if l.get("excluded")))


@app.get("/api/business-overview/sales/trend", response_model=BOVSalesTrendResponse)
async def get_business_overview_sales_trend(
    preset: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
    bucket: str = "day", sources: str = "backoffice,shopify",
    store_ids: Optional[str] = None, cost_mode: str = "default",
    db: Session = Depends(get_db),
):
    cfg = _bov_config(db)
    period = _bov_period(cfg, preset, date_from, date_to)
    b = _bov_check_bucket(bucket)
    src = [s.strip().lower() for s in (sources or "").split(",") if s.strip()]
    src = [s for s in src if s in ("backoffice", "shopify")] or ["backoffice", "shopify"]
    res = await _bov_sales_trend(db, cfg, period, b, src, only_ids=_bov_parse_store_ids(store_ids),
                                 cost_mode=_bov_cost_mode(cost_mode))
    return BOVSalesTrendResponse(
        period=BOVPeriod(**res["period"]),
        bucket=b,
        sources={k: BOVSalesSourceStatus(**v) for k, v in res["sources"].items()},
        buckets=[BOVSalesBucket(**x) for x in res["buckets"]],
        previous_buckets=[BOVSalesBucket(**x) for x in res["previous_buckets"]],
        totals={k: BOVSalesSourceTotals(**v) for k, v in res["totals"].items()},
        previous_totals={k: BOVSalesSourceTotals(**v) for k, v in res["previous_totals"].items()},
        change_pct=res["change_pct"],
        warnings=res["warnings"],
        cost_mode=res.get("cost_mode") or "default",
        per_store=res.get("per_store") or [],
        store_ids=res.get("store_ids") or [],
        generated_at=datetime.utcnow(),
    )


@app.get("/api/business-overview/sales/breakdown", response_model=BOVSalesBreakdownResponse)
async def get_business_overview_sales_breakdown(
    preset: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
    by: str = "customer", source: str = "all", limit: int = 10,
    store_ids: Optional[str] = None, cost_mode: str = "default",
    db: Session = Depends(get_db),
):
    """
    Top customers / reps (BackOffice) and top products (BackOffice + Shopify,
    merged by barcode = ProductUPC). Cost basis follows cost_mode: BackOffice =
    local Items_tbl.UnitCost, Shopify = S2S UnitPriceC; 's2s' = S2S UnitCost for
    everything (customer/rep cost then unavailable — no UPC dimension).
    """
    cfg = _bov_config(db)
    period = _bov_period(cfg, preset, date_from, date_to)
    only = _bov_parse_store_ids(store_ids)
    by = (by or "customer").strip().lower()
    source = (source or "all").strip().lower()
    if by not in ("customer", "rep", "product"):
        raise HTTPException(status_code=400, detail="by must be customer, rep or product")
    if source not in ("backoffice", "shopify", "all"):
        raise HTTPException(status_code=400, detail="source must be backoffice, shopify or all")
    if by != "product" and source == "shopify":
        raise HTTPException(status_code=400, detail="Shopify breakdown supports by=product only")
    if by != "product":
        source = "backoffice"
    limit = max(1, min(int(limit or 10), 200))
    resp: Dict[str, Any] = {"period": period.as_dict(), "by": by, "source": source, "configured": False,
                            "rows": [], "total_revenue": 0.0, "warnings": []}
    cmode = _bov_cost_mode(cost_mode)
    resp["cost_mode"] = cmode
    s2s_lookup = _bov_make_cost_lookup(db, cfg, "unit_cost")
    warnings: List[str] = []
    if cmode == "s2s" and not getattr(s2s_lookup, "configured", False):
        warnings.append("S2S cost: Item Tracker S2S store is not configured — cost unavailable")
    merged: Dict[str, Dict[str, Any]] = {}
    total_rev = 0.0

    def _mkey(r: Dict[str, Any]) -> str:
        if by == "rep":
            return (r.get("name") or "").strip().lower() or "__unassigned"
        return (r.get("key") or r.get("name") or "").strip().lower() or f"__{r.get('name')}"

    def _add(r: Dict[str, Any], src: str) -> None:
        mk = _mkey(r)
        m = merged.get(mk)
        if m is None:
            m = merged[mk] = {"key": r.get("key"), "name": r.get("name"), "secondary": r.get("secondary"),
                              "orders": 0, "revenue": 0.0, "cost": 0.0, "units": 0.0,
                              "revenue_backoffice": 0.0, "revenue_shopify": 0.0,
                              "units_backoffice": 0.0, "units_shopify": 0.0, "cost_known": True}
        elif not m.get("name") and r.get("name"):
            m["name"] = r["name"]
        if not m.get("secondary"):
            m["secondary"] = r.get("secondary")
        m["orders"] += int(r.get("orders") or 0)
        m["revenue"] += float(r.get("revenue") or 0.0)
        m["units"] += float(r.get("units") or 0.0)
        m[f"revenue_{src}"] += float(r.get("revenue") or 0.0)
        m[f"units_{src}"] += float(r.get("units") or 0.0)
        if r.get("cost") is None:
            m["cost_known"] = False
        else:
            m["cost"] += float(r.get("cost") or 0.0)

    # ---- BackOffice
    if source in ("backoffice", "all"):
        if _bov_sales_stores(db, cfg):
            resp["configured"] = True
            stores = _bov_sales_stores(db, cfg, only)
            if stores:
                excl_sales, _ = _bov_excluded_names(db)
                per_store_limit = limit if len(stores) == 1 and source == "backoffice" else max(limit * 3, 50)
                bd_results, daily_results = await asyncio.gather(
                    _bov_fanout(stores, lambda st: bov.backoffice_breakdown_async(
                        **_bov_conn_kwargs(st), date_from=period.start.isoformat(), date_to_excl=period.end_excl,
                        by=by, limit=per_store_limit, excluded_sales_names=excl_sales, cost_mode=cmode)),
                    _bov_fanout(stores, lambda st: bov.backoffice_daily_sales_async(
                        **_bov_conn_kwargs(st), date_from=period.start.isoformat(), date_to_excl=period.end_excl,
                        excluded_sales_names=excl_sales, excluded_return_names=[])),
                )
                failures = [f"{st.name}: {err}" for st, ok, err, _p in bd_results if not ok]
                warnings.extend(failures)
                bo_rows: List[Dict[str, Any]] = []
                for st, ok, _err, rows in bd_results:
                    if ok:
                        bo_rows.extend(rows if isinstance(rows, list) else [])
                if cmode == "s2s" and by == "product" and bo_rows:
                    upcs = sorted({(r.get("key") or "").strip() for r in bo_rows if (r.get("key") or "").strip()})
                    unit_costs = await s2s_lookup(upcs) if (upcs and getattr(s2s_lookup, "configured", False)) else {}
                    for r in bo_rows:
                        uc = unit_costs.get((r.get("key") or "").strip())
                        r["cost"] = (float(uc) * float(r.get("units") or 0)) if uc is not None else None
                for r in bo_rows:
                    _add(r, "backoffice")
                any_daily = False
                for _st, ok, _err, daily in daily_results:
                    if ok:
                        any_daily = True
                        total_rev += bov.sum_daily(daily.get("days") or {}, period.start, period.end, ["revenue"])["revenue"]
                if not any_daily:
                    total_rev += sum(float(r.get("revenue_backoffice") or 0.0) for r in merged.values())

    # ---- Shopify (products only, merged by barcode)
    if by == "product" and source in ("shopify", "all"):
        if _bov_shopify_stores(db, cfg):
            resp["configured"] = True
            stores = _bov_shopify_stores(db, cfg, only)
            if stores:
                synced = await asyncio.to_thread(shopify_sync.get_synced_stores)
                sh_rows: List[Dict[str, Any]] = []
                for st in stores:
                    info = synced.get(st["id"])
                    if not info:
                        warnings.append(f"{st['name']}: not synced")
                        continue
                    try:
                        rows = await bov.shopify_top_products(st["id"], info.get("shop_timezone") or _bov_tz(cfg),
                                                              period.start.isoformat(), period.end_excl, max(limit * 3, 50),
                                                              _bov_shopify_exclusions(db))
                        sh_rows.extend(rows)
                    except Exception as e:
                        warnings.append(f"{st['name']}: {e}")
                # cost per unit from the S2S Items_tbl by barcode (memoised lookup, one round trip)
                cost_lookup = s2s_lookup if cmode == "s2s" else _bov_make_cost_lookup(db, cfg, _bov_shopify_cost_field(cmode))
                barcodes = sorted({(r.get("key") or "").strip() for r in sh_rows if (r.get("key") or "").strip()})
                unit_costs = await cost_lookup(barcodes) if (barcodes and getattr(cost_lookup, "configured", False)) else {}
                for r in sh_rows:
                    bc = (r.get("key") or "").strip()
                    uc = unit_costs.get(bc)
                    r["cost"] = (float(uc) * float(r.get("units") or 0)) if uc is not None else None
                    _add(r, "shopify")
                # period Shopify revenue for the share denominator
                for st in stores:
                    info = synced.get(st["id"])
                    if not info:
                        continue
                    try:
                        po = await bov.shopify_period_orders(st["id"], info.get("shop_timezone") or _bov_tz(cfg),
                                                             period.start.isoformat(), period.end_excl, _bov_shopify_exclusions(db))
                        total_rev += float(po.get("revenue") or 0.0)
                    except Exception:
                        pass

    if not resp["configured"]:
        return BOVSalesBreakdownResponse(**resp)
    rows_out = sorted(merged.values(), key=lambda x: -(x.get("revenue") or 0))[:limit]
    if not total_rev:
        total_rev = sum(float(r.get("revenue") or 0.0) for r in merged.values())
    out_rows: List[Dict[str, Any]] = []
    for r in rows_out:
        rev = round(r.get("revenue") or 0.0, 2)
        cost = round(r.get("cost") or 0.0, 2) if r.get("cost_known", True) else None
        out_rows.append({
            "key": r.get("key"), "name": r.get("name"), "secondary": r.get("secondary"),
            "orders": int(r.get("orders") or 0), "revenue": rev,
            "cost": cost, "profit": (round(rev - cost, 2) if cost is not None else None),
            "margin_pct": (bov.margin_pct(rev, cost) if cost is not None else None),
            "units": float(r.get("units") or 0.0),
            "share_pct": (round(rev / total_rev * 100, 2) if total_rev else None),
            "revenue_backoffice": round(r.get("revenue_backoffice") or 0.0, 2),
            "revenue_shopify": round(r.get("revenue_shopify") or 0.0, 2),
            "units_backoffice": float(r.get("units_backoffice") or 0.0),
            "units_shopify": float(r.get("units_shopify") or 0.0),
        })
    resp["rows"] = out_rows
    resp["total_revenue"] = round(total_rev, 2)
    resp["warnings"] = warnings
    if warnings and not out_rows:
        resp["error"] = "; ".join(warnings)
    return BOVSalesBreakdownResponse(**resp)


@app.get("/api/business-overview/products", response_model=BOVProductsResponse)
async def get_business_overview_products(
    preset: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
    store_ids: Optional[str] = None, limit: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """
    Products tab: every product sold in the period, one row per product per
    store (BackOffice sales stores + synced Shopify mirrors), with BOTH cost
    bases side by side — local cost (own Items_tbl.UnitCost for BackOffice,
    S2S UnitPriceC for Shopify) and S2S cost (S2S Items_tbl.UnitCost) — plus
    the margin each implies. Ignores cost_mode by design.
    """
    cfg = _bov_config(db)
    period = _bov_period(cfg, preset, date_from, date_to)
    only = _bov_parse_store_ids(store_ids)
    try:
        max_rows = max(1, min(int(limit or bov.MAX_LIST_LIMIT), bov.MAX_LIST_LIMIT))
    except (TypeError, ValueError):
        max_rows = bov.MAX_LIST_LIMIT
    if not (_bov_sales_stores(db, cfg) or _bov_shopify_stores(db, cfg)):
        return BOVProductsResponse(configured=False, period=BOVPeriod(**period.as_dict()))
    bo_stores = _bov_sales_stores(db, cfg, only)
    sh_stores = _bov_shopify_stores(db, cfg, only)
    if not (bo_stores or sh_stores):
        return BOVProductsResponse(configured=True, filtered_out=True, period=BOVPeriod(**period.as_dict()))

    warnings: List[str] = []
    statuses: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []

    # ---- BackOffice: per-UPC aggregate with the store's own local cost
    if bo_stores:
        excl_sales, _ = _bov_excluded_names(db)
        results = await _bov_fanout(bo_stores, lambda st: bov.backoffice_products_sold_async(
            **_bov_conn_kwargs(st), date_from=period.start.isoformat(), date_to_excl=period.end_excl,
            excluded_sales_names=excl_sales))
        for st, ok, err, payload in results:
            st_rows = payload if isinstance(payload, list) else []
            statuses.append({"store_id": st.id, "store_name": st.name, "error": (None if ok else (err or "failed")),
                             "count": (len(st_rows) if ok else None),
                             "amount": (round(sum(float(r.get("revenue") or 0) for r in st_rows), 2) if ok else None)})
            if not ok:
                warnings.append(f"{st.name}: {err or 'failed'}")
                continue
            for r in st_rows:
                rows.append({**r, "store_id": st.id, "store_name": st.name, "store_type": "backoffice"})

    # ---- Shopify: local mirror, per barcode; both costs come from the S2S lookup
    if sh_stores:
        synced = await asyncio.to_thread(shopify_sync.get_synced_stores)
        sh_excl = _bov_shopify_exclusions(db)
        usable = []
        for st in sh_stores:
            if st["id"] in synced:
                usable.append(st)
            else:
                warnings.append(f"{st['name']}: not synced")
                statuses.append({"store_id": st["id"], "store_name": st["name"], "error": "not synced"})
        sh_results = await asyncio.gather(*[bov.shopify_products_sold(
            st["id"], (synced.get(st["id"]) or {}).get("shop_timezone") or _bov_tz(cfg),
            period.start.isoformat(), period.end_excl, sh_excl) for st in usable], return_exceptions=True)
        for st, res in zip(usable, sh_results):
            if isinstance(res, Exception):
                warnings.append(f"{st['name']}: {res}")
                statuses.append({"store_id": st["id"], "store_name": st["name"], "error": str(res)})
                continue
            statuses.append({"store_id": st["id"], "store_name": st["name"], "error": None,
                             "count": len(res),
                             "amount": round(sum(float(r.get("revenue") or 0) for r in res), 2)})
            for r in res:
                title = (r.get("title") or "").strip()
                variant = (r.get("variant_title") or "").strip()
                rows.append({
                    "upc": ((r.get("barcode") or "").strip() or None),
                    "description": (f"{title} — {variant}" if title and variant else (title or variant or None)),
                    "sku": r.get("sku"),
                    "orders": int(r.get("orders") or 0),
                    "revenue": round(float(r.get("revenue") or 0), 2),
                    "units": float(r.get("units") or 0),
                    "local_cost": None,   # filled from the S2S lookup (UnitPriceC) below
                    "store_id": st["id"], "store_name": st["name"], "store_type": "shopify",
                })

    # ---- One batch lookup on the S2S store: UnitCost (S2S basis) + UnitPriceC (Shopify local basis)
    conn = _bov_cost_conn(db, cfg)
    cost_store = db.query(Store).filter(Store.id == conn.store_id).first() if conn else None
    upcs = sorted({r["upc"] for r in rows if r.get("upc")})
    by_upc: Dict[str, Any] = {}
    lookup_error: Optional[str] = None
    if conn is not None and upcs:
        ok, err, found = await get_item_prices_batch_async(host=conn.host, port=conn.port, database=conn.database_name,
                                                          username=conn.username, password=conn.password,
                                                          upcs=upcs, include_discontinued=True)
        if ok and isinstance(found, dict):
            by_upc = found
        else:
            lookup_error = err or "cost lookup failed"
    if conn is None:
        warnings.append("Item Tracker S2S store is not configured — S2S cost unavailable")
    elif lookup_error:
        warnings.append(f"S2S cost lookup failed: {lookup_error}")

    def _s2s_field(upc: Optional[str], field: str) -> Optional[float]:
        rec = by_upc.get(upc) if upc else None
        if not rec:
            return None
        v = rec.get(field)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    for r in rows:
        units = float(r.get("units") or 0)
        rev = float(r.get("revenue") or 0)
        r["avg_price"] = (round(rev / units, 2) if units else None)
        if r["store_type"] == "shopify":
            local_unit = _s2s_field(r.get("upc"), "unit_delivery_b")
            local_total = (round(local_unit * units, 2) if local_unit is not None else None)
        else:
            local_total = r.get("local_cost")
            local_unit = (round(local_total / units, 4) if (local_total is not None and units) else None)
        s2s_unit = _s2s_field(r.get("upc"), "unit_cost")
        s2s_total = (round(s2s_unit * units, 2) if s2s_unit is not None else None)
        r["local_unit_cost"] = local_unit
        r["local_cost"] = (round(local_total, 2) if local_total is not None else None)
        r["local_profit"] = (round(rev - local_total, 2) if local_total is not None else None)
        r["local_margin_pct"] = (bov.margin_pct(rev, local_total) if local_total is not None else None)
        r["s2s_unit_cost"] = s2s_unit
        r["s2s_cost"] = s2s_total
        r["s2s_profit"] = (round(rev - s2s_total, 2) if s2s_total is not None else None)
        r["s2s_margin_pct"] = (bov.margin_pct(rev, s2s_total) if s2s_total is not None else None)

    # ---- Totals over ALL rows (weighted margins on the cost-known subset)
    tot_rev = sum(float(r.get("revenue") or 0) for r in rows)

    def _basis_totals(cost_key: str) -> Dict[str, Optional[float]]:
        known = [r for r in rows if r.get(cost_key) is not None]
        if not known:
            return {"cost": None, "profit": None, "margin": None, "coverage": (0.0 if rows else None)}
        cost = sum(float(r[cost_key]) for r in known)
        rev_known = sum(float(r.get("revenue") or 0) for r in known)
        return {"cost": round(cost, 2), "profit": round(rev_known - cost, 2),
                "margin": bov.margin_pct(rev_known, cost),
                "coverage": (round(rev_known / tot_rev * 100, 1) if tot_rev else None)}

    local_t = _basis_totals("local_cost")
    s2s_t = _basis_totals("s2s_cost")
    totals = BOVProductsTotals(
        products=len(rows),
        units=round(sum(float(r.get("units") or 0) for r in rows), 2),
        revenue=round(tot_rev, 2),
        local_cost=local_t["cost"], local_profit=local_t["profit"],
        local_margin_pct=local_t["margin"], local_cost_coverage=local_t["coverage"],
        s2s_cost=s2s_t["cost"], s2s_profit=s2s_t["profit"],
        s2s_margin_pct=s2s_t["margin"], s2s_cost_coverage=s2s_t["coverage"],
    )

    rows.sort(key=lambda x: -(x.get("revenue") or 0))
    out = rows[:max_rows]
    err_msg = ("; ".join(warnings) if warnings and not rows else None)
    return BOVProductsResponse(
        configured=True, period=BOVPeriod(**period.as_dict()),
        rows=[BOVProductRow(**r) for r in out], count=len(rows), totals=totals,
        warnings=warnings, truncated=len(rows) > len(out),
        cost_store_id=(cost_store.id if cost_store else None),
        cost_store_name=(cost_store.name if cost_store else None),
        stores=[BOVStoreStatus(**s) for s in statuses], error=err_msg,
    )


# ---- Access gate: the Overview is password protected ------------------------

BOV_PASSWORD_SETTING_KEY = "business_overview_password"
BOV_DEFAULT_PASSWORD = "admin1972"


class BOVUnlockRequest(BaseModel):
    password: str


@app.post("/api/business-overview/unlock")
def business_overview_unlock(data: BOVUnlockRequest, db: Session = Depends(get_db)):
    """
    Check the Overview password. The password lives in settings
    (`business_overview_password`; default admin1972) so it can be changed
    without a deploy. Returns 401 on mismatch; the client keeps a session flag.
    """
    row = db.query(Setting).filter(Setting.key == BOV_PASSWORD_SETTING_KEY).first()
    expected = (row.value if row and row.value else BOV_DEFAULT_PASSWORD)
    import hmac
    if not hmac.compare_digest(str(data.password or ""), str(expected)):
        raise HTTPException(status_code=401, detail="Incorrect password")
    return {"ok": True}


# ---- Shopify: order flow + catch-up sync ------------------------------------

@app.get("/api/business-overview/shopify/orders", response_model=BOVShopifyOrdersResponse)
async def get_business_overview_shopify_orders(
    preset: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
    store_ids: Optional[str] = None, live: bool = True,
    db: Session = Depends(get_db),
):
    """
    Per Shopify store: orders placed / fulfilled / unfulfilled / cancelled in the
    period (local mirror, shop calendar) plus the live fulfillment buckets used
    by the Fulfillment Status page (open backlog, to fulfil, on picklist,
    in process, on hold) when `live` is set.
    """
    cfg = _bov_config(db)
    period = _bov_period(cfg, preset, date_from, date_to)
    only = _bov_parse_store_ids(store_ids)
    if not _bov_shopify_stores(db, cfg):
        return BOVShopifyOrdersResponse(configured=False, period=BOVPeriod(**period.as_dict()), live=live)
    stores = _bov_shopify_stores(db, cfg, only)
    if not stores:
        return BOVShopifyOrdersResponse(configured=True, filtered_out=True, period=BOVPeriod(**period.as_dict()), live=live)
    synced = await asyncio.to_thread(shopify_sync.get_synced_stores)
    sh_excl = _bov_shopify_exclusions(db)

    async def one(st: Dict[str, Any]) -> Dict[str, Any]:
        row: Dict[str, Any] = {"store_id": st["id"], "store_name": st["name"], "synced": st["id"] in synced}
        info = synced.get(st["id"]) or {}
        last = info.get("last_completed_at")
        row["last_synced_at"] = last.isoformat() if hasattr(last, "isoformat") else (str(last) if last else None)
        tasks = []
        if row["synced"]:
            tasks.append(bov.shopify_period_orders(st["id"], info.get("shop_timezone") or _bov_tz(cfg),
                                                   period.start.isoformat(), period.end_excl, sh_excl))
        else:
            tasks.append(asyncio.sleep(0, result=None))
        if live:
            tasks.append(count_fulfillment_buckets_for_store(st))
        else:
            tasks.append(asyncio.sleep(0, result=None))
        mirror_res, live_res = await asyncio.gather(*tasks, return_exceptions=True)
        if isinstance(mirror_res, Exception):
            row["error"] = str(mirror_res)
        elif isinstance(mirror_res, dict):
            row.update(mirror_res)
        elif not row["synced"]:
            row["error"] = "not synced — run Data Sync"
        if isinstance(live_res, Exception):
            row["live_error"] = str(live_res)
        elif isinstance(live_res, dict):
            if live_res.get("error"):
                row["live_error"] = live_res["error"]
            for k in ("open_orders", "on_hold", "in_process", "on_picklist", "to_fulfill"):
                row[k] = live_res.get(k)
        return row

    per_store = await asyncio.gather(*[one(st) for st in stores])
    totals: Dict[str, float] = {}
    for r in per_store:
        for k in ("orders", "revenue", "cancelled", "fulfilled_in_period", "fulfilled_from_period",
                  "unfulfilled_from_period", "on_hold_from_period", "open_orders", "on_hold",
                  "in_process", "on_picklist", "to_fulfill"):
            v = r.get(k)
            if v is not None:
                totals[k] = totals.get(k, 0) + float(v)
    totals["revenue"] = round(totals.get("revenue", 0.0), 2)
    statuses = [{"store_id": r["store_id"], "store_name": r["store_name"],
                 "error": r.get("error") or r.get("live_error")} for r in per_store]
    all_failed = all((r.get("error") and (not live or r.get("live_error"))) for r in per_store) if per_store else False
    return BOVShopifyOrdersResponse(
        configured=True, live=live, period=BOVPeriod(**period.as_dict()),
        stores=[BOVStoreStatus(**x) for x in statuses],
        per_store=[BOVShopifyStoreOrders(**r) for r in per_store],
        totals=totals,
        skipped_stores=[r["store_name"] for r in per_store if not r["synced"]],
        error=("; ".join(f"{r['store_name']}: {r.get('error') or r.get('live_error')}" for r in per_store) if all_failed else None),
        store_name=(stores[0]["name"] if len(stores) == 1 else ", ".join(st["name"] for st in stores)),
        store_id=(stores[0]["id"] if len(stores) == 1 else None),
    )


@app.get("/api/business-overview/shopify/orders/list", response_model=BOVShopifyOrdersListResponse)
async def get_business_overview_shopify_orders_list(
    kind: str = "open", days: Optional[float] = None, store_ids: Optional[str] = None, limit: int = 500,
    db: Session = Depends(get_db),
):
    """Orders behind the Shopify alerts across the configured stores (mirror): on_hold | unfulfilled_aged | open."""
    kind = (kind or "open").strip().lower()
    if kind not in ("on_hold", "unfulfilled_aged", "open"):
        raise HTTPException(status_code=400, detail="kind must be on_hold, unfulfilled_aged or open")
    cfg = _bov_config(db)
    only = _bov_parse_store_ids(store_ids)
    if not _bov_shopify_stores(db, cfg):
        return BOVShopifyOrdersListResponse(configured=False, kind=kind)
    stores = _bov_shopify_stores(db, cfg, only)
    if not stores:
        return BOVShopifyOrdersListResponse(configured=True, filtered_out=True, kind=kind)
    rules = bov_merge_alert_rules(cfg.alert_rules if cfg else None)
    if days is None:
        days = float(rules["shopify_unfulfilled_age"].get("days", 2))
    synced = await asyncio.to_thread(shopify_sync.get_synced_stores)
    usable = [st for st in stores if st["id"] in synced]
    skipped = [st["name"] for st in stores if st["id"] not in synced]
    limit = max(1, min(int(limit or 500), 2000))
    results = await asyncio.gather(*[bov.shopify_orders_list(st["id"], kind, days * 24.0, limit) for st in usable], return_exceptions=True)
    rows: List[Dict[str, Any]] = []
    statuses: List[Dict[str, Any]] = []
    for st, res in zip(usable, results):
        if isinstance(res, Exception):
            statuses.append({"store_id": st["id"], "store_name": st["name"], "error": str(res)})
            continue
        for r in res:
            r["store_name"] = st["name"]
        rows.extend(res)
        statuses.append({"store_id": st["id"], "store_name": st["name"], "count": len(res),
                         "amount": round(sum(float(r.get("total_price") or 0) for r in res), 2)})
    rows.sort(key=lambda r: r.get("created_at") or "")
    all_failed = bool(statuses) and all(x.get("error") for x in statuses)
    return BOVShopifyOrdersListResponse(
        configured=True, kind=kind, older_than_days=(days if kind == "unfulfilled_aged" else None),
        orders=[BOVShopifyOrderRow(**r) for r in rows], count=len(rows),
        total_amount=round(sum(float(r.get("total_price") or 0) for r in rows), 2),
        stores=[BOVStoreStatus(**x) for x in statuses], skipped_stores=skipped, limit=limit,
        truncated=any((x.get("count") or 0) >= limit for x in statuses),
        error=("; ".join(f"{x['store_name']}: {x['error']}" for x in statuses) if all_failed else None),
        store_name=(", ".join(st["name"] for st in usable) if usable else None),
    )


@app.get("/api/business-overview/shopify/orders/{store_id}/{shopify_id}", response_model=BOVShopifyOrderDetailResponse)
async def get_business_overview_shopify_order_detail(store_id: int, shopify_id: int, db: Session = Depends(get_db)):
    cfg = _bov_config(db)
    store = next((st for st in _bov_shopify_stores(db, cfg) if st["id"] == store_id), None)
    if store is None:
        raise HTTPException(status_code=400, detail=f"Store {store_id} is not a configured Shopify store.")
    payload = await bov.shopify_order_detail(store_id, shopify_id)
    if not payload.get("header"):
        raise HTTPException(status_code=404, detail="Order not found in the local mirror")
    header = payload["header"]
    header["store_name"] = store["name"]
    # Per-line product cost/profit from the S2S items table (UnitPriceC by barcode);
    # soft — unresolved lookups leave the cost fields null.
    lines = payload.get("lines") or []
    lookup = _bov_make_cost_lookup(db, cfg, "unit_delivery_b")
    barcodes = sorted({(l.get("barcode") or "").strip() for l in lines if (l.get("barcode") or "").strip()})
    unit_costs = await lookup(barcodes) if (barcodes and getattr(lookup, "configured", False)) else {}
    cost_known = bool(getattr(lookup, "configured", False)) and not getattr(lookup, "failed", None)
    revenue = cost = units = known = 0.0
    for l in lines:
        qty = float(l["current_quantity"] if l.get("current_quantity") is not None else (l.get("quantity") or 0))
        rev = float(l.get("discounted_total") or 0)
        uc = unit_costs.get((l.get("barcode") or "").strip()) if cost_known else None
        l["unit_cost"] = (float(uc) if uc is not None else None)
        l["line_cost"] = (round(qty * float(uc), 4) if uc is not None else None)
        l["line_profit"] = (round(rev - qty * float(uc), 4) if uc is not None else None)
        l["margin_pct"] = (bov.margin_pct(rev, qty * float(uc)) if (uc is not None and rev) else None)
        revenue += rev
        units += qty
        if uc is not None:
            cost += qty * float(uc)
            known += qty
    header["revenue"] = round(revenue, 2)
    header["cost_coverage"] = (round(known / units, 4) if units else None)
    if units and not known:
        header["cost"] = header["product_profit"] = header["margin_pct"] = None
    else:
        header["cost"] = round(cost, 2)
        header["product_profit"] = round(revenue - cost, 2)
        header["margin_pct"] = bov.margin_pct(revenue, cost)
    domain = (store.get("shop_domain") or "").replace("https://", "").replace("http://", "").strip("/")
    admin_url = f"https://{domain}/admin/orders/{shopify_id}" if domain else None
    return BOVShopifyOrderDetailResponse(header=BOVShopifyOrderHeader(**header),
                                         lines=[BOVShopifyOrderLine(**l) for l in payload.get("lines") or []],
                                         store_name=store["name"], admin_url=admin_url)


@app.get("/api/business-overview/shopify/missing-cost", response_model=BOVMissingCostResponse)
async def get_business_overview_shopify_missing_cost(
    preset: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
    store_ids: Optional[str] = None, cost_mode: str = "default",
    db: Session = Depends(get_db),
):
    """
    Shopify products sold in the period whose barcode does not resolve to a cost
    in the S2S store (no barcode, barcode not in Items_tbl, or the cost column —
    UnitPriceC by default, UnitCost in S2S mode — empty) — the list behind
    "Shopify cost known for N%", exportable to hand off for fixing.
    """
    cfg = _bov_config(db)
    period = _bov_period(cfg, preset, date_from, date_to)
    only = _bov_parse_store_ids(store_ids)
    cost_field = _bov_shopify_cost_field(_bov_cost_mode(cost_mode))
    if not _bov_shopify_stores(db, cfg):
        return BOVMissingCostResponse(configured=False, period=BOVPeriod(**period.as_dict()))
    stores = _bov_shopify_stores(db, cfg, only)
    if not stores:
        return BOVMissingCostResponse(configured=True, filtered_out=True, period=BOVPeriod(**period.as_dict()))
    synced = await asyncio.to_thread(shopify_sync.get_synced_stores)
    usable = [st for st in stores if st["id"] in synced]
    skipped = [st["name"] for st in stores if st["id"] not in synced]
    sh_excl = _bov_shopify_exclusions(db)
    results = await asyncio.gather(*[bov.shopify_products_sold(st["id"], (synced.get(st["id"]) or {}).get("shop_timezone") or _bov_tz(cfg),
                                                                period.start.isoformat(), period.end_excl, sh_excl) for st in usable], return_exceptions=True)
    statuses: List[Dict[str, Any]] = []
    sold: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for st, res in zip(usable, results):
        if isinstance(res, Exception):
            statuses.append({"store_id": st["id"], "store_name": st["name"], "error": str(res)})
            continue
        statuses.append({"store_id": st["id"], "store_name": st["name"], "count": len(res)})
        for r in res:
            sold.append((st, r))
    conn = _bov_cost_conn(db, cfg)
    cost_store = db.query(Store).filter(Store.id == conn.store_id).first() if conn else None
    barcodes = sorted({(r.get("barcode") or "").strip() for _st, r in sold if (r.get("barcode") or "").strip()})
    by_upc: Dict[str, Any] = {}
    lookup_error: Optional[str] = None
    if conn is not None and barcodes:
        ok, err, found = await get_item_prices_batch_async(host=conn.host, port=conn.port, database=conn.database_name,
                                                          username=conn.username, password=conn.password,
                                                          upcs=barcodes, include_discontinued=True)
        if ok and isinstance(found, dict):
            by_upc = found
        else:
            lookup_error = err or "cost lookup failed"
    rows: List[Dict[str, Any]] = []
    for st, r in sold:
        bc = (r.get("barcode") or "").strip()
        if not bc:
            reason = "no_barcode"
        elif conn is None or lookup_error:
            continue   # cannot judge without a cost source
        elif bc not in by_upc:
            reason = "not_in_items"
        else:
            c = by_upc[bc].get(cost_field)
            try:
                has = c is not None and float(c) > 0
            except (TypeError, ValueError):
                has = False
            if has:
                continue
            reason = "no_cost"
        domain = (st.get("shop_domain") or "").replace("https://", "").replace("http://", "").strip("/")
        admin_url = f"https://{domain}/admin/products/{r['product_shopify_id']}" if domain and r.get("product_shopify_id") else None
        rows.append({**r, "store_id": st["id"], "store_name": st["name"], "reason": reason, "admin_url": admin_url})
    rows.sort(key=lambda x: -(x.get("revenue") or 0))
    err_msg = None
    if conn is None:
        err_msg = "Item Tracker S2S store is not configured — cannot check costs"
    elif lookup_error:
        err_msg = f"Cost lookup failed: {lookup_error}"
    return BOVMissingCostResponse(
        configured=True, period=BOVPeriod(**period.as_dict()),
        cost_store_name=(cost_store.name if cost_store else None),
        rows=[BOVMissingCostRow(**x) for x in rows], count=len(rows),
        units=round(sum(float(x.get("units") or 0) for x in rows), 2),
        revenue=round(sum(float(x.get("revenue") or 0) for x in rows), 2),
        products_checked=len(sold), stores=[BOVStoreStatus(**x) for x in statuses], skipped_stores=skipped,
        error=err_msg,
    )


@app.get("/api/business-overview/shopify/exclusions", response_model=BOVShopifyExclusionList)
def list_business_overview_shopify_exclusions(db: Session = Depends(get_db)):
    rows = db.query(BusinessOverviewShopifyExclusion).order_by(BusinessOverviewShopifyExclusion.created_at.desc()).all()
    out = []
    for e in rows:
        d = BOVShopifyExclusion.model_validate(e)
        d.store_name = e.store.name if e.store else None
        out.append(d)
    return BOVShopifyExclusionList(exclusions=out, total=len(out))


@app.post("/api/business-overview/shopify/exclusions", response_model=BOVShopifyExclusion)
def add_business_overview_shopify_exclusion(data: BOVShopifyExclusionCreate, db: Session = Depends(get_db)):
    bc = (data.barcode or "").strip() or None
    if not bc and not data.variant_shopify_id and not data.product_shopify_id:
        raise HTTPException(status_code=400, detail="An exclusion needs a barcode, a Shopify variant id or a product id")
    if data.store_id is not None and not db.query(Store).filter(Store.id == data.store_id, Store.store_type == StoreType.shopify).first():
        raise HTTPException(status_code=400, detail=f"Invalid Shopify store ID: {data.store_id}")
    q = db.query(BusinessOverviewShopifyExclusion)
    q = q.filter(BusinessOverviewShopifyExclusion.store_id.is_(None)) if data.store_id is None else q.filter(BusinessOverviewShopifyExclusion.store_id == data.store_id)
    q = q.filter(BusinessOverviewShopifyExclusion.variant_shopify_id.is_(None)) if not data.variant_shopify_id else q.filter(BusinessOverviewShopifyExclusion.variant_shopify_id == data.variant_shopify_id)
    q = q.filter(BusinessOverviewShopifyExclusion.product_shopify_id.is_(None)) if not data.product_shopify_id else q.filter(BusinessOverviewShopifyExclusion.product_shopify_id == data.product_shopify_id)
    q = q.filter(BusinessOverviewShopifyExclusion.barcode.is_(None)) if bc is None else q.filter(BusinessOverviewShopifyExclusion.barcode == bc)
    row = q.first()
    if not row:
        row = BusinessOverviewShopifyExclusion(store_id=data.store_id, variant_shopify_id=data.variant_shopify_id,
                                               product_shopify_id=data.product_shopify_id, barcode=bc, sku=data.sku,
                                               title=data.title, note=data.note)
        db.add(row)
        db.commit()
        db.refresh(row)
    d = BOVShopifyExclusion.model_validate(row)
    d.store_name = row.store.name if row.store else None
    return d


@app.delete("/api/business-overview/shopify/exclusions/{exclusion_id}")
def delete_business_overview_shopify_exclusion(exclusion_id: int, db: Session = Depends(get_db)):
    row = db.query(BusinessOverviewShopifyExclusion).filter(BusinessOverviewShopifyExclusion.id == exclusion_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Exclusion not found")
    db.delete(row)
    db.commit()
    return {"deleted": exclusion_id}


@app.post("/api/business-overview/shopify/refresh", response_model=BOVShopifyRefreshResponse)
async def business_overview_shopify_refresh(
    store_ids: Optional[str] = None, max_age_minutes: float = 10.0,
    db: Session = Depends(get_db),
):
    """
    Catch-up incremental sync of the configured Shopify mirrors (same claim /
    run / release sequence as the Lost Customers pre-run refresh). Stores whose
    last successful sync is younger than `max_age_minutes`, that never synced,
    or that are mid-sync are skipped; failures never raise — the page keeps
    using the last synced data.
    """
    cfg = _bov_config(db)
    only = _bov_parse_store_ids(store_ids)
    stores = _bov_shopify_stores(db, cfg, only)
    if not stores:
        return BOVShopifyRefreshResponse(results=[], synced_any=False, seconds=0.0)
    started = asyncio.get_running_loop().time()
    state_rows = {r["store_id"]: dict(r) for r in db.execute(sa_text(
        "SELECT store_id, last_completed_at, last_sync_started_at, status, heartbeat_at "
        "FROM shopify_sync_state WHERE store_id = ANY(:ids)"), {"ids": [st["id"] for st in stores]}).mappings()}
    now = datetime.now(timezone.utc)

    async def refresh_one(sh: Dict[str, Any]) -> Dict[str, Any]:
        res: Dict[str, Any] = {"store_id": sh["id"], "store_name": sh["name"]}
        st = state_rows.get(sh["id"])
        last = st["last_completed_at"] if st else None
        res["last_synced_at"] = last.isoformat() if last else None
        anchor = st["last_sync_started_at"] if st else None
        if not st or last is None or anchor is None:
            res.update(status="never_synced", note="never synced — run a full Data Sync first")
            return res
        if max_age_minutes > 0 and (now - last).total_seconds() < max_age_minutes * 60:
            res.update(status="fresh", note=f"synced {int((now - last).total_seconds() // 60)} min ago")
            return res
        token = await asyncio.to_thread(shopify_sync.claim_sync, sh["id"], "incremental")
        if token is None:
            res.update(status="running", note="a sync is already running")
            return res

        async def _quiet_emit(kind, payload):
            return None

        t0 = asyncio.get_running_loop().time()
        try:
            summary = await shopify_sync.run_store_sync(dict(sh), "incremental", anchor, _quiet_emit, claim_token=token)
            await asyncio.to_thread(shopify_sync.release_sync, sh["id"], counts=summary["totals"],
                                    run_started=summary["run_started"], claim_token=token)
            d = summary["synced"]
            res.update(status="synced", seconds=round(asyncio.get_running_loop().time() - t0, 1),
                       orders=int(d.get("orders") or 0), customers=int(d.get("customers") or 0),
                       note=f"{int(d.get('orders') or 0):,} order(s) updated",
                       last_synced_at=summary["run_started"].isoformat() if summary.get("run_started") else res["last_synced_at"])
        except asyncio.CancelledError:
            asyncio.create_task(asyncio.to_thread(shopify_sync.release_sync, sh["id"], error="cancelled", claim_token=token))
            raise
        except Exception as e:
            await asyncio.to_thread(shopify_sync.release_sync, sh["id"], error=str(e)[:500], claim_token=token)
            res.update(status="failed", note=f"refresh failed: {str(e)[:160]} — using last synced data")
        return res

    results = await asyncio.gather(*[refresh_one(sh) for sh in stores], return_exceptions=True)
    out: List[Dict[str, Any]] = []
    for sh, r in zip(stores, results):
        if isinstance(r, Exception):
            out.append({"store_id": sh["id"], "store_name": sh["name"], "status": "failed", "note": str(r)[:160]})
        else:
            out.append(r)
    return BOVShopifyRefreshResponse(
        results=[BOVShopifyRefreshResult(**r) for r in out],
        synced_any=any(r.get("status") == "synced" for r in out),
        seconds=round(asyncio.get_running_loop().time() - started, 1),
    )


# ---- Attention strip: operational alerts against configurable thresholds ----

def _bov_days_label(v) -> str:
    try:
        d = float(v)
    except (TypeError, ValueError):
        return f"{v} days"
    if d == int(d):
        return f"{int(d)} day{'s' if int(d) != 1 else ''}"
    return f"{d:g} days"


@app.get("/api/business-overview/alerts", response_model=BOVAlertsResponse)
async def get_business_overview_alerts(
    preset: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
    store_ids: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Evaluate the operational alert rules (unshipped past cutoff, open-invoice
    age, stuck quotations, overdue POs, Shopify on-hold / unfulfilled aging /
    stale sync). Money rules (margin floor, revenue drop) are evaluated on the
    client from the summary it already holds, using the same merged rules
    returned here. A failing rule lands in `errors`, never a 500.
    """
    cfg = _bov_config(db)
    period = _bov_period(cfg, preset, date_from, date_to)
    only = _bov_parse_store_ids(store_ids)
    rules = bov_merge_alert_rules(cfg.alert_rules if cfg else None)
    tz_name = _bov_tz(cfg)
    try:
        now_tz = datetime.now(_BovZoneInfo(tz_name))
    except Exception:
        now_tz = datetime.now(timezone.utc)
    today = now_tz.date()
    alerts: List[Dict[str, Any]] = []
    checked: List[str] = []
    skipped: List[str] = []
    errors: List[str] = []
    excl_names, _ = _bov_excluded_names(db)
    sales_stores = _bov_sales_stores(db, cfg, only)
    purchases_store, purch_filtered_out = _bov_purchases_store(db, cfg, only)
    admin_store = _resolve_admin_store_soft(db)
    shopify_stores = _bov_shopify_stores(db, cfg, only)

    def _store_bits(results, key="count") -> Tuple[List[str], str]:
        names = [st.name for st, ok, _e, p in results if ok and (p.get(key) or 0) > 0]
        detail = ", ".join(f"{st.name} {bovInt(p.get(key) or 0)}" for st, ok, _e, p in results if ok and (p.get(key) or 0) > 0)
        return names, detail

    def bovInt(v):
        try:
            return f"{int(v):,}"
        except (TypeError, ValueError):
            return str(v)

    tasks: List[Any] = []
    match_by_key: Dict[str, Dict[str, Any]] = {}
    keys: List[str] = []

    # --- invoices: past cutoff / too old (per-store overrides: a store that
    #     never enters tracking numbers can opt out or use its own threshold)
    def _store_rule(rule: Dict[str, Any], st) -> Optional[Dict[str, Any]]:
        ov = (rule.get("stores") or {}).get(str(st.id)) or {}
        if ov.get("enabled") is False:
            return None
        eff = {k: v for k, v in rule.items() if k != "stores"}
        eff.update({k: v for k, v in ov.items() if k != "enabled"})
        return eff

    r = rules["unshipped_cutoff"]
    if r.get("enabled") and sales_stores:
        per_store_cut: List[Tuple[Any, str]] = []
        opted_out: List[str] = []
        for st in sales_stores:
            eff = _store_rule(r, st)
            if eff is None:
                opted_out.append(st.name)
                continue
            hh, mm = [int(x) for x in str(eff.get("cutoff", "14:00")).split(":")]
            cutoff_dt = now_tz.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if now_tz >= cutoff_dt:
                per_store_cut.append((st, cutoff_dt.strftime("%Y-%m-%d %H:%M")))
        if opted_out:
            skipped.append(f"unshipped_cutoff: not applied to {', '.join(opted_out)}")
        if per_store_cut:
            keys.append("unshipped_cutoff")
            cut_by_id = {st.id: d for st, d in per_store_cut}
            match_by_key["unshipped_cutoff"] = {"kind": "invoice_open_before", "before_by_store": {str(k): v for k, v in cut_by_id.items()}}
            tasks.append(_bov_fanout([st for st, _d in per_store_cut], lambda st: bov.open_invoices_count_async(
                **_bov_conn_kwargs(st), dated_before=cut_by_id[st.id], excluded_names=excl_names)))
        elif len(opted_out) < len(sales_stores):
            skipped.append("unshipped_cutoff: cutoff not reached yet")
    elif not r.get("enabled"):
        skipped.append("unshipped_cutoff: disabled")
    r = rules["open_invoice_age"]
    if r.get("enabled") and sales_stores:
        per_store_age: List[Tuple[Any, str]] = []
        opted_out = []
        for st in sales_stores:
            eff = _store_rule(r, st)
            if eff is None:
                opted_out.append(st.name)
                continue
            per_store_age.append((st, (today - timedelta(days=float(eff.get("days", 2)))).isoformat()))
        if opted_out:
            skipped.append(f"open_invoice_age: not applied to {', '.join(opted_out)}")
        if per_store_age:
            keys.append("open_invoice_age")
            age_by_id = {st.id: d for st, d in per_store_age}
            match_by_key["open_invoice_age"] = {"kind": "invoice_open_before", "before_by_store": {str(k): v for k, v in age_by_id.items()}}
            tasks.append(_bov_fanout([st for st, _d in per_store_age], lambda st: bov.open_invoices_count_async(
                **_bov_conn_kwargs(st), dated_before=age_by_id[st.id], excluded_names=excl_names)))
    elif not r.get("enabled"):
        skipped.append("open_invoice_age: disabled")
    # --- quotations stuck
    r = rules["quotation_stuck"]
    if r.get("enabled") and admin_store is not None:
        source_dbs = _bov_quotation_source_dbs(db, only)
        if source_dbs is not None and not source_dbs:
            skipped.append("quotation_stuck: no BackOffice store in filter")
        else:
            keys.append("quotation_stuck")
            started_before = (now_tz - timedelta(days=float(r.get("days", 1)))).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
            match_by_key["quotation_stuck"] = {"kind": "quotation_started_before", "before": started_before}
            statuses = list((cfg.quotation_statuses if cfg else BOV_DEFAULT_QUOTATION_STATUSES) or [])
            tasks.append(bov.quotations_in_progress_async(
                **_bov_conn_kwargs(admin_store), statuses=statuses, limit=1, include_list=False,
                source_dbs=source_dbs, excluded_names=excl_names, started_before=started_before))
    elif not r.get("enabled"):
        skipped.append("quotation_stuck: disabled")
    # --- POs overdue
    r = rules["po_overdue"]
    if r.get("enabled") and purchases_store is not None and not purch_filtered_out:
        keys.append("po_overdue")
        before = (today - timedelta(days=int(float(r.get("days", 14))))).isoformat()
        match_by_key["po_overdue"] = {"kind": "po_placed_before", "before": before}
        tasks.append(bov.incoming_purchases_async(**_bov_conn_kwargs(purchases_store), limit=1, include_list=False, placed_before=before,
                                                  excluded_product_ids=_bov_po_exclusion_ids(db, purchases_store.id) or None))
    elif not r.get("enabled"):
        skipped.append("po_overdue: disabled")
    # --- Shopify mirror exceptions
    synced = await asyncio.to_thread(shopify_sync.get_synced_stores) if shopify_stores else {}
    sh_rules_on = rules["shopify_on_hold"].get("enabled") or rules["shopify_unfulfilled_age"].get("enabled")
    sh_synced_stores = [st for st in shopify_stores if st["id"] in synced]
    if sh_rules_on and sh_synced_stores:
        keys.append("shopify_exceptions")
        hours = float(rules["shopify_unfulfilled_age"].get("days", 2)) * 24.0
        match_by_key["shopify_on_hold"] = {"kind": "shopify_on_hold"}
        match_by_key["shopify_unfulfilled_age"] = {"kind": "shopify_unfulfilled_before",
                                                   "before": (now_tz - timedelta(hours=hours)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

        async def _sh_all():
            res = await asyncio.gather(*[bov.shopify_exception_counts(st["id"], hours) for st in sh_synced_stores], return_exceptions=True)
            return list(zip(sh_synced_stores, res))
        tasks.append(_sh_all())

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for key, res in zip(keys, results):
        checked.append(key)
        if isinstance(res, Exception):
            errors.append(f"{key}: {res}")
            continue
        try:
            if key in ("unshipped_cutoff", "open_invoice_age"):
                fan = res
                fails = [f"{st.name}: {err}" for st, ok, err, _p in fan if not ok]
                if fails and len(fails) == len(fan):
                    errors.append(f"{key}: {'; '.join(fails)}")
                    continue
                if fails:
                    errors.append(f"{key} (partial): {'; '.join(fails)}")
                count = sum(int(p.get("count") or 0) for _st, ok, _e, p in fan if ok)
                amount = round(sum(float(p.get("total_amount") or 0) for _st, ok, _e, p in fan if ok), 2)
                if count > 0:
                    names, detail = _store_bits(fan)
                    if key == "unshipped_cutoff":
                        rr = rules["unshipped_cutoff"]
                        cutoffs = {(rr.get("stores") or {}).get(str(st.id), {}).get("cutoff", rr.get("cutoff")) for st, ok, _e, _p in fan if ok}
                        cut_label = f"the {rr.get('cutoff')} cutoff" if len(cutoffs) <= 1 else "today's cutoff"
                        alerts.append({"key": key, "severity": "critical", "count": count, "amount": amount, "stores": names,
                                       "title": f"{bovInt(count)} unshipped invoice{'s' if count != 1 else ''} past {cut_label}",
                                       "detail": f"No tracking number yet · {detail}",
                                       "action": {"section": "invoices", "tab": "invoices:open", "open_all_dates": True,
                                                  "sort": {"widget": "invoicesOpen", "key": "age_days", "dir": "desc"}, "target": "bov-invoices-card",
                                                  "match": match_by_key.get("unshipped_cutoff")}})
                    else:
                        rr = rules["open_invoice_age"]
                        ages = {(rr.get("stores") or {}).get(str(st.id), {}).get("days", rr.get("days")) for st, ok, _e, _p in fan if ok}
                        age_label = _bov_days_label(rr.get("days", 2)) if len(ages) <= 1 else "its store's limit"
                        alerts.append({"key": key, "severity": "warn", "count": count, "amount": amount, "stores": names,
                                       "title": f"{bovInt(count)} open invoice{'s' if count != 1 else ''} older than {age_label}",
                                       "detail": f"Still unshipped · {detail}",
                                       "action": {"section": "invoices", "tab": "invoices:open", "open_all_dates": True,
                                                  "sort": {"widget": "invoicesOpen", "key": "age_days", "dir": "desc"}, "target": "bov-invoices-card",
                                                  "match": match_by_key.get("open_invoice_age")}})
            elif key == "quotation_stuck":
                ok, err, payload = res
                if not ok:
                    errors.append(f"{key}: {err}")
                    continue
                count = int(payload.get("count") or 0)
                if count > 0:
                    rr = rules["quotation_stuck"]
                    by = ", ".join(f"{x.get('status') or '—'} {bovInt(x.get('count') or 0)}" for x in (payload.get("by_status") or []) if x.get("count"))
                    alerts.append({"key": key, "severity": "warn", "count": count, "amount": payload.get("total_amount"), "stores": [],
                                   "title": f"{bovInt(count)} quotation{'s' if count != 1 else ''} in progress for more than {_bov_days_label(rr.get('days', 1))}",
                                   "detail": by or None,
                                   "action": {"section": "quotations", "sort": {"widget": "quotations", "key": "start_date", "dir": "asc"}, "target": "bov-quotations-card",
                                              "match": match_by_key.get("quotation_stuck")}})
            elif key == "po_overdue":
                ok, err, payload = res
                if not ok:
                    errors.append(f"{key}: {err}")
                    continue
                count = int(payload.get("count") or 0)
                if count > 0:
                    rr = rules["po_overdue"]
                    alerts.append({"key": key, "severity": "warn", "count": count, "amount": payload.get("outstanding_value"), "stores": [purchases_store.name],
                                   "title": f"{bovInt(count)} purchase order{'s' if count != 1 else ''} outstanding for more than {int(float(rr.get('days', 14)))} days",
                                   "detail": f"{bovInt(payload.get('qty_outstanding') or 0)} units still expected",
                                   "action": {"section": "purchasing", "tab": "purchases:incoming", "sort": {"widget": "purchasesIncoming", "key": "po_date", "dir": "asc"}, "target": "bov-purchases-card",
                                              "match": match_by_key.get("po_overdue")}})
            elif key == "shopify_exceptions":
                on_hold = 0; on_hold_v = 0.0; unf = 0; unf_v = 0.0
                hold_names: List[str] = []; unf_names: List[str] = []
                for st, cnt in res:
                    if isinstance(cnt, Exception):
                        errors.append(f"shopify ({st['name']}): {cnt}")
                        continue
                    if cnt.get("on_hold"):
                        on_hold += cnt["on_hold"]; on_hold_v += cnt.get("on_hold_value") or 0; hold_names.append(f"{st['name']} {bovInt(cnt['on_hold'])}")
                    if cnt.get("unfulfilled_old"):
                        unf += cnt["unfulfilled_old"]; unf_v += cnt.get("unfulfilled_old_value") or 0; unf_names.append(f"{st['name']} {bovInt(cnt['unfulfilled_old'])}")
                if rules["shopify_on_hold"].get("enabled") and on_hold > 0:
                    alerts.append({"key": "shopify_on_hold", "severity": "warn", "count": on_hold, "amount": round(on_hold_v, 2), "stores": [n.rsplit(" ", 1)[0] for n in hold_names],
                                   "title": f"{bovInt(on_hold)} Shopify order{'s' if on_hold != 1 else ''} on hold", "detail": ", ".join(hold_names),
                                   "action": {"section": "shopify", "tab": "shopifyorders:on_hold", "target": "bov-shopify-orders-card", "match": match_by_key.get("shopify_on_hold")}})
                if rules["shopify_unfulfilled_age"].get("enabled") and unf > 0:
                    rr = rules["shopify_unfulfilled_age"]
                    alerts.append({"key": "shopify_unfulfilled_age", "severity": "warn", "count": unf, "amount": round(unf_v, 2), "stores": [n.rsplit(" ", 1)[0] for n in unf_names],
                                   "title": f"{bovInt(unf)} Shopify order{'s' if unf != 1 else ''} unfulfilled for more than {_bov_days_label(rr.get('days', 2))}", "detail": ", ".join(unf_names),
                                   "action": {"section": "shopify", "tab": "shopifyorders:unfulfilled_aged", "target": "bov-shopify-orders-card", "match": match_by_key.get("shopify_unfulfilled_age")}})
        except Exception as e:  # never let a rule take the strip down
            errors.append(f"{key}: {e}")

    # --- Shopify sync stale / failed / never synced (no query beyond state)
    r = rules["shopify_sync_stale"]
    if r.get("enabled") and shopify_stores:
        checked.append("shopify_sync_stale")
        try:
            states = {st["store_id"]: st for st in await asyncio.to_thread(shopify_sync.get_sync_states)}
            hours = float(r.get("days", 1)) * 24.0
            now_utc = datetime.now(timezone.utc)
            bad: List[str] = []
            for st in shopify_stores:
                row = states.get(st["id"])
                last = None
                if row and row.get("last_completed_at"):
                    try:
                        last = datetime.fromisoformat(str(row["last_completed_at"]).replace("Z", "+00:00"))
                    except ValueError:
                        last = None
                if not row or last is None:
                    bad.append(f"{st['name']}: never synced")
                elif row.get("status") == "error":
                    bad.append(f"{st['name']}: last sync failed")
                elif (now_utc - last).total_seconds() > hours * 3600:
                    age_h = (now_utc - last).total_seconds() / 3600
                    bad.append(f"{st['name']}: synced {age_h / 24:.1f} days ago" if age_h >= 48 else f"{st['name']}: synced {age_h:.0f} h ago")
            if bad:
                alerts.append({"key": "shopify_sync_stale", "severity": "info", "count": len(bad), "stores": [b.split(":")[0] for b in bad],
                               "title": f"Shopify data stale for {len(bad)} store{'s' if len(bad) != 1 else ''}", "detail": "; ".join(bad),
                               "action": {"section": "shopify", "target": "bov-shopify-card"}})
        except Exception as e:
            errors.append(f"shopify_sync_stale: {e}")
    elif not r.get("enabled"):
        skipped.append("shopify_sync_stale: disabled")

    sev_rank = {"critical": 0, "warn": 1, "info": 2}
    alerts.sort(key=lambda a: (sev_rank.get(a["severity"], 9), -(a.get("count") or 0)))
    return BOVAlertsResponse(
        period=BOVPeriod(**period.as_dict()), rules=rules,
        alerts=[BOVAlert(**{**a, "action": BOVAlertAction(**a["action"]) if a.get("action") else None}) for a in alerts],
        checked=checked, skipped=skipped, errors=errors, generated_at=datetime.utcnow(),
    )


# ============================================================================
# Month End — combined BackOffice invoices + Shopify orders with real shipping
# ============================================================================

def _month_end_default_range(tz: str) -> Tuple[str, str]:
    """Previous calendar month in the configured timezone."""
    today = bov.today_in_tz(tz)
    prev_end = today.replace(day=1) - timedelta(days=1)
    return prev_end.replace(day=1).isoformat(), prev_end.isoformat()


def _month_end_totals(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    t = {"orders": 0, "total": 0.0, "revenue": 0.0, "cost": 0.0, "product_profit": 0.0,
         "shipping_collected": 0.0, "shipping_cost": 0.0, "profit": 0.0, "profit_known": 0}
    for r in rows:
        t["orders"] += 1
        for k in ("total", "revenue", "cost", "product_profit", "shipping_collected", "shipping_cost"):
            v = r.get(k)
            if v is not None:
                t[k] += float(v)
        if r.get("profit") is not None:
            t["profit"] += float(r["profit"])
            t["profit_known"] += 1
    for k in ("total", "revenue", "cost", "product_profit", "shipping_collected", "shipping_cost", "profit"):
        t[k] = round(t[k], 2)
    return t


# How far past the period a parcel may still belong to one of its orders: the
# window query covers [start, end + pad); later shipments are swept by the
# exact IN(...) fallback over just the unmatched order names.
_MONTH_END_PARCEL_PAD_DAYS = 45

# Month End is a month-close report: totals must cover every order, so its
# per-store row ceiling sits far above monthly volume (~6k Shopify orders)
# instead of the 5k MAX_LIST_LIMIT the interactive BOV lists use.
_MONTH_END_MAX_ROWS = 20000

# Estimated shipping for orders without a parcel: average the real parcel costs
# of same-store orders shipped to the same state with a total within
# ±max($10, 10% of the total) — the flat floor serves typical orders, the
# percentage keeps large totals from having an impossibly narrow window.
# Comparables come from the period plus this many days of lookback.
_MONTH_END_ESTIMATE_LOOKBACK_DAYS = 90
_MONTH_END_ESTIMATE_TOLERANCE = 10.0
_MONTH_END_ESTIMATE_TOLERANCE_PCT = 0.10


async def _month_end_payload(db: Session, date_from: Optional[str], date_to: Optional[str],
                             limit: int, store_ids: Optional[str] = None, progress=None) -> Dict[str, Any]:
    async def note(msg: str):
        if progress:
            await progress(msg)

    cfg = _bov_config(db)
    tz = _bov_tz(cfg)
    if not date_from and not date_to:
        date_from, date_to = _month_end_default_range(tz)
    period = _bov_period(cfg, None, date_from, date_to)
    limit = max(1, min(int(limit or _MONTH_END_MAX_ROWS), _MONTH_END_MAX_ROWS))

    only = _bov_parse_store_ids(store_ids)
    sales_stores = _bov_sales_stores(db, cfg, only)
    shopify_stores = _bov_shopify_stores(db, cfg, only)
    if not sales_stores and not shopify_stores:
        # Distinguish "nothing configured" from "the topbar store filter excludes everything".
        if only is not None and (_bov_sales_stores(db, cfg) or _bov_shopify_stores(db, cfg)):
            return {"configured": True, "filtered_out": True, "period": period.as_dict(), "limit": limit}
        return {"configured": False, "period": period.as_dict(), "limit": limit}

    warnings: List[str] = []
    synced = await asyncio.to_thread(shopify_sync.get_synced_stores) if shopify_stores else {}
    sh_excl = _bov_shopify_exclusions(db)
    usable_shopify: List[Dict[str, Any]] = []
    for st in shopify_stores:
        info = synced.get(st["id"])
        if not info:
            warnings.append(f"{st['name']}: not synced — skipped (run Data Sync)")
            continue
        st["_tz"] = info.get("shop_timezone") or tz
        usable_shopify.append(st)

    excl_sales = _bov_excluded_names(db)[0]

    async def _bo(st: Store):
        # The invoice helper clamps to its own MAX_LIST_LIMIT (5k) — far above
        # monthly BackOffice volume; only the Shopify side needs the higher cap.
        return await bov.invoices_in_period_async(
            **_bov_conn_kwargs(st), date_from=period.start.isoformat(), date_to_excl=period.end_excl,
            limit=min(limit, bov.MAX_LIST_LIMIT), sort_by="invoice_date", sort_order="desc", include_list=True,
            today=period.today, excluded_names=excl_sales, cost_mode="default")

    est_start = (period.start - timedelta(days=_MONTH_END_ESTIMATE_LOOKBACK_DAYS)).isoformat()

    async def _sh(st: Dict[str, Any]):
        (ok, err, payload), lines, comparables = await asyncio.gather(
            bov.month_end_shopify_orders(st["id"], st["_tz"], period.start.isoformat(), period.end_excl, limit),
            bov.month_end_shopify_lines(st["id"], st["_tz"], period.start.isoformat(), period.end_excl, sh_excl),
            bov.month_end_ship_comparables(st["id"], st["_tz"], est_start, period.end_excl),
        )
        if not ok:
            return ok, err, payload
        payload["lines"] = lines
        payload["comparables"] = comparables
        return True, None, payload

    await note(f"Loading orders from {len(sales_stores)} BackOffice store(s) and "
               f"{len(usable_shopify)} synced Shopify store(s)…")
    timings: Dict[str, float] = {}
    t_fetch = time.monotonic()
    bo_results, sh_results = await asyncio.gather(
        _bov_fanout(sales_stores, _bo),
        asyncio.gather(*[_sh(st) for st in usable_shopify], return_exceptions=True),
    )
    timings["fetch"] = round(time.monotonic() - t_fetch, 2)

    stores_status: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []
    truncated = False

    # ---- BackOffice rows (profit already net of Invoices_tbl.ShippingCost)
    for st, ok, err, payload in bo_results:
        if not ok:
            warnings.append(f"{st.name}: {err}")
            stores_status.append({"store_id": st.id, "store_name": st.name, "source": "backoffice", "error": err})
            continue
        stores_status.append({"store_id": st.id, "store_name": st.name, "source": "backoffice",
                              "count": int(payload.get("count") or 0), "truncated": bool(payload.get("truncated"))})
        truncated = truncated or bool(payload.get("truncated"))
        for inv in payload.get("invoices") or []:
            rows.append({
                "source": "backoffice",
                "row_key": f"bo:{st.id}:{inv['invoice_id']}",
                "store_id": st.id, "store_name": st.name,
                "date": inv.get("invoice_date"),
                "number": inv.get("invoice_number") or str(inv.get("invoice_id")),
                "customer": inv.get("business_name"),
                "total": inv.get("invoice_total"),
                "revenue": inv.get("revenue"), "cost": inv.get("cost"),
                "product_profit": inv.get("profit"),
                "shipping_collected": None,
                "shipping_cost": inv.get("shipping_cost"),
                "shipping_missing": False,
                "parcels": None,
                "profit": inv.get("net_profit"),
                "cost_coverage": inv.get("cost_coverage"),
                "status": "shipped" if inv.get("is_shipped") else "open",
            })

    # ---- Shopify store results
    sh_ok: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for st, res in zip(usable_shopify, sh_results):
        if isinstance(res, Exception):
            warnings.append(f"{st['name']}: {res}")
            stores_status.append({"store_id": st["id"], "store_name": st["name"], "source": "shopify", "error": str(res)})
            continue
        ok, err, payload = res
        if not ok:
            warnings.append(f"{st['name']}: {err}")
            stores_status.append({"store_id": st["id"], "store_name": st["name"], "source": "shopify", "error": err})
            continue
        stores_status.append({"store_id": st["id"], "store_name": st["name"], "source": "shopify",
                              "count": int(payload.get("count") or 0), "truncated": bool(payload.get("truncated"))})
        truncated = truncated or bool(payload.get("truncated"))
        sh_ok.append((st, payload))

    # ---- S2S cost lookup (UnitPriceC) + shipper parcels lookup, concurrently
    # (both hit MSSQL; running them in parallel keeps total latency = max, not sum)
    shipper_store = _resolve_shipper_store_soft(db)
    shipper: Dict[str, Any] = {"configured": shipper_store is not None,
                               "store_name": shipper_store.name if shipper_store else None,
                               "matched": 0, "unmatched": 0, "error": None}
    all_names = [o.get("name") for _st, p in sh_ok for o in (p.get("orders") or []) if o.get("name")]
    bo_count = sum(int(s.get("count") or 0) for s in stores_status if s["source"] == "backoffice" and not s.get("error"))
    await note(f"Fetched {bo_count:,} invoices and {len(all_names):,} Shopify orders "
               f"({timings['fetch']}s) — resolving product and shipping costs…")

    async def _cost_lookup() -> Dict[str, float]:
        t = time.monotonic()
        try:
            if not sh_ok:
                return {}
            barcodes = sorted({bc for _st, p in sh_ok for lines in (p.get("lines") or {}).values()
                               for (bc, _u, _r) in lines if bc})
            lookup = _bov_make_cost_lookup(db, cfg, "unit_delivery_b")
            if not getattr(lookup, "configured", False):
                warnings.append("Item Tracker S2S store not configured — Shopify cost/profit unavailable")
                return {}
            if not barcodes:
                return {}
            await note(f"Looking up product cost for {len(barcodes):,} barcodes on the S2S store…")
            costs = await lookup(barcodes)
            if getattr(lookup, "failed", None):
                warnings.append(f"Shopify cost lookup failed — profit unavailable: {lookup.failed}")
            else:
                await note(f"Product costs resolved ({round(time.monotonic() - t, 1)}s)")
            return costs
        finally:
            timings["cost_lookup"] = round(time.monotonic() - t, 2)

    async def _parcels() -> Dict[str, Dict[str, float]]:
        t = time.monotonic()
        try:
            if not shipper_store:
                if sh_ok:
                    warnings.append("Shipper store not configured — Shopify shipping cost unavailable")
                return {}
            if not all_names:
                return {}
            await note(f"Summing shipper parcel costs for {len(all_names):,} orders…")
            # One date-bounded aggregate covers a period's parcels; only names it
            # missed (late shipments) fall back to the exact IN(...) lookup. The
            # window starts at the estimate lookback so comparable orders get
            # their real parcel costs from the same single query.
            pad_end = (period.end + timedelta(days=_MONTH_END_PARCEL_PAD_DAYS + 1)).isoformat()
            ok, err, pmap = await bov.parcel_costs_window_async(
                **_bov_conn_kwargs(shipper_store),
                date_from=est_start, date_to_excl=pad_end)
            if not ok:
                shipper["error"] = err
                warnings.append(f"Shipper parcels lookup failed — Shopify shipping cost unavailable: {err}")
                return {}
            leftover = sorted({n for n in all_names if bov.normalize_order_number(n) not in pmap})
            if leftover:
                await note(f"Checking {len(leftover):,} orders without a parcel in the shipping window…")
                ok2, err2, extra = await bov.parcel_costs_async(
                    **_bov_conn_kwargs(shipper_store), order_numbers=leftover)
                if ok2:
                    pmap.update(extra)
                else:
                    warnings.append(f"Shipper parcels fallback lookup failed: {err2}")
            await note(f"Shipping costs matched ({round(time.monotonic() - t, 1)}s)")
            return pmap
        finally:
            timings["parcels"] = round(time.monotonic() - t, 2)

    unit_costs, parcel_map = await asyncio.gather(_cost_lookup(), _parcels())
    await note("Building the combined list…")

    parcels_usable = bool(shipper_store) and not shipper["error"]

    # ---- Comparable pools for estimating missing shipping: per store, plus a
    # cross-store pool for stores with no parcel history of their own (e.g. a
    # store that ships outside the shipper database entirely).
    store_buckets: Dict[int, Dict[str, List[Tuple[float, float]]]] = {}
    global_buckets: Dict[str, List[Tuple[float, float]]] = {}
    if parcels_usable:
        for st, payload in sh_ok:
            b = store_buckets.setdefault(st["id"], {})
            for c in payload.get("comparables") or []:
                p = parcel_map.get(bov.normalize_order_number(c["name"]))
                # A matched parcel with cost <= 0 means the cost was never
                # recorded — it is not a valid comparable.
                if p is None or float(p["cost"] or 0) <= 0 or c["total"] is None or not c["state"]:
                    continue
                pair = (float(c["total"]), float(p["cost"]))
                b.setdefault(c["state"], []).append(pair)
                global_buckets.setdefault(c["state"], []).append(pair)
        for bk in store_buckets.values():
            for pairs in bk.values():
                pairs.sort()
        for pairs in global_buckets.values():
            pairs.sort()

    def _ship_estimate(buckets: Dict[str, List[Tuple[float, float]]],
                       state: str, total: float) -> Tuple[Optional[float], Optional[int]]:
        pairs = buckets.get(state) or []
        tol = max(_MONTH_END_ESTIMATE_TOLERANCE, total * _MONTH_END_ESTIMATE_TOLERANCE_PCT)
        lo = bisect.bisect_left(pairs, (total - tol, float("-inf")))
        hi = bisect.bisect_right(pairs, (total + tol, float("inf")))
        if hi <= lo:
            return None, None
        return round(sum(c for _t, c in pairs[lo:hi]) / (hi - lo), 2), hi - lo

    # ---- Shopify rows: profit = product profit + shipping collected − parcels cost
    for st, payload in sh_ok:
        lines_by_order = payload.get("lines") or {}
        for o in payload.get("orders") or []:
            costing = bov.shopify_order_costing(lines_by_order.get(o["shopify_id"]) or [], unit_costs)
            parcel = parcel_map.get(bov.normalize_order_number(o.get("name")))
            if parcels_usable:
                shipper["matched" if parcel else "unmatched"] += 1
            ship_cost = parcel["cost"] if parcel else None
            missing = bool(parcels_usable and parcel is None)
            # Cost unknown either way: no parcel matched, or a parcel matched
            # but its cost was never recorded (summed to 0).
            cost_unknown = missing or bool(parcel is not None and float(parcel["cost"] or 0) <= 0)
            est = est_n = None
            est_cross = False
            if cost_unknown and o.get("ship_state") and o.get("total_price") is not None:
                t0 = float(o["total_price"])
                est, est_n = _ship_estimate(store_buckets.get(st["id"]) or {}, o["ship_state"], t0)
                if est is None:
                    est, est_n = _ship_estimate(global_buckets, o["ship_state"], t0)
                    est_cross = est is not None
            pp = costing["product_profit"]
            profit = (round(pp + (o.get("total_shipping") or 0.0) - (ship_cost or 0.0), 2)
                      if pp is not None else None)
            rows.append({
                "source": "shopify",
                "row_key": f"sh:{st['id']}:{o['shopify_id']}",
                "store_id": st["id"], "store_name": st["name"],
                "date": o.get("created_at"),
                "number": o.get("name"),
                "customer": o.get("customer_name"),
                "total": o.get("total_price"),
                "revenue": costing["revenue"], "cost": costing["cost"],
                "product_profit": pp,
                "shipping_collected": o.get("total_shipping"),
                "shipping_cost": ship_cost,
                "shipping_missing": missing,
                "ship_state": o.get("ship_state"),
                "shipping_estimate": est,
                "shipping_estimate_n": est_n,
                "shipping_estimate_cross": est_cross or None,
                "parcels": int(parcel["parcels"]) if parcel else None,
                "profit": profit,
                "cost_coverage": costing["cost_coverage"],
                "status": (str(o.get("financial_status") or "").lower() or None),
            })

    rows.sort(key=lambda r: (r.get("date") or ""), reverse=True)
    by_source = {src: _month_end_totals([r for r in rows if r["source"] == src])
                 for src in ("backoffice", "shopify") if any(r["source"] == src for r in rows)}
    return {
        "configured": True,
        "period": period.as_dict(),
        "stores": stores_status,
        "rows": rows,
        "totals": _month_end_totals(rows),
        "by_source": by_source,
        "shipper": shipper,
        "warnings": warnings,
        "limit": limit,
        "truncated": truncated,
        "timings": timings,
    }


@app.get("/api/business-overview/month-end", response_model=MonthEndResponse)
async def get_month_end(date_from: Optional[str] = None, date_to: Optional[str] = None,
                        limit: int = _MONTH_END_MAX_ROWS, store_ids: Optional[str] = None,
                        db: Session = Depends(get_db)):
    payload = await _month_end_payload(db, date_from, date_to, limit, store_ids)
    return MonthEndResponse(**payload)


@app.get("/api/business-overview/month-end/stream")
async def stream_month_end(date_from: Optional[str] = None, date_to: Optional[str] = None,
                           limit: int = _MONTH_END_MAX_ROWS, store_ids: Optional[str] = None,
                           db: Session = Depends(get_db)):
    """SSE twin of /month-end: progress events while the report is computed,
    then one `result` event carrying the full payload."""
    queue: asyncio.Queue = asyncio.Queue()

    async def progress(msg: str):
        await queue.put(("progress", {"message": msg}))

    async def runner():
        try:
            payload = await _month_end_payload(db, date_from, date_to, limit, store_ids, progress=progress)
            await queue.put(("result", payload))
        except HTTPException as e:
            await queue.put(("error", {"message": str(e.detail)}))
        except Exception as e:
            await queue.put(("error", {"message": str(e)}))
        await queue.put(None)

    async def gen():
        task = asyncio.create_task(runner())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield "event: heartbeat\ndata: {}\n\n"
                    continue
                if item is None:
                    break
                ev, data = item
                yield f"event: {ev}\ndata: {json.dumps(data)}\n\n"
        except GeneratorExit:
            task.cancel()
            raise
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                                      "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
