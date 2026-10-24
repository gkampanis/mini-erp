"""Synthetic purchase tags, protected history and stale-queue exclusion."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.application.service import ERP
from app.application.supplier_purchases import SupplierPurchases
from app.application.workspace import Workspace
from app.application.rpa import RPA
from app.application.ebs_reconciliation import EBSReconciliation
from app.infrastructure.importers.excel import preview
from app.ui.document_views import belongs
from tests.fixtures import workbook,HEADERS,ROW,reconcile_empty


def synthetic_vat(number=1):
    base=f'{90000000+number:08d}'
    return base+str(sum(int(d)*2**(8-i) for i,d in enumerate(base))%11%10)


class PurchaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.erp=ERP(self.root/'data')
        self.company=self.erp.company('000000000','ΣΥΝΘΕΤΙΚΗ');self.other=self.erp.company('000000009','ΑΛΛΗ ΣΥΝΘΕΤΙΚΗ')
        self.supplier=synthetic_vat();self.service=SupplierPurchases(self.erp)
        self.add('1','2026-09-21');self.add('2','2026-10-21');self.add('1','2026-09-21',company=self.other)
    def tearDown(self):self.erp.close();self.temp.cleanup()
    def add(self,number,day,*,company=None):
        row=list(ROW);row[0]=self.supplier;row[3]=number;row[4]=day;row[8]=str(70000000+int(number))
        path=self.root/'synthetic.xlsx';workbook(path,[HEADERS,row])
        self.erp.commit_import(company or self.company,preview(path),confirmed=True)
        return self.erp.search(company or self.company,str(70000000+int(number)))[0]['id']
    def test_all_months_same_ids_values_sources_and_evidence_are_preserved(self):
        reconcile_empty(self.erp,self.company)
        from tests.test_workspace import synthetic_pdf
        document=self.erp.search(self.company)[0]['id']
        self.erp.attach_pdf(self.company,document,'synthetic.pdf',data=synthetic_pdf(),confirmed=True)
        attachments=[tuple(r) for r in self.erp.db.execute('SELECT * FROM attachments')]
        before=self.erp.search(self.company);raw=[tuple(r) for r in self.erp.db.execute('SELECT * FROM source_records')]
        evidence=[tuple(r) for r in self.erp.db.execute('SELECT * FROM ebs_matches')]
        report=self.service.set(self.company,self.supplier,True)
        self.assertEqual(report['changed'],2);self.assertFalse(report['exceptions'])
        self.assertEqual(self.erp.search(self.company),before)
        self.assertEqual([tuple(r) for r in self.erp.db.execute('SELECT * FROM source_records')],raw)
        self.assertEqual([tuple(r) for r in self.erp.db.execute('SELECT * FROM ebs_matches')],evidence)
        self.assertEqual([tuple(r) for r in self.erp.db.execute('SELECT * FROM attachments')],attachments)
        rows=Workspace(self.erp).rows(self.company)
        self.assertTrue(all(belongs(r,'purchases') and not belongs(r,'expenses') for r in rows))
        self.assertFalse(any(r['is_purchase'] for r in Workspace(self.erp).rows(self.other)))
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM document_preparations').fetchone()[0],0)
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM counterparty_accounts').fetchone()[0],0)
    def test_rule_survives_restart_new_import_and_reversal_without_account(self):
        result=self.service.set(self.company,self.supplier,True)
        again=ERP(self.erp.directory)
        try:self.assertTrue(SupplierPurchases(again).inspect(self.company,self.supplier)['enabled'])
        finally:again.close()
        new=self.add('3','2026-11-21');self.assertTrue(next(r for r in Workspace(self.erp).rows(self.company) if r['id']==new)['is_purchase'])
        self.service.set(self.company,self.supplier,False,expected_version=result['version'])
        self.assertFalse(any(r['is_purchase'] for r in Workspace(self.erp).rows(self.company)))
        self.assertEqual(self.erp.db.execute("SELECT count(*) FROM audit_events WHERE action='supplier_purchase_rule_changed'").fetchone()[0],2)
    def test_purchases_are_excluded_from_simulation_live_and_existing_queued_attempts(self):
        ids=[r['id'] for r in self.erp.search(self.company)];rpa=RPA(self.erp)
        for document in ids:self.erp.prepare_document(self.company,document,'6','64.03',confirmed=True)
        job=rpa.create(self.company,ids,confirmed=True)
        original=[i['payload'] for i in rpa.items(self.company,job)[1]]
        report=self.service.set(self.company,self.supplier,True)
        self.assertEqual(report['queues'],2)
        items=rpa.items(self.company,job)[1]
        self.assertTrue(all(i['status']=='excluded_purchase' for i in items));self.assertEqual([i['payload'] for i in items],original)
        self.assertEqual(rpa.expense_scope(self.company,ids)['purchases'],ids)
        for mode in ('simulation','fill_only'):
            with self.assertRaises(ValueError):rpa.create(self.company,ids,mode=mode,confirmed=True)
        calls=[]
        class Adapter:
            def fill(self,*args):calls.append(args)
        rpa.advance(self.company,job,adapter=Adapter());self.assertEqual(calls,[])
        self.service.set(self.company,self.supplier,False)
        self.assertTrue(all(i['status']=='excluded_purchase' for i in rpa.items(self.company,job)[1]))
    def test_registered_completed_and_active_records_are_reported_without_changes(self):
        ids=[r['id'] for r in self.erp.search(self.company)];rpa=RPA(self.erp)
        for document in ids:self.erp.prepare_document(self.company,document,'6','64.03',confirmed=True)
        EBSReconciliation(self.erp).confirm_manual(self.company,ids[0],'Συνθετική επιβεβαίωση',confirmed=True)
        job=rpa.create(self.company,[ids[1]],confirmed=True)
        with self.erp.db:self.erp.db.execute("UPDATE rpa_jobs SET status='running' WHERE id=?",(job,))
        saved=[tuple(r) for r in self.erp.db.execute('SELECT * FROM rpa_items')]
        report=self.service.set(self.company,self.supplier,True)
        self.assertEqual(report['changed'],0);self.assertEqual(len(report['exceptions']),2)
        self.assertEqual([tuple(r) for r in self.erp.db.execute('SELECT * FROM rpa_items')],saved)
        self.assertTrue(any('Ενεργή' in r['reason'] for r in report['exceptions']))
    def test_revenue_and_movement_of_same_vat_are_never_reclassified(self):
        ids=[r['id'] for r in self.erp.search(self.company)]
        with self.erp.db:
            self.erp.db.execute("UPDATE documents SET direction='outgoing' WHERE id=?",(ids[0],))
            self.erp.db.execute("UPDATE documents SET kind='delivery_note' WHERE id=?",(ids[1],))
        report=self.service.set(self.company,self.supplier,True);self.assertEqual(report['changed'],0)
        self.add('3','2026-11-21')
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM document_purchase_tags').fetchone()[0],1)
    def test_invalid_vat_and_other_company_cannot_create_a_rule(self):
        for value in ('','123','abcdefghi','000000000',self.supplier[:-1]+str((int(self.supplier[-1])+1)%10)):
            with self.assertRaises(ValueError):self.service.set(self.company,value,True)
        empty=self.erp.company('000000008','ΑΔΕΙΑ')
        with self.assertRaises(ValueError):self.service.set(empty,self.supplier,True)
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM supplier_purchase_rules').fetchone()[0],0)
    def test_future_aade_import_applies_rule_without_tagging_income_or_movement(self):
        from app.application.mydata import MyData
        from app.infrastructure.aade.client import parsed_page
        from tests.test_workflow import response
        self.service.set(self.company,self.supplier,True);api=MyData(self.erp)
        for index,(code,outgoing) in enumerate([('1.1',False),('1.1',True),('9.3',False),('14.1',True)]):
            raw=response(mark=str(88000001+index),number=str(90+index),issuer='000000000' if outgoing else self.supplier,receiver=self.supplier if outgoing else '000000000')
            raw=raw.replace(b'<invoiceType>1.1</invoiceType>',f'<invoiceType>{code}</invoiceType>'.encode())
            api.persist(self.company,'production','2026-10-01','2026-10-31',[(raw,parsed_page(raw))],'RequestTransmittedDocs' if outgoing else 'RequestDocs')
            api.import_documents(self.company,'production','2026-10-01','2026-10-31',confirmed=True,direction='outgoing' if outgoing else 'incoming')
        rows={r['mark']:r for r in Workspace(self.erp).rows(self.company)}
        self.assertTrue(rows['88000001']['purchase_classified']);self.assertFalse(rows['88000002']['purchase_classified'])
        self.assertFalse(rows['88000003']['purchase_classified']);self.assertTrue(rows['88000004']['purchase_classified'])
        self.assertTrue(belongs(rows['88000002'],'income'));self.assertTrue(belongs(rows['88000003'],'movement'))
        self.assertFalse(belongs(rows['88000004'],'income'))
    def test_completed_simulation_is_preserved_while_other_pending_documents_move(self):
        document=self.erp.search(self.company)[0]['id'];self.erp.prepare_document(self.company,document,'6','64.03',confirmed=True)
        rpa=RPA(self.erp);job=rpa.create(self.company,[document],confirmed=True);rpa.advance(self.company,job)
        before=[tuple(r) for r in self.erp.db.execute('SELECT * FROM rpa_items')]
        result=self.service.set(self.company,self.supplier,True)
        self.assertEqual(result['changed'],1);self.assertEqual(result['exceptions'][0]['document'],document)
        self.assertEqual([tuple(r) for r in self.erp.db.execute('SELECT * FROM rpa_items')],before)
    def test_interrupted_real_attempt_remains_in_ebs_review_after_restart(self):
        from app.ui.ebs_reconciliation import result_title
        document=self.erp.search(self.company)[0]['id'];reconcile_empty(self.erp,self.company)
        self.erp.prepare_document(self.company,document,'6','64.03',confirmed=True)
        rpa=RPA(self.erp);job=rpa.create(self.company,[document],mode='fill_only',confirmed=True)
        class Interrupted:
            def fill(self,*args):raise RuntimeError('Synthetic interruption')
        rpa.advance(self.company,job,mapping={'fake':(1,1)},live_confirmed=True,adapter=Interrupted())
        again=ERP(self.erp.directory)
        try:
            RPA(again).recover(self.company);state=EBSReconciliation(again).results(self.company)[document]
            self.assertEqual(result_title(state),'Χρειάζεται έλεγχος στο EBS')
            for mode in ('simulation','fill_only'):
                with self.assertRaises(ValueError):RPA(again).create(self.company,[document],mode=mode,confirmed=True)
        finally:again.close()
    def test_account_rule_edits_do_not_undo_purchase_classification_or_require_purchase_accounts(self):
        from app.application.supplier_accounts import SupplierAccounts
        self.service.set(self.company,self.supplier,True)
        cp=self.erp.search(self.company)[0]['counterparty_id']
        report=SupplierAccounts(self.erp).save(self.company,[cp],'6','64.03',confirmed=True)
        self.assertEqual(report['updated'],0);self.assertEqual(len(report['purchases']),2)
        self.assertTrue(all(r['is_purchase'] for r in Workspace(self.erp).rows(self.company)))
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM document_preparations').fetchone()[0],0)
    def test_rule_tags_and_queues_rollback_together_if_audit_fails(self):
        document=self.erp.search(self.company)[0]['id'];self.erp.prepare_document(self.company,document,'6','64.03',confirmed=True)
        rpa=RPA(self.erp);job=rpa.create(self.company,[document],confirmed=True)
        before=[tuple(r) for r in self.erp.db.execute('SELECT * FROM rpa_items')]
        with patch.object(self.erp.repository,'audit',side_effect=RuntimeError('Synthetic audit failure')):
            with self.assertRaises(RuntimeError):self.service.set(self.company,self.supplier,True)
        self.assertEqual([tuple(r) for r in self.erp.db.execute('SELECT * FROM rpa_items')],before)
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM supplier_purchase_rules').fetchone()[0],0)
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM document_purchase_tags').fetchone()[0],0)
    def test_mixed_existing_queue_skips_purchases_and_executes_the_other_supplier(self):
        path=self.root/'other-supplier.xlsx';row=list(ROW);row[0]=synthetic_vat(2);row[8]='79000001'
        workbook(path,[HEADERS,row]);self.erp.commit_import(self.company,preview(path),confirmed=True)
        ids=[r['id'] for r in self.erp.search(self.company)];rpa=RPA(self.erp)
        for document in ids:self.erp.prepare_document(self.company,document,'6','64.03',confirmed=True)
        other=self.erp.search(self.company,'79000001')[0]['id'];job=rpa.create(self.company,ids,confirmed=True)
        self.service.set(self.company,self.supplier,True);calls=[]
        class Adapter:
            def fill(self,payload,mapping):calls.append(payload['document_id'])
        result=rpa.advance(self.company,job,adapter=Adapter())
        self.assertEqual(calls,[other]);self.assertEqual(result['status'],'completed')
