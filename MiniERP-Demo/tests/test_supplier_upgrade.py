"""Synthetic stable-baseline supplier propagation and persistent group reversal."""
import unittest
from tests import test_supplier_purchases as fixtures
from app.application.supplier_accounts import SupplierAccounts
from app.application.counterparties import Counterparties
from app.application.ebs_reconciliation import EBSReconciliation
from app.application.rpa import RPA
from app.application.service import ERP

class SupplierUpgradeTests(unittest.TestCase):
    setUp=fixtures.PurchaseTests.setUp
    tearDown=fixtures.PurchaseTests.tearDown
    add=fixtures.PurchaseTests.add
    def test_expense_account_without_preferred_group_updates_pending_not_registered(self):
        rows=self.erp.search(self.company);cp=rows[0]['counterparty_id'];ids=[r['id'] for r in rows]
        EBSReconciliation(self.erp).confirm_manual(self.company,ids[0],'Synthetic check',confirmed=True)
        cards=Counterparties(self.erp);card,_=cards.detail(self.company,cp)
        result=cards.save(self.company,cp,card['name'],['supplier'],confirmed=True,accounts=dict(purchases_account='',expenses_account='64.03',preferred_group=None),apply_pending=True)
        self.assertEqual(result['pending_update']['updated'],1)
        self.assertIsNone(self.erp.preparation(self.company,ids[0]))
        self.assertEqual(self.erp.preparation(self.company,ids[1])['account_code'],'64.03')
        self.assertEqual(RPA(self.erp).payload(self.company,ids[1])['account'],'64.03')

    def test_group_views_and_previous_group_survive_restart_keep_accounts(self):
        cp=self.erp.search(self.company)[0]['counterparty_id'];accounts=SupplierAccounts(self.erp)
        accounts.save(self.company,[cp],'6','64.03',confirmed=True)
        self.assertEqual(accounts.rows(self.company)[0]['group'],'6')
        self.service.set(self.company,self.supplier,True)
        self.assertEqual(accounts.rows(self.company)[0]['group'],'2')
        again=ERP(self.erp.directory)
        try:
            from app.application.supplier_purchases import SupplierPurchases
            service=SupplierPurchases(again)
            self.assertEqual(service.inspect(self.company,self.supplier)['previous_group'],'6')
            service.restore(self.company,self.supplier)
        finally:again.close()
        self.assertEqual(accounts.rows(self.company)[0]['group'],'6')
        self.assertEqual(Counterparties(self.erp).detail(self.company,cp)[0]['accounts']['expenses_account'],'64.03')

    def test_unknown_previous_group_cannot_be_invented(self):
        self.service.set(self.company,self.supplier,True)
        with self.assertRaises(ValueError):self.service.restore(self.company,self.supplier)
        self.assertTrue(self.service.inspect(self.company,self.supplier)['enabled'])

    def test_assigned_card_without_documents_is_visible_without_duplicate_rows(self):
        with self.erp.db:
            cp=self.erp.db.execute("INSERT INTO counterparties(company_id,vat,name) VALUES (?,?,?)",(self.company,'000000007','SYNTHETIC NO DOCUMENTS')).lastrowid
        accounts=SupplierAccounts(self.erp);accounts.save(self.company,[cp],'6','64.03',confirmed=True)
        rows=[r for r in accounts.rows(self.company) if r['id']==cp]
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['group'],'6');self.assertEqual(rows[0]['document_count'],0)

    def test_changed_expense_mapping_updates_paused_unexecuted_payload(self):
        cp=self.erp.search(self.company)[0]['counterparty_id'];accounts=SupplierAccounts(self.erp)
        accounts.save(self.company,[cp],'6','64.03',confirmed=True)
        ids=[r['id'] for r in self.erp.search(self.company)]
        rpa=RPA(self.erp);job=rpa.create(self.company,ids,confirmed=True)
        with self.erp.db:self.erp.db.execute("UPDATE rpa_jobs SET status='paused' WHERE id=?",(job,))
        report=accounts.save(self.company,[cp],'6','64.09',confirmed=True)
        self.assertEqual(report['queues'],len(ids))
        self.assertTrue(all(i['payload']['account']=='64.09' for i in rpa.items(self.company,job)[1]))
