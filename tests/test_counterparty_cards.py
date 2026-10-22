"""One stable card per company/VAT, with roles independent of accounting group."""
import json
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from app.application.service import ERP
from app.application.counterparties import Counterparties
from app.application.workspace import Workspace
from app.application.mydata import MyData
from app.infrastructure.aade.client import parsed_page
from app.infrastructure.importers.excel import preview
from tests.fixtures import demos,workbook,HEADERS,ROW
from tests.test_workflow import response


class CounterpartyCardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.erp=ERP(self.root/'data')
        self.company=self.erp.company('000000000','ΣΥΝΘΕΤΙΚΗ');demos(self.root/'input');self.erp.commit_import(self.company,preview(self.root/'input/separate.xlsx'),confirmed=True)
        self.service=Counterparties(self.erp)
    def tearDown(self):self.erp.close();self.temp.cleanup()

    def test_code_unique_stable_across_import_and_reopen(self):
        cards=self.service.list(self.company);before={r['vat']:r['code'] for r in cards}
        self.assertEqual(len(set(before.values())),2);self.assertTrue(all(c.startswith('ΣΥΝ-') for c in before.values()))
        self.erp.commit_import(self.company,preview(self.root/'input/separate.xlsx'),confirmed=True)
        self.assertEqual({r['vat']:r['code'] for r in self.service.list(self.company)},before)
        self.erp.close();self.erp=ERP(self.root/'data');self.service=Counterparties(self.erp)
        self.assertEqual({r['vat']:r['code'] for r in self.service.list(self.company)},before)
        with self.assertRaises(sqlite3.IntegrityError),self.erp.db:self.erp.db.execute("UPDATE counterparties SET code='OTHER' WHERE id=?",(cards[0]['id'],))

    def test_same_vat_separate_company_and_tenant_checks(self):
        other=self.erp.company('000000009','ΑΛΛΗ');self.erp.commit_import(other,preview(self.root/'input/separate.xlsx'),confirmed=True)
        first=self.service.list(self.company)[0];second=self.service.list(other)[0]
        self.assertEqual(first['vat'],second['vat']);self.assertNotEqual(first['code'],second['code'])
        with self.assertRaises(ValueError):self.service.detail(other,first['id'])
        with self.assertRaises(ValueError):self.service.save(other,first['id'],'bad',['supplier'],confirmed=True)

    def test_roles_and_name_change_do_not_reclassify_or_duplicate_documents(self):
        card=self.service.list(self.company)[0];docs=self.service.detail(self.company,card['id'])[1]
        self.erp.prepare_document(self.company,docs[0]['id'],'2','20.01',confirmed=True)
        updated=self.service.save(self.company,card['id'],'ΝΕΑ ΕΠΩΝΥΜΙΑ',['supplier','creditor'],confirmed=True)
        self.assertEqual(updated['code'],card['code']);self.assertEqual(updated['vat'],card['vat'])
        self.assertEqual(set(updated['roles']),{'supplier','creditor'})
        self.assertEqual(self.erp.search(self.company,card['vat'])[0]['name'],'ΝΕΑ ΕΠΩΝΥΜΙΑ')
        self.assertEqual(self.erp.preparation(self.company,docs[0]['id'])['nature_group'],'2')
        self.assertEqual(len(self.service.detail(self.company,card['id'])[1]),len(docs))
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM account_mappings').fetchone()[0],0)

    def test_edit_and_audit_rollback_together(self):
        card=self.service.list(self.company)[0]
        with patch.object(self.erp.repository,'audit',side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):self.service.save(self.company,card['id'],'CHANGED',['creditor'],confirmed=True)
        self.assertEqual(self.service.detail(self.company,card['id'])[0]['name'],card['name'])
        with self.assertRaises(ValueError):self.service.save(self.company,card['id'],'CHANGED',['creditor'])

    def test_issued_aade_document_creates_customer_card_without_duplicate_excel(self):
        raw=response(mark='80000001',issuer='000000000',receiver='000000008')
        MyData(self.erp).persist(self.company,'production','2026-10-01','2026-10-31',[(raw,parsed_page(raw))],method='RequestTransmittedDocs')
        card=self.service.list(self.company,'000000008')[0]
        self.assertIn('customer',card['roles']);self.assertTrue(card['code']);self.assertEqual(card['document_count'],0)
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM documents').fetchone()[0],2)

    def test_defaults_reappear_for_new_invoice_without_auto_approval(self):
        from tests.fixtures import ROW,HEADERS,workbook
        card=self.service.list(self.company,'000000001')[0]
        self.service.save(self.company,card['id'],card['name'],['supplier','creditor'],confirmed=True,accounts=dict(purchases_account='20.01',expenses_account='64.03',preferred_group='6'))
        row=list(ROW);row[3]='NEXT';row[8]='93000001';workbook(self.root/'next.xlsx',[HEADERS,row])
        self.erp.commit_import(self.company,preview(self.root/'next.xlsx'),confirmed=True)
        new=next(r for r in Workspace(self.erp).rows(self.company) if r['number']=='NEXT')
        self.assertEqual((new['suggested_group'],new['suggested_account']),('6','64.03'))
        self.assertIsNone(self.erp.preparation(self.company,new['id']))
        self.assertEqual(self.service.detail(self.company,card['id'])[0]['accounts']['purchases_account'],'20.01')

    def test_account_group_mismatch_does_not_partially_update_card(self):
        card=self.service.list(self.company)[0]
        with self.assertRaises(ValueError):self.service.save(self.company,card['id'],'WRONG',['creditor'],confirmed=True,accounts=dict(purchases_account='64.03',expenses_account='',preferred_group='2'))
        self.assertEqual(self.service.detail(self.company,card['id'])[0]['name'],card['name'])
