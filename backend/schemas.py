from pydantic import BaseModel, Field
from typing import Optional, Literal, List, Dict
from datetime import datetime, date

# Store Schemas
class StoreBase(BaseModel):
    name: str
    is_active: bool = True
    store_category: str = "retail"

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
    store_category: str = "retail"
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

# Item Tracker Schemas
class ItemTrackerConfigBase(BaseModel):
    s2s_store_id: Optional[int] = None
    sales_store_ids: List[int] = []
    inventory_store_id: Optional[int] = None

class ItemTrackerConfigCreate(ItemTrackerConfigBase):
    pass

class ItemTrackerConfigResponse(ItemTrackerConfigBase):
    id: int
    s2s_store_name: Optional[str] = None
    sales_store_names: List[str] = []
    inventory_store_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ItemTrackerSearchRequest(BaseModel):
    upc: str
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    show_voided: bool = False

class ItemInfo(BaseModel):
    product_id: int
    product_upc: str
    product_description: Optional[str] = None
    last_received: Optional[datetime] = None
    last_sold: Optional[datetime] = None
    unit_price: Optional[float] = None
    unit_cost: Optional[float] = None
    avr_cost: Optional[float] = None
    quant_on_hand: Optional[float] = None

class ItemTrackerEvent(BaseModel):
    event_type: Literal["purchase", "sale", "customer_return", "vendor_return", "inventory_recount", "in_progress"]
    event_date: Optional[datetime] = None
    store_name: str
    document_number: Optional[str] = None
    quantity: Optional[float] = None
    price_or_cost: Optional[float] = None
    business_name: Optional[str] = None
    line_id: Optional[int] = None
    extended_amount: Optional[float] = None
    is_voided: Optional[bool] = None
    username: Optional[str] = None
    update_type: Optional[str] = None
    running_balance: Optional[float] = None
    expected_balance: Optional[float] = None

class ItemTrackerSearchResponse(BaseModel):
    upc: str
    item_info: Optional[ItemInfo] = None
    events: List[ItemTrackerEvent]
    event_counts: Dict[str, int]
    total_events: int
    stores_searched: int


class ItemTrackerSummaryItemInfo(BaseModel):
    product_upc: str
    product_description: Optional[str] = None
    quant_on_hand: Optional[float] = None
    unit_price: Optional[float] = None
    unit_cost: Optional[float] = None
    avr_cost: Optional[float] = None


class ItemTrackerQuantityTotals(BaseModel):
    purchase: float = 0.0
    sale: float = 0.0
    customer_return: float = 0.0
    vendor_return: float = 0.0
    inventory_recount: float = 0.0


class ItemTrackerSummaryResponse(BaseModel):
    upc: str
    item_info: Optional[ItemTrackerSummaryItemInfo] = None
    event_counts: Dict[str, int]
    quantity_totals: ItemTrackerQuantityTotals
    net_quantity: float
    beginning_inventory: Optional[float] = None
    ending_inventory: Optional[float] = None
    total_events: int
    stores_searched: int
    errors: Optional[List[str]] = None


class DescriptionAutocompleteRequest(BaseModel):
    query: str


class DescriptionAutocompleteResult(BaseModel):
    product_id: int
    product_upc: str
    product_description: str
    quant_on_hand: int = 0


class DescriptionAutocompleteResponse(BaseModel):
    results: List[DescriptionAutocompleteResult]
    count: int


class PriceSearchRequest(BaseModel):
    upc: str
    store_ids: List[int]
    include_sibling_barcodes: bool = False


class StorePriceInfo(BaseModel):
    store_id: int
    store_name: str
    store_type: str
    product_found: bool
    product_description: Optional[str] = None
    unit_price: Optional[float] = None
    unit_cost: Optional[float] = None
    unit_delivery_b: Optional[float] = None
    unit_list_price: Optional[float] = None
    variants: Optional[List[dict]] = None


class PriceUpdateItem(BaseModel):
    store_id: int
    store_type: str
    upc: Optional[str] = None
    new_price: Optional[float] = None
    new_cost: Optional[float] = None
    old_price: Optional[float] = None
    old_cost: Optional[float] = None
    new_delivery_b: Optional[float] = None
    old_delivery_b: Optional[float] = None
    new_list_price: Optional[float] = None
    old_list_price: Optional[float] = None
    product_description: Optional[str] = None
    variant_updates: Optional[List[dict]] = None


class PriceUpdateRequest(BaseModel):
    upc: str
    updates: List[PriceUpdateItem]


