-- Add list price tracking columns to price_update_history
ALTER TABLE price_update_history ADD COLUMN IF NOT EXISTS old_list_price NUMERIC(10,2);
ALTER TABLE price_update_history ADD COLUMN IF NOT EXISTS new_list_price NUMERIC(10,2);
