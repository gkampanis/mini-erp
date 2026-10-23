-- Original AADE type remains independent of the local accounting group.
ALTER TABLE mydata_records ADD COLUMN invoice_type TEXT NOT NULL DEFAULT '';
ALTER TABLE mydata_records ADD COLUMN is_delivery_note INTEGER NOT NULL DEFAULT 0 CHECK(is_delivery_note IN (0,1));
UPDATE mydata_records SET invoice_type=coalesce(json_extract(record_json,'$.kind'),'');
CREATE INDEX mydata_document ON mydata_records(company_id,document_id,environment);

CREATE TABLE ebs_reconciliation_runs(
 id INTEGER PRIMARY KEY,company_id INTEGER NOT NULL REFERENCES companies(id),company_vat TEXT NOT NULL,
 date_from TEXT NOT NULL,date_to TEXT NOT NULL,filename TEXT NOT NULL,sha256 TEXT NOT NULL,storage_path TEXT NOT NULL,
 sheet TEXT NOT NULL,header_row INTEGER NOT NULL,mapping_json TEXT NOT NULL,complete INTEGER NOT NULL CHECK(complete IN (0,1)),
 report_json TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ebs_runs_period ON ebs_reconciliation_runs(company_id,date_from,date_to,id);
CREATE TABLE ebs_excel_rows(
 id INTEGER PRIMARY KEY,run_id INTEGER NOT NULL REFERENCES ebs_reconciliation_runs(id),row_number INTEGER NOT NULL,
 raw_json TEXT NOT NULL,normalized_json TEXT,error TEXT NOT NULL DEFAULT '',UNIQUE(run_id,row_number)
);
CREATE TABLE ebs_matches(
 id INTEGER PRIMARY KEY,run_id INTEGER NOT NULL REFERENCES ebs_reconciliation_runs(id),document_id INTEGER NOT NULL REFERENCES documents(id),
 status TEXT NOT NULL CHECK(status IN ('registered','not_registered','not_found','review')),reason TEXT NOT NULL,
 excel_rows_json TEXT NOT NULL,snapshot_hash TEXT NOT NULL,UNIQUE(run_id,document_id)
);
CREATE TABLE ebs_column_mappings(company_id INTEGER NOT NULL REFERENCES companies(id),layout_hash TEXT NOT NULL,sheet TEXT NOT NULL,header_row INTEGER NOT NULL,mapping_json TEXT NOT NULL,PRIMARY KEY(company_id,layout_hash));
ALTER TABLE rpa_jobs ADD COLUMN reconciled_only INTEGER NOT NULL DEFAULT 0 CHECK(reconciled_only IN (0,1));
CREATE TRIGGER ebs_run_no_update BEFORE UPDATE ON ebs_reconciliation_runs BEGIN SELECT RAISE(ABORT,'immutable reconciliation run'); END;
CREATE TRIGGER ebs_run_no_delete BEFORE DELETE ON ebs_reconciliation_runs BEGIN SELECT RAISE(ABORT,'immutable reconciliation run'); END;
CREATE TRIGGER ebs_rows_no_update BEFORE UPDATE ON ebs_excel_rows BEGIN SELECT RAISE(ABORT,'immutable Excel evidence'); END;
CREATE TRIGGER ebs_rows_no_delete BEFORE DELETE ON ebs_excel_rows BEGIN SELECT RAISE(ABORT,'immutable Excel evidence'); END;
CREATE TRIGGER ebs_matches_no_update BEFORE UPDATE ON ebs_matches BEGIN SELECT RAISE(ABORT,'immutable reconciliation result'); END;
CREATE TRIGGER ebs_matches_no_delete BEFORE DELETE ON ebs_matches BEGIN SELECT RAISE(ABORT,'immutable reconciliation result'); END;
CREATE TRIGGER ebs_match_company_insert BEFORE INSERT ON ebs_matches
WHEN NOT EXISTS(SELECT 1 FROM documents d JOIN ebs_reconciliation_runs r ON r.company_id=d.company_id WHERE d.id=NEW.document_id AND r.id=NEW.run_id)
BEGIN SELECT RAISE(ABORT,'reconciliation company mismatch'); END;
