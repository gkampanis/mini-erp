import json,tempfile,unittest
from pathlib import Path
from app.application.service import ERP
from app.application.history_accounts import HistoryAccounts
from tests.fixtures import demos,workbook
from app.infrastructure.importers.excel import preview


class HistoryAccountTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.erp=ERP(self.root/'data');self.addCleanup(self.erp.close)
        self.company=self.erp.company('000000000','SYNTHETIC')
        demos(self.root/'input');self.erp.commit_import(self.company,preview(self.root/'input/separate.xlsx'),confirmed=True)
        self.cp=self.erp.search(self.company,'10000001')[0]['counterparty_id']
        with self.erp.db:self.erp.db.execute("UPDATE counterparties SET name='TEST CREDITOR',environment='production' WHERE id=?",(self.cp,))
        self.service=HistoryAccounts(self.erp)
    def packet(self,rows=None):
        path=self.root/'accounts.xlsx'
        workbook(path,[['Συν/νος','Ημ/νία','Παρ/κό','Δαπάνη','Περιγραφή'],*(rows or [['Test creditor','2026-09-01','TED1','64.03.0000',''],['TEST CREDITOR','2026-09-02','TED2','64.03.0000',''],['Test Creditor','2026-09-03','TED3','64.09.0000','']])])
        return self.service.preview(self.company,path)
    def choices(self,p):return [dict(key=p['rows'][0]['key'],card_id=self.cp,account=p['rows'][0]['account'])]
    def test_most_frequent_unique_reference_and_exact_name_preview(self):
        p=self.packet();row=p['rows'][0]
        self.assertEqual((row['card_id'],row['account'],row['frequency'],row['total']),(self.cp,'64.03.0000',2,3))
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM counterparty_accounts').fetchone()[0],0)
    def test_apply_updates_only_card_atomic_audited_and_does_not_reapply(self):
        p=self.packet();before=[tuple(r) for r in self.erp.db.execute('SELECT * FROM documents')]
        with self.assertRaises(ValueError):self.service.apply(p,self.choices(p))
        report=self.service.apply(p,self.choices(p),confirmed=True)
        self.assertEqual(report['updated'],1)
        self.assertEqual(self.erp.db.execute('SELECT expenses_account FROM counterparty_accounts WHERE counterparty_id=?',(self.cp,)).fetchone()[0],'64.03.0000')
        self.assertEqual([tuple(r) for r in self.erp.db.execute('SELECT * FROM documents')],before)
        doc=self.erp.search(self.company,'10000001')[0]['id']
        self.assertEqual(self.erp.preparation(self.company,doc)['account_code'],'64.03.0000')
        self.assertEqual(self.service.apply(p,self.choices(p),confirmed=True)['updated'],0)
    def test_ties_and_fuzzy_names_require_explicit_card_and_winner(self):
        p=self.packet([['TEST CREDITO','2026-09-01','A','64.03.0000',''],['TEST CREDITO','2026-09-02','B','64.09.0000','']]);row=p['rows'][0]
        self.assertIsNone(row['card_id']);self.assertIsNone(row['account'])
        self.assertIn(self.cp,[c['id'] for c in row['candidates']])
        with self.assertRaises(ValueError):self.service.apply(p,[dict(key=row['key'],card_id=self.cp,account='64.08.0000')],confirmed=True)
        self.assertEqual(self.service.apply(p,[dict(key=row['key'],card_id=self.cp,account='64.09.0000')],confirmed=True)['updated'],1)
    def test_duplicate_source_rows_do_not_change_most_frequent_invoice_account(self):
        p=self.packet([['TEST CREDITOR','','A','64.03.0000','']]*5+[['TEST CREDITOR','','B','64.09.0000',''],['TEST CREDITOR','','C','64.09.0000','']])
        self.assertEqual((p['rows'][0]['account'],p['rows'][0]['total']),('64.09.0000',3))

    def test_purchase_history_does_not_block_expense_preview_or_become_expense(self):
        p=self.packet([['TEST CREDITOR','','A','64.03.0000',''],['PURCHASE SOURCE','','B','25.05.00.0024','']])
        row=next(r for r in p['rows'] if r['source_name']=='PURCHASE SOURCE')
        self.assertTrue(row['excluded']);self.assertEqual(row['account'],'25.05.00.0024')
        with self.assertRaises(ValueError):self.service.apply(p,[dict(key=row['key'],card_id=self.cp,account=row['account'])],confirmed=True)
    def test_group2_and_other_company_cards_cannot_be_overwritten(self):
        from app.application.supplier_accounts import SupplierAccounts
        SupplierAccounts(self.erp).save(self.company,[self.cp],'2','20.01.0000',confirmed=True,classify_supplier=False)
        p=self.packet()
        with self.assertRaises(ValueError):self.service.apply(p,self.choices(p),confirmed=True)
        other=self.erp.company('000000009','OTHER');q=dict(p,company=other)
        with self.assertRaises(ValueError):self.service.apply(q,self.choices(p),confirmed=True)
    def test_failure_rolls_back_entire_batch_and_source_change_is_rejected(self):
        from unittest.mock import patch
        p=self.packet();q=dict(p,data=b'changed')
        with self.assertRaises(ValueError):self.service.apply(q,self.choices(p),confirmed=True)
        with patch.object(self.erp.repository,'audit',side_effect=RuntimeError('test')):
            with self.assertRaises(RuntimeError):self.service.apply(p,self.choices(p),confirmed=True)
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM counterparty_accounts').fetchone()[0],0)

    def test_registered_document_and_secondary_vat_rules_are_preserved(self):
        from app.application.ebs_reconciliation import EBSReconciliation
        from unittest.mock import patch
        doc=self.erp.search(self.company,'10000001')[0]['id']
        self.erp.prepare_document(self.company,doc,'6','64.08.0000',confirmed=True)
        before=dict(self.erp.preparation(self.company,doc))
        p=self.packet()
        with patch.object(EBSReconciliation,'results',return_value={doc:dict(status='registered')}):
            report=self.service.apply(p,self.choices(p),confirmed=True)
        self.assertEqual(self.erp.preparation(self.company,doc),before)
        self.assertIn(doc,report['protected'])
        self.assertEqual(report['updated'],1)

    def test_changed_card_and_duplicate_target_abort_before_any_batch_changes(self):
        from app.application.supplier_accounts import SupplierAccounts
        p=self.packet();choices=self.choices(p)
        SupplierAccounts(self.erp).save(self.company,[self.cp],'6','64.08.0000',confirmed=True,apply_pending=False,classify_supplier=False)
        with self.assertRaises(ValueError):self.service.apply(p,choices,confirmed=True)
        p=self.packet()
        with self.assertRaises(ValueError):self.service.apply(p,self.choices(p)*2,confirmed=True)
        self.assertEqual(self.erp.db.execute('SELECT expenses_account FROM counterparty_accounts WHERE counterparty_id=?',(self.cp,)).fetchone()[0],'64.08.0000')

    def test_previous_real_attempt_preserves_approval_and_payload(self):
        from app.application.rpa import RPA
        from tests.fixtures import reconcile_empty
        doc=self.erp.search(self.company,'10000001')[0]['id']
        self.erp.prepare_document(self.company,doc,'6','64.08.0000',confirmed=True)
        reconcile_empty(self.erp,self.company)
        job=RPA(self.erp).create(self.company,[doc],mode='simulation',confirmed=True)
        with self.erp.db:
            self.erp.db.execute("UPDATE rpa_jobs SET mode='fill_only',status='paused' WHERE id=?",(job,))
            self.erp.db.execute("UPDATE rpa_items SET status='uncertain' WHERE job_id=?",(job,))
        before=dict(self.erp.preparation(self.company,doc));item=dict(self.erp.db.execute('SELECT * FROM rpa_items WHERE job_id=?',(job,)).fetchone())
        p=self.packet();report=self.service.apply(p,self.choices(p),confirmed=True)
        self.assertEqual(self.erp.preparation(self.company,doc),before)
        self.assertEqual(dict(self.erp.db.execute('SELECT * FROM rpa_items WHERE job_id=?',(job,)).fetchone()),item)
        self.assertIn(doc,report['protected'])
