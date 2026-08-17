from pydantic import BaseModel, ConfigDict, Field, field_validator
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
    first_order_tag: str = "First order"

class MSSQLStoreCreate(StoreBase):
    store_type: Literal["mssql"] = "mssql"
    connection: MSSQLConnectionBase

class ShopifyStoreCreate(StoreBase):
    store_type: Literal["shopify"] = "shopify"
    connection: ShopifyConnectionBase

class ShipperStoreCreate(StoreBase):
    store_type: Literal["shipper"] = "shipper"
    connection: MSSQLConnectionBase

class MSSQLConnectionUpdate(BaseModel):
    host: str
    port: int = 1433
    database_name: str
    username: str
    password: Optional[str] = None  # blank/None => keep current

class MSSQLStoreUpdate(StoreBase):
    connection: MSSQLConnectionUpdate

class ShipperStoreUpdate(StoreBase):
    connection: MSSQLConnectionUpdate

class ShopifyConnectionUpdate(BaseModel):
    shop_domain: str
    admin_api_key: Optional[str] = None  # blank/None => keep current
    api_version: str = "2025-01"
    update_sku_with_barcode: bool = False

class ShopifyStoreUpdate(StoreBase):
    connection: ShopifyConnectionUpdate

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
    use_local_data: bool = True


class FulfillmentStatusRow(BaseModel):
    store_id: int
    store_name: str
    open_orders: Optional[int] = None
    on_hold: Optional[int] = None
    in_process: Optional[int] = None
    on_picklist: Optional[int] = None
    to_fulfill: Optional[int] = None
    error: Optional[str] = None


class FulfillmentStatusTotals(BaseModel):
    open_orders: int
    on_hold: int
    in_process: int
    on_picklist: int
    to_fulfill: int


class FulfillmentStatusResponse(BaseModel):
    stores: List[FulfillmentStatusRow]
    totals: FulfillmentStatusTotals


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
    tag: Optional[str] = None  # if omitted, falls back to the store's saved tag


class ShopifyFirstOrderTagUpdate(BaseModel):
    first_order_tag: str


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


class NewCustomersByMonthRequest(BaseModel):
    store_ids: List[int]
    start_date: str  # YYYY-MM-DD
    end_date: str    # YYYY-MM-DD
    tag: Optional[str] = None  # blank -> each store falls back to its own saved tag


class LostCustomersRequest(BaseModel):
    # A browser holding a stale app.js would otherwise POST the old
    # active_since/silent_since pair, have both silently ignored, and be handed a
    # plausible report computed against a default cutoff it never asked for. A
    # 422 is the only honest outcome.
    model_config = ConfigDict(extra="forbid")

    store_ids: List[int]
    # How far back to look. None/blank = this shop's entire Shopify history.
    # A cost bound, not a window edge: nothing is classified against it unless
    # require_acquired_in_window is set.
    history_from: Optional[str] = None
    # Rolling silence, resolved per shop against that shop's own today. Replaces
    # an absolute cutoff date, under which every departure month carried a
    # different silence requirement and the monthly bars were not comparable.
    silent_months: Literal[3, 4, 5, 6, 7, 8, 9, 12] = 6
    min_orders: int = 1
    # Restrict to customers whose FIRST completed order falls inside the window.
    # Was unconditional; off means the departure timeline covers every customer,
    # including long-standing ones, which is what a churn-by-month report wants.
    require_acquired_in_window: bool = False
    # Drop customers who kept buying at another shop; checked against every
    # active Shopify store, including ones not selected for the report.
    exclude_cross_store: bool = True
    # How soon after going quiet here an order elsewhere counts as a move.
    # None follows silent_months.
    moved_within_months: Optional[Literal[3, 4, 5, 6, 7, 8, 9, 12]] = None
    # Trace where the newly-acquired customers came from. Off by default: it is
    # a second cross-store sweep, over a cohort that is far larger than the lost
    # list, so it is worth paying for only when the answer is being read.
    check_arrivals: bool = False
    # Pull each synced store's Shopify delta before running, so the local
    # mirror is current. Costs a few seconds per synced store; stores without
    # a sync are untouched (they use the live API regardless).
    refresh_local_data: bool = False

    # Every window decision in this report is a string comparison, so a non-ISO
    # date does not fail — it quietly compares wrong ("2024-8-1" sorts after
    # "2024-12-31"). The date input protects the UI path only; this protects the
    # endpoint. Blank normalises to None, i.e. all history.
    @field_validator("history_from")
    @classmethod
    def _iso_date_or_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not str(v).strip():
            return None
        try:
            return date.fromisoformat(str(v).strip()).isoformat()
        except ValueError:
            raise ValueError("must be a calendar date in YYYY-MM-DD form")


