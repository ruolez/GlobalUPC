from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Union, AsyncGenerator, Optional
from pydantic import BaseModel
from datetime import datetime
import uvicorn
import asyncio
import json
import uuid
import os

from database import get_db, engine
from models import Store, MSSQLConnection, ShopifyConnection, Setting, StoreType, UPCUpdateHistory, UPCExclusion, ItemTrackerConfig, ItemTrackerExclusion, PriceUpdateHistory
from schemas import (
    MSSQLStoreCreate, ShopifyStoreCreate, StoreResponse,
    SettingCreate, SettingUpdate, SettingResponse,
    UPCSearchRequest, UPCSearchResponse, ProductVariantMatch,
    UPCUpdateRequest, UPCUpdateResult,
    ConfigExportResponse, ConfigImportRequest, ConfigImportResponse,
    StoreImportResult, StoreExport,
    OrphanedUPCAuditRequest, OrphanedUPCRecord, OrphanedUPCAuditResponse,
    ReconciliationRequest, ReconciliationMatch, ReconciliationResponse,
    ReconciliationUpdateRequest, ReconciliationUpdateResult, ReconciliationUpdateResponse,
    UPCUpdateHistoryResponse, UPCUpdateHistoryListRequest, UPCUpdateHistoryListResponse,
    CategoryResponse, SubCategoryResponse, StoreComparisonRequest, StoreComparisonResponse, MissingProductRecord,
    UPCExclusionCreate, UPCExclusionResponse, UPCExclusionListResponse,
    DeliveryBSyncRequest, DeliveryBStoreResult,
    ItemTrackerConfigCreate, ItemTrackerConfigResponse, ItemTrackerSearchRequest,
    ItemInfo, ItemTrackerEvent, ItemTrackerSearchResponse,
    DescriptionAutocompleteRequest, DescriptionAutocompleteResult, DescriptionAutocompleteResponse,
    ItemTrackerExclusionCreate, ItemTrackerExclusionResponse, ItemTrackerExclusionListResponse,
    PriceSearchRequest, StorePriceInfo, PriceUpdateItem, PriceUpdateRequest,
    PriceUpdateHistoryResponse, PriceUpdateHistoryBatch, PriceUpdateHistoryListResponse
)
from mssql_helper import (
    test_mssql_connection, search_upc_across_mssql_stores, search_products_by_upc,
    update_upc_across_mssql_stores, audit_orphaned_upcs,
    find_matches_by_product_id, find_matches_by_description, update_orphaned_upcs,
    check_upc_exists, sync_unit_price_c_across_stores,
    get_item_prices_async, update_item_prices_async
)
from shopify_helper import (
    test_shopify_connection, search_barcode_across_shopify_stores,
    search_products_by_barcode, update_barcodes_across_shopify_stores,
    check_barcode_exists, search_product_prices_by_barcode, update_variant_prices,
    get_all_product_variant_prices
)
from item_tracker_helper import (
    get_item_info_async, get_purchases_async, get_sales_async,
    get_customer_returns_async, get_vendor_returns_async,
    search_products_by_description_async, get_inventory_recounts_async
)

