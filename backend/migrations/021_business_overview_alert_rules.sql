-- Migration: Business Overview — alert rules / thresholds
-- Version: 021
-- Date: 2026-08-18
-- Description: JSONB of per-rule settings (enabled + thresholds) for the
--              "Attention" strip on the Overview. Defaults live in code and are
--              merged over this object, so new rules appear automatically.

ALTER TABLE business_overview_config
    ADD COLUMN IF NOT EXISTS alert_rules JSONB NOT NULL DEFAULT '{}'::jsonb;
