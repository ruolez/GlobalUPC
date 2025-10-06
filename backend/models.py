from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import enum

class StoreType(str, enum.Enum):
    mssql = "mssql"
    shopify = "shopify"

class Store(Base):
    __tablename__ = "stores"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    store_type = Column(Enum(StoreType), nullable=False)
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
    store_type = Column(Enum(StoreType), nullable=False)
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
