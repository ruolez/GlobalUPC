-- Per-store tag used by Shopify Analytics to identify first-time-customer orders.
-- Default keeps existing behavior for any store that hasn't been customized yet.
ALTER TABLE shopify_connections
    ADD COLUMN IF NOT EXISTS first_order_tag VARCHAR(100) NOT NULL DEFAULT 'First order';