class CustomerDetailRequest(BaseModel):
    store_id: int
    customer_id: str           # Shopify GID
    limit: int = 5


class LostProductsStore(BaseModel):
    store_id: int
    order_ids: List[str]       # numeric Shopify order ids (GID stripped)


class LostProductsRequest(BaseModel):
    stores: List[LostProductsStore]
    # The period being analysed, which is what the baseline is sampled from: one
    # drilled month, or the whole report window. Not the lost-customer window —
    # these only ever bound the comparison cohort.
    active_since: str          # baseline window start, YYYY-MM-DD
    silent_since: str          # baseline window end, YYYY-MM-DD

    # Unvalidated until now, and the failure was silent in the worst direction:
    # a bad pair makes the baseline come back empty, which flags EVERY product as
    # "only in lost customers' orders" — the strongest churn signal the report
    # can emit, manufactured out of a malformed date.
    @field_validator("active_since", "silent_since")
    @classmethod
    def _iso_date(cls, v: str) -> str:
        try:
            return date.fromisoformat((v or "").strip()).isoformat()
        except ValueError:
            raise ValueError("must be a calendar date in YYYY-MM-DD form")


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


# Inventory Time Schemas
class InventoryTimeRequest(BaseModel):
    username: str
    date_from: str  # "YYYY-MM-DD"
    date_to: str    # "YYYY-MM-DD"


class InventoryTimeSession(BaseModel):
    start: datetime
    end: datetime
    item_count: int
    seconds: float


class InventoryTimeResponse(BaseModel):
    configured: bool = True
    total_seconds: float = 0.0
    session_count: int = 0
    item_count: int = 0
    sessions: List[InventoryTimeSession] = []
    timeout_minutes: float = 0.0
    isolated_minutes: float = 0.0


class InventoryTimeUsersResponse(BaseModel):
    configured: bool = False
    users: List[str] = []


# Checked Orders Schemas
class CheckedOrderUser(BaseModel):
    id: int
    name: str


class CheckedOrdersUsersResponse(BaseModel):
    configured: bool = False
    users: List[CheckedOrderUser] = []


class CheckedOrdersRequest(BaseModel):
    checker_id: int
    date_from: str  # "YYYY-MM-DD"
    date_to: str    # "YYYY-MM-DD"


class CheckedOrder(BaseModel):
    order_number: str
    created_at: datetime
    check_completed_at: datetime
    seconds: float
    value: float = 0.0
    product_count: int = 0


class CheckedOrdersResponse(BaseModel):
    configured: bool = True
    order_count: int = 0
    total_seconds: float = 0.0
    average_seconds: float = 0.0
    total_value: float = 0.0
    slow_threshold_minutes: float = 0.0
    seconds_per_product: float = 10.0
    orders: List[CheckedOrder] = []


class ShopifySyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # incremental re-fetches records whose updated_at moved since the last
    # successful run; full re-downloads everything and prunes deleted records.
    # The first-ever sync of a store always runs full regardless.
    mode: Literal["incremental", "full"] = "incremental"


# ============================================================================
# Business Overview Schemas
# ============================================================================
BOV_DEFAULT_QUOTATION_STATUSES = ["In Progress", "Locked"]


class BusinessOverviewConfigCreate(BaseModel):
    sales_store_ids: List[int] = []
    sales_store_id: Optional[int] = None      # legacy single value; merged into sales_store_ids
    purchases_store_id: Optional[int] = None
    shopify_store_ids: List[int] = []
    quotation_statuses: List[str] = list(BOV_DEFAULT_QUOTATION_STATUSES)
    timezone: str = "America/Chicago"


class BusinessOverviewConfigResponse(BaseModel):
    id: int = 0
    configured: bool = False
    sales_store_ids: List[int] = []
    sales_store_names: List[str] = []
    sales_store_id: Optional[int] = None      # first sales store (legacy)
    sales_store_name: Optional[str] = None
    purchases_store_id: Optional[int] = None
    purchases_store_name: Optional[str] = None
    shopify_store_ids: List[int] = []
    shopify_store_names: List[str] = []
    quotation_statuses: List[str] = []
    timezone: str = "America/Chicago"
    # Resolved read-only context (not stored on this table)
    admin_store_id: Optional[int] = None
    admin_store_name: Optional[str] = None
    cost_store_id: Optional[int] = None
    cost_store_name: Optional[str] = None
    sales_exclusions_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class BOVStoreOption(BaseModel):
    id: int
    name: str
    store_type: str
    is_active: bool = True
    synced: Optional[bool] = None
    last_synced_at: Optional[str] = None
    shop_timezone: Optional[str] = None
    database_name: Optional[str] = None      # MSSQL only — matches QuotationsInProgress.SourceDB


