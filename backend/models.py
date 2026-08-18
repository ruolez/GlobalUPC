from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, ForeignKey, Enum, Text, Numeric, UniqueConstraint, ForeignKeyConstraint
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import enum

class StoreType(str, enum.Enum):
    mssql = "mssql"
    shopify = "shopify"
    shipper = "shipper"

class StoreCategory(str, enum.Enum):
    wholesale = "wholesale"
    retail = "retail"

class Store(Base):
    __tablename__ = "stores"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    store_type = Column(Enum(StoreType, name='store_type', create_type=False), nullable=False)
    store_category = Column(Enum(StoreCategory, name='store_category', create_type=False), nullable=False, server_default='retail')
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    mssql_connection = relationship("MSSQLConnection", back_populates="store", uselist=False, cascade="all, delete-orphan")
    shopify_connection = relationship("ShopifyConnection", back_populates="store", uselist=False, cascade="all, delete-orphan")

class MSSQLConnection(Base):
    __tablename__ = "mssql_connections"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, unique=True)
    host = Column(String(255), nullable=False)
    port = Column(Integer, default=1433)
    database_name = Column(String(255), nullable=False)
    username = Column(String(255), nullable=False)
    password = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    store = relationship("Store", back_populates="mssql_connection")

class ShopifyConnection(Base):
    __tablename__ = "shopify_connections"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, unique=True)
    shop_domain = Column(String(255), nullable=False, unique=True)
    admin_api_key = Column(String(512), nullable=False)
    api_version = Column(String(50), default="2025-01")
    update_sku_with_barcode = Column(Boolean, default=False)
    first_order_tag = Column(String(100), nullable=False, server_default="First order")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    store = relationship("Store", back_populates="shopify_connection")

class Setting(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(255), nullable=False, unique=True, index=True)
    value = Column(String)
    description = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class UPCUpdateHistory(Base):
    __tablename__ = "upc_update_history"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(String(36), nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True)
    store_name = Column(String(255), nullable=False)
    store_type = Column(Enum(StoreType, name='store_type', create_type=False), nullable=False)
    old_upc = Column(String(255), nullable=False, index=True)
    new_upc = Column(String(255), nullable=False, index=True)

    # Context fields
    product_id = Column(String(255))
    product_title = Column(Text)
    variant_id = Column(String(255))
    variant_title = Column(String(255))
    table_name = Column(String(255))
    primary_keys = Column(JSONB)

    # Result fields
    success = Column(Boolean, nullable=False)
    items_updated_count = Column(Integer, default=0)
    error_message = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    store = relationship("Store")

class UPCExclusion(Base):
    __tablename__ = "upc_exclusions"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True)
    upc = Column(String(255), nullable=False)
    excluded_at = Column(DateTime(timezone=True), server_default=func.now())
    notes = Column(Text)

    store = relationship("Store")

