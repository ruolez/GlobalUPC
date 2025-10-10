from pydantic import BaseModel, Field
from typing import Optional, Literal, List, Dict
from datetime import datetime, date

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

# SQL UPC Audit Schemas
class OrphanedUPCAuditRequest(BaseModel):
    store_id: int
    target_store_id: Optional[int] = None  # Optional: compare against different database's Items_tbl
    date_from: Optional[date] = None
    date_to: Optional[date] = None

class OrphanedUPCRecord(BaseModel):
    table_name: str
    primary_key: int
    upc: str
    product_id: Optional[int] = None  # ProductID from the detail table
    description: Optional[str] = None

class OrphanedUPCAuditResponse(BaseModel):
    store_id: int
    store_name: str
    orphaned_records: list[OrphanedUPCRecord]
    total_orphaned: int
    tables_checked: int

# SQL UPC Reconciliation Schemas
class ReconciliationRequest(BaseModel):
    store_id: int
    match_type: Literal["product_id", "product_description"]
    orphaned_records: List[OrphanedUPCRecord]

class ReconciliationMatch(BaseModel):
    table_name: str
    primary_key: int
    orphaned_upc: str
    match_found: bool
    items_tbl_upc: Optional[str] = None
    match_field_value: str  # The ProductID or ProductDescription used for matching

class ReconciliationResponse(BaseModel):
    matches: List[ReconciliationMatch]
    total_checked: int
    total_matched: int

class ReconciliationUpdateRequest(BaseModel):
    store_id: int
    updates: List[ReconciliationMatch]  # Only matched records to update

class ReconciliationUpdateResult(BaseModel):
    table_name: str
    primary_key: int
    success: bool
    updated_upc: Optional[str] = None
    error: Optional[str] = None

class ReconciliationUpdateResponse(BaseModel):
    results: List[ReconciliationUpdateResult]
    total_updated: int
    total_failed: int

# UPC Update History Schemas
class UPCUpdateHistoryResponse(BaseModel):
    id: int
    batch_id: str
    store_id: int
    store_name: str
    store_type: str
    old_upc: str
    new_upc: str
    product_id: Optional[str] = None
    product_title: Optional[str] = None
    variant_id: Optional[str] = None
    variant_title: Optional[str] = None
    table_name: Optional[str] = None
    primary_keys: Optional[List] = None
    success: bool
    items_updated_count: int
    error_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
        use_enum_values = True

class UPCUpdateHistoryBatch(BaseModel):
    batch_id: str
    old_upc: str
    new_upc: str
    created_at: datetime
    total_stores: int
    successful_stores: int
    failed_stores: int
    total_items_updated: int
    updates: List[UPCUpdateHistoryResponse]

class UPCUpdateHistoryListRequest(BaseModel):
    store_id: Optional[int] = None
    upc_search: Optional[str] = None  # Searches both old_upc and new_upc
    success_filter: Optional[bool] = None  # None = all, True = success only, False = failed only
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    limit: int = 50
    offset: int = 0

class UPCUpdateHistoryListResponse(BaseModel):
    batches: List[UPCUpdateHistoryBatch]
    total: int
    limit: int
    offset: int

# Store Comparison Schemas
class CategoryResponse(BaseModel):
    category_id: int
    category_name: str

class SubCategoryResponse(BaseModel):
    subcategory_id: int
    subcategory_name: str
    category_id: int

class StoreComparisonFilters(BaseModel):
    category_ids: Optional[List[int]] = None
    subcategory_ids: Optional[List[int]] = None
    include_discontinued: bool = False

class StoreComparisonRequest(BaseModel):
    primary_store_id: int
    comparison_store_id: int
    filters: StoreComparisonFilters = StoreComparisonFilters()

class MissingProductRecord(BaseModel):
    product_id: int
    product_upc: str
    product_description: str
    category_name: str
    subcategory_name: str
    discontinued: bool

class StoreComparisonResponse(BaseModel):
    primary_store_id: int
    primary_store_name: str
    comparison_store_id: int
    comparison_store_name: str
    missing_products: List[MissingProductRecord]
    total_checked: int
    total_missing: int
    category_stats: Dict[str, int]  # category_name -> count

# UPC Exclusion Schemas
class UPCExclusionCreate(BaseModel):
    store_id: int
    upc: str
    notes: Optional[str] = None

class UPCExclusionResponse(BaseModel):
    id: int
    store_id: int
    store_name: str
    upc: str
    excluded_at: datetime
    notes: Optional[str] = None

    class Config:
        from_attributes = True

class UPCExclusionListResponse(BaseModel):
    exclusions: List[UPCExclusionResponse]
    total: int
