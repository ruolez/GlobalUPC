from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Union, AsyncGenerator
from pydantic import BaseModel
import uvicorn
import asyncio
import json

from database import get_db, engine
from models import Store, MSSQLConnection, ShopifyConnection, Setting, StoreType
from schemas import (
    MSSQLStoreCreate, ShopifyStoreCreate, StoreResponse,
    SettingCreate, SettingUpdate, SettingResponse,
    UPCSearchRequest, UPCSearchResponse, ProductVariantMatch,
    UPCUpdateRequest, UPCUpdateResult,
    ConfigExportResponse, ConfigImportRequest, ConfigImportResponse,
    StoreImportResult, StoreExport
)
from mssql_helper import test_mssql_connection, search_upc_across_mssql_stores, search_products_by_upc, update_upc_across_mssql_stores
from shopify_helper import test_shopify_connection, search_barcode_across_shopify_stores, search_products_by_barcode, update_barcodes_across_shopify_stores

app = FastAPI(title="Global UPC API", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

        # Search Shopify stores
        if shopify_stores:
            yield f"event: progress\ndata: {json.dumps({'status': 'searching', 'store_type': 'shopify', 'count': len(shopify_stores)})}\n\n"

            for store in shopify_stores:
                yield f"event: progress\ndata: {json.dumps({'status': 'searching_store', 'store_name': store['name'], 'store_type': 'shopify'})}\n\n"

                # Search single store
                success, error, variants = await search_products_by_barcode(
                    shop_domain=store["shop_domain"],
                    admin_api_key=store["admin_api_key"],
                    barcode=upc,
                    api_version=store.get("api_version", "2025-01")
                )

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

        # Search MSSQL stores
        if mssql_stores:
            print(f"[SEARCH] Starting MSSQL search for {len(mssql_stores)} stores")
            yield f"event: progress\ndata: {json.dumps({'status': 'searching', 'store_type': 'mssql', 'count': len(mssql_stores)})}\n\n"

            for idx, store in enumerate(mssql_stores):
                print(f"[SEARCH] MSSQL store {idx + 1}/{len(mssql_stores)}: {store['name']}")
                yield f"event: progress\ndata: {json.dumps({'status': 'searching_store', 'store_name': store['name'], 'store_type': 'mssql'})}\n\n"

                # Search single store across all tables
                success, error, table_results = await search_products_by_upc(
                    host=store["host"],
                    port=store["port"],
                    database=store["database_name"],
                    username=store["username"],
                    password=store["password"],
                    upc=upc
                )

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

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
