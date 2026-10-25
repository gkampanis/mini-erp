import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from app.application.service import ERP
from app.domain.validation import cents, iso_date
from app.infrastructure.database import backup
from app.infrastructure.importers.excel import preview
from tests.fixtures import workbook, demos, HEADERS, ROW


class SliceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        demos(self.root/'input')
        self.erp = ERP(self.root/'data')
        self.company = self.erp.company('000000000','ΣΥΝΘΕΤΙΚΗ ΕΤΑΙΡΕΙΑ')

    def tearDown(self):
        self.erp.close()
        self.tmp.cleanup()

    def item(self):
        return preview(self.root/'input/separate.xlsx')

    def test_two_layouts_persistence_search_detail(self):
        first = self.erp.commit_import(self.company,self.item(),confirmed=True)
        self.assertEqual((first['inserted'],len(first['rejected'])),(2,1))
        self.erp.commit_import(self.company,preview(self.root/'input/combined.xlsx'),confirmed=True)
        self.erp.close()
        self.erp = ERP(self.root/'data')
        self.assertEqual(len(self.erp.search(self.company)),3)
        found = self.erp.search(self.company,'000000001')[0]
        self.assertEqual((found['net_minor'],found['gross_minor']),(10,12))
        self.assertEqual(len(self.erp.search(self.company,'συνθετικοσ')),3)
        row, events = self.erp.detail(self.company,found['id'])
        self.assertEqual(row['series'],'ΔΟΚ')
        self.assertIn('000000001',row['raw_json'])
        self.assertEqual(events[0]['action'],'document_imported')
        self.assertEqual(hashlib.sha256((self.root/'data/sources'/ (row['sha256']+'.xlsx')).read_bytes()).hexdigest(),row['sha256'])
        combined = self.erp.search(self.company,'10000003')[0]
        self.assertEqual((combined['series'],combined['number']),('Γ','3'))

    def test_duplicate_and_conflict(self):
        self.erp.commit_import(self.company,self.item(),confirmed=True)
        again = self.erp.commit_import(self.company,self.item(),confirmed=True)
        self.assertEqual((again['inserted'],again['duplicates']),(0,2))
        changed = list(ROW); changed[5:8] = ['1','0,24','1,24']
        workbook(self.root/'conflict.xlsx',[HEADERS,changed])
        report = self.erp.commit_import(self.company,preview(self.root/'conflict.xlsx'),confirmed=True)
        self.assertEqual(report['inserted'],0)
        self.assertIn('Σύγκρουση',report['rejected'][0]['reason'])
        self.assertEqual(self.erp.search(self.company,'000000001')[0]['net_minor'],10)

    def test_interruption_rolls_back_and_retry(self):
        with self.assertRaises(RuntimeError):
            self.erp.commit_import(self.company,self.item(),confirmed=True,fail_after=0)
        self.erp.close()
        self.erp = ERP(self.root/'data')
        for table in ['documents','source_records','import_jobs','audit_events','counterparties']:
            self.assertEqual(self.erp.db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
        self.assertEqual(self.erp.commit_import(self.company,self.item(),confirmed=True)['inserted'],2)

    def test_approval_and_preview_tampering(self):
        with self.assertRaises(ValueError):self.erp.commit_import(self.company,self.item())
        item = self.item()
        item.records[0]['document']['net_minor'] = 999999
        self.erp.commit_import(self.company,item,confirmed=True)
        self.assertEqual(self.erp.search(self.company,'000000001')[0]['net_minor'],10)
        item.data += b'changed'
        with self.assertRaises(ValueError):self.erp.commit_import(self.company,item,confirmed=True)

    def test_immutable_sources_audit(self):
        self.erp.commit_import(self.company,self.item(),confirmed=True)
        for query in ['UPDATE source_records SET raw_json="x"','DELETE FROM source_records','DELETE FROM audit_events','UPDATE audit_events SET actor="x"']:
            with self.assertRaises(sqlite3.IntegrityError):
                with self.erp.db:self.erp.db.execute(query)

    def test_money_and_dates(self):
        self.assertEqual(cents('1.234,56'),123456)
        self.assertEqual(cents('1,234.56'),123456)
        for invalid in ['NaN','Infinity','','1e99']:
            with self.assertRaises(ValueError):cents(invalid)
        self.assertEqual(iso_date('1'), '1900-01-01')
        self.assertEqual(iso_date('0',True),'1904-01-01')
        with self.assertRaises(ValueError):iso_date('60')

    def test_formula_and_invalid_amounts(self):
        workbook(self.root/'formula.xlsx',[HEADERS,ROW],formula=True)
        self.assertIn('Τύπος',preview(self.root/'formula.xlsx').rejected[0]['reason'])
        for value in ['NaN','-10']:
            row = list(ROW); row[5] = value
            workbook(self.root/'bad.xlsx',[HEADERS,row])
            self.assertEqual(len(preview(self.root/'bad.xlsx').records),0)

    def test_manual_mapping_and_missing_headers(self):
        workbook(self.root/'unknown.xlsx',[['col'+str(i) for i in range(9)],ROW])
        item = preview(self.root/'unknown.xlsx')
        self.assertEqual(len(item.records),0)
        remap = preview(self.root/'unknown.xlsx',self.item().mapping)
        self.assertEqual(len(remap.records),1)
        with self.assertRaises(ValueError):preview(self.root/'unknown.xlsx',{'vat':999})

    def test_limits_and_xml_entities(self):
        with patch('app.infrastructure.importers.excel.MAX_EXPANDED',10):
            with self.assertRaises(ValueError):self.item()
        with patch('app.infrastructure.importers.excel.MAX_ROWS',1):
            with self.assertRaises(ValueError):self.item()
        with zipfile.ZipFile(self.root/'entity.xlsx','w') as z:
            z.writestr('xl/workbook.xml','<!DOCTYPE x [<!ENTITY a "b">]><x/>')
        with self.assertRaises(ValueError):preview(self.root/'entity.xlsx')

    def test_tenant_isolation(self):
        other = self.erp.company('000000009','ΑΛΛΗ ΣΥΝΘΕΤΙΚΗ')
        self.erp.commit_import(self.company,self.item(),confirmed=True)
        self.assertEqual(self.erp.search(other),[])
        with self.assertRaises(ValueError):self.erp.detail(other,1)
        self.assertEqual(self.erp.commit_import(other,self.item(),confirmed=True)['inserted'],2)

    def test_backup_and_migrations(self):
        self.erp.commit_import(self.company,self.item(),confirmed=True)
        backup(self.erp.db,self.root/'backup.sqlite3')
        with sqlite3.connect(self.root/'backup.sqlite3') as restored:
            self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(restored.execute('SELECT count(*) FROM documents').fetchone()[0],2)
        self.erp.close()
        self.erp = ERP(self.root/'data')
        self.assertEqual([r[0] for r in self.erp.db.execute('SELECT version FROM schema_migrations ORDER BY version')], ['001_initial.sql', '002_preparation.sql', '003_rounding.sql', '004_workspace.sql', '005_workflow.sql', '006_mydata_read.sql', '007_counterparty_cards.sql', '008_account_defaults.sql', '009_registry.sql', '010_aade_workflow.sql', '011_ebs_reconciliation.sql','012_matching_quality.sql','013_supplier_purchases.sql','014_supplier_previous_group.sql'])


class ProcessCrashTests(unittest.TestCase):
    def test_actual_process_exit_mid_transaction(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            demos(root/'input')
            script = '''import os,sys
from app.application.service import ERP
from app.infrastructure.importers.excel import preview
service=ERP(sys.argv[1])
company=service.company('000000000','SYNTHETIC')
original=service.repository.audit
def crash(*args,**kwargs):
    original(*args,**kwargs)
    os._exit(73)
service.repository.audit=crash
service.commit_import(company,preview(sys.argv[2]),confirmed=True)
'''
            result = subprocess.run([sys.executable,'-c',script,str(root/'data'),str(root/'input/separate.xlsx')],cwd=Path(__file__).resolve().parents[1])
            self.assertEqual(result.returncode,73)
            service = ERP(root/'data')
            try:
                self.assertEqual(service.search(1),[])
                self.assertEqual(service.db.execute('SELECT count(*) FROM import_jobs').fetchone()[0],0)
                self.assertEqual(service.commit_import(1,preview(root/'input/separate.xlsx'),confirmed=True)['inserted'],2)
            finally:
                service.close()

if __name__ == "__main__": unittest.main()
