"""Month acquisition, supplier propagation and durable RPA state regressions."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.application.service import ERP
from app.application.workspace import Workspace
from app.application.rpa import RPA
from app.application.mydata import MyData
from app.infrastructure.importers.excel import preview
from tests.fixtures import demos,workbook,HEADERS,ROW
from tests.test_workflow import FakeEBS,response,Opener

class MonthlyWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.erp=ERP(self.root/'data')
        self.company=self.erp.company('000000008','ΣΥΝΘΕΤΙΚΗ');demos(self.root/'input');self.erp.commit_import(self.company,preview(self.root/'input/separate.xlsx'),confirmed=True)
        from tests.fixtures import reconcile_empty
        reconcile_empty(self.erp,self.company)
        self.ids=[r['id'] for r in Workspace(self.erp).rows(self.company)]
        self.cps=[r['counterparty_id'] for r in Workspace(self.erp).rows(self.company)]
    def tearDown(self):self.erp.close();self.tmp.cleanup()
    def test_month_bounds_include_leap_day_and_reject_invalid_month(self):
        from app.application.periods import month_bounds
        self.assertEqual(month_bounds('2024','2'),('2024-02-01','2024-02-29'))
        self.assertEqual(month_bounds(2026,12),('2026-12-01','2026-12-31'))
        with self.assertRaises(ValueError):month_bounds(2026,13)
    def test_bulk_supplier_update_reaches_pending_queue_and_actual_adapter_payload(self):
        from app.application.supplier_accounts import SupplierAccounts
        service=SupplierAccounts(self.erp);service.save(self.company,self.cps,'6','64.03',confirmed=True)
        rpa=RPA(self.erp);job=rpa.create(self.company,self.ids,confirmed=True)
        service.save(self.company,self.cps,'6','64.09',confirmed=True)
        self.assertTrue(all(i['payload']['account']=='64.09' for i in rpa.items(self.company,job)[1]))
        class Capture:
            def fill(self,payload,mapping):self.payload=payload
        adapter=Capture();rpa.advance(self.company,job,adapter=adapter)
        self.assertEqual(adapter.payload['account'],'64.09')
    def test_started_or_saved_documents_are_reported_and_never_rewritten(self):
        from app.application.supplier_accounts import SupplierAccounts
        service=SupplierAccounts(self.erp);service.save(self.company,self.cps,'6','64.03',confirmed=True)
        rpa=RPA(self.erp);job=rpa.create(self.company,self.ids,mode='fill_only',confirmed=True)
        item=rpa.items(self.company,job)[1][0]
        with self.erp.db:self.erp.db.execute("UPDATE rpa_items SET status='save_invoked' WHERE id=?",(item['id'],))
        report=service.save(self.company,self.cps,'6','64.09',confirmed=True)
        self.assertEqual(len(report['protected']),1)
        self.assertEqual(self.erp.preparation(self.company,item['document_id'])['account_code'],'64.03')
        self.assertEqual(rpa.items(self.company,job)[1][0]['payload']['account'],'64.03')
    def test_supplier_update_atomic_and_company_scoped(self):
        from app.application.supplier_accounts import SupplierAccounts
        service=SupplierAccounts(self.erp)
        with patch.object(self.erp.repository,'audit',side_effect=RuntimeError('synthetic')):
            with self.assertRaises(RuntimeError):service.save(self.company,self.cps,'6','64.03',confirmed=True)
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM document_preparations').fetchone()[0],0)
        other=self.erp.company('000000009','ΑΛΛΗ')
        with self.assertRaises(ValueError):service.save(other,self.cps,'6','64.03',confirmed=True)
    def test_manual_pause_requires_explicit_resume_without_replay(self):
        Workspace(self.erp).approve_many(self.company,[dict(document=d,group='6',account='64.03') for d in self.ids],confirmed=True)
        rpa=RPA(self.erp);job=rpa.create(self.company,self.ids,confirmed=True)
        rpa.advance(self.company,job);rpa.pause(self.company,job)
        with self.assertRaises(ValueError):rpa.advance(self.company,job)
        rpa.advance(self.company,job,continue_after_pause=True)
        self.assertEqual([i['status'] for i in rpa.items(self.company,job)[1]],['simulated','simulated'])
    def test_month_fetches_all_pages_both_directions_and_downloads_each_pdf_once(self):
        import socket
        from io import BytesIO
        from email.message import Message
        from app.infrastructure.aade.client import Client
        from app.application.sync import Sync
        from tests.test_workspace import synthetic_pdf
        token='<continuationToken><nextPartitionKey>P</nextPartitionKey><nextRowKey>R</nextRowKey></continuationToken>'
        bodies=[response(mark='31000001',number='31',receiver='000000008',continuation=token),response(mark='31000002',number='32',receiver='000000008'),response(mark='81000001',number='77',issuer='000000008',receiver='000000007')]
        class PDFResponse(BytesIO):
            def __init__(self):
                super().__init__(synthetic_pdf());self.status=200;self.headers=Message();self.headers['Content-Type']='application/pdf'
            def geturl(self):return 'https://example.com/synthetic.pdf'
        class PDFOpener:
            def __init__(self):self.calls=[]
            def open(self,request,timeout):self.calls.append(request);return PDFResponse()
        provider=PDFOpener();public=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))]
        with patch('app.infrastructure.providers.pdf_downloads.build_opener',return_value=provider),patch('app.infrastructure.providers.pdf_downloads.socket.getaddrinfo',return_value=public):
            opener=Opener(bodies);result=Sync(self.erp).run(self.company,'test','2026-10-01','2026-10-31',book=False,client=Client('test','synthetic','synthetic',opener=opener),methods=['RequestDocs','RequestTransmittedDocs'])
            self.assertEqual(len(opener.requests),3);self.assertIn('nextPartitionKey=P',opener.requests[1].full_url)
            self.assertEqual(result['import']['inserted'],3);self.assertEqual(result['pdf']['saved'],2)
            self.assertEqual(len(provider.calls),2)  # Revenue PDFs require an explicit individual action.
            result=Sync(self.erp).run(self.company,'test','2026-10-01','2026-10-31',book=False,client=Client('test','synthetic','synthetic',opener=Opener(bodies)),methods=['RequestDocs','RequestTransmittedDocs'])
            self.assertEqual(result['import']['inserted'],0);self.assertEqual(result['pdf']['skipped'],2);self.assertEqual(len(provider.calls),2)
        docs=self.erp.search(self.company)
        self.assertEqual(len(docs),5);self.assertEqual(self.erp.db.execute('SELECT count(*) FROM attachments').fetchone()[0],2)
        outgoing=next(d for d in docs if d['direction']=='outgoing')
        self.assertEqual(outgoing['vat'],'000000007')
        self.assertIn(outgoing['id'],RPA(self.erp).expense_scope(self.company,[outgoing['id']])['outgoing'])
        with self.assertRaises(ValueError):RPA(self.erp).payload(self.company,outgoing['id'])
        self.assertEqual({r['match_status'] for r in MyData(self.erp).records(self.company,'test')},{'matched'})

    def test_bulk_account_reaches_save_adapter_without_claiming_database_verification(self):
        from app.application.supplier_accounts import SupplierAccounts
        from app.infrastructure.ebs_adapter.adapter import FIELDS
        service=SupplierAccounts(self.erp);service.save(self.company,self.cps,'6','64.03',confirmed=True)
        profile=dict(mapping={f:[10+i,20+i] for i,(f,_) in enumerate(FIELDS)},save=[100,200],new=[300,400])
        Workspace(self.erp).save_profile(self.company,profile);rpa=RPA(self.erp)
        job=rpa.create(self.company,[self.ids[0]],mode='fill_only',execution='save_new',pilot=True,confirmed=True)
        service.save(self.company,self.cps,'6','64.09',confirmed=True)
        fake=FakeEBS();seen=[];fill=fake.fill
        def capture(payload,mapping):seen.append(payload['account']);fill(payload,mapping)
        fake.fill=capture;rpa.advance(self.company,job,live_confirmed=True,adapter=fake)
        self.assertEqual(seen,['64.09']);self.assertEqual(rpa.progress(self.company,job)['verified_in_ebs'],0)
        self.assertEqual(rpa.progress(self.company,job)['save_requested'],1)

    def test_month_book_then_details_then_pdf_reuses_existing_excel_document(self):
        import socket
        from io import BytesIO
        from email.message import Message
        from app.application.sync import Sync
        from app.infrastructure.aade.client import Client
        from tests.test_workspace import synthetic_pdf
        book=b'<RequestedBookInfo><bookInfo><counterVatNumber>000000001</counterVatNumber><issueDate>2026-10-21</issueDate><invType>1.1</invType><count>1</count><netValue>0.10</netValue></bookInfo></RequestedBookInfo>'
        raw=response(receiver='000000008')
        class PDFResponse(BytesIO):
            def __init__(self):
                super().__init__(synthetic_pdf());self.status=200;self.headers=Message();self.headers['Content-Type']='application/pdf'
            def geturl(self):return 'https://example.com/synthetic.pdf'
        class PDFOpener:
            def __init__(self):self.calls=[]
            def open(self,request,timeout):self.calls.append(request);return PDFResponse()
        provider=PDFOpener();public=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))]
        notices=[];opener=Opener([book,raw])
        document=self.erp.search(self.company,'10000001')[0]['id']
        with patch('app.infrastructure.providers.pdf_downloads.build_opener',return_value=provider),patch('app.infrastructure.providers.pdf_downloads.socket.getaddrinfo',return_value=public):
            for current in (opener,Opener([book,raw])):
                result=Sync(self.erp).run(self.company,'test','2026-10-01','2026-10-31',client=Client('test','synthetic','synthetic',opener=current),notice=notices.append)
                self.assertEqual(result['import']['inserted'],0)
                self.assertEqual(len(self.erp.search(self.company)),2)
            self.assertEqual(len(provider.calls),1)
        self.assertIn('/RequestMyExpenses?',opener.requests[0].full_url)
        self.assertIn('/RequestDocs?',opener.requests[1].full_url)
        self.assertIn('dateFrom=01%2F10%2F2026',opener.requests[1].full_url)
        self.assertEqual(result['book']['count'],1)
        self.assertEqual(result['pdf']['skipped'],1)
        self.assertIn('βιβλίου',notices[0]);self.assertIn('αντιστοίχιση MARK',notices[1]);self.assertIn('σύνδεση PDF',notices[2])
        attachments=self.erp.attachments(self.company,document)
        self.assertEqual(len(attachments),1)
        self.assertEqual(self.erp.attachment_path(self.company,document,attachments[0]['id']).read_bytes(),synthetic_pdf())
        self.assertEqual({r['document_id'] for r in MyData(self.erp).records(self.company,'test')},{document})

    def test_account_change_during_native_prepare_blocks_old_payload_before_typing(self):
        from app.application.supplier_accounts import SupplierAccounts
        from app.infrastructure.ebs_adapter.adapter import FIELDS
        service=SupplierAccounts(self.erp);service.save(self.company,self.cps,'6','64.03',confirmed=True)
        Workspace(self.erp).save_profile(self.company,dict(mapping={f:[10+i,20+i] for i,(f,_) in enumerate(FIELDS)},save=[100,200],new=[300,400]))
        rpa=RPA(self.erp);job=rpa.create(self.company,[self.ids[0]],mode='fill_only',execution='save_new',pilot=True,confirmed=True)
        fake=FakeEBS();prepare=fake.prepare
        def changing(profile,expected):
            service.save(self.company,self.cps,'6','64.09',confirmed=True)
            return prepare(profile,expected)
        fake.prepare=changing
        with self.assertRaises(ValueError):rpa.advance(self.company,job,live_confirmed=True,adapter=fake)
        self.assertFalse(any(c[0]=='fill' for c in fake.calls))
        self.assertEqual(rpa.items(self.company,job)[1][0]['status'],'queued')
    def test_failed_later_page_never_reports_first_page_as_complete_month(self):
        from app.application.sync import Sync
        from app.infrastructure.aade.client import Client
        token='<continuationToken><nextPartitionKey>P</nextPartitionKey><nextRowKey>R</nextRowKey></continuationToken>'
        client=Client('test','synthetic','synthetic',opener=Opener([response(mark='32000001',number='41',receiver='000000008',continuation=token),b'<html>not API data</html>']))
        result=Sync(self.erp).run(self.company,'test','2026-10-01','2026-10-31',book=False,download=False,client=client)
        self.assertEqual(len(result['errors']),1);self.assertEqual(result['import']['inserted'],0)
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM mydata_records').fetchone()[0],0)
        self.assertEqual(len(self.erp.search(self.company)),2)

    def test_group_two_is_never_reclassified_by_bulk_expense_rule(self):
        from app.application.supplier_accounts import SupplierAccounts
        self.erp.prepare_document(self.company,self.ids[0],'2','20.01',confirmed=True)
        SupplierAccounts(self.erp).save(self.company,self.cps,'6','64.09',confirmed=True)
        self.assertEqual(self.erp.preparation(self.company,self.ids[0])['nature_group'],'2')
        scope=RPA(self.erp).expense_scope(self.company,self.ids)
        self.assertEqual(scope['purchases'],[self.ids[0]]);self.assertEqual(scope['expenses'],[self.ids[1]])

    def test_crash_between_items_recovers_paused_and_keeps_progress(self):
        Workspace(self.erp).approve_many(self.company,[dict(document=d,group='6',account='64.03') for d in self.ids],confirmed=True)
        rpa=RPA(self.erp);job=rpa.create(self.company,self.ids,confirmed=True);rpa.advance(self.company,job)
        self.assertEqual(rpa.items(self.company,job)[0]['status'],'running')
        self.assertEqual(rpa.recover(self.company),0)
        self.assertEqual(rpa.items(self.company,job)[0]['status'],'paused')
        rpa.advance(self.company,job,continue_after_pause=True)
        self.assertEqual(rpa.progress(self.company,job)['simulated'],2)

    def test_test_api_document_allows_simulation_but_never_live_ebs(self):
        from app.infrastructure.aade.client import parsed_page
        from app.application.supplier_accounts import SupplierAccounts
        raw=response(mark='35000001',number='51',receiver='000000008')
        MyData(self.erp).persist(self.company,'test','2026-10-01','2026-10-31',[(raw,parsed_page(raw))])
        MyData(self.erp).import_incoming(self.company,'test','2026-10-01','2026-10-31',confirmed=True)
        document=next(d for d in self.erp.search(self.company) if d['mark']=='35000001')
        SupplierAccounts(self.erp).save(self.company,[document['counterparty_id']],'6','64.03',confirmed=True)
        from tests.fixtures import reconcile_empty
        reconcile_empty(self.erp,self.company)
        RPA(self.erp).create(self.company,[document['id']],confirmed=True)
        with self.assertRaises(ValueError):RPA(self.erp).create(self.company,[document['id']],mode='fill_only',confirmed=True)
    def test_account_update_requires_pause_and_rolls_back_while_job_running(self):
        from app.application.supplier_accounts import SupplierAccounts
        service=SupplierAccounts(self.erp);service.save(self.company,self.cps,'6','64.03',confirmed=True)
        job=RPA(self.erp).create(self.company,self.ids,confirmed=True)
        with self.erp.db:self.erp.db.execute("UPDATE rpa_jobs SET status='running' WHERE id=?",(job,))
        with self.assertRaises(ValueError):service.save(self.company,self.cps,'6','64.09',confirmed=True)
        self.assertEqual({r[0] for r in self.erp.db.execute('SELECT account_code FROM document_preparations')},{'64.03'})
        self.assertEqual({r[0] for r in self.erp.db.execute('SELECT expenses_account FROM counterparty_accounts')},{'64.03'})
    def test_visual_confirmation_is_distinct_from_save_click_and_review_note(self):
        from app.application.supplier_accounts import SupplierAccounts
        SupplierAccounts(self.erp).save(self.company,self.cps,'6','64.03',confirmed=True)
        rpa=RPA(self.erp);job=rpa.create(self.company,self.ids,mode='fill_only',confirmed=True)
        item=rpa.items(self.company,job)[1][0]
        with self.erp.db:self.erp.db.execute("UPDATE rpa_items SET status='save_invoked' WHERE id=?",(item['id'],))
        self.assertEqual(rpa.progress(self.company,job)['verified_in_ebs'],0)
        rpa.reviewed(self.company,job,item['id'],'Σημείωση χωρίς επιβεβαίωση',confirmed=True)
        self.assertEqual(rpa.progress(self.company,job)['verified_in_ebs'],0)
        rpa.reviewed(self.company,job,item['id'],'Οπτικά αποθηκευμένο',confirmed=True,stored_in_ebs=True)
        self.assertEqual(rpa.progress(self.company,job)['verified_in_ebs'],1)
        self.assertEqual(rpa.progress(self.company,job)['automatically_verified'],0)
    def test_review_of_fill_without_save_never_counts_as_agent_save_command(self):
        from app.application.supplier_accounts import SupplierAccounts
        SupplierAccounts(self.erp).save(self.company,self.cps,'6','64.03',confirmed=True)
        rpa=RPA(self.erp);job=rpa.create(self.company,[self.ids[0]],mode='fill_only',confirmed=True)
        item=rpa.items(self.company,job)[1][0]
        with self.erp.db:self.erp.db.execute("UPDATE rpa_items SET status='filled_no_save' WHERE id=?",(item['id'],))
        rpa.reviewed(self.company,job,item['id'],'Ελέγχθηκε μόνο η συμπλήρωση',confirmed=True)
        p=rpa.progress(self.company,job)
        self.assertEqual(p['save_requested'],0);self.assertEqual(p['verified_in_ebs'],0)