class BusinessOverviewConfigOptions(BaseModel):
    mssql_stores: List[BOVStoreOption] = []
    shopify_stores: List[BOVStoreOption] = []
    quotation_statuses: List[str] = []
    admin_configured: bool = False
    admin_store_name: Optional[str] = None


class BOVPeriod(BaseModel):
    start: str
    end: str
    prev_start: str
    prev_end: str
    days: int
    preset: Optional[str] = None
    timezone: str
    today: str


class BOVStoreStatus(BaseModel):
    store_id: int
    store_name: str
    error: Optional[str] = None


class BOVBlockStatus(BaseModel):
    configured: bool = False
    store_id: Optional[int] = None
    store_name: Optional[str] = None
    error: Optional[str] = None
    stores: List[BOVStoreStatus] = []        # per-store status when a block fans out
    filtered_out: bool = False               # source exists but is outside the active store filter


class BOVSeriesPoint(BaseModel):
    key: str
    start: str
    end: str
    label: str
    values: Dict[str, float] = {}


class BOVRangeTotals(BaseModel):
    current: Dict[str, float] = {}
    previous: Dict[str, float] = {}
    change_pct: Dict[str, Optional[float]] = {}


# ---- Quotations in progress -----------------------------------------------
class BOVQuotationRow(BaseModel):
    quotation_number: str
    source_db: Optional[str] = None
    status: Optional[str] = None
    user_status: Optional[str] = None
    start_date: Optional[str] = None
    last_update: Optional[str] = None
    business_name: Optional[str] = None
    account_no: Optional[str] = None
    sales_rep: Optional[str] = None
    sales_rep_id: Optional[int] = None
    packer: Optional[str] = None
    checker: Optional[str] = None
    line_count: int = 0
    total_qty: float = 0.0
    quotation_total: Optional[float] = None
    dop2: Optional[str] = None
    dop3: Optional[str] = None
    invoice_number: Optional[str] = None


class BOVQuotationStatusCount(BaseModel):
    status: Optional[str] = None
    count: int = 0
    total_amount: float = 0.0
    total_qty: float = 0.0


class BOVQuotationsBlock(BOVBlockStatus):
    count: int = 0
    total_amount: float = 0.0
    total_qty: float = 0.0
    by_status: List[BOVQuotationStatusCount] = []
    statuses: List[str] = []


class BOVQuotationsResponse(BOVQuotationsBlock):
    quotations: List[BOVQuotationRow] = []
    limit: int = 0
    truncated: bool = False


# ---- Invoices ---------------------------------------------------------------
class BOVInvoiceRow(BaseModel):
    invoice_id: int
    store_id: Optional[int] = None
    store_name: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    invoice_type: Optional[str] = None
    customer_id: Optional[int] = None
    business_name: Optional[str] = None
    account_no: Optional[str] = None
    po_number: Optional[str] = None
    ship_date: Optional[str] = None
    ship_city: Optional[str] = None
    ship_state: Optional[str] = None
    sales_rep_id: Optional[int] = None
    sales_rep: Optional[str] = None
    shipper_id: Optional[int] = None
    shipper: Optional[str] = None
    tracking_no: Optional[str] = None
    tot_qty_ord: Optional[float] = None
    tot_qty_shp: Optional[float] = None
    no_lines: Optional[int] = None
    no_boxes: Optional[int] = None
    invoice_subtotal: Optional[float] = None
    total_taxes: Optional[float] = None
    shipping_cost: Optional[float] = None
    invoice_total: Optional[float] = None
    notes: Optional[str] = None
    age_days: Optional[int] = None


class BOVOpenInvoicesBlock(BOVBlockStatus):
    count: int = 0
    total_amount: float = 0.0
    total_qty: float = 0.0
    oldest_invoice_date: Optional[str] = None
    oldest_age_days: Optional[int] = None
    aging: Dict[str, int] = {}          # keys "0-1", "2-3", "4+"


class BOVOpenInvoicesResponse(BOVOpenInvoicesBlock):
    invoices: List[BOVInvoiceRow] = []
    limit: int = 0
    truncated: bool = False


class BOVShippedInvoicesBlock(BOVBlockStatus):
    period: Optional[BOVPeriod] = None
    totals: Optional[BOVRangeTotals] = None   # invoices, total_amount, total_qty, boxes


