-- Migration: Business Overview — multiple sales/invoice stores
-- Version: 020
-- Date: 2026-08-17
-- Description: sales_store_id (single) becomes sales_store_ids (JSONB list) so
--              invoices, revenue and margin can be aggregated across several
--              BackOffice stores. The old column is kept (unused) and its value
--              is carried into the new list.

ALTER TABLE business_overview_config
    ADD COLUMN IF NOT EXISTS sales_store_ids JSONB NOT NULL DEFAULT '[]'::jsonb;

UPDATE business_overview_config
   SET sales_store_ids = jsonb_build_array(sales_store_id)
 WHERE sales_store_id IS NOT NULL
   AND (sales_store_ids IS NULL OR sales_store_ids = '[]'::jsonb);
