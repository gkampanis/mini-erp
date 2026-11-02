"""Synthetic regressions for queues excluded before any EBS input."""
import unittest
from types import SimpleNamespace
from tests import test_supplier_purchases as purchase_tests
from app.application.rpa import RPA
from app.application.supplier_accounts import SupplierAccounts
from app.application.ebs_reconciliation import EBSReconciliation
from app.ui.rpa_panel import RPAPanel
from tests.fixtures import reconcile_empty
from tests.test_workflow import FakeEBS


class PurchaseAttemptTests(unittest.TestCase):
    setUp=purchase_tests.PurchaseTests.setUp
    tearDown=purchase_tests.PurchaseTests.tearDown
    add=purchase_tests.PurchaseTests.add

    def excluded(self):
        reconcile_empty(self.erp,self.company)
        self.ids=[r['id'] for r in self.erp.search(self.company)]
        for document in self.ids:self.erp.prepare_document(self.company,document,'6','64.03',confirmed=True)
        self.rpa=RPA(self.erp)
        self.job=self.rpa.create(self.company,self.ids,mode='fill_only',confirmed=True)
        self.service.set(self.company,self.supplier,True)

    def test_undo_exclusion_can_prepare_and_create_fresh_queue_without_rearming_history(self):
        self.excluded()
        history=[tuple(r) for r in self.erp.db.execute('SELECT * FROM rpa_items')]
        result=self.service.set(self.company,self.supplier,False)
        self.assertEqual(result['changed'],2)
        self.assertEqual(result['exceptions'],[])
        states=EBSReconciliation(self.erp).results(self.company)
        self.assertTrue(all(states[d]['status']=='not_registered' for d in self.ids))
        cp=self.erp.search(self.company)[0]['counterparty_id']
        report=SupplierAccounts(self.erp).save(self.company,[cp],'6','64.09',confirmed=True)
        self.assertEqual(report['updated'],2)
        self.assertEqual(report['protected'],[])
        self.assertEqual([tuple(r) for r in self.erp.db.execute('SELECT * FROM rpa_items')],history)
        fake=FakeEBS()
        self.rpa.advance(self.company,self.job,adapter=fake,live_confirmed=True)
        self.assertEqual(fake.calls,[])
        self.assertEqual([tuple(r) for r in self.erp.db.execute('SELECT * FROM rpa_items')],history)
        fresh=self.rpa.create(self.company,self.ids,mode='fill_only',confirmed=True)
        self.assertNotEqual(fresh,self.job)
        self.assertTrue(all(i['status']=='queued' for i in self.rpa.items(self.company,fresh)[1]))
        self.assertTrue(all(i['status']=='excluded_purchase' for i in self.rpa.items(self.company,self.job)[1]))

    def test_excluded_queue_does_not_protect_pending_account_approval(self):
        self.excluded()
        self.service.set(self.company,self.supplier,False)
        cp=self.erp.search(self.company)[0]['counterparty_id']
        report=SupplierAccounts(self.erp).save(self.company,[cp],'6','64.09',confirmed=True)
        self.assertEqual(report['updated'],2)
        self.assertEqual(report['protected'],[])

    def test_pending_panel_scope_keeps_pre_input_exclusions(self):
        self.excluded()
        panel=object.__new__(RPAPanel)
        panel.owner=SimpleNamespace(erp=self.erp,company=self.company,
            tree=SimpleNamespace(get_children=lambda:[str(d) for d in self.ids],selection=lambda:()),
            _documents={r['id']:r for r in self.erp.search(self.company)})
        panel.scope=SimpleNamespace(get=lambda:'Εκκρεμή προς EBS')
        self.assertEqual(panel.ids(),sorted(self.ids,key=lambda d:panel.owner._documents[d]['source_record_id']))

    def test_real_attempt_states_remain_protected(self):
        self.excluded()
        for status in ('started','save_pending','uncertain','filled_no_save','save_invoked','ui_saved_review','reviewed_by_operator'):
            with self.subTest(status=status):
                with self.erp.db:
                    self.erp.db.execute('UPDATE rpa_items SET status=? WHERE job_id=?',(status,self.job))
                result=self.service.set(self.company,self.supplier,False)
                self.assertEqual(result['changed'],0)
                self.assertEqual(len(result['exceptions']),2)
                self.assertTrue(all(EBSReconciliation(self.erp).results(self.company)[d]['match_kind']=='attempt' for d in self.ids))
                # Restore synthetic pre-input rows only to isolate each state case.
                with self.erp.db:self.erp.db.execute("UPDATE rpa_items SET status='excluded_purchase'")

    def test_undo_pre_input_exclusion_while_other_supplier_runs_same_job(self):
        supplier=self.supplier
        self.supplier=purchase_tests.synthetic_vat(2)
        other=self.add('3','2026-10-21')
        self.supplier=supplier
        reconcile_empty(self.erp,self.company)
        ids=[r['id'] for r in self.erp.search(self.company)]
        for document in ids:self.erp.prepare_document(self.company,document,'6','64.03',confirmed=True)
        rpa=RPA(self.erp)
        job=rpa.create(self.company,ids,mode='fill_only',confirmed=True)
        self.service.set(self.company,supplier,True)
        with self.erp.db:
            self.erp.db.execute("UPDATE rpa_jobs SET status='running' WHERE id=?",(job,))
            self.erp.db.execute("UPDATE rpa_items SET status='started' WHERE job_id=? AND document_id=?",(job,other))
        history=[tuple(r) for r in self.erp.db.execute('SELECT * FROM rpa_items ORDER BY id')]
        result=self.service.set(self.company,supplier,False)
        self.assertEqual(result['changed'],2)
        self.assertEqual(result['exceptions'],[])
        self.assertEqual([tuple(r) for r in self.erp.db.execute('SELECT * FROM rpa_items ORDER BY id')],history)
        self.assertEqual(self.erp.db.execute('SELECT status FROM rpa_jobs WHERE id=?',(job,)).fetchone()[0],'running')
        self.assertFalse(any(r['is_purchase'] for r in purchase_tests.Workspace(self.erp).rows(self.company) if r['id']!=other))