class BOVShippedInvoicesResponse(BOVShippedInvoicesBlock):
    bucket: str = "day"
    series: List[BOVSeriesPoint] = []
    previous_series: List[BOVSeriesPoint] = []
    invoices: List[BOVInvoiceRow] = []
    limit: int = 0
    truncated: bool = False


class BOVInvoiceLine(BaseModel):
    line_id: int
    product_id: Optional[int] = None
    product_sku: Optional[str] = None
    product_upc: Optional[str] = None
    product_description: Optional[str] = None
    unit_desc: Optional[str] = None
    unit_qty: Optional[float] = None
    qty_ordered: Optional[float] = None
    qty_shipped: Optional[float] = None
    unit_price: Optional[float] = None
    unit_cost: Optional[float] = None
    discount: Optional[float] = None
    ds_percent: Optional[bool] = None
    extended_price: Optional[float] = None
    extended_cost: Optional[float] = None
    line_cost: float = 0.0
    line_profit: Optional[float] = None
    margin_pct: Optional[float] = None
    void: bool = False


class BOVInvoiceHeader(BOVInvoiceRow):
    invoice_title: Optional[str] = None
    ship_to: Optional[str] = None
    ship_address1: Optional[str] = None
    ship_address2: Optional[str] = None
    ship_contact: Optional[str] = None
    ship_zip_code: Optional[str] = None
    ship_phone_no: Optional[str] = None
    term_id: Optional[int] = None
    term: Optional[str] = None
    tot_qty_rtrnd: Optional[float] = None
    total_weight: Optional[float] = None
    total_discounts: Optional[float] = None
    other_charges: Optional[float] = None
    total_credits: Optional[float] = None
    total_payments: Optional[float] = None
    void: bool = False
    is_shipped: bool = False
    revenue: float = 0.0
    cost: float = 0.0
    profit: float = 0.0
    margin_pct: Optional[float] = None


class BOVInvoiceDetailResponse(BaseModel):
    header: BOVInvoiceHeader
    lines: List[BOVInvoiceLine] = []
    store_name: Optional[str] = None


# ---- Purchase orders --------------------------------------------------------
class BOVPurchaseOrderRow(BaseModel):
    po_id: int
    po_number: Optional[str] = None
    po_date: Optional[str] = None
    required_date: Optional[str] = None
    supplier_id: Optional[int] = None
    business_name: Optional[str] = None
    account_no: Optional[str] = None
    status: Optional[int] = None
    po_total: Optional[float] = None
    no_lines: Optional[int] = None
    tot_qty_ord: Optional[float] = None
    tot_qty_rcv: Optional[float] = None
    qty_outstanding: Optional[float] = None
    outstanding_value: Optional[float] = None
    last_received: Optional[str] = None
    qty_received: Optional[float] = None
    received_value: Optional[float] = None
    lines_received: Optional[int] = None


class BOVIncomingPurchasesBlock(BOVBlockStatus):
    count: int = 0
    po_total: float = 0.0
    outstanding_value: float = 0.0
    qty_outstanding: float = 0.0
    oldest_po_date: Optional[str] = None


class BOVIncomingPurchasesResponse(BOVIncomingPurchasesBlock):
    purchase_orders: List[BOVPurchaseOrderRow] = []
    limit: int = 0
    truncated: bool = False


class BOVPurchasesRangeBlock(BOVBlockStatus):
    period: Optional[BOVPeriod] = None
    # purchased: purchase_orders, total, qty  |  received: purchase_orders, qty, value
    totals: Optional[BOVRangeTotals] = None


class BOVPurchasesRangeResponse(BOVPurchasesRangeBlock):
    bucket: str = "day"
    series: List[BOVSeriesPoint] = []
    previous_series: List[BOVSeriesPoint] = []
    purchase_orders: List[BOVPurchaseOrderRow] = []
    limit: int = 0
    truncated: bool = False


class BOVPurchaseOrderLine(BaseModel):
    line_id: int
    product_id: Optional[int] = None
    product_sku: Optional[str] = None
    product_upc: Optional[str] = None
    supplier_sku: Optional[str] = None
    product_description: Optional[str] = None
    unit_desc: Optional[str] = None
    unit_qty: Optional[float] = None
    qty_ordered: Optional[float] = None
    qty_received: Optional[float] = None
    qty_outstanding: float = 0.0
    unit_cost: Optional[float] = None
    extended_cost: Optional[float] = None
    date_received: Optional[str] = None


