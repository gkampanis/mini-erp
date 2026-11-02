-- Keep every document ID and all dependent rows. Legacy Excel belongs to production.
PRAGMA legacy_alter_table=ON;
CREATE TABLE counterparties_isolated(id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id), vat TEXT NOT NULL CHECK(length(vat)=9), name TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'supplier', code TEXT, environment TEXT NOT NULL DEFAULT 'production' CHECK(environment IN ('test','production')), UNIQUE(company_id,environment,vat));
INSERT INTO counterparties_isolated SELECT *, 'production' FROM counterparties;
DROP TABLE counterparties;
ALTER TABLE counterparties_isolated RENAME TO counterparties;
CREATE UNIQUE INDEX counterparty_code ON counterparties(company_id,code);
CREATE TRIGGER counterparty_assign_code AFTER INSERT ON counterparties WHEN NEW.code IS NULL
BEGIN UPDATE counterparties SET code='ΣΥΝ-'||printf('%06d',NEW.id) WHERE id=NEW.id; END;
CREATE TRIGGER counterparty_code_fixed BEFORE UPDATE OF code ON counterparties WHEN OLD.code IS NOT NULL AND NEW.code IS NOT OLD.code
BEGIN SELECT RAISE(ABORT,'counterparty code is permanent'); END;
CREATE TRIGGER counterparty_initial_role AFTER INSERT ON counterparties
BEGIN INSERT INTO counterparty_roles(counterparty_id,role) VALUES (NEW.id,CASE WHEN NEW.role IN ('supplier','creditor','customer') THEN NEW.role ELSE 'supplier' END); END;
CREATE TABLE documents_isolated(id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id), counterparty_id INTEGER NOT NULL REFERENCES counterparties(id), source_record_id INTEGER NOT NULL REFERENCES source_records(id), direction TEXT NOT NULL CHECK(direction IN ('incoming','outgoing')), kind TEXT NOT NULL, series TEXT NOT NULL, number TEXT NOT NULL, issue_date TEXT NOT NULL, mark TEXT, net_minor INTEGER NOT NULL CHECK(typeof(net_minor)='integer'), tax_minor INTEGER NOT NULL CHECK(typeof(tax_minor)='integer'), gross_minor INTEGER NOT NULL CHECK(typeof(gross_minor)='integer' AND gross_minor=net_minor+tax_minor+rounding_minor), rounding_minor INTEGER NOT NULL DEFAULT 0 CHECK(typeof(rounding_minor)='integer' AND abs(rounding_minor)<=1), currency TEXT NOT NULL CHECK(currency='EUR'), status TEXT NOT NULL DEFAULT 'needs_review', environment TEXT NOT NULL DEFAULT 'production' CHECK(environment IN ('test','production')), UNIQUE(company_id,environment,counterparty_id,direction,kind,series,number,issue_date));
INSERT INTO documents_isolated SELECT d.*, COALESCE((SELECT s.environment FROM source_records r JOIN mydata_syncs s ON s.id=json_extract(r.raw_json,'$._sync') WHERE r.id=d.source_record_id AND json_extract(r.raw_json,'$._source') LIKE 'myDATA %' AND s.company_id=d.company_id),'production') FROM documents d;
DROP TABLE documents;
ALTER TABLE documents_isolated RENAME TO documents;
-- Quarantine test-only historical evidence, keeping original IDs/defaults/code.
-- Snapshot-only creation provenance is ambiguous; test quarantine avoids promotion.
CREATE TEMP TABLE migration_test_cards AS
SELECT c.id,c.company_id,
 CASE WHEN EXISTS(SELECT 1 FROM documents d WHERE d.counterparty_id=c.id) THEN 'test_documents_only' ELSE 'test_snapshots_only_ambiguous_creation' END AS reason
FROM counterparties c
WHERE (
 EXISTS(SELECT 1 FROM documents d WHERE d.counterparty_id=c.id AND d.environment='test')
 OR EXISTS(SELECT 1 FROM mydata_records m WHERE m.company_id=c.company_id AND m.environment='test'
 AND CASE json_extract(m.record_json,'$.direction') WHEN 'incoming' THEN json_extract(m.record_json,'$.vat') WHEN 'outgoing' THEN json_extract(m.record_json,'$.receiver') END=c.vat)
)
AND NOT EXISTS(SELECT 1 FROM documents d WHERE d.counterparty_id=c.id AND d.environment='production')
AND NOT EXISTS(SELECT 1 FROM mydata_records m WHERE m.company_id=c.company_id AND m.environment='production'
 AND CASE json_extract(m.record_json,'$.direction') WHEN 'incoming' THEN json_extract(m.record_json,'$.vat') WHEN 'outgoing' THEN json_extract(m.record_json,'$.receiver') END=c.vat);
