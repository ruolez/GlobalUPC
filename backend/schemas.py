from pydantic import BaseModel, Field
from typing import Optional, Literal, List
from datetime import datetime

# Store Schemas
class StoreBase(BaseModel):
    name: str
    is_active: bool = True

class MSSQLConnectionBase(BaseModel):
    host: str
    port: int = 1433
    database_name: str
    username: str
    password: str

class ShopifyConnectionBase(BaseModel):
    shop_domain: str
    admin_api_key: str
    api_version: str = "2025-01"
    update_sku_with_barcode: bool = False

class MSSQLStoreCreate(StoreBase):
    store_type: Literal["mssql"] = "mssql"
    connection: MSSQLConnectionBase

class ShopifyStoreCreate(StoreBase):
    store_type: Literal["shopify"] = "shopify"
    connection: ShopifyConnectionBase

class MSSQLConnectionResponse(MSSQLConnectionBase):
    id: int
    store_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ShopifyConnectionResponse(ShopifyConnectionBase):
    id: int
    store_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class StoreResponse(StoreBase):
    id: int
    store_type: str
    created_at: datetime
    updated_at: datetime
    mssql_connection: Optional[MSSQLConnectionResponse] = None
    shopify_connection: Optional[ShopifyConnectionResponse] = None

    class Config:
        from_attributes = True

# Settings Schemas
class SettingBase(BaseModel):
    key: str
    value: Optional[str] = None
    description: Optional[str] = None

class SettingCreate(SettingBase):
    pass

class SettingUpdate(BaseModel):
    value: Optional[str] = None
    description: Optional[str] = None

class SettingResponse(SettingBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# UPC Search/Update Schemas
class UPCSearchRequest(BaseModel):
    upc: str

class ProductVariantMatch(BaseModel):
    store_id: int
    store_name: str
    store_type: Literal["shopify", "mssql"]
    product_id: str
    product_title: str
    variant_id: Optional[str] = None
    variant_title: Optional[str] = None
    current_barcode: str
    sku: Optional[str] = None

    # MSSQL-specific fields for aggregated results
    table_name: Optional[str] = None  # e.g., "QuotationsDetails_tbl"
    match_count: Optional[int] = None  # Number of rows found in this table
    primary_keys: Optional[List[int]] = None  # LineID or ProductID values for updates

class UPCSearchResponse(BaseModel):
    upc: str
    matches: list[ProductVariantMatch]
    total_found: int
    stores_searched: int

class UPCUpdateRequest(BaseModel):
    old_upc: str
    new_upc: str
    matches: List[ProductVariantMatch]  # All matches found during search

class UPCUpdateResult(BaseModel):
    store_id: int
    store_name: str
    success: bool
    updated_count: int
    error: Optional[str] = None

class UPCUpdateResponse(BaseModel):
    old_upc: str
    new_upc: str
    results: list[UPCUpdateResult]
    total_updated: int

# Config Import/Export Schemas
class StoreExport(BaseModel):
    name: str
    is_active: bool
    connection: dict

class ConfigExportResponse(BaseModel):
    version: str
    exported_at: datetime
    mssql_stores: list[StoreExport]
    shopify_stores: list[StoreExport]

class ConfigImportRequest(BaseModel):
    version: str
    exported_at: Optional[datetime] = None
    mssql_stores: list[StoreExport]
    shopify_stores: list[StoreExport]

class StoreImportResult(BaseModel):
    name: str
    store_type: Literal["mssql", "shopify"]
    status: Literal["created", "skipped", "failed"]
    reason: Optional[str] = None

class ConfigImportResponse(BaseModel):
    total_stores: int
    created: int
    skipped: int
    failed: int
    results: list[StoreImportResult]