class BOVPurchaseOrderHeader(BOVPurchaseOrderRow):
    po_title: Optional[str] = None
    ship_to: Optional[str] = None
    ship_address1: Optional[str] = None
    ship_address2: Optional[str] = None
    ship_contact: Optional[str] = None
    ship_city: Optional[str] = None
    ship_state: Optional[str] = None
    ship_zip_code: Optional[str] = None
    ship_phone_no: Optional[str] = None
    employee_id: Optional[int] = None
    term_id: Optional[int] = None
    shipper_id: Optional[int] = None
    notes: Optional[str] = None
    supplier_contact: Optional[str] = None
    supplier_phone: Optional[str] = None
    is_received: bool = False


class BOVPurchaseOrderDetailResponse(BaseModel):
    header: BOVPurchaseOrderHeader
    lines: List[BOVPurchaseOrderLine] = []
    store_name: Optional[str] = None


# ---- Sales / margin ---------------------------------------------------------
class BOVSalesSourceTotals(BaseModel):
    revenue: float = 0.0
    cost: float = 0.0
    profit: float = 0.0
    margin_pct: Optional[float] = None
    returns: float = 0.0
    net_revenue: float = 0.0
    orders: int = 0
    units: float = 0.0
    cost_coverage: Optional[float] = None   # Shopify: share of units with a known cost (0..1)


class BOVSalesBucket(BaseModel):
    key: str
    start: str
    end: str
    label: str
    backoffice: Optional[BOVSalesSourceTotals] = None
    shopify: Optional[BOVSalesSourceTotals] = None
    total: BOVSalesSourceTotals


class BOVSalesSourceStatus(BaseModel):
    configured: bool = False
    store_ids: List[int] = []
    store_names: List[str] = []
    error: Optional[str] = None               # set only when every store of the source failed
    skipped_stores: List[str] = []
    failed_stores: List[str] = []             # "Store: error" for partial failures


class BOVSalesTrendResponse(BaseModel):
    period: BOVPeriod
    bucket: str
    sources: Dict[str, BOVSalesSourceStatus] = {}          # "backoffice", "shopify"
    buckets: List[BOVSalesBucket] = []
    previous_buckets: List[BOVSalesBucket] = []
    totals: Dict[str, BOVSalesSourceTotals] = {}           # "backoffice", "shopify", "total"
    previous_totals: Dict[str, BOVSalesSourceTotals] = {}
    change_pct: Dict[str, Dict[str, Optional[float]]] = {} # per source: revenue/cost/profit/margin_pct/orders/units
    warnings: List[str] = []
    store_ids: List[int] = []                              # store filter applied (empty = all)
    generated_at: datetime


class BOVBreakdownRow(BaseModel):
    key: Optional[str] = None
    name: Optional[str] = None
    secondary: Optional[str] = None
    orders: int = 0
    revenue: float = 0.0
    cost: Optional[float] = None
    profit: Optional[float] = None
    margin_pct: Optional[float] = None
    units: float = 0.0
    share_pct: Optional[float] = None


class BOVSalesBreakdownResponse(BaseModel):
    period: BOVPeriod
    by: str
    source: str
    configured: bool = False
    error: Optional[str] = None
    rows: List[BOVBreakdownRow] = []
    total_revenue: float = 0.0
    warnings: List[str] = []


class BOVShopifyStoreOpen(BaseModel):
    store_id: int
    store_name: str
    count: Optional[int] = None
    open_value: Optional[float] = None
    source: Optional[str] = None       # "live" | "local"
    error: Optional[str] = None


class BOVShopifyOpenOrdersBlock(BOVBlockStatus):
    count: int = 0
    open_value: Optional[float] = None
    per_store: List[BOVShopifyStoreOpen] = []


class BOVSalesSummaryBlock(BaseModel):
    configured: bool = False
    sources: Dict[str, BOVSalesSourceStatus] = {}
    totals: Dict[str, BOVSalesSourceTotals] = {}
    previous_totals: Dict[str, BOVSalesSourceTotals] = {}
    change_pct: Dict[str, Dict[str, Optional[float]]] = {}
    sparkline: List[BOVSeriesPoint] = []            # daily, values: revenue, profit
    previous_sparkline: List[BOVSeriesPoint] = []
    warnings: List[str] = []


class BusinessOverviewSummaryResponse(BaseModel):
    period: BOVPeriod
    quotations: BOVQuotationsBlock
    invoices_open: BOVOpenInvoicesBlock
    invoices_shipped: BOVShippedInvoicesBlock
    purchases_incoming: BOVIncomingPurchasesBlock
    purchases_purchased: BOVPurchasesRangeBlock
    purchases_received: BOVPurchasesRangeBlock
    sales: BOVSalesSummaryBlock
    shopify_open_orders: BOVShopifyOpenOrdersBlock
    store_ids: List[int] = []                              # store filter applied (empty = all)
    generated_at: datetime
