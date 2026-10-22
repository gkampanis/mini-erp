-- Preserve document IDs, raw source, approvals and audits in one migration transaction.
CREATE TABLE documents_rounded(id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id), counterparty_id INTEGER NOT NULL REFERENCES counterparties(id), source_record_id INTEGER NOT NULL REFERENCES source_records(id), direction TEXT NOT NULL CHECK(direction IN ('incoming','outgoing')), kind TEXT NOT NULL, series TEXT NOT NULL, number TEXT NOT NULL, issue_date TEXT NOT NULL, mark TEXT, net_minor INTEGER NOT NULL CHECK(typeof(net_minor)='integer'), tax_minor INTEGER NOT NULL CHECK(typeof(tax_minor)='integer'), gross_minor INTEGER NOT NULL CHECK(typeof(gross_minor)='integer' AND gross_minor=net_minor+tax_minor+rounding_minor), rounding_minor INTEGER NOT NULL DEFAULT 0 CHECK(typeof(rounding_minor)='integer' AND abs(rounding_minor)<=1), currency TEXT NOT NULL CHECK(currency='EUR'), status TEXT NOT NULL DEFAULT 'needs_review', UNIQUE(company_id,counterparty_id,direction,kind,series,number,issue_date));
INSERT INTO documents_rounded(id,company_id,counterparty_id,source_record_id,direction,kind,series,number,issue_date,mark,net_minor,tax_minor,gross_minor,currency,status,rounding_minor) SELECT id,company_id,counterparty_id,source_record_id,direction,kind,series,number,issue_date,mark,net_minor,tax_minor,gross_minor,currency,status,0 FROM documents;
CREATE TABLE preparation_backup AS SELECT * FROM document_preparations;
DROP TABLE document_preparations;
DROP TABLE documents;
ALTER TABLE documents_rounded RENAME TO documents;
CREATE UNIQUE INDEX documents_mark ON documents(company_id,mark) WHERE mark IS NOT NULL;
CREATE INDEX documents_date ON documents(company_id,issue_date);
CREATE INDEX documents_counterparty ON documents(company_id,counterparty_id);
-- User-owned local decisions are separate from immutable imported document data.
CREATE TABLE document_preparations (
    document_id INTEGER PRIMARY KEY REFERENCES documents(id),
    company_id INTEGER NOT NULL REFERENCES companies(id),
    nature_group TEXT NOT NULL CHECK(nature_group IN ('2','6')),
    account_code TEXT NOT NULL CHECK(length(account_code) BETWEEN 1 AND 40 AND substr(account_code,1,1)=nature_group),
    note TEXT NOT NULL DEFAULT '' CHECK(length(note)<=2000),
    approved_by TEXT NOT NULL CHECK(length(trim(approved_by)) BETWEEN 1 AND 128),
    approved_at TEXT NOT NULL
);
CREATE INDEX preparation_company ON document_preparations(company_id,nature_group);
CREATE TRIGGER preparation_company_insert BEFORE INSERT ON document_preparations
WHEN NOT EXISTS (SELECT 1 FROM documents WHERE id=NEW.document_id AND company_id=NEW.company_id)
BEGIN SELECT RAISE(ABORT,'document company mismatch'); END;
CREATE TRIGGER preparation_company_update BEFORE UPDATE ON document_preparations
WHEN NOT EXISTS (SELECT 1 FROM documents WHERE id=NEW.document_id AND company_id=NEW.company_id)
BEGIN SELECT RAISE(ABORT,'document company mismatch'); END;

INSERT INTO document_preparations SELECT * FROM preparation_backup;
DROP TABLE preparation_backup;
