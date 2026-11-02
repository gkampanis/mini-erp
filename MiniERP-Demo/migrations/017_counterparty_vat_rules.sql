CREATE UNIQUE INDEX counterparty_vat_scope ON counterparties(id,company_id,environment);
CREATE TABLE counterparty_vat_rules(
 company_id INTEGER NOT NULL REFERENCES companies(id),
 environment TEXT NOT NULL CHECK(environment IN ('production','test')),
 counterparty_id INTEGER NOT NULL,
 vat_category INTEGER NOT NULL CHECK(vat_category BETWEEN 1 AND 10),
 vat_exemption INTEGER NOT NULL DEFAULT 0 CHECK(vat_exemption>=0),
 use_primary INTEGER NOT NULL CHECK(use_primary IN (0,1)),
 account TEXT,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(company_id,environment,counterparty_id,vat_category,vat_exemption),
 FOREIGN KEY(counterparty_id,company_id,environment) REFERENCES counterparties(id,company_id,environment),
 CHECK((use_primary=1 AND account IS NULL) OR (use_primary=0 AND length(trim(account))>0))
);
