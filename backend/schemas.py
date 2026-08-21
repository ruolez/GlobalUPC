from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Optional, Literal, List, Dict, Tuple, Any
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
    auth_method: Literal["token", "client_credentials"] = "token"
    admin_api_key: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    api_version: str = "2025-01"
    update_sku_with_barcode: bool = False
    first_order_tag: str = "First order"

    @model_validator(mode="after")
    def _require_mode_credentials(self):
        if self.auth_method == "token":
            if not self.admin_api_key:
                raise ValueError("admin_api_key is required for token auth")
        else:
            if not self.client_id or not self.client_secret:
                raise ValueError("client_id and client_secret are required for OAuth client credentials auth")
        return self

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
    auth_method: Literal["token", "client_credentials"] = "token"
    admin_api_key: Optional[str] = None  # blank/None => keep current
    client_id: Optional[str] = None
    client_secret: Optional[str] = None  # blank/None => keep current
    api_version: str = "2025-01"
    update_sku_with_barcode: bool = False

    @model_validator(mode="after")
    def _require_mode_credentials(self):
        if self.auth_method == "client_credentials" and not self.client_id:
            raise ValueError("client_id is required for OAuth client credentials auth")
        return self

class ShopifyStoreUpdate(StoreBase):
    connection: ShopifyConnectionUpdate

class MSSQLConnectionResponse(MSSQLConnectionBase):
    id: int
    store_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Standalone (does NOT inherit ShopifyConnectionBase) so client_secret is
# never serialized into API responses.
class ShopifyConnectionResponse(BaseModel):
    id: int
    store_id: int
    shop_domain: str
    auth_method: str = "token"
    admin_api_key: Optional[str] = None
    client_id: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    api_version: str = "2025-01"
    update_sku_with_barcode: bool = False
    first_order_tag: str = "First order"
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

# Alert rules for the Overview "Attention" strip. Stored per-rule settings are
# merged over these defaults (see bov_merge_alert_rules) so new rules show up
# without a migration. Thresholds are validated in the config endpoint.
BOV_DEFAULT_ALERT_RULES: Dict[str, Dict] = {
    "unshipped_cutoff":        {"enabled": True, "cutoff": "14:00"},
    "open_invoice_age":        {"enabled": True, "days": 2},
    "quotation_stuck":         {"enabled": True, "days": 1},
    "po_overdue":              {"enabled": True, "days": 14},
    "shopify_on_hold":         {"enabled": True},
    "shopify_unfulfilled_age": {"enabled": True, "days": 2},
    "shopify_sync_stale":      {"enabled": True, "days": 1},
    "margin_floor":            {"enabled": True, "pct": 15, "per_store": True},
    "revenue_drop":            {"enabled": True, "pct": 20},
}


# Rules that accept per-store overrides ({"stores": {"<store_id>": {enabled, <field>}}}):
# stores that never enter tracking numbers must be able to opt out of the
# open-invoice rules, or set their own cutoff / age.
BOV_PER_STORE_RULES: Dict[str, Tuple[str, ...]] = {
    "unshipped_cutoff": ("cutoff",),
    "open_invoice_age": ("days",),
    "margin_floor": ("pct",),          # per store (BackOffice or Shopify): own floor or opt out
}


def bov_merge_alert_rules(stored: Optional[Dict]) -> Dict[str, Dict]:
    """Defaults overlaid with whatever is stored (unknown keys are dropped)."""
    out: Dict[str, Dict] = {}
    stored = stored if isinstance(stored, dict) else {}
    for key, defaults in BOV_DEFAULT_ALERT_RULES.items():
        merged = dict(defaults)
        val = stored.get(key)
        if isinstance(val, dict):
            for k, v in val.items():
                if k in defaults:
                    merged[k] = v
            if key in BOV_PER_STORE_RULES and isinstance(val.get("stores"), dict):
                allowed = ("enabled",) + BOV_PER_STORE_RULES[key]
                clean: Dict[str, Dict] = {}
                for sid, ov in val["stores"].items():
                    if not isinstance(ov, dict):
                        continue
                    entry = {k: v for k, v in ov.items() if k in allowed}
                    if entry:
                        clean[str(sid)] = entry
                if clean:
                    merged["stores"] = clean
        out[key] = merged
    return out


