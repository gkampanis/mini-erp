"""Current VAT mapping is presentation data, never historical posting evidence."""
import unittest
from tests import test_supplier_purchases as fixtures
from app.application.supplier_accounts import SupplierAccounts
from app.application.counterparties import Counterparties
from app.application.ebs_reconciliation import EBSReconciliation

class AccountDisplayTests(unittest.TestCase):
    setUp=fixtures.PurchaseTests.setUp
    tearDown=fixtures.PurchaseTests.tearDown
    add=fixtures.PurchaseTests.add
    def test_current_mapping_is_company_scoped_and_does_not_rewrite_registered_preparation(self):
        service=SupplierAccounts(self.erp);doc=self.erp.search(self.company)[0];cp=doc['counterparty_id']
        service.save(self.company,[cp],'6','64.03',confirmed=True)
        EBSReconciliation(self.erp).confirm_manual(self.company,doc['id'],'Synthetic confirmation',confirmed=True)
        before=self.erp.preparation(self.company,doc['id'])
        service.save(self.company,[cp],'6','64.09',confirmed=True)
        self.assertEqual(service.display_accounts(self.company)[self.supplier],'64.09')
        self.assertNotIn(self.supplier,service.display_accounts(self.other))
        self.assertEqual(self.erp.preparation(self.company,doc['id']),before)
        dump=list(self.erp.db.iterdump());service.display_accounts(self.company)
        self.assertEqual(list(self.erp.db.iterdump()),dump)
