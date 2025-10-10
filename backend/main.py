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
from models import Store, MSSQLConnection, ShopifyConnection, Setting, StoreType, UPCUpdateHistory, UPCExclusion
from schemas import (
    MSSQLStoreCreate, ShopifyStoreCreate, StoreResponse,
    SettingCreate, SettingUpdate, SettingResponse,
    UPCSearchRequest, UPCSearchResponse, ProductVariantMatch,
    UPCUpdateRequest, UPCUpdateResult,
    UPCValidationRequest, UPCValidationResponse,
    ConfigExportResponse, ConfigImportRequest, ConfigImportResponse,
    StoreImportResult, StoreExport,
    OrphanedUPCAuditRequest, OrphanedUPCRecord, OrphanedUPCAuditResponse,
    ReconciliationRequest, ReconciliationMatch, ReconciliationResponse,
    ReconciliationUpdateRequest, ReconciliationUpdateResult, ReconciliationUpdateResponse,
    UPCUpdateHistoryResponse, UPCUpdateHistoryListRequest, UPCUpdateHistoryListResponse,
    CategoryResponse, SubCategoryResponse, StoreComparisonRequest, StoreComparisonResponse, MissingProductRecord,
    UPCExclusionCreate, UPCExclusionResponse, UPCExclusionListResponse
)
from mssql_helper import (
    test_mssql_connection, search_upc_across_mssql_stores, search_products_by_upc,
    update_upc_across_mssql_stores, audit_orphaned_upcs,
    find_matches_by_product_id, find_matches_by_description, update_orphaned_upcs,
    check_upc_exists
)
from shopify_helper import test_shopify_connection, search_barcode_across_shopify_stores, search_products_by_barcode, update_barcodes_across_shopify_stores, check_barcode_exists

app = FastAPI(title="Global UPC API", version="1.0.0")

# Read SERVER_IP from environment variable
SERVER_IP = os.getenv("SERVER_IP", "localhost")
FRONTEND_PORT = os.getenv("FRONTEND_PORT", "8080")

# Build CORS origins list
cors_origins = [
    f"http://{SERVER_IP}:{FRONTEND_PORT}",
    f"http://localhost:{FRONTEND_PORT}",
    "http://localhost:8080",  # Fallback for development
]

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

@app.post("/api/upc/validate", response_model=UPCValidationResponse)
async def validate_upc(request: UPCValidationRequest, db: Session = Depends(get_db)):
    """
    Validate if a UPC already exists in any active store (MSSQL or Shopify).
    Used before UPC updates to prevent duplicates.
    """
    upc = request.upc.strip()

    if not upc:
        raise HTTPException(status_code=400, detail="UPC is required")

    # Get all active stores
    active_stores = db.query(Store).filter(Store.is_active == True).all()

    if not active_stores:
        return UPCValidationResponse(
            exists=False,
            matches=[],
            total_matches=0
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

    all_matches = []

    # Check Shopify stores
    if shopify_stores:
        for shop_store in shopify_stores:
            success, error, variants = await check_barcode_exists(
                shop_domain=shop_store["shop_domain"],
                admin_api_key=shop_store["admin_api_key"],
                barcode=upc,
                api_version=shop_store.get("api_version", "2025-01")
            )

            if success and variants:
                for variant in variants:
                    all_matches.append(ProductVariantMatch(
                        store_id=shop_store["id"],
                        store_name=shop_store["name"],
                        store_type="shopify",
                        product_id=variant["product_id"],
                        product_title=variant["product_title"],
                        variant_id=variant["variant_id"],
                        variant_title=variant["variant_title"],
                        current_barcode=variant["barcode"],
                        sku=variant["sku"]
                    ))

    # Check MSSQL stores
    if mssql_stores:
        for mssql_store in mssql_stores:
            success, error, results = await check_upc_exists(
                host=mssql_store["host"],
                port=mssql_store["port"],
                database=mssql_store["database_name"],
                username=mssql_store["username"],
                password=mssql_store["password"],
                upc=upc
            )

            if success and results:
                for result in results:
                    all_matches.append(ProductVariantMatch(
                        store_id=mssql_store["id"],
                        store_name=mssql_store["name"],
                        store_type="mssql",
                        product_id=result["product_id"],
                        product_title=result["product_description"],
                        variant_id=None,
                        variant_title=None,
                        current_barcode=result["upc"],
                        sku=None
                    ))

    return UPCValidationResponse(
        exists=len(all_matches) > 0,
        matches=all_matches,
        total_matches=len(all_matches)
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
                elif table_name == "QuotationDetails":
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
                yield f"event: progress\ndata: {json.dumps({'status': 'updating_store', 'store_name': store_update['store_name'], 'store_type': 'shopify'})}\n\n"

                # Call update function for this store
                results = await update_barcodes_across_shopify_stores([store_update])

                for result in results:
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
                yield f"event: progress\ndata: {json.dumps({'status': 'updating_store', 'store_name': store_update['store_name'], 'store_type': 'mssql'})}\n\n"

                # Call update function for this store
                results = await update_upc_across_mssql_stores([store_update])

                for result in results:
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

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