def _bov_validate_rule_fields(key: str, r: Dict) -> Optional[str]:
    import re
    if "enabled" in r and not isinstance(r.get("enabled"), bool):
        return f"{key}: enabled must be true/false"
    if "cutoff" in r:
        if not isinstance(r["cutoff"], str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", r["cutoff"]):
            return f"{key}: cutoff must be HH:MM (24h)"
    for num in ("days", "hours"):
        if num in r:
            try:
                v = float(r[num])
            except (TypeError, ValueError):
                return f"{key}: {num} must be a number"
            if v < 0 or v > 10000:
                return f"{key}: {num} out of range"
    if "pct" in r:
        try:
            v = float(r["pct"])
        except (TypeError, ValueError):
            return f"{key}: pct must be a number"
        if v < 0 or v > 100:
            return f"{key}: pct must be between 0 and 100"
    if "per_store" in r and not isinstance(r["per_store"], bool):
        return f"{key}: per_store must be true/false"
    return None


def bov_validate_alert_rules(rules: Dict[str, Dict]) -> Optional[str]:
    """Return an error message for the first invalid threshold, else None."""
    for key, r in rules.items():
        err = _bov_validate_rule_fields(key, r)
        if err:
            return err
        for sid, ov in (r.get("stores") or {}).items():
            err = _bov_validate_rule_fields(f"{key} (store {sid})", ov)
            if err:
                return err
    return None


def _bov_validate_alert_rules_legacy(rules: Dict[str, Dict]) -> Optional[str]:
    import re
    for key, r in rules.items():
        if not isinstance(r.get("enabled", True), bool):
            return f"{key}: enabled must be true/false"
        if "cutoff" in r:
            if not isinstance(r["cutoff"], str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", r["cutoff"]):
                return f"{key}: cutoff must be HH:MM (24h)"
        for num in ("days", "hours"):
            if num in r:
                try:
                    v = float(r[num])
                except (TypeError, ValueError):
                    return f"{key}: {num} must be a number"
                if v < 0 or v > 10000:
                    return f"{key}: {num} out of range"
        if "pct" in r:
            try:
                v = float(r["pct"])
            except (TypeError, ValueError):
                return f"{key}: pct must be a number"
            if v < 0 or v > 100:
                return f"{key}: pct must be between 0 and 100"
        if "per_store" in r and not isinstance(r["per_store"], bool):
            return f"{key}: per_store must be true/false"
    return None


class BusinessOverviewConfigCreate(BaseModel):
    sales_store_ids: List[int] = []
    sales_store_id: Optional[int] = None      # legacy single value; merged into sales_store_ids
    purchases_store_id: Optional[int] = None
    shopify_store_ids: List[int] = []
    quotation_statuses: List[str] = list(BOV_DEFAULT_QUOTATION_STATUSES)
    timezone: str = "America/Chicago"
    alert_rules: Optional[Dict[str, Dict]] = None    # partial per-rule overrides; merged over defaults


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
    alert_rules: Dict[str, Dict] = {}
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
    count: Optional[int] = None          # per-store contribution when the block fans out
    amount: Optional[float] = None


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
    revenue: Optional[float] = None
    cost: Optional[float] = None
    profit: Optional[float] = None
    margin_pct: Optional[float] = None
    cost_coverage: Optional[float] = None


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
    is_shipped: Optional[bool] = None
    revenue: Optional[float] = None
    cost: Optional[float] = None
    profit: Optional[float] = None
    net_profit: Optional[float] = None  # profit minus shipping_cost — the "real" profit
    margin_pct: Optional[float] = None
    cost_coverage: Optional[float] = None


class BOVInvoicesPeriodResponse(BOVBlockStatus):
    period: Optional[BOVPeriod] = None
    count: int = 0
    open_count: int = 0
    shipped_count: int = 0
    total_amount: float = 0.0
    open_amount: float = 0.0
    shipped_amount: float = 0.0
    total_qty: float = 0.0
    invoices: List[BOVInvoiceRow] = []
    limit: int = 0
    truncated: bool = False


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
    line_unit_cost: Optional[float] = None       # cost stamped on the invoice line (reference)
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
    cost_basis: str = "local"                     # local = store Items_tbl.UnitCost, s2s = S2S Items_tbl.UnitCost


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


class BOVPlacedPurchasesBlock(BOVBlockStatus):
    # POs placed but awaiting vendor confirmation (Status 0, blank PoHeader) — snapshot, no date filter
    count: int = 0
    po_total: float = 0.0
    qty_ordered: float = 0.0
    oldest_po_date: Optional[str] = None


class BOVPlacedPurchasesResponse(BOVPlacedPurchasesBlock):
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
    excluded: bool = False
    exclusion_id: Optional[int] = None


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
    excluded_lines: int = 0


# ---- Sales / margin ---------------------------------------------------------
class BOVSalesSourceTotals(BaseModel):
    revenue: float = 0.0
    cost: float = 0.0
    profit: float = 0.0                     # revenue − cost − shipping_cost (BackOffice ships; Shopify 0)
    shipping_cost: float = 0.0              # BackOffice Invoices_tbl.ShippingCost summed over the bucket
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


class BOVSalesStoreTotals(BaseModel):
    store_id: int
    store_name: str
    source: str                          # backoffice | shopify
    revenue: float = 0.0
    cost: float = 0.0
    profit: float = 0.0
    shipping_cost: float = 0.0
    margin_pct: Optional[float] = None
    orders: int = 0
    units: float = 0.0
    cost_coverage: Optional[float] = None
    error: Optional[str] = None


class BOVSalesTrendResponse(BaseModel):
    period: BOVPeriod
    bucket: str
    sources: Dict[str, BOVSalesSourceStatus] = {}          # "backoffice", "shopify"
    buckets: List[BOVSalesBucket] = []
    previous_buckets: List[BOVSalesBucket] = []
    totals: Dict[str, BOVSalesSourceTotals] = {}           # "backoffice", "shopify", "total"
    previous_totals: Dict[str, BOVSalesSourceTotals] = {}
    change_pct: Dict[str, Dict[str, Optional[float]]] = {} # per source: revenue/cost/profit/margin_pct/orders/units
    per_store: List[BOVSalesStoreTotals] = []
    cost_mode: str = "default"
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
    revenue_backoffice: Optional[float] = None
    revenue_shopify: Optional[float] = None
    units_backoffice: Optional[float] = None
    units_shopify: Optional[float] = None


class BOVSalesBreakdownResponse(BaseModel):
    period: BOVPeriod
    by: str
    source: str
    configured: bool = False
    error: Optional[str] = None
    rows: List[BOVBreakdownRow] = []
    total_revenue: float = 0.0
    cost_mode: str = "default"
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
    cost_mode: str = "default"
    per_store: List[BOVSalesStoreTotals] = []
    sources: Dict[str, BOVSalesSourceStatus] = {}
    totals: Dict[str, BOVSalesSourceTotals] = {}
    previous_totals: Dict[str, BOVSalesSourceTotals] = {}
    change_pct: Dict[str, Dict[str, Optional[float]]] = {}
    sparkline: List[BOVSeriesPoint] = []            # daily, values: revenue, profit
    previous_sparkline: List[BOVSeriesPoint] = []
    warnings: List[str] = []


class BOVShopifyStoreOrders(BaseModel):
    store_id: int
    store_name: str
    synced: bool = False
    last_synced_at: Optional[str] = None
    # Mirror (selected period, shop calendar)
    orders: Optional[int] = None
    revenue: Optional[float] = None
    cancelled: Optional[int] = None
    fulfilled_in_period: Optional[int] = None
    fulfilled_from_period: Optional[int] = None
    unfulfilled_from_period: Optional[int] = None
    on_hold_from_period: Optional[int] = None
    error: Optional[str] = None
    # Live fulfillment buckets (whole open backlog, any date)
    open_orders: Optional[int] = None
    on_hold: Optional[int] = None
    in_process: Optional[int] = None
    on_picklist: Optional[int] = None
    to_fulfill: Optional[int] = None
    live_error: Optional[str] = None


class BOVShopifyOrdersResponse(BOVBlockStatus):
    period: Optional[BOVPeriod] = None
    live: bool = True
    stores: List[BOVStoreStatus] = []
    per_store: List[BOVShopifyStoreOrders] = []
    totals: Dict[str, float] = {}
    skipped_stores: List[str] = []


class BOVShopifyOrderRow(BaseModel):
    store_id: int
    store_name: Optional[str] = None
    shopify_id: int
    name: Optional[str] = None
    created_at: Optional[str] = None
    processed_at: Optional[str] = None
    fulfilled_at: Optional[str] = None
    closed_at: Optional[str] = None
    cancelled_at: Optional[str] = None
    financial_status: Optional[str] = None
    fulfillment_status: Optional[str] = None
    total_price: Optional[float] = None
    subtotal_price: Optional[float] = None
    total_shipping: Optional[float] = None
    total_refunded: Optional[float] = None
    currency: Optional[str] = None
    email: Optional[str] = None
    tags: List[str] = []
    note: Optional[str] = None
    ship_city: Optional[str] = None
    ship_province_code: Optional[str] = None
    ship_country_code: Optional[str] = None
    ship_zip: Optional[str] = None
    shipping_line_title: Optional[str] = None
    tracking_company: Optional[str] = None
    tracking_number: Optional[str] = None
    tracking_url: Optional[str] = None
    customer_name: Optional[str] = None
    customer_orders: Optional[int] = None
    age_hours: Optional[float] = None


class BOVShopifyOrdersListResponse(BOVBlockStatus):
    kind: str
    older_than_days: Optional[float] = None
    orders: List[BOVShopifyOrderRow] = []
    count: int = 0
    total_amount: float = 0.0
    skipped_stores: List[str] = []
    limit: int = 0
    truncated: bool = False


class BOVShopifyOrderLine(BaseModel):
    shopify_id: Optional[int] = None
    title: Optional[str] = None
    variant_title: Optional[str] = None
    sku: Optional[str] = None
    vendor: Optional[str] = None
    barcode: Optional[str] = None
    product_title: Optional[str] = None
    quantity: Optional[int] = None
    current_quantity: Optional[int] = None
    unit_price: Optional[float] = None
    discounted_total: Optional[float] = None


class BOVShopifyOrderHeader(BOVShopifyOrderRow):
    fulfillments: List[Dict[str, Any]] = []


class BOVShopifyOrderDetailResponse(BaseModel):
    header: BOVShopifyOrderHeader
    lines: List[BOVShopifyOrderLine] = []
    store_name: Optional[str] = None
    admin_url: Optional[str] = None


class BOVMissingCostRow(BaseModel):
    store_id: int
    store_name: str
    barcode: Optional[str] = None
    sku: Optional[str] = None
    vendor: Optional[str] = None
    title: Optional[str] = None
    variant_title: Optional[str] = None
    product_shopify_id: Optional[int] = None
    variant_shopify_id: Optional[int] = None
    orders: int = 0
    units: float = 0.0
    revenue: float = 0.0
    reason: str                               # no_barcode | not_in_items | no_cost
    admin_url: Optional[str] = None


class BOVMissingCostResponse(BOVBlockStatus):
    period: Optional[BOVPeriod] = None
    cost_store_name: Optional[str] = None
    rows: List[BOVMissingCostRow] = []
    count: int = 0
    units: float = 0.0
    revenue: float = 0.0
    products_checked: int = 0
    skipped_stores: List[str] = []


# ---- Products sold (per product per store, both cost bases) ----------------
class BOVProductRow(BaseModel):
    store_id: int
    store_name: str
    store_type: str                           # backoffice | shopify
    upc: Optional[str] = None
    description: Optional[str] = None
    sku: Optional[str] = None
    orders: int = 0
    units: float = 0.0
    revenue: float = 0.0
    avg_price: Optional[float] = None         # revenue / units
    local_unit_cost: Optional[float] = None   # own Items_tbl.UnitCost (BackOffice) / S2S UnitPriceC (Shopify)
    local_cost: Optional[float] = None
    local_profit: Optional[float] = None
    local_margin_pct: Optional[float] = None
    s2s_unit_cost: Optional[float] = None     # S2S Items_tbl.UnitCost
    s2s_cost: Optional[float] = None
    s2s_profit: Optional[float] = None
    s2s_margin_pct: Optional[float] = None


class BOVProductsTotals(BaseModel):
    products: int = 0
    units: float = 0.0
    revenue: float = 0.0
    local_cost: Optional[float] = None
    local_profit: Optional[float] = None
    local_margin_pct: Optional[float] = None
    local_cost_coverage: Optional[float] = None   # % of revenue with a known local cost
    s2s_cost: Optional[float] = None
    s2s_profit: Optional[float] = None
    s2s_margin_pct: Optional[float] = None
    s2s_cost_coverage: Optional[float] = None


class BOVProductsResponse(BOVBlockStatus):
    period: Optional[BOVPeriod] = None
    rows: List[BOVProductRow] = []
    count: int = 0                            # rows before the limit
    totals: Optional[BOVProductsTotals] = None
    warnings: List[str] = []
    truncated: bool = False
    cost_store_id: Optional[int] = None
    cost_store_name: Optional[str] = None


class BOVShopifyExclusionCreate(BaseModel):
    store_id: Optional[int] = None            # None = all stores
    variant_shopify_id: Optional[int] = None
    product_shopify_id: Optional[int] = None
    barcode: Optional[str] = None
    sku: Optional[str] = None
    title: Optional[str] = None
    note: Optional[str] = None


class BOVShopifyExclusion(BOVShopifyExclusionCreate):
    id: int
    store_name: Optional[str] = None
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class BOVShopifyExclusionList(BaseModel):
    exclusions: List[BOVShopifyExclusion] = []
    total: int = 0


class BOVPoExclusionCreate(BaseModel):
    product_id: int                            # PurchaseOrdersDetails_tbl.ProductID
    product_sku: Optional[str] = None
    product_upc: Optional[str] = None
    description: Optional[str] = None
    note: Optional[str] = None


class BOVPoExclusion(BOVPoExclusionCreate):
    id: int
    store_id: int
    store_name: Optional[str] = None
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class BOVPoExclusionList(BaseModel):
    exclusions: List[BOVPoExclusion] = []
    total: int = 0


class BOVShopifyRefreshResult(BaseModel):
    store_id: int
    store_name: str
    status: str                       # synced | fresh | running | never_synced | failed
    note: Optional[str] = None
    seconds: Optional[float] = None
    orders: Optional[int] = None
    customers: Optional[int] = None
    last_synced_at: Optional[str] = None


class BOVShopifyRefreshResponse(BaseModel):
    results: List[BOVShopifyRefreshResult] = []
    synced_any: bool = False
    seconds: float = 0.0


class BOVAlertAction(BaseModel):
    section: str                              # overview | quotations | invoices | purchasing | shopify
    tab: Optional[str] = None                 # e.g. "invoices:open", "purchases:incoming"
    sort: Optional[Dict[str, str]] = None     # {"widget": "invoicesOpen", "key": "age_days", "dir": "desc"}
    open_all_dates: Optional[bool] = None     # invoices Open tab: whole backlog
    target: Optional[str] = None              # element id to scroll to / flash
    match: Optional[Dict[str, Any]] = None    # row predicate so the list can highlight the alerted rows


class BOVAlert(BaseModel):
    key: str
    severity: str                             # critical | warn
    title: str
    detail: Optional[str] = None
    count: Optional[int] = None
    amount: Optional[float] = None
    stores: List[str] = []
    action: Optional[BOVAlertAction] = None


class BOVAlertsResponse(BaseModel):
    period: BOVPeriod
    rules: Dict[str, Dict] = {}
    alerts: List[BOVAlert] = []
    checked: List[str] = []
    skipped: List[str] = []                   # disabled or not applicable (e.g. cutoff not reached)
    errors: List[str] = []
    generated_at: datetime


class BusinessOverviewSummaryResponse(BaseModel):
    period: BOVPeriod
    quotations: BOVQuotationsBlock
    invoices_open: BOVOpenInvoicesBlock
    invoices_shipped: BOVShippedInvoicesBlock
    purchases_incoming: BOVIncomingPurchasesBlock
    purchases_purchased: BOVPlacedPurchasesBlock
    purchases_received: BOVPurchasesRangeBlock
    sales: BOVSalesSummaryBlock
    shopify_open_orders: BOVShopifyOpenOrdersBlock
    store_ids: List[int] = []                              # store filter applied (empty = all)
    generated_at: datetime


# ---- Month End --------------------------------------------------------------
class MonthEndRow(BaseModel):
    source: str                                  # "backoffice" | "shopify"
    row_key: str                                 # "bo:<store_id>:<invoice_id>" | "sh:<store_id>:<shopify_id>"
    store_id: int
    store_name: str
    date: Optional[str] = None
    number: Optional[str] = None
    customer: Optional[str] = None
    total: Optional[float] = None
    revenue: Optional[float] = None              # product revenue (line-level)
    cost: Optional[float] = None
    product_profit: Optional[float] = None       # revenue - cost
    shipping_collected: Optional[float] = None   # Shopify checkout shipping; None for BackOffice
    shipping_cost: Optional[float] = None        # BackOffice Invoices_tbl.ShippingCost | Σ shipper parcels.cost
    shipping_missing: bool = False               # Shopify: shipper configured but no parcel matched
    parcels: Optional[int] = None                # Shopify: matched parcel/box count
    profit: Optional[float] = None               # product_profit + shipping_collected - shipping_cost
    cost_coverage: Optional[float] = None
    status: Optional[str] = None                 # backoffice: shipped/open · shopify: financial_status


class MonthEndTotals(BaseModel):
    orders: int = 0
    total: float = 0.0
    revenue: float = 0.0
    cost: float = 0.0
    product_profit: float = 0.0
    shipping_collected: float = 0.0
    shipping_cost: float = 0.0
    profit: float = 0.0
    profit_known: int = 0                        # rows whose profit could be computed


class MonthEndStoreStatus(BaseModel):
    store_id: int
    store_name: str
    source: str
    count: Optional[int] = None
    error: Optional[str] = None
    truncated: bool = False


class MonthEndShipperStatus(BaseModel):
    configured: bool = False
    store_name: Optional[str] = None
    matched: int = 0
    unmatched: int = 0
    error: Optional[str] = None


class MonthEndResponse(BaseModel):
    configured: bool = False
    period: Optional[BOVPeriod] = None
    stores: List[MonthEndStoreStatus] = []
    rows: List[MonthEndRow] = []
    totals: Optional[MonthEndTotals] = None
    by_source: Dict[str, MonthEndTotals] = {}
    shipper: MonthEndShipperStatus = MonthEndShipperStatus()
    warnings: List[str] = []
    limit: int = 0
    truncated: bool = False
    timings: Dict[str, float] = {}               # per-stage seconds: fetch / cost_lookup / parcels