class PriceUpdateHistoryResponse(BaseModel):
    id: int
    batch_id: str
    store_id: int
    store_name: str
    store_type: str
    upc: str
    product_description: Optional[str] = None
    variant_id: Optional[str] = None
    variant_title: Optional[str] = None
    variant_barcode: Optional[str] = None
    old_price: Optional[float] = None
    old_cost: Optional[float] = None
    new_price: Optional[float] = None
    new_cost: Optional[float] = None
    old_delivery_b: Optional[float] = None
    new_delivery_b: Optional[float] = None
    old_list_price: Optional[float] = None
    new_list_price: Optional[float] = None
    success: bool
    rows_affected: int
    error_message: Optional[str] = None
    is_mirror: bool = False
    mirror_source_store_id: Optional[int] = None
    mirror_source_store_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
        use_enum_values = True


class PriceUpdateHistoryBatch(BaseModel):
    batch_id: str
    upc: str
    product_description: Optional[str] = None
    created_at: datetime
    total_stores: int
    successful_stores: int
    failed_stores: int
    entries: List[PriceUpdateHistoryResponse]


class PriceUpdateHistoryListResponse(BaseModel):
    batches: List[PriceUpdateHistoryBatch]
    total: int
    limit: int
    offset: int


class StoreMirrorCreate(BaseModel):
    source_store_id: int
    mirror_store_id: int


class StoreMirrorResponse(BaseModel):
    id: int
    source_store_id: int
    source_store_name: str
    source_store_type: str
    mirror_store_id: int
    mirror_store_name: str
    mirror_store_type: str
    created_at: datetime

    class Config:
        from_attributes = True


class StoreMirrorListResponse(BaseModel):
    mirrors: List[StoreMirrorResponse]
    total: int


class ItemTrackerExclusionCreate(BaseModel):
    business_name: str
    void_status: Optional[int] = None  # NULL=all, 0=non-voided, 1=voided
    notes: Optional[str] = None


class ItemTrackerExclusionResponse(BaseModel):
    id: int
    business_name: str
    void_status: Optional[int] = None
    excluded_at: datetime
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class ItemTrackerExclusionListResponse(BaseModel):
    exclusions: List[ItemTrackerExclusionResponse]
    total: int


class StoreNameUpdate(BaseModel):
    name: str

class StoreCategoryUpdate(BaseModel):
    store_category: Literal["wholesale", "retail"]


class ShopifySalesRequest(BaseModel):
    store_ids: List[int]
    start_date: str
    end_date: str


class SalesReportRequest(BaseModel):
    mssql_store_ids: List[int] = []
    shopify_store_ids: List[int] = []
    date_from: Optional[str] = None
    date_to: Optional[str] = None


class SalesExclusionCreate(BaseModel):
    business_name: str
    void_status: Optional[int] = None
    notes: Optional[str] = None


class SalesExclusionResponse(BaseModel):
    id: int
    business_name: str
    void_status: Optional[int] = None
    excluded_at: datetime
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class SalesExclusionListResponse(BaseModel):
    exclusions: List[SalesExclusionResponse]
    total: int


class SalesConfigCreate(BaseModel):
    s2s_store_id: Optional[int] = None
    mssql_store_ids: List[int] = []
    shopify_store_ids: List[int] = []


class SalesConfigResponse(BaseModel):
    id: int
    s2s_store_id: Optional[int] = None
    s2s_store_name: Optional[str] = None
    mssql_store_ids: List[int] = []
    mssql_store_names: List[str] = []
    shopify_store_ids: List[int] = []
    shopify_store_names: List[str] = []
    excluded_subcategories: List[str] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Shopify Analytics Schemas
class FirstCustomerReturnsRequest(BaseModel):
    store_id: int
    start_date: str  # YYYY-MM-DD
    end_date: str    # YYYY-MM-DD


class FirstCustomerReturnsRow(BaseModel):
    customer_id: Optional[str] = None
    customer_name: str
    customer_email: Optional[str] = None
    first_order_id: Optional[str] = None
    first_order_name: str
    first_order_date: Optional[str] = None
    first_order_amount: str
    first_order_currency: str
    subsequent_count: int
    subsequent_amount: str
    subsequent_currency: str


class FirstCustomerReturnsSummary(BaseModel):
    first_time_customers: int
    customers_with_returns: int
    total_subsequent_orders: int
    total_subsequent_amount: str
    currency: str


# Quotations In Progress Schemas
class QuotationsInProgressFilter(BaseModel):
    # "all" -> no scan filter
    # "in"  -> has scan-in (regardless of scan-out)
    # "out" -> has scan-out (regardless of scan-in)
    # "none" -> has neither scan-in nor scan-out
    scan_filter: Literal["all", "in", "out", "none"] = "all"
    source_dbs: List[str] = []
    packers: List[str] = []
    checkers: List[str] = []
    search: Optional[str] = None
    sort_by: Literal[
        "start_date", "quotation_number", "packer", "checker",
        "dop2", "dop3", "total_qty", "business_name", "source_db"
    ] = "start_date"
    sort_order: Literal["asc", "desc"] = "desc"
    limit: int = Field(default=500, ge=1, le=5000)


