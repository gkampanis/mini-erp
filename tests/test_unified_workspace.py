"""Monthly views use canonical records, official metadata and existing safeguards."""
import json
from pathlib import Path
import tempfile
import unittest
from app.application.service import ERP
from app.application.mydata import MyData
from app.application.workspace import Workspace
from app.application.supplier_accounts import SupplierAccounts
from app.application.ebs_reconciliation import EBSReconciliation
from app.infrastructure.aade.client import parsed_page
from app.ui.document_views import belongs
from tests.test_workflow import response
from tests.test_workspace import MemoryVault


class UnifiedWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.erp=ERP(Path(self.temp.name),MemoryVault())
        self.company=self.erp.company('000000000','ΣΥΝΘΕΤΙΚΗ');self.mydata=MyData(self.erp)
    def tearDown(self):self.erp.close();self.temp.cleanup()
    def receive(self,code='1.1',mark='10000001',*,delivery=False,environment='production',outgoing=False):
        raw=response(mark=mark,number=mark,issuer='000000000' if outgoing else '000000001',receiver='000000002' if outgoing else '000000000')
        raw=raw.replace(b'<invoiceType>1.1</invoiceType>',f'<invoiceType>{code}</invoiceType><isDeliveryNote>{str(delivery).lower()}</isDeliveryNote><correlatedInvoices>99999999</correlatedInvoices>'.encode())
        raw=raw.replace(b'</invoiceSummary>',b'</invoiceSummary><invoiceDeliveryStatus>3</invoiceDeliveryStatus><deliveryLifecycle><deliveryEvents><eventType>RegisterTransfer</eventType></deliveryEvents></deliveryLifecycle>')
        if code in ('9.3','10.1'):raw=raw.replace(b'0.10',b'0.00').replace(b'0.02',b'0.00').replace(b'0.12',b'0.00')
        method='RequestTransmittedDocs' if outgoing else 'RequestDocs'
        self.mydata.persist(self.company,environment,'2026-10-01','2026-10-31',[(raw,parsed_page(raw))],method)
        return self.mydata.import_documents(self.company,environment,'2026-10-01','2026-10-31',confirmed=True,direction='outgoing' if outgoing else 'incoming')
    def test_invoice_in_two_views_has_one_document_and_keeps_delivery_metadata(self):
        self.receive(delivery=True);rows=Workspace(self.erp).rows(self.company,month='2026-10')
        self.assertEqual(len(rows),1);row=rows[0]
        self.assertTrue(belongs(row,'expenses'));self.assertTrue(belongs(row,'movement'));self.assertFalse(belongs(row,'income'))
        self.assertEqual(row['delivery_status'],'3');self.assertEqual(row['correlated_marks'],['99999999'])
        stored=json.loads(self.mydata.records(self.company,'production')[0]['record_json'])
        self.assertIn('RegisterTransfer',stored['delivery_lifecycle'])
        again=self.receive(delivery=True);self.assertEqual(again['inserted'],0);self.assertEqual(again['duplicates'],1)
        self.assertEqual(len(self.erp.search(self.company)),1)
    def test_dispatch_receipt_income_and_unknown_stay_in_correct_views(self):
        for code,mark,outgoing in [('9.3','10000001',False),('10.1','10000002',False),('1.1','10000003',True),('99.99','10000004',False)]:self.receive(code,mark,outgoing=outgoing)
        rows=Workspace(self.erp).rows(self.company)
        self.assertEqual(sum(belongs(r,'movement') for r in rows),2)
        self.assertEqual(sum(belongs(r,'income') for r in rows),1)
        receipts=[r for r in rows if r['invoice_type']=='10.1'];self.assertEqual(receipts[0]['family'],'quantity_receipt')
        self.assertFalse(receipts[0]['rpa_allowed']);self.assertEqual(receipts[0]['gross_minor'],0)
        repeated=self.receive('10.1','10000002');self.assertEqual(repeated['inserted'],0);self.assertEqual(repeated['duplicates'],3)
        self.assertEqual(len(self.erp.search(self.company)),4)
    def test_environment_switch_does_not_show_other_environment_only_documents(self):
        self.receive(mark='10000001',environment='test');self.receive(mark='10000002',environment='production')
        self.assertEqual([r['mark'] for r in Workspace(self.erp).rows(self.company)],['10000002'])
        self.erp.save_mydata_credentials(self.company,'test','synthetic','synthetic',confirmed=True)
        self.assertEqual([r['mark'] for r in Workspace(self.erp).rows(self.company)],['10000001'])
        self.assertEqual(len(self.erp.search(self.company)),2)
    def test_company_boundaries_and_month_are_preserved(self):
        self.receive();other=self.erp.company('000000009','ΑΛΛΗ ΣΥΝΘΕΤΙΚΗ')
        self.assertEqual(Workspace(self.erp).rows(other),[])
        self.assertEqual(Workspace(self.erp).rows(self.company,month='2026-09'),[])
    def test_self_recorded_expense_is_not_revenue_or_an_expense_rpa_candidate(self):
        from app.application.rpa import RPA
        self.receive('14.1',outgoing=True)
        row=Workspace(self.erp).rows(self.company)[0]
        self.assertTrue(belongs(row,'expenses'));self.assertFalse(belongs(row,'income'))
        self.assertEqual(RPA(self.erp).expense_scope(self.company,[row['id']])['expenses'],[])
        supplier=SupplierAccounts(self.erp).rows(self.company)
        self.assertEqual([r['vat'] for r in supplier],['000000002'])
    def test_supplier_mapping_skips_non_value_records_without_losing_invoice_update(self):
        self.receive();self.receive('9.3','10000002')
        cp=self.erp.search(self.company)[0]['counterparty_id']
        report=SupplierAccounts(self.erp).save(self.company,[cp],'6','64.03',confirmed=True)
        self.assertEqual(report['updated'],1);self.assertEqual(len(report['needs_review']),1)
        invoice=next(r for r in self.erp.search(self.company) if r['kind']=='invoice')
        self.assertEqual(self.erp.preparation(self.company,invoice['id'])['account_code'],'64.03')
    def test_supplier_mapping_preserves_confirmed_registered_invoice(self):
        self.receive();row=self.erp.search(self.company)[0]
        self.erp.prepare_document(self.company,row['id'],'6','64.01',confirmed=True)
        EBSReconciliation(self.erp).confirm_manual(self.company,row['id'],'Συνθετικός οπτικός έλεγχος',confirmed=True)
        report=SupplierAccounts(self.erp).save(self.company,[row['counterparty_id']],'6','64.03',confirmed=True)
        self.assertEqual(report['protected'],[row['id']]);self.assertEqual(report['updated'],0)
        self.assertEqual(self.erp.preparation(self.company,row['id'])['account_code'],'64.01')
