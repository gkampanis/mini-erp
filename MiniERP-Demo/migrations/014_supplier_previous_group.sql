ALTER TABLE supplier_purchase_rules ADD COLUMN previous_group TEXT CHECK(previous_group IN ('2','6'));
