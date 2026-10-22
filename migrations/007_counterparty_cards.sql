ALTER TABLE counterparties ADD COLUMN code TEXT;
UPDATE counterparties SET code='ΣΥΝ-'||printf('%06d',id);
CREATE UNIQUE INDEX counterparty_code ON counterparties(company_id,code);
CREATE TRIGGER counterparty_assign_code AFTER INSERT ON counterparties WHEN NEW.code IS NULL
BEGIN UPDATE counterparties SET code='ΣΥΝ-'||printf('%06d',NEW.id) WHERE id=NEW.id; END;
CREATE TRIGGER counterparty_code_fixed BEFORE UPDATE OF code ON counterparties WHEN OLD.code IS NOT NULL AND NEW.code IS NOT OLD.code
BEGIN SELECT RAISE(ABORT,'counterparty code is permanent'); END;
CREATE TABLE counterparty_roles(counterparty_id INTEGER NOT NULL REFERENCES counterparties(id),role TEXT NOT NULL CHECK(role IN ('supplier','creditor','customer')),PRIMARY KEY(counterparty_id,role));
INSERT INTO counterparty_roles(counterparty_id,role) SELECT id,CASE WHEN role IN ('supplier','creditor','customer') THEN role ELSE 'supplier' END FROM counterparties;
CREATE TRIGGER counterparty_initial_role AFTER INSERT ON counterparties
BEGIN INSERT INTO counterparty_roles(counterparty_id,role) VALUES (NEW.id,CASE WHEN NEW.role IN ('supplier','creditor','customer') THEN NEW.role ELSE 'supplier' END); END;
