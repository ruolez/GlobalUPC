-- Shopify stores that never ship orders: excluded from the Est. shipping
-- estimation (Overview profit + Month End).
ALTER TABLE business_overview_config
    ADD COLUMN IF NOT EXISTS ship_estimate_excluded_store_ids JSONB DEFAULT '[]'::jsonb;