class ItemTrackerConfig(Base):
    __tablename__ = "item_tracker_config"

    id = Column(Integer, primary_key=True, index=True)
    s2s_store_id = Column(Integer, ForeignKey("stores.id", ondelete="SET NULL"), nullable=True)
    sales_store_ids = Column(JSONB, default=[])
    inventory_store_id = Column(Integer, ForeignKey("stores.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    s2s_store = relationship("Store", foreign_keys=[s2s_store_id])
    inventory_store = relationship("Store", foreign_keys=[inventory_store_id])

class SalesExclusion(Base):
    __tablename__ = "sales_exclusions"

    id = Column(Integer, primary_key=True, index=True)
    business_name = Column(String(255), nullable=False)
    void_status = Column(Integer, nullable=True)
    excluded_at = Column(DateTime(timezone=True), server_default=func.now())
    notes = Column(Text)

class SalesConfig(Base):
    __tablename__ = "sales_config"

    id = Column(Integer, primary_key=True, index=True)
    s2s_store_id = Column(Integer, ForeignKey("stores.id", ondelete="SET NULL"), nullable=True)
    mssql_store_ids = Column(JSONB, default=[])
    shopify_store_ids = Column(JSONB, default=[])
    excluded_subcategories = Column(JSONB, default=[])
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    s2s_store = relationship("Store", foreign_keys=[s2s_store_id])

class BusinessOverviewConfig(Base):
    __tablename__ = "business_overview_config"

    id = Column(Integer, primary_key=True, index=True)
    sales_store_id = Column(Integer, ForeignKey("stores.id", ondelete="SET NULL"), nullable=True)  # legacy single value
    sales_store_ids = Column(JSONB, default=[])
    purchases_store_id = Column(Integer, ForeignKey("stores.id", ondelete="SET NULL"), nullable=True)
    shopify_store_ids = Column(JSONB, default=[])
    quotation_statuses = Column(JSONB, default=["In Progress", "Locked"])
    timezone = Column(String(64), nullable=False, server_default="America/Chicago")
    alert_rules = Column(JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    sales_store = relationship("Store", foreign_keys=[sales_store_id])
    purchases_store = relationship("Store", foreign_keys=[purchases_store_id])

class BusinessOverviewShopifyExclusion(Base):
    __tablename__ = "business_overview_shopify_exclusions"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id", ondelete="CASCADE"), nullable=True)
    variant_shopify_id = Column(BigInteger, nullable=True)
    product_shopify_id = Column(BigInteger, nullable=True)
    barcode = Column(Text, nullable=True)
    sku = Column(Text, nullable=True)
    title = Column(Text, nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    store = relationship("Store")

class PriceUpdateHistory(Base):
    __tablename__ = "price_update_history"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(String(36), nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True)
    store_name = Column(String(255), nullable=False)
    store_type = Column(Enum(StoreType, name='store_type', create_type=False), nullable=False)
    upc = Column(String(255), nullable=False, index=True)
    product_description = Column(Text)
    variant_id = Column(String(255))
    variant_title = Column(String(255))
    variant_barcode = Column(String(255))
    old_price = Column(Numeric(10, 2))
    old_cost = Column(Numeric(10, 2))
    new_price = Column(Numeric(10, 2))
    new_cost = Column(Numeric(10, 2))
    old_delivery_b = Column(Numeric(10, 2))
    new_delivery_b = Column(Numeric(10, 2))
    old_list_price = Column(Numeric(10, 2))
    new_list_price = Column(Numeric(10, 2))
    success = Column(Boolean, nullable=False)
    rows_affected = Column(Integer, default=0)
    error_message = Column(Text)
    is_mirror = Column(Boolean, default=False)
    mirror_source_store_id = Column(Integer, ForeignKey("stores.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    store = relationship("Store", foreign_keys=[store_id])
    mirror_source_store = relationship("Store", foreign_keys=[mirror_source_store_id])


class StoreMirror(Base):
    __tablename__ = "store_mirrors"

    id = Column(Integer, primary_key=True, index=True)
    source_store_id = Column(Integer, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True)
    mirror_store_id = Column(Integer, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    source_store = relationship("Store", foreign_keys=[source_store_id])
    mirror_store = relationship("Store", foreign_keys=[mirror_store_id])


class ItemTrackerExclusion(Base):
    __tablename__ = "item_tracker_exclusions"

    id = Column(Integer, primary_key=True, index=True)
    business_name = Column(String(255), nullable=False)
    void_status = Column(Integer, nullable=True)  # NULL=all, 0=non-voided, 1=voided
    excluded_at = Column(DateTime(timezone=True), server_default=func.now())
    notes = Column(Text)


class ShopifySyncState(Base):
    __tablename__ = "shopify_sync_state"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, unique=True)
    status = Column(String(20), nullable=False, server_default="idle")
    phase = Column(String(40))
    mode = Column(String(12))
    run_started_at = Column(DateTime(timezone=True))
    heartbeat_at = Column(DateTime(timezone=True))
    last_completed_at = Column(DateTime(timezone=True))
    last_sync_started_at = Column(DateTime(timezone=True))
    shop_timezone = Column(String(64))
    customers_count = Column(Integer, default=0)
    orders_count = Column(Integer, default=0)
    line_items_count = Column(Integer, default=0)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    store = relationship("Store")


class ShopifyCustomer(Base):
    __tablename__ = "shopify_customers"

    id = Column(BigInteger, primary_key=True)
    store_id = Column(Integer, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    shopify_id = Column(BigInteger, nullable=False)
    shopify_gid = Column(Text, nullable=False)
    email = Column(Text)
    email_normalized = Column(Text)
    first_name = Column(Text)
    last_name = Column(Text)
    display_name = Column(Text)
    phone = Column(Text)
    state = Column(String(30))
    verified_email = Column(Boolean)
    tags = Column(ARRAY(Text))
    note = Column(Text)
    number_of_orders = Column(Integer)
    amount_spent = Column(Numeric(14, 2))
    currency = Column(String(10))
    default_address_zip = Column(Text)
    default_province_code = Column(Text)
    default_country_code = Column(Text)
    created_at = Column(DateTime(timezone=True))
    shopify_updated_at = Column(DateTime(timezone=True))
    raw = Column(JSONB, nullable=False)
    synced_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("store_id", "shopify_id"),)


class ShopifyOrder(Base):
    __tablename__ = "shopify_orders"

    id = Column(BigInteger, primary_key=True)
    store_id = Column(Integer, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    shopify_id = Column(BigInteger, nullable=False)
    shopify_gid = Column(Text, nullable=False)
    name = Column(Text)
    customer_shopify_id = Column(BigInteger)
    email = Column(Text)
    created_at = Column(DateTime(timezone=True))
    processed_at = Column(DateTime(timezone=True))
    shopify_updated_at = Column(DateTime(timezone=True))
    cancelled_at = Column(DateTime(timezone=True))
    closed_at = Column(DateTime(timezone=True))
    financial_status = Column(String(30))
    fulfillment_status = Column(String(30))
    tags = Column(ARRAY(Text))
    note = Column(Text)
    total_price = Column(Numeric(14, 2))
    subtotal_price = Column(Numeric(14, 2))
    total_discounts = Column(Numeric(14, 2))
    total_refunded = Column(Numeric(14, 2))
    currency = Column(String(10))
    ship_province_code = Column(Text)
    ship_province = Column(Text)
    ship_country_code = Column(Text)
    ship_zip = Column(Text)
    ship_city = Column(Text)
    shipping_line_title = Column(Text)
    shipping_carrier_identifier = Column(Text)
    fulfilled_at = Column(DateTime(timezone=True))
    in_transit_at = Column(DateTime(timezone=True))
    delivered_at = Column(DateTime(timezone=True))
    tracking_company = Column(Text)
    tracking_number = Column(Text)
    tracking_url = Column(Text)
    fulfillments = Column(JSONB)
    raw = Column(JSONB, nullable=False)
    synced_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("store_id", "shopify_id"),)


class ShopifyOrderLineItem(Base):
    __tablename__ = "shopify_order_line_items"

    id = Column(BigInteger, primary_key=True)
    store_id = Column(Integer, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    order_shopify_id = Column(BigInteger, nullable=False)
    shopify_id = Column(BigInteger, nullable=False)
    title = Column(Text)
    variant_title = Column(Text)
    sku = Column(Text)
    vendor = Column(Text)
    barcode = Column(Text)
    product_title = Column(Text)
    product_shopify_id = Column(BigInteger)
    variant_shopify_id = Column(BigInteger)
    quantity = Column(Integer)
    original_unit_price = Column(Numeric(14, 2))
    discounted_total = Column(Numeric(14, 2))
    raw = Column(JSONB)

    __table_args__ = (
        UniqueConstraint("store_id", "shopify_id"),
        ForeignKeyConstraint(
            ["store_id", "order_shopify_id"],
            ["shopify_orders.store_id", "shopify_orders.shopify_id"],
            ondelete="CASCADE",
        ),
    )
