"""Account edits share pending scope and never rewrite attempted payload history."""
import unittest
from tests import test_supplier_purchases as fixtures
from app.application.supplier_accounts import SupplierAccounts
from app.application.counterparties import Counterparties
from app.application.workspace import Workspace
from app.application.rpa import RPA
from app.application.ebs_reconciliation import EBSReconciliation

class AccountConsistencyTests(unittest.TestCase):
    setUp=fixtures.PurchaseTests.setUp
    tearDown=fixtures.PurchaseTests.tearDown
    add=fixtures.PurchaseTests.add
    def setup_accounts(self):
        rows=self.erp.search(self.company);self.ids=[r['id'] for r in rows];self.cp=rows[0]['counterparty_id']
        SupplierAccounts(self.erp).save(self.company,[self.cp],'6','64.03',confirmed=True)
        from tests.fixtures import reconcile_empty
        reconcile_empty(self.erp,self.company)
        self.job=RPA(self.erp).create(self.company,self.ids,mode='fill_only',confirmed=True)
        with self.erp.db:
            self.erp.db.execute("UPDATE rpa_jobs SET status='paused' WHERE id=?",(self.job,))
            self.erp.db.execute("UPDATE rpa_items SET status='uncertain' WHERE job_id=? AND document_id=?",(self.job,self.ids[0]))
        self.history=dict(self.erp.db.execute('SELECT * FROM rpa_items WHERE job_id=? AND document_id=?',(self.job,self.ids[0])).fetchone())
    def assert_consistent(self):
        self.assertEqual(Counterparties(self.erp).detail(self.company,self.cp)[0]['accounts']['expenses_account'],'64.09')
        for d in self.ids:self.assertEqual(self.erp.preparation(self.company,d)['account_code'],'64.09')
        self.assertEqual(dict(self.erp.db.execute('SELECT * FROM rpa_items WHERE id=?',(self.history['id'],)).fetchone()),self.history)
        queued=[i for i in RPA(self.erp).items(self.company,self.job)[1] if i['status']=='queued']
        self.assertTrue(all(i['payload']['account']=='64.09' for i in queued))
    def test_selected_remember_updates_all_pending_and_card_after_old_attempt(self):
        self.setup_accounts()
        Workspace(self.erp).approve_many(self.company,[dict(document=self.ids[0],group='6',account='64.09')],confirmed=True,remember=True)
        self.assert_consistent()
    def test_card_edit_updates_pending_after_old_attempt(self):
        self.setup_accounts();cards=Counterparties(self.erp);card,_=cards.detail(self.company,self.cp)
        cards.save(self.company,self.cp,card['name'],['supplier'],confirmed=True,accounts=dict(purchases_account='',expenses_account='64.09',preferred_group='6'),apply_pending=True)
        self.assert_consistent()
    def test_bulk_supplier_edit_updates_pending_after_old_attempt(self):
        self.setup_accounts()
        SupplierAccounts(self.erp).save(self.company,[self.cp],'6','64.09',confirmed=True)
        self.assert_consistent()
    def test_document_only_change_keeps_card_and_other_document(self):
        self.setup_accounts()
        Workspace(self.erp).approve_many(self.company,[dict(document=self.ids[0],group='6',account='64.09')],confirmed=True)
        self.assertEqual(self.erp.preparation(self.company,self.ids[0])['account_code'],'64.09')
        self.assertEqual(self.erp.preparation(self.company,self.ids[1])['account_code'],'64.03')
        self.assertEqual(SupplierAccounts(self.erp).display_accounts(self.company)[self.supplier],'64.03')
    def test_confirmed_registered_preparation_cannot_be_changed_by_selection(self):
        self.setup_accounts();EBSReconciliation(self.erp).confirm_manual(self.company,self.ids[0],'Synthetic actual registration',confirmed=True)
        with self.assertRaises(ValueError):Workspace(self.erp).approve_many(self.company,[dict(document=self.ids[0],group='6',account='64.09')],confirmed=True,remember=True)
        self.assertEqual(SupplierAccounts(self.erp).display_accounts(self.company)[self.supplier],'64.03')

    def test_final_rebind_failure_rolls_back_card_all_pending_and_audit(self):
        from unittest.mock import patch
        self.setup_accounts();before=list(self.erp.db.iterdump());original=SupplierAccounts.rebind_pending;calls=[]
        def rebind(service,company,document):
            calls.append(document)
            if len(calls)==3:raise RuntimeError('Synthetic final rebind failure')
            return original(service,company,document)
        # apply_pending calls rebind only for the other queued document? Both
        # preparations are changed; each is visited even without queued items.
        with patch.object(SupplierAccounts,'rebind_pending',autospec=True,side_effect=rebind):
            with self.assertRaises(RuntimeError):
                Workspace(self.erp).approve_many(self.company,[dict(document=self.ids[0],group='6',account='64.09')],confirmed=True,remember=True)
        self.assertEqual(list(self.erp.db.iterdump()),before)

    def test_remember_document_purchase_account_never_reclassifies_expense_sibling(self):
        self.setup_accounts()
        Workspace(self.erp).approve_many(self.company,[dict(document=self.ids[0],group='2',account='20.01')],confirmed=True,remember=True)
        self.assertEqual(self.erp.preparation(self.company,self.ids[1])['nature_group'],'6')
        self.assertEqual(self.erp.preparation(self.company,self.ids[1])['account_code'],'64.03')
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM document_purchase_tags').fetchone()[0],0)
        other=next(i for i in RPA(self.erp).items(self.company,self.job)[1] if i['document_id']==self.ids[1])
        self.assertEqual(other['status'],'queued');self.assertEqual(other['payload']['account'],'64.03')