class QuotationInProgressSummary(BaseModel):
    quotation_number: Optional[str] = None
    source_db: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    pause_date: Optional[str] = None
    pause_reason: Optional[str] = None
    account_no: Optional[str] = None
    sales_rep: Optional[str] = None
    sales_rep_id: Optional[int] = None
    product_count: int = 0
    total_qty: int = 0
    packer: Optional[str] = None
    checker: Optional[str] = None
    business_name: Optional[str] = None
    dop2: Optional[str] = None
    dop3: Optional[str] = None
    last_update: Optional[str] = None
    user_status: Optional[str] = None
    invoice_number: Optional[str] = None


class QuotationsInProgressFilterOptions(BaseModel):
    source_dbs: List[str] = []
    packers: List[str] = []
    checkers: List[str] = []
    statuses: List[str] = []


class QuotationsInProgressListResponse(BaseModel):
    quotations: List[QuotationInProgressSummary]
    filter_options: QuotationsInProgressFilterOptions
    admin_store_id: Optional[int] = None
    admin_store_name: Optional[str] = None


class QuotationProductLine(BaseModel):
    id: int
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: Optional[str] = None
    source_db: Optional[str] = None
    quotation_number: Optional[str] = None
    packer: Optional[str] = None
    checker: Optional[str] = None
    pause_date: Optional[str] = None
    pause_reason: Optional[str] = None
    account_no: Optional[str] = None
    sales_rep_id: Optional[int] = None
    product_description: Optional[str] = None
    product_upc: Optional[str] = None
    product_sku: Optional[str] = None
    qty: int = 0
    cate_id: Optional[int] = None
    sub_cate_id: Optional[int] = None
    flag1: Optional[bool] = None
    flag2: Optional[bool] = None
    flag3: Optional[bool] = None
    unit_cost: Optional[float] = None
    price: Optional[float] = None


class QuotationInProgressHeader(BaseModel):
    quotation_number: Optional[str] = None
    status: Optional[str] = None
    source_db: Optional[str] = None
    invoice_number: Optional[str] = None
    business_name: Optional[str] = None
    account_no: Optional[str] = None
    sales_rep: Optional[str] = None
    packer: Optional[str] = None
    checker: Optional[str] = None
    username: Optional[str] = None
    user_status: Optional[str] = None
    last_update: Optional[str] = None
    total_qty: Optional[int] = None
    ship_to: Optional[str] = None
    ship_address1: Optional[str] = None
    ship_address2: Optional[str] = None
    ship_contact: Optional[str] = None
    ship_city: Optional[str] = None
    ship_state: Optional[str] = None
    ship_zip_code: Optional[str] = None
    ship_phone_no: Optional[str] = None
    shipper_id: Optional[str] = None
    term_id: Optional[str] = None
    quotation_total: Optional[str] = None
    comment: Optional[str] = None
    notes: Optional[str] = None
    dop1: Optional[str] = None
    dop2: Optional[str] = None
    dop3: Optional[str] = None
    date_create: Optional[str] = None


class QuotationProductsResponse(BaseModel):
    products: List[QuotationProductLine]
    header: Optional[QuotationInProgressHeader] = None


class QuotationSearchProduct(BaseModel):
    quotation_number: Optional[str] = None
    source_db: Optional[str] = None
    business_name: Optional[str] = None
    product_upc: Optional[str] = None
    product_sku: Optional[str] = None
    product_description: Optional[str] = None
    qty: int = 0
    dop2: Optional[str] = None
    dop3: Optional[str] = None
    unit_cost: Optional[float] = None
    price: Optional[float] = None


class QuotationSearchResponse(BaseModel):
    products: List[QuotationSearchProduct]
    quotation_count: int = 0


# Dashboard Schemas
class DashboardStoreStats(BaseModel):
    total: int = 0
    active: int = 0
    by_type: Dict[str, int] = {}
    by_category: Dict[str, int] = {}


class DashboardExclusionCounts(BaseModel):
    upc: int = 0
    item_tracker: int = 0
    sales: int = 0


class DashboardMirrorStats(BaseModel):
    count: int = 0


class DashboardBatchSummary(BaseModel):
    batches: int = 0
    success_rate: Optional[float] = None  # null when batches == 0


class DashboardInProgressStats(BaseModel):
    configured: bool = False
    total: int = 0
    oldest_started_at: Optional[str] = None
    error: Optional[str] = None


class DashboardConfigCheck(BaseModel):
    key: Literal["admin_store_id", "item_tracker_s2s", "shopify_sales_s2s"]
    ok: bool
    store_name: Optional[str] = None


class DashboardStatsResponse(BaseModel):
    stores: DashboardStoreStats
    exclusions: DashboardExclusionCounts
    mirrors: DashboardMirrorStats
    upc_updates_7d: DashboardBatchSummary
    price_updates_7d: DashboardBatchSummary
    in_progress: DashboardInProgressStats
    config_health: List[DashboardConfigCheck]
    generated_at: datetime