UPDATE counterparties SET environment='test' WHERE id IN (SELECT id FROM migration_test_cards);
INSERT INTO audit_events(company_id,actor,action,entity_id,payload)
SELECT company_id,'migration016','migration_environment_quarantined',NULL,json_object('counterparty_id',id,'environment','test','reason',reason) FROM migration_test_cards;
-- Keep quarantined suppliers' future-import rules in the same namespace.
CREATE TABLE supplier_purchase_rules_isolated(company_id INTEGER NOT NULL REFERENCES companies(id),environment TEXT NOT NULL DEFAULT 'production' CHECK(environment IN ('test','production')),vat TEXT NOT NULL CHECK(length(vat)=9),enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),version INTEGER NOT NULL DEFAULT 1,previous_group TEXT CHECK(previous_group IN ('2','6')),PRIMARY KEY(company_id,environment,vat));
INSERT INTO supplier_purchase_rules_isolated SELECT r.company_id,CASE WHEN EXISTS(SELECT 1 FROM migration_test_cards q JOIN counterparties c ON c.id=q.id WHERE q.company_id=r.company_id AND c.vat=r.vat) THEN 'test' ELSE 'production' END,r.vat,r.enabled,r.version,r.previous_group FROM supplier_purchase_rules r;
DROP TABLE supplier_purchase_rules;
ALTER TABLE supplier_purchase_rules_isolated RENAME TO supplier_purchase_rules;
DROP TABLE migration_test_cards;
-- Only mixed cards need a separate test card; production defaults stay on their original card.
INSERT INTO counterparties(company_id,vat,name,role,environment) SELECT DISTINCT c.company_id,c.vat,c.name,c.role,'test' FROM counterparties c JOIN documents d ON d.counterparty_id=c.id WHERE d.environment='test' AND c.environment='production';
UPDATE documents SET counterparty_id=(SELECT t.id FROM counterparties p JOIN counterparties t ON t.company_id=p.company_id AND t.vat=p.vat AND t.environment='test' WHERE p.id=documents.counterparty_id) WHERE environment='test';
CREATE UNIQUE INDEX documents_mark ON documents(company_id,environment,mark) WHERE mark IS NOT NULL;
CREATE INDEX documents_date ON documents(company_id,issue_date);
CREATE INDEX documents_counterparty ON documents(company_id,counterparty_id);
ALTER TABLE import_jobs ADD COLUMN environment TEXT NOT NULL DEFAULT 'production' CHECK(environment IN ('test','production'));
UPDATE import_jobs SET environment='test' WHERE
 EXISTS(SELECT 1 FROM source_records r JOIN mydata_syncs s ON s.id=json_extract(r.raw_json,'$._sync') AND s.company_id=import_jobs.company_id WHERE r.job_id=import_jobs.id AND s.environment='test')
 AND NOT EXISTS(SELECT 1 FROM source_records r JOIN documents d ON d.source_record_id=r.id WHERE r.job_id=import_jobs.id AND d.environment='production');
-- Old cross-environment links are invalid; leave the original record for explicit reconciliation.
UPDATE mydata_records SET document_id=NULL,match_status='unmatched' WHERE document_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM documents d WHERE d.id=mydata_records.document_id AND d.company_id=mydata_records.company_id AND d.environment=mydata_records.environment);
PRAGMA legacy_alter_table=OFF;
-- Documents and cards must share both tenant and environment, including direct writes.
CREATE TRIGGER document_environment_insert BEFORE INSERT ON documents
WHEN NOT EXISTS(SELECT 1 FROM counterparties c WHERE c.id=NEW.counterparty_id AND c.company_id=NEW.company_id AND c.environment=NEW.environment)
BEGIN SELECT RAISE(ABORT,'document counterparty environment mismatch'); END;
CREATE TRIGGER document_environment_update BEFORE UPDATE OF company_id,counterparty_id,environment ON documents
WHEN NOT EXISTS(SELECT 1 FROM counterparties c WHERE c.id=NEW.counterparty_id AND c.company_id=NEW.company_id AND c.environment=NEW.environment)
BEGIN SELECT RAISE(ABORT,'document counterparty environment mismatch'); END;
