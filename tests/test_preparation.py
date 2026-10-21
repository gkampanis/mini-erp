"""Explicit local decisions and persisted review feedback; no EBS automation."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from app.application.service import ERP
from app.infrastructure.importers.excel import preview
from tests.fixtures import demos, workbook, HEADERS, ROW


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        demos(self.root/'input')
        self.erp = ERP(self.root/'data')
        self.company = self.erp.company('000000000','ΣΥΝΘΕΤΙΚΗ ΕΤΑΙΡΕΙΑ')
        self.erp.commit_import(self.company,preview(self.root/'input/separate.xlsx'),confirmed=True)
        self.document = self.erp.search(self.company,'000000001')[0]['id']

    def tearDown(self):
        self.erp.close()
        self.temp.cleanup()

    def prepare(self, **kwargs):
        values = dict(group='6',account_code='64.03.00.0024',note='Έλεγχος συνθετικού παραστατικού',actor='operator_test',confirmed=True)
        values.update(kwargs)
        return self.erp.prepare_document(self.company,self.document,**values)

    def events(self):
        return self.erp.db.execute("SELECT * FROM audit_events WHERE action='document_prepared' ORDER BY id").fetchall()

    def test_explicit_confirmation_and_validation_are_required(self):
        for invalid in [dict(confirmed=False),dict(confirmed=1),dict(group='3'),dict(actor='  '),
                        dict(account_code='20.00'),dict(account_code='64..03'),dict(account_code='64; DROP'),
                        dict(account_code='٦4.03'),dict(account_code='6'*41),dict(note='x'*2001)]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):self.prepare(**invalid)
        self.assertIsNone(self.erp.preparation(self.company,self.document))
        self.assertEqual(len(self.events()),0)

    def test_prepare_is_separate_from_original_and_persists(self):
        before,_ = self.erp.detail(self.company,self.document)
        result = self.prepare()
        after,_ = self.erp.detail(self.company,self.document)
        self.assertEqual(before,after)
        self.assertEqual(after['status'],'needs_review')
        self.assertEqual(result['nature_group'],'6')
        self.assertEqual(result['approved_by'],'operator_test')
        self.assertTrue(result['approved_at'].endswith('Z'))
        row = self.erp.search(self.company,'000000001')[0]
        self.assertEqual((row['nature_group'],row['account_code']),('6','64.03.00.0024'))
        self.erp.close()
        self.erp = ERP(self.root/'data')
        self.assertEqual(self.erp.preparation(self.company,self.document),result)

    def test_reapproval_records_before_after_without_supplier_auto_mapping(self):
        initial = self.prepare()
        revised = self.prepare(group='2',account_code='20.01',actor='second_operator')
        self.assertEqual(len(self.events()),2)
        history = json.loads(self.events()[1]['payload'])
        self.assertEqual(history['before'],initial)
        self.assertEqual(history['after'],revised)
        self.assertEqual(self.events()[1]['actor'],'second_operator')
        other_document = self.erp.search(self.company,'000000002')[0]['id']
        self.assertIsNone(self.erp.preparation(self.company,other_document))
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM account_mappings').fetchone()[0],0)

    def test_tenant_and_missing_document_rejected(self):
        other = self.erp.company('000000009','ΑΛΛΗ ΣΥΝΘΕΤΙΚΗ ΕΤΑΙΡΕΙΑ')
        for company,document in [(other,self.document),(self.company,9999)]:
            with self.assertRaises(ValueError):self.erp.preparation(company,document)
            with self.assertRaises(ValueError):self.erp.prepare_document(company,document,'6','64.03',confirmed=True)
        self.assertEqual(len(self.events()),0)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.erp.db:
                self.erp.db.execute("INSERT INTO document_preparations VALUES (?,?, '6','64.03','','x','now')",(self.document,other))

    def test_preparation_and_audit_rollback_together(self):
        with patch.object(self.erp.repository,'audit',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):self.prepare()
        self.assertIsNone(self.erp.preparation(self.company,self.document))
        self.assertEqual(len(self.events()),0)
        initial = self.prepare()
        with patch.object(self.erp.repository,'audit',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):self.prepare(group='2',account_code='20.01')
        self.assertEqual(self.erp.preparation(self.company,self.document),initial)
        self.assertEqual(len(self.events()),1)

    def test_import_reviews_include_persisted_rejections_and_duplicates(self):
        self.erp.commit_import(self.company,preview(self.root/'input/separate.xlsx'),confirmed=True)
        reviews = self.erp.import_reviews(self.company)
        self.assertEqual(len(reviews),2)
        self.assertGreater(reviews[0]['id'],reviews[1]['id'])
        latest = reviews[0]
        self.assertEqual((latest['inserted_count'],latest['duplicate_count'],latest['rejected_count'],latest['warning_count']),(0,2,1,0))
        self.assertEqual(latest['report']['rejected'][0]['row'],4)
        self.assertEqual(len(latest['sha256']),64)
        other = self.erp.company('000000009','ΑΛΛΗ ΣΥΝΘΕΤΙΚΗ ΕΤΑΙΡΕΙΑ')
        self.assertEqual(self.erp.import_reviews(other),[])

    def test_same_year_reference_warning_does_not_reject_or_merge(self):
        changed = list(ROW)
        changed[2] = changed[2].lower()  # conservative Unicode casefold comparison
        changed[4] = '22/10/2026'
        changed[8] = '20000001'
        workbook(self.root/'later.xlsx',[HEADERS,changed])
        result = self.erp.commit_import(self.company,preview(self.root/'later.xlsx'),confirmed=True)
        self.assertEqual((result['inserted'],result['duplicates'],len(result['rejected'])),(1,0,0))
        self.assertEqual(len(result['warnings']),1)
        self.assertEqual(result['warnings'][0]['related_document_ids'],[self.document])
        self.assertEqual(self.erp.import_reviews(self.company)[0]['warning_count'],1)
        self.assertEqual(len(self.erp.search(self.company,'000000001')),2)
        changed[4] = '22/10/2027'
        changed[8] = '20000002'
        workbook(self.root/'next_year.xlsx',[HEADERS,changed])
        result = self.erp.commit_import(self.company,preview(self.root/'next_year.xlsx'),confirmed=True)
        self.assertEqual((result['inserted'],result['warnings']),(1,[]))

    def test_upgrade_preserves_imported_data(self):
        # Simulate a previously prepared 001 database, then apply 002 on reopen.
        original,_ = self.erp.detail(self.company,self.document)
        with self.erp.db:
            self.erp.db.execute('DROP TABLE document_preparations')
            self.erp.db.execute("DELETE FROM schema_migrations WHERE version='002_preparation.sql'")
        self.erp.close()
        self.erp = ERP(self.root/'data')
        after,_ = self.erp.detail(self.company,self.document)
        self.assertEqual(original,after)
        self.assertIsNone(self.erp.preparation(self.company,self.document))
        self.assertEqual(self.erp.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')


if __name__=='__main__':unittest.main()
