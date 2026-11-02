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
