ALTER TABLE price_update_history ADD COLUMN IF NOT EXISTS old_delivery_b NUMERIC(10,2);
ALTER TABLE price_update_history ADD COLUMN IF NOT EXISTS new_delivery_b NUMERIC(10,2);