app = FastAPI(title="Global UPC API", version="1.0.0")

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

    return StreamingResponse(
        generate_update_events(),
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
        executor = ThreadPoolExecutor(max_workers=1)

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

@app.delete("/api/stores/{store_id}", status_code=204)
def delete_store(store_id: int, db: Session = Depends(get_db)):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    db.delete(store)
    db.commit()
    return None

@app.patch("/api/stores/{store_id}/toggle", response_model=StoreResponse)
def toggle_store_active(store_id: int, db: Session = Depends(get_db)):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    store.is_active = not store.is_active
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
        try:
            import queue
            progress_queue = queue.Queue()

            def progress_callback(data: dict):
                progress_queue.put(data)

            # Start reconciliation in background task
            import asyncio
            from concurrent.futures import ThreadPoolExecutor

            loop = asyncio.get_event_loop()
            executor = ThreadPoolExecutor(max_workers=1)

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
            import time
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
            # Client disconnected - clean shutdown
            print("[RECONCILIATION] Client disconnected, stopping reconciliation operation")
            return
        except Exception as e:
            print(f"[RECONCILIATION] Error in streaming: {e}")
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

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
        try:
            import queue
            progress_queue = queue.Queue()

            def progress_callback(data: dict):
                progress_queue.put(data)

            # Start update in background task
            import asyncio
            from concurrent.futures import ThreadPoolExecutor

            loop = asyncio.get_event_loop()
            executor = ThreadPoolExecutor(max_workers=1)

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
            import time
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
            # Client disconnected - clean shutdown
            print("[RECONCILIATION UPDATE] Client disconnected, stopping update operation")
            return
        except Exception as e:
            print(f"[RECONCILIATION UPDATE] Error in streaming: {e}")
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

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

# Store Comparison Endpoints
@app.get("/api/stores/mssql/{store_id}/categories", response_model=List[CategoryResponse])
async def get_store_categories(store_id: int, db: Session = Depends(get_db)):
    """
    Get all categories from a specific MSSQL store.
    """
    from mssql_helper import get_categories

    # Get store from database
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    # Validate store is MSSQL type
    if store.store_type != StoreType.mssql or not store.mssql_connection:
        raise HTTPException(status_code=400, detail="Store is not an MSSQL database")

    # Get connection details
    conn = store.mssql_connection

    # Fetch categories
    success, error, categories = await get_categories(
        host=conn.host,
        port=conn.port,
        database=conn.database_name,
        username=conn.username,
        password=conn.password
    )

    if not success:
        raise HTTPException(status_code=500, detail=error or "Failed to fetch categories")

    return categories

@app.get("/api/stores/mssql/{store_id}/subcategories", response_model=List[SubCategoryResponse])
async def get_store_subcategories(
    store_id: int,
    category_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    Get subcategories from a specific MSSQL store, optionally filtered by category.
    """
    from mssql_helper import get_subcategories

    # Get store from database
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    # Validate store is MSSQL type
    if store.store_type != StoreType.mssql or not store.mssql_connection:
        raise HTTPException(status_code=400, detail="Store is not an MSSQL database")

    # Get connection details
    conn = store.mssql_connection

    # Fetch subcategories
    success, error, subcategories = await get_subcategories(
        host=conn.host,
        port=conn.port,
        database=conn.database_name,
        username=conn.username,
        password=conn.password,
        category_id=category_id
    )

    if not success:
        raise HTTPException(status_code=500, detail=error or "Failed to fetch subcategories")

    return subcategories

@app.post("/api/comparison/stores/stream")
async def compare_stores_stream(request: StoreComparisonRequest, db: Session = Depends(get_db)):
    """
    Compare Items_tbl between two MSSQL stores with SSE streaming progress.
    Finds products in primary store that don't exist in comparison store.
    """
    primary_store_id = request.primary_store_id
    comparison_store_id = request.comparison_store_id
    filters = request.filters

    # Get both stores from database
    primary_store = db.query(Store).filter(Store.id == primary_store_id).first()
    comparison_store = db.query(Store).filter(Store.id == comparison_store_id).first()

    if not primary_store:
        raise HTTPException(status_code=404, detail="Primary store not found")
    if not comparison_store:
        raise HTTPException(status_code=404, detail="Comparison store not found")

    # Validate both stores are MSSQL type
    if primary_store.store_type != StoreType.mssql or not primary_store.mssql_connection:
        raise HTTPException(status_code=400, detail="Primary store is not an MSSQL database")
    if comparison_store.store_type != StoreType.mssql or not comparison_store.mssql_connection:
        raise HTTPException(status_code=400, detail="Comparison store is not an MSSQL database")

    # Get connection details
    primary_conn = primary_store.mssql_connection
    comparison_conn = comparison_store.mssql_connection

    async def generate_comparison_events():
        """Generator for SSE events during store comparison"""
        try:
            import queue
            progress_queue = queue.Queue()

            def progress_callback(data: dict):
                progress_queue.put(data)

            # Start comparison in background task
            import asyncio
            from concurrent.futures import ThreadPoolExecutor
            from mssql_helper import compare_stores_sync

            loop = asyncio.get_event_loop()
            executor = ThreadPoolExecutor(max_workers=1)

            # Run comparison in executor
            comparison_future = loop.run_in_executor(
                executor,
                lambda: compare_stores_sync(
                    primary_host=primary_conn.host,
                    primary_port=primary_conn.port,
                    primary_database=primary_conn.database_name,
                    primary_username=primary_conn.username,
                    primary_password=primary_conn.password,
                    comparison_host=comparison_conn.host,
                    comparison_port=comparison_conn.port,
                    comparison_database=comparison_conn.database_name,
                    comparison_username=comparison_conn.username,
                    comparison_password=comparison_conn.password,
                    category_ids=filters.category_ids,
                    subcategory_ids=filters.subcategory_ids,
                    include_discontinued=filters.include_discontinued,
                    progress_callback=progress_callback,
                    tds_version="7.4"
                )
            )

            # Poll queue for progress updates
            import time
            last_event_time = time.time()
            HEARTBEAT_INTERVAL = 15

            while not comparison_future.done():
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
            success, error, missing_products, total_checked = await comparison_future

            # Drain any remaining progress events
            while not progress_queue.empty():
                try:
                    progress_data = progress_queue.get_nowait()
                    yield f"event: progress\ndata: {json.dumps(progress_data)}\n\n"
                except queue.Empty:
                    break

            if not success:
                yield f"event: error\ndata: {json.dumps({'message': error or 'Comparison failed'})}\n\n"
                return

            # Calculate category statistics
            category_stats = {}
            for product in missing_products:
                category = product["category_name"]
                category_stats[category] = category_stats.get(category, 0) + 1

            # Send complete event with results
            result_data = {
                'primary_store_id': primary_store_id,
                'primary_store_name': primary_store.name,
                'comparison_store_id': comparison_store_id,
                'comparison_store_name': comparison_store.name,
                'missing_products': missing_products,
                'total_checked': total_checked,
                'total_missing': len(missing_products),
                'category_stats': category_stats
            }

            yield f"event: complete\ndata: {json.dumps(result_data)}\n\n"

        except GeneratorExit:
            # Client disconnected - clean shutdown
            print("[COMPARISON] Client disconnected, stopping comparison operation")
            return
        except Exception as e:
            print(f"[COMPARISON] Error in streaming: {e}")
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return StreamingResponse(
        generate_comparison_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

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

# Delivery B - UnitPriceC Sync Endpoint
@app.post("/api/delivery-b/sync/stream")
async def delivery_b_sync_stream(request: DeliveryBSyncRequest, db: Session = Depends(get_db)):
    """
    Sync UnitPriceC from primary MSSQL store to all other active MSSQL stores.
    Only processes active products (Discontinued = 0) matching by ProductUPC.
    Returns Server-Sent Events stream with real-time progress.
    """
    async def generate_sync_events():
        """Generator for SSE events during UnitPriceC sync"""
        try:
            primary_store_id = request.primary_store_id

            # Get primary store from database
            primary_store = db.query(Store).filter(Store.id == primary_store_id).first()
            if not primary_store:
                yield f"event: error\ndata: {json.dumps({'message': 'Primary store not found'})}\n\n"
                return

            # Validate primary store is MSSQL type
            if primary_store.store_type != StoreType.mssql or not primary_store.mssql_connection:
                yield f"event: error\ndata: {json.dumps({'message': 'Primary store is not an MSSQL database'})}\n\n"
                return

            # Check if primary store is an inventory store (name contains "inventory" or "inv")
            store_name_lower = primary_store.name.lower()
            if "inventory" in store_name_lower or "inv" in store_name_lower:
                yield f"event: error\ndata: {json.dumps({'message': 'Cannot use inventory store as primary store'})}\n\n"
                return

            # Get all active MSSQL stores excluding primary and inventory stores
            all_stores = db.query(Store).filter(
                Store.is_active == True,
                Store.store_type == StoreType.mssql
            ).all()

            # Filter out primary store and inventory stores
            destination_stores = []
            for store in all_stores:
                if store.id == primary_store_id:
                    continue  # Skip primary store

                store_name_lower = store.name.lower()
                if "inventory" in store_name_lower or "inv" in store_name_lower:
                    continue  # Skip inventory stores

                if store.mssql_connection:
                    destination_stores.append(store)

            if not destination_stores:
                yield f"event: error\ndata: {json.dumps({'message': 'No valid destination stores found'})}\n\n"
                return

            print(f"[DELIVERY-B] Starting sync from primary store: {primary_store.name}")
            print(f"[DELIVERY-B] Destination stores: {[s.name for s in destination_stores]}")

            # Send start event
            yield f"event: progress\ndata: {json.dumps({'status': 'starting', 'primary_store': primary_store.name, 'destination_count': len(destination_stores)})}\n\n"

            # Create a queue for progress updates from the thread
            import queue
            progress_queue = queue.Queue()

            # Define progress callback that puts events in queue
            def progress_callback(data: dict):
                progress_queue.put(data)

            # Prepare primary store connection data
            primary_conn = primary_store.mssql_connection
            primary_store_data = {
                "store_id": primary_store.id,
                "store_name": primary_store.name,
                "host": primary_conn.host,
                "port": primary_conn.port,
                "database_name": primary_conn.database_name,
                "username": primary_conn.username,
                "password": primary_conn.password
            }

            # Prepare destination stores connection data
            destination_stores_data = []
            for store in destination_stores:
                conn = store.mssql_connection
                destination_stores_data.append({
                    "store_id": store.id,
                    "store_name": store.name,
                    "host": conn.host,
                    "port": conn.port,
                    "database_name": conn.database_name,
                    "username": conn.username,
                    "password": conn.password
                })

            # Start sync operation
            loop = asyncio.get_event_loop()

            # Call sync function
            sync_task = asyncio.create_task(
                sync_unit_price_c_across_stores(
                    primary_store=primary_store_data,
                    destination_stores=destination_stores_data,
                    progress_callback=progress_callback,
                    tds_version="7.4"
                )
            )

            # Poll queue for progress updates while sync runs
            import time
            last_event_time = time.time()
            HEARTBEAT_INTERVAL = 15  # Send ping every 15 seconds

            while not sync_task.done():
                try:
                    # Check for progress updates (non-blocking)
                    progress_data = progress_queue.get_nowait()

                    print(f"[DELIVERY-B] Progress: {progress_data}")

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
            results = await sync_task

            # Drain any remaining progress events
            while not progress_queue.empty():
                try:
                    progress_data = progress_queue.get_nowait()
                    yield f"event: progress\ndata: {json.dumps(progress_data)}\n\n"
                except queue.Empty:
                    break

            print(f"[DELIVERY-B] Completed sync for {primary_store.name}: {len(results)} destination stores processed")

            # Calculate totals
            total_products_matched = sum(r["products_matched"] for r in results)
            total_products_updated = sum(r["products_updated"] for r in results)
            successful_stores = sum(1 for r in results if len(r["errors"]) == 0)

            # Send complete event with results
            result_data = {
                'primary_store_id': primary_store_id,
                'primary_store_name': primary_store.name,
                'results': results,
                'total_destination_stores': len(results),
                'successful_stores': successful_stores,
                'total_products_matched': total_products_matched,
                'total_products_updated': total_products_updated
            }

            yield f"event: complete\ndata: {json.dumps(result_data)}\n\n"

        except GeneratorExit:
            # Client disconnected - clean shutdown
            print("[DELIVERY-B] Client disconnected, stopping sync operation")
            return
        except Exception as e:
            print(f"[DELIVERY-B] Error in streaming: {e}")
            import traceback
            traceback.print_exc()
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return StreamingResponse(
        generate_sync_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

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
            "inventory_recount": 0
        }
        stores_searched = 1  # S2S store
        item_info = None
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

            # Filter out excluded business names (void-aware)
            exclusions = db.query(ItemTrackerExclusion).all()

            # Build exclusion lookup: {business_name_lower: [exclusion objects]}
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
                    # NULL void_status = exclude all events for this business
                    if excl.void_status is None:
                        return True
                    # For sale events, check void status match
                    if event.event_type == "sale" and event.is_voided is not None:
                        if excl.void_status == 1 and event.is_voided:
                            return True  # Exclude voided
                        if excl.void_status == 0 and not event.is_voided:
                            return True  # Exclude non-voided

                return False

            if exclusion_map:
                original_count = len(all_events)
                all_events = [e for e in all_events if not should_exclude(e)]
                filtered_count = original_count - len(all_events)
                if filtered_count > 0:
                    # Update event counts after filtering
                    event_counts = {
                        "purchase": 0,
                        "sale": 0,
                        "customer_return": 0,
                        "vendor_return": 0,
                        "inventory_recount": 0
                    }
                    for event in all_events:
                        event_counts[event.event_type] += 1

            # Sort all events by date (newest first)
            all_events.sort(key=lambda e: e.event_date if e.event_date else datetime.min, reverse=True)

            # Calculate running balance (working backwards from current QoH)
            if item_info and item_info.quant_on_hand is not None:
                balance = item_info.quant_on_hand
                for event in all_events:
                    if event.event_type == "inventory_recount":
                        event.expected_balance = balance
                        new_qty = event.extended_amount  # NewQty stored in extended_amount
                        event.running_balance = new_qty  # Absolute qty after recount
                        event.extended_amount = None  # Clear it, not needed in response
                        balance = new_qty if new_qty is not None else balance
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

        for store_id in request.store_ids:
            store = db.query(Store).filter(Store.id == store_id, Store.is_active == True).first()
            if not store:
                continue

            yield f"event: progress\ndata: {json.dumps({'status': 'searching', 'message': f'Searching {store.name}...'})}\n\n"

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

                if success and item_data:
                    prices.append({
                        "store_id": store.id,
                        "store_name": store.name,
                        "store_type": "mssql",
                        "product_found": True,
                        "product_description": item_data["description"],
                        "unit_price": item_data["unit_price"],
                        "unit_cost": item_data["unit_cost"],
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
                        "variants": None,
                    })
                    yield f"event: progress\ndata: {json.dumps({'status': 'error', 'message': f'Error searching {store.name}: {error}'})}\n\n"

            elif store.store_type == StoreType.shopify and store.shopify_connection:
                conn = store.shopify_connection
                success, error, variants = await search_product_prices_by_barcode(
                    shop_domain=conn.shop_domain,
                    admin_api_key=conn.admin_api_key,
                    barcode=upc,
                    api_version=conn.api_version
                )

                if success and variants:
                    # Step 2: Fetch ALL variants of the parent product(s)
                    searched_variant_ids = {v["variant_id"] for v in variants}
                    product_ids = list({v["product_id"] for v in variants})

                    all_variants = []
                    for pid in product_ids:
                        p_success, p_error, p_variants = await get_all_product_variant_prices(
                            shop_domain=conn.shop_domain,
                            admin_api_key=conn.admin_api_key,
                            product_id=pid,
                            api_version=conn.api_version
                        )
                        if p_success and p_variants:
                            all_variants.extend(p_variants)

                    # Get searched variant price for filtering siblings
                    searched_price = None
                    for v in variants:
                        if v.get("price") is not None:
                            searched_price = str(v["price"])
                            break

                    # Deduplicate by variant_id, mark searched vs sibling
                    seen = set()
                    merged_variants = []
                    for v in all_variants:
                        vid = v["variant_id"]
                        if vid in seen:
                            continue
                        seen.add(vid)
                        v["is_searched"] = vid in searched_variant_ids
                        if v["is_searched"]:
                            merged_variants.append(v)
                        elif v.get("barcode") and v["barcode"].strip():
                            # Only include siblings at the same price level
                            if searched_price is not None and str(v.get("price")) == searched_price:
                                merged_variants.append(v)

                    prices.append({
                        "store_id": store.id,
                        "store_name": store.name,
                        "store_type": "shopify",
                        "product_found": True,
                        "product_description": variants[0].get("product_title"),
                        "unit_price": None,
                        "unit_cost": None,
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
                        "variants": None,
                    })
                    yield f"event: progress\ndata: {json.dumps({'status': 'error', 'message': f'Error searching {store.name}: {error}'})}\n\n"

        # Enhancement B: Sibling MSSQL lookups
        sibling_prices = []
        if request.include_sibling_barcodes:
            sibling_barcodes = set()
            sibling_barcode_info = {}
            source_store_ids = set()
            for p in prices:
                if p["store_type"] == "shopify" and p.get("variants"):
                    contributed = False
                    for v in p["variants"]:
                        bc = (v.get("barcode") or "").strip()
                        if bc and not v.get("is_searched") and bc != upc:
                            sibling_barcodes.add(bc)
                            sibling_barcode_info[bc] = v.get("variant_title", "")
                            contributed = True
                    if contributed:
                        source_store_ids.add(p["store_id"])

            if sibling_barcodes:
                mssql_store_ids = [sid for sid in request.store_ids if sid in {p["store_id"] for p in prices if p["store_type"] == "mssql"}]
                mssql_stores = []
                for sid in mssql_store_ids:
                    s = db.query(Store).filter(Store.id == sid, Store.is_active == True).first()
                    if s and s.mssql_connection:
                        mssql_stores.append(s)

                for bc in sorted(sibling_barcodes):
                    variant_title = sibling_barcode_info.get(bc, "")
                    for store in mssql_stores:
                        conn = store.mssql_connection
                        yield f"event: progress\ndata: {json.dumps({'status': 'searching', 'message': f'Searching sibling barcode {bc} in {store.name}...'})}\n\n"

                        success, error, item_data = await get_item_prices_async(
                            host=conn.host,
                            port=conn.port,
                            database=conn.database_name,
                            username=conn.username,
                            password=conn.password,
                            upc=bc
                        )

                        if success and item_data:
                            sibling_prices.append({
                                "store_id": store.id,
                                "store_name": store.name,
                                "store_type": "mssql",
                                "product_found": True,
                                "product_description": item_data["description"],
                                "unit_price": item_data["unit_price"],
                                "unit_cost": item_data["unit_cost"],
                                "variants": None,
                                "sibling_barcode": bc,
                                "sibling_variant_title": variant_title,
                            })
                            yield f"event: progress\ndata: {json.dumps({'status': 'found', 'message': f'Found sibling {bc} in {store.name}'})}\n\n"
                        elif success:
                            sibling_prices.append({
                                "store_id": store.id,
                                "store_name": store.name,
                                "store_type": "mssql",
                                "product_found": False,
                                "product_description": None,
                                "unit_price": None,
                                "unit_cost": None,
                                "variants": None,
                                "sibling_barcode": bc,
                                "sibling_variant_title": variant_title,
                            })
                            yield f"event: progress\ndata: {json.dumps({'status': 'not_found', 'message': f'Sibling {bc} not found in {store.name}'})}\n\n"

                # Enhancement C: Sibling Shopify lookups
                target_shopify = [
                    p for p in prices
                    if p["store_type"] == "shopify" and p["store_id"] not in source_store_ids
                ]
                for target_entry in target_shopify:
                    store = db.query(Store).filter(Store.id == target_entry["store_id"], Store.is_active == True).first()
                    if not store or not store.shopify_connection:
                        continue
                    conn = store.shopify_connection
                    for bc in sorted(sibling_barcodes):
                        yield f"event: progress\ndata: {json.dumps({'status': 'searching', 'message': f'Searching sibling barcode {bc} in {store.name}...'})}\n\n"
                        try:
                            success, error, variants = await search_product_prices_by_barcode(
                                shop_domain=conn.shop_domain,
                                admin_api_key=conn.admin_api_key,
                                barcode=bc,
                                api_version=conn.api_version
                            )
                        except Exception:
                            continue

                        if not (success and variants):
                            continue

                        searched_variant_ids = {v["variant_id"] for v in variants}
                        product_ids = list({v["product_id"] for v in variants})

                        all_variants = []
                        for pid in product_ids:
                            try:
                                p_success, p_error, p_variants = await get_all_product_variant_prices(
                                    shop_domain=conn.shop_domain,
                                    admin_api_key=conn.admin_api_key,
                                    product_id=pid,
                                    api_version=conn.api_version
                                )
                                if p_success and p_variants:
                                    all_variants.extend(p_variants)
                            except Exception:
                                pass

                        if not all_variants:
                            continue

                        searched_price = None
                        for v in variants:
                            if v.get("price") is not None:
                                searched_price = str(v["price"])
                                break

                        seen = set()
                        merged_variants = []
                        for v in all_variants:
                            vid = v["variant_id"]
                            if vid in seen:
                                continue
                            seen.add(vid)
                            v["is_searched"] = vid in searched_variant_ids
                            if v["is_searched"]:
                                merged_variants.append(v)
                            elif v.get("barcode") and v["barcode"].strip():
                                if searched_price is not None and str(v.get("price")) == searched_price:
                                    merged_variants.append(v)

                        if not merged_variants:
                            continue

                        idx = prices.index(target_entry)
                        if not target_entry["product_found"]:
                            prices[idx] = {
                                "store_id": store.id,
                                "store_name": store.name,
                                "store_type": "shopify",
                                "product_found": True,
                                "product_description": variants[0].get("product_title"),
                                "unit_price": None,
                                "unit_cost": None,
                                "variants": merged_variants,
                            }
                            yield f"event: progress\ndata: {json.dumps({'status': 'found', 'message': f'Found sibling match ({len(merged_variants)} variant(s)) in {store.name}'})}\n\n"
                            break
                        else:
                            existing_variant_ids = {v["variant_id"] for v in (target_entry.get("variants") or [])}
                            new_variants = [v for v in merged_variants if v["variant_id"] not in existing_variant_ids]
                            if new_variants:
                                prices[idx]["variants"] = (prices[idx].get("variants") or []) + new_variants
                                yield f"event: progress\ndata: {json.dumps({'status': 'found', 'message': f'Found sibling match ({len(new_variants)} new variant(s)) in {store.name}'})}\n\n"

        yield f"event: complete\ndata: {json.dumps({'prices': prices, 'sibling_prices': sibling_prices})}\n\n"

    return StreamingResponse(
        generate_events(),
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

        for update in request.updates:
            store = db.query(Store).filter(Store.id == update.store_id, Store.is_active == True).first()
            if not store:
                results.append({"store_id": update.store_id, "store_name": "Unknown", "success": False, "error": "Store not found"})
                continue

            yield f"event: progress\ndata: {json.dumps({'status': 'updating', 'message': f'Updating {store.name}...'})}\n\n"

            if update.store_type == "mssql" and store.mssql_connection:
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
                    unit_cost=update.new_cost
                )

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
                    old_price=update.old_price,
                    old_cost=update.old_cost,
                    new_price=update.new_price,
                    new_cost=update.new_cost,
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

            elif update.store_type == "shopify" and store.shopify_connection and update.variant_updates:
                conn = store.shopify_connection
                products = {}
                for vu in update.variant_updates:
                    pid = vu["product_id"]
                    if pid not in products:
                        products[pid] = []
                    products[pid].append(vu)

                total_updated = 0
                errors = []
                for product_id, variants in products.items():
                    success, error, count = await update_variant_prices(
                        shop_domain=conn.shop_domain,
                        admin_api_key=conn.admin_api_key,
                        product_id=product_id,
                        variant_updates=variants,
                        api_version=conn.api_version
                    )
                    if success:
                        total_updated += count
                    else:
                        errors.append(error)

                store_success = len(errors) == 0
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

        yield f"event: complete\ndata: {json.dumps({'results': results, 'batch_id': batch_id})}\n\n"

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
    )


@app.get("/api/price-updates/history", response_model=PriceUpdateHistoryListResponse)
def get_price_update_history(
    store_id: Optional[int] = None,
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
    if store_id is not None:
        base_filters.append(PriceUpdateHistory.store_id == store_id)
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

    batches = []
    for bid in batch_id_list:
        entries = db.query(PriceUpdateHistory).filter(
            PriceUpdateHistory.batch_id == bid
        ).all()

        if entries:
            first = entries[0]
            successful = sum(1 for e in entries if e.success)
            failed = len(entries) - successful

            batches.append(PriceUpdateHistoryBatch(
                batch_id=bid,
                upc=first.upc,
                product_description=first.product_description,
                created_at=first.created_at,
                total_stores=len(entries),
                successful_stores=successful,
                failed_stores=failed,
                entries=entries
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


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
