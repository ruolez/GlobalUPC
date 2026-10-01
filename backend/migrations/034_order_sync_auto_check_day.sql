-- Migration: Order Sync automation — which day a scheduled run checks
-- Version: 034
-- Date: 2026-10-01
-- Description: A scheduled run used to always reconcile the day before it
--              runs. `check_day` makes that a choice: 'previous' (the old
--              behaviour, still the default) or 'same' (an evening run checks
--              its own day).

ALTER TABLE order_sync_auto_config
    ADD COLUMN IF NOT EXISTS check_day VARCHAR(8) NOT NULL DEFAULT 'previous';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'order_sync_auto_config_check_day_chk'
    ) THEN
        ALTER TABLE order_sync_auto_config
            ADD CONSTRAINT order_sync_auto_config_check_day_chk
            CHECK (check_day IN ('previous', 'same'));
    END IF;
END $$;
