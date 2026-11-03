"""Synthetic document namespace regressions."""
import tempfile
import unittest
from pathlib import Path
from app.application.service import ERP
from app.infrastructure.importers.excel import preview
from tests.fixtures import workbook, HEADERS, ROW


class EnvironmentIsolationTests(unittest.TestCase):
    def test_same_invoice_has_separate_environment_identity_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            erp = ERP(Path(directory) / 'data')
            try:
                company = erp.company('000000000', 'Synthetic')
                path = Path(directory) / 'synthetic.xlsx'
                workbook(path, [HEADERS, ROW])
                packet = preview(path)
                checked = packet
                test = erp.repository.persist_import(company, packet, checked, environment='test')
                production = erp.repository.persist_import(company, packet, checked, environment='production')
                self.assertEqual((test['inserted'], production['inserted']), (1, 1))
                rows = erp.db.execute('SELECT id,environment,source_record_id FROM documents ORDER BY id').fetchall()
                self.assertEqual([r['environment'] for r in rows], ['test', 'production'])
                self.assertNotEqual(rows[0]['source_record_id'], rows[1]['source_record_id'])
                self.assertEqual([r['id'] for r in erp.search(company)], [rows[1]['id']])
                self.assertEqual([r['id'] for r in erp.search(company, environment='test')], [rows[0]['id']])
                self.assertEqual(erp.repository.persist_import(company, packet, checked)['duplicates'], 1)
                self.assertEqual(erp.db.execute('PRAGMA foreign_key_check').fetchall(), [])
                erp.db.execute("INSERT INTO document_preparations VALUES(?,?,'6','64','','Synthetic','2026-01-01')", (rows[0]['id'],company))
                from app.application.counterparties import Counterparties
                self.assertEqual(Counterparties(erp).list(company,environment='test')[0]['transaction_scope'], 'Έξοδα (6) → EBS')
                import sqlite3
                with self.assertRaises(sqlite3.IntegrityError):
                    erp.db.execute("UPDATE documents SET counterparty_id=(SELECT counterparty_id FROM documents WHERE environment='production') WHERE environment='test'")
            finally:
                erp.close()

    def test_populated_legacy_migration_retains_links_and_assigns_sync_environment(self):
        import sqlite3
        from app.infrastructure.database import MIGRATIONS, connect
        with tempfile.TemporaryDirectory() as directory:
            db = sqlite3.connect(Path(directory) / 'mini_erp.sqlite3')
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('CREATE TABLE schema_migrations(version TEXT PRIMARY KEY)')
            for migration in sorted(MIGRATIONS.glob('*.sql')):
                if migration.name >= '016': break
                db.executescript(migration.read_text())
                db.execute('INSERT INTO schema_migrations VALUES (?)', (migration.name,))
                db.commit()
            db.executescript("""
                INSERT INTO companies VALUES (1,'000000000','Synthetic');
                INSERT INTO counterparties(id,company_id,vat,name,role) VALUES (1,1,'000000001','Supplier','supplier');
                INSERT INTO counterparties(id,company_id,vat,name,role) VALUES (2,1,'000000002','Test only supplier','supplier');
                INSERT INTO account_mappings VALUES(1,2,'64.99','Synthetic');
                INSERT INTO counterparty_accounts(counterparty_id,company_id,expenses_account,preferred_group,approved_by) VALUES(2,1,'64.99','6','Synthetic');
                INSERT INTO import_jobs(id,company_id,filename,sha256,status,report) VALUES(1,1,'synthetic','hash','completed','{}');
                INSERT INTO mydata_syncs(id,company_id,environment,method,date_from,date_to,report) VALUES(1,1,'test','RequestDocs','2026-01-01','2026-01-01','{}');
                INSERT INTO counterparties(id,company_id,vat,name,role) VALUES(3,1,'900000030','Snapshot only incoming','supplier'),(4,1,'000000004','Snapshot only outgoing','customer'),(5,1,'000000005','Both snapshots','supplier');
                INSERT INTO account_mappings VALUES(1,3,'64.98','Synthetic');
                INSERT INTO supplier_purchase_rules VALUES(1,'000000002',1,7,'6');
                INSERT INTO supplier_purchase_rules VALUES(1,'900000030',1,8,'6');
                INSERT INTO mydata_syncs(id,company_id,environment,method,date_from,date_to,report) VALUES(2,1,'production','RequestDocs','2026-01-01','2026-01-01','{}');
                INSERT INTO mydata_records(company_id,environment,mark,record_json,match_status,last_sync) VALUES
                (1,'test','30','{"direction":"incoming","vat":"900000030"}','unmatched',1),
                (1,'test','40','{"direction":"outgoing","vat":"000000000","receiver":"000000004"}','unmatched',1),
                (1,'test','50','{"direction":"incoming","vat":"000000005"}','unmatched',1),
                (1,'production','50','{"direction":"incoming","vat":"000000005"}','unmatched',2);
                INSERT INTO source_records VALUES(1,1,1,'{"_source":"myDATA RequestDocs","_sync":1}');
                INSERT INTO source_records VALUES(2,1,2,'{}');
                INSERT INTO source_records VALUES(3,1,3,'{"_source":"myDATA RequestDocs","_sync":1}');
                INSERT INTO documents(id,company_id,counterparty_id,source_record_id,direction,kind,series,number,issue_date,mark,net_minor,tax_minor,gross_minor,currency) VALUES(1,1,1,1,'incoming','invoice','A','1','2026-01-01','1',100,24,124,'EUR'),(2,1,1,2,'incoming','invoice','A','2','2026-01-01','2',100,24,124,'EUR'),(3,1,2,3,'incoming','invoice','B','3','2026-01-01','3',100,24,124,'EUR');
                INSERT INTO attachments(id,company_id,document_id,kind,sha256,storage_path,original_filename) VALUES(1,1,1,'invoice','hash','synthetic.pdf','synthetic.pdf');
                INSERT INTO rpa_jobs(id,company_id,mode,status) VALUES(1,1,'simulation','queued');
                INSERT INTO rpa_items(id,job_id,document_id,payload) VALUES(1,1,1,'{}');
                INSERT INTO document_preparations VALUES(1,1,'6','64','note','Synthetic','2026-01-01');
                INSERT INTO document_purchase_tags VALUES(1,1,1);
            """)
            db.close()
            migrated = connect(directory)
            try:
                self.assertEqual([tuple(r) for r in migrated.execute('SELECT id,environment FROM documents ORDER BY id')], [(1,'test'),(2,'production'),(3,'test')])
                self.assertEqual(migrated.execute('SELECT environment FROM counterparties WHERE id=2').fetchone()[0], 'test')
                self.assertEqual(migrated.execute('SELECT counterparty_id FROM documents WHERE id=3').fetchone()[0], 2)
                self.assertEqual(migrated.execute("SELECT count(*) FROM counterparties WHERE vat='000000002' AND environment='production'").fetchone()[0], 0)
                self.assertEqual(migrated.execute("SELECT count(*) FROM account_mappings a JOIN counterparties c ON c.id=a.counterparty_id WHERE c.environment='production'").fetchone()[0], 0)
                self.assertEqual(migrated.execute('SELECT expenses_account FROM counterparty_accounts WHERE counterparty_id=2').fetchone()[0], '64.99')
                self.assertEqual([tuple(r) for r in migrated.execute('SELECT id,environment FROM counterparties WHERE id IN (3,4,5) ORDER BY id')], [(3,'test'),(4,'test'),(5,'production')])
                self.assertEqual(migrated.execute('SELECT account FROM account_mappings WHERE counterparty_id=3').fetchone()[0], '64.98')
                self.assertEqual(migrated.execute("SELECT count(*) FROM audit_events WHERE action='migration_environment_quarantined' AND json_extract(payload,'$.counterparty_id') IN (3,4)").fetchone()[0], 2)
                self.assertEqual([tuple(r) for r in migrated.execute('SELECT environment,enabled,version,previous_group FROM supplier_purchase_rules ORDER BY version')], [('test',1,7,'6'),('test',1,8,'6')])
                for table in ('attachments','rpa_items','document_preparations','document_purchase_tags'):
                    self.assertEqual(migrated.execute(f'SELECT document_id FROM {table}').fetchone()[0],1)
                self.assertEqual(migrated.execute('PRAGMA foreign_key_check').fetchall(), [])
                self.assertEqual(migrated.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                with self.assertRaises(sqlite3.IntegrityError):
                    migrated.execute("INSERT INTO document_preparations VALUES(2,999,'6','64','','Synthetic','2026-01-01')")
            finally:
                migrated.close()
            erp = ERP(directory)
            try:
                row = list(ROW);row[0] = '900000030';row[3] = 'fresh-production'
                path = Path(directory) / 'fresh.xlsx';workbook(path,[HEADERS,row])
                packet=preview(path);erp.repository.persist_import(1,packet,packet)
                document = erp.search(1, 'fresh-production')[0]['id']
                self.assertEqual(erp.db.execute('SELECT count(*) FROM document_purchase_tags WHERE document_id=?',(document,)).fetchone()[0],0)
                from app.application.supplier_purchases import SupplierPurchases
                SupplierPurchases(erp).set(1,'900000030',True)
                self.assertEqual([r[0] for r in erp.db.execute("SELECT environment FROM supplier_purchase_rules WHERE vat='900000030' ORDER BY environment")],['production','test'])
            finally:
                erp.close()
