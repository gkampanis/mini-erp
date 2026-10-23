"""Connected workflow acceptance: one Excel, AADE reconciliation, PDF and EBS."""
from contextlib import contextmanager
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs,urlsplit
from app.application.service import ERP
from app.application.workspace import Workspace
from app.application.rpa import RPA
from app.application.mydata import MyData
from app.infrastructure.aade.client import Client,APIError,parsed_page,NoRedirect
from app.infrastructure.importers.excel import preview
from app.infrastructure.ebs_adapter.adapter import FIELDS
from tests.fixtures import demos,workbook,HEADERS,ROW
from tests.test_workspace import synthetic_pdf,MemoryVault


def response(mark='10000001',receiver='000000000',issuer='000000001',continuation='',number='1'):
    return f'''<RequestedDoc xmlns="http://www.aade.gr/myDATA/invoice/v1.0">{continuation}<invoicesDoc><invoice><mark>{mark}</mark><issuer><vatNumber>{issuer}</vatNumber><name>ΣΥΝΘΕΤΙΚΟΣ ΠΡΟΜΗΘΕΥΤΗΣ</name></issuer><counterpart><vatNumber>{receiver}</vatNumber></counterpart><invoiceHeader><series>ΔΟΚ</series><aa>{number}</aa><issueDate>2026-10-21</issueDate><invoiceType>1.1</invoiceType></invoiceHeader><invoiceSummary><totalNetValue>0.10</totalNetValue><totalVatAmount>0.02</totalVatAmount><totalGrossValue>0.12</totalGrossValue></invoiceSummary><downloadingInvoiceUrl>https://example.com/synthetic.pdf</downloadingInvoiceUrl></invoice></invoicesDoc></RequestedDoc>'''.encode()


class Opener:
    def __init__(self,bodies):self.bodies=list(bodies);self.requests=[]
    def open(self,request,timeout):
        self.requests.append(request)
        item=self.bodies.pop(0)
        if isinstance(item,Exception):raise item
        return BytesIO(item)


class FakeEBS:
    def __init__(self,fail=None):self.calls=[];self.handle=100;self.fail=fail
    def prepare(self,profile,expected):
        self.calls.append(('prepare',expected))
        if self.fail=='prepare':raise RuntimeError('synthetic target mismatch')
        return self.handle
    def fill(self,payload,mapping):
        self.calls.append(('fill',payload['document_id']))
        if self.fail=='fill':raise RuntimeError('synthetic interrupted typing')
    def save(self,point):
        self.calls.append(('save',tuple(point)))
        if self.fail=='save':raise RuntimeError('synthetic interrupted Save')
    def open_new(self,point):
        self.calls.append(('new',tuple(point)))
        if self.fail=='new':raise RuntimeError('synthetic missing new form')
        self.handle+=1;return self.handle


class ConnectedWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.erp=ERP(self.root/'data',MemoryVault())
        self.company=self.erp.company('000000000','ΣΥΝΘΕΤΙΚΗ');self.other=self.erp.company('000000009','ΑΛΛΗ ΣΥΝΘΕΤΙΚΗ')
        demos(self.root/'input');self.erp.commit_import(self.company,preview(self.root/'input/separate.xlsx'),confirmed=True)
        from tests.fixtures import reconcile_empty
        reconcile_empty(self.erp,self.company)
        self.ids=[row['id'] for row in Workspace(self.erp).rows(self.company)]
        self.workspace=Workspace(self.erp);self.rpa=RPA(self.erp)
        self.profile=dict(mapping={f:[10+i,20+i] for i,(f,_) in enumerate(FIELDS)},save=[100,200],new=[300,400])

    def tearDown(self):self.erp.close();self.temp.cleanup()

    def approve(self,ids=None,account='64.03',remember=False):
        self.workspace.approve_many(self.company,[dict(document=x,group=account[0],account=account) for x in (ids or self.ids)],confirmed=True,remember=remember)

    def pilot(self):
        self.approve();self.workspace.save_profile(self.company,self.profile)
        job=self.rpa.create(self.company,[self.ids[0]],mode='fill_only',execution='save_new',pilot=True,confirmed=True)
        fake=FakeEBS();result=self.rpa.advance(self.company,job,live_confirmed=True,adapter=fake)
        item=self.rpa.items(self.company,job)[1][0]
        self.workspace.confirm_pilot(self.company,item['id'],'Ελέγχθηκε συνθετικό ΤΕΔ',confirmed=True)
        return job,fake,result

    def test_rows_are_visible_immediately_after_one_import_without_rpa_queue(self):
        rows=self.workspace.rows(self.company)
        self.assertEqual(len(rows),2);self.assertTrue(all(r['ebs_state']=='not_sent' for r in rows))
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM rpa_jobs').fetchone()[0],0)
        self.assertTrue(all(r['name'] and r['vat'] for r in rows))

    def test_bulk_accounts_are_atomic_scoped_and_suggestions_require_approval(self):
        self.assertEqual(self.workspace.suggestions(self.company,'000000001'),[])
        decisions=[dict(document=x,group='6',account='64.03') for x in self.ids]
        with patch.object(self.erp.repository,'audit',side_effect=RuntimeError('synthetic audit fault')):
            with self.assertRaises(RuntimeError):self.workspace.approve_many(self.company,decisions,confirmed=True,remember=True)
        self.assertTrue(all(self.erp.preparation(self.company,x) is None for x in self.ids))
        self.approve(remember=True);self.assertEqual(self.workspace.suggestions(self.company,'000000001'),['64.03'])
        self.assertEqual(self.workspace.suggestions(self.other,'000000001'),[])
        self.approve([self.ids[0]],account='64.04');self.assertEqual(self.workspace.suggestions(self.company,'000000001'),['64.03','64.04'])
        with self.assertRaises(ValueError):self.workspace.approve_many(self.other,decisions,confirmed=True)

    def test_profile_persists_but_position_change_invalidates_pilot(self):
        self.pilot();self.assertTrue(self.workspace.profile(self.company)['pilot_at'])
        self.workspace.save_profile(self.company,self.profile);self.assertTrue(self.workspace.profile(self.company)['pilot_at'])
        revised=dict(self.profile,save=[111,222]);self.workspace.save_profile(self.company,revised)
        self.assertIsNone(self.workspace.profile(self.company)['pilot_at'])
        with self.assertRaises(ValueError):self.rpa.create(self.company,[self.ids[1]],mode='fill_only',execution='save_new',confirmed=True)

    def test_pilot_saves_last_without_opening_new_and_batch_cannot_repost(self):
        job,fake,result=self.pilot()
        self.assertEqual(result['item_status'],'save_invoked');self.assertEqual([x[0] for x in fake.calls],['prepare','fill','save'])
        self.assertEqual(self.workspace.rows(self.company)[0]['ebs_state'],'reviewed_by_operator')
        with self.assertRaises(ValueError):self.rpa.create(self.company,[self.ids[0]],mode='fill_only',execution='save_new',confirmed=True)
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM documents').fetchone()[0],2)

    def test_complete_batch_uses_same_excel_rows_and_save_new_order(self):
        self.pilot()
        rows=[HEADERS]
        for index in range(2):
            row=list(ROW);row[3]='LINK'+str(index);row[8]=str(92000000+index);rows.append(row)
        workbook(self.root/'new.xlsx',rows);self.erp.commit_import(self.company,preview(self.root/'new.xlsx'),confirmed=True)
        from tests.fixtures import reconcile_empty
        reconcile_empty(self.erp,self.company)
        ids=[r['id'] for r in self.workspace.rows(self.company) if r['number'].startswith('LINK')];self.approve(ids)
        job=self.rpa.create(self.company,ids,mode='fill_only',execution='save_new',confirmed=True);fake=FakeEBS()
        first=self.rpa.advance(self.company,job,live_confirmed=True,adapter=fake);self.assertEqual(first['item_status'],'ui_saved_review')
        last=self.rpa.advance(self.company,job,live_confirmed=True,adapter=fake);self.assertEqual(last['status'],'completed')
        self.assertEqual([x[0] for x in fake.calls],['prepare','fill','save','new','prepare','fill','save'])
        self.assertEqual([x[1] for x in fake.calls if x[0]=='fill'],ids)
        self.assertFalse(any(i['status']=='confirmed_in_erp' for i in self.rpa.items(self.company,job)[1]))

    def test_full_preflight_stops_before_typing_if_later_approval_changed(self):
        self.pilot();self.approve([self.ids[1]])
        job=self.rpa.create(self.company,[self.ids[1]],mode='fill_only',execution='save_new',confirmed=True)
        self.approve([self.ids[1]],account='64.99');fake=FakeEBS()
        with self.assertRaises(ValueError):self.rpa.advance(self.company,job,live_confirmed=True,adapter=fake)
        self.assertEqual(fake.calls,[])

    def test_failures_in_save_or_new_stay_uncertain_and_recovery_never_replays(self):
        self.approve();self.workspace.save_profile(self.company,self.profile)
        job=self.rpa.create(self.company,[self.ids[0]],mode='fill_only',execution='save_new',pilot=True,confirmed=True)
        fake=FakeEBS(fail='save');result=self.rpa.advance(self.company,job,live_confirmed=True,adapter=fake)
        self.assertEqual(result['item_status'],'uncertain')
        with self.assertRaises(ValueError):self.rpa.advance(self.company,job,live_confirmed=True,adapter=fake)
        with self.erp.db:self.erp.db.execute("UPDATE rpa_items SET status='save_pending' WHERE job_id=?",(job,))
        self.assertEqual(self.rpa.recover(self.company),1)
        with self.assertRaises(ValueError):self.workspace.confirm_pilot(self.company,self.rpa.items(self.company,job)[1][0]['id'],'not saved',confirmed=True)

    def test_real_40_pause_before_new_and_resume_never_replays_saved_invoice(self):
        self.pilot();rows=[HEADERS]
        for index in range(41):
            row=list(ROW);row[3]='FORTY'+str(index);row[8]=str(94000000+index);rows.append(row)
        workbook(self.root/'forty.xlsx',rows);self.erp.commit_import(self.company,preview(self.root/'forty.xlsx'),confirmed=True)
        from tests.fixtures import reconcile_empty
        reconcile_empty(self.erp,self.company)
        ids=[r['id'] for r in self.workspace.rows(self.company) if r['number'].startswith('FORTY')];self.approve(ids)
        job=self.rpa.create(self.company,ids,mode='fill_only',execution='save_new',confirmed=True);fake=FakeEBS()
        for _ in range(40):result=self.rpa.advance(self.company,job,live_confirmed=True,adapter=fake)
        self.assertEqual(result['status'],'paused');self.assertEqual(sum(x[0]=='new' for x in fake.calls),39)
        self.assertEqual(self.rpa.items(self.company,job)[0]['need_new'],1)
        with self.assertRaises(ValueError):self.rpa.advance(self.company,job,live_confirmed=True,adapter=fake)
        result=self.rpa.advance(self.company,job,live_confirmed=True,adapter=fake,continue_after_pause=True)
        self.assertEqual(result['status'],'completed');self.assertEqual(sum(x[0]=='new' for x in fake.calls),40)
        self.assertEqual([x[1] for x in fake.calls if x[0]=='fill'],ids)

    def test_upgrade_existing_004_preserves_approvals_pdf_and_rpa_history(self):
        from app.infrastructure import database
        old=self.root/'previous';migrations=self.root/'old-migrations';migrations.mkdir()
        for name in ['001_initial.sql','002_preparation.sql','003_rounding.sql','004_workspace.sql']:(migrations/name).write_bytes((database.MIGRATIONS/name).read_bytes())
        with patch.object(database,'MIGRATIONS',migrations):
            service=ERP(old)
            try:
                company=service.company('000000008','ΣΥΝΘΕΤΙΚΗ')
                service.commit_import(company,preview(self.root/'input/separate.xlsx'),confirmed=True)
                document=service.search(company)[0]['id'];service.prepare_document(company,document,'6','64.03',confirmed=True)
                attachment=service.attach_pdf(company,document,'synthetic.pdf',data=synthetic_pdf(),confirmed=True)
                original=service.detail(company,document)[0];approval=service.preparation(company,document)
                with service.db:
                    job=service.db.execute("INSERT INTO rpa_jobs(company_id,mode,status) VALUES (?,'simulation','completed')",(company,)).lastrowid
                    service.db.execute("INSERT INTO rpa_items(job_id,document_id,payload,status) VALUES (?,?,?,'simulated')",(job,document,json.dumps(dict(synthetic=True))))
                raw=[tuple(r) for r in service.db.execute('SELECT * FROM source_records')]
                audit=[tuple(r) for r in service.db.execute('SELECT * FROM audit_events')]
            finally:service.close()
        service=ERP(old)
        try:
            self.assertEqual(service.detail(company,document)[0],original);self.assertEqual(service.preparation(company,document),approval)
            self.assertEqual(service.attachments(company,document)[0],attachment)
            self.assertEqual(service.attachment_path(company,document,attachment['id']).read_bytes(),synthetic_pdf())
            self.assertEqual([tuple(r) for r in service.db.execute('SELECT * FROM source_records')],raw)
            self.assertEqual([tuple(r) for r in service.db.execute('SELECT * FROM audit_events')],audit)
            self.assertEqual(service.db.execute('SELECT status,execution FROM rpa_jobs WHERE id=?',(job,)).fetchone()[0],'completed')
            self.assertEqual(service.db.execute('SELECT status FROM rpa_items WHERE job_id=?',(job,)).fetchone()[0],'simulated')
            self.assertEqual(service.db.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(service.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        finally:service.close()

    def test_purchase_expense_partition_preserves_cards_and_queues_only_expenses(self):
        from app.application.counterparties import Counterparties
        self.workspace.approve_many(self.company,[dict(document=self.ids[0],group='2',account='20.01'),dict(document=self.ids[1],group='6',account='64.03')],confirmed=True)
        before=self.erp.detail(self.company,self.ids[0])[0]
        scope=self.rpa.expense_scope(self.company,self.ids)
        self.assertEqual(scope,dict(expenses=[self.ids[1]],purchases=[self.ids[0]],needs_review=[],outgoing=[],excluded_types=[]))
        job=self.rpa.create(self.company,scope['expenses'],confirmed=True)
        self.rpa.advance(self.company,job)
        self.assertEqual([i['document_id'] for i in self.rpa.items(self.company,job)[1]],[self.ids[1]])
        self.assertEqual(self.erp.detail(self.company,self.ids[0])[0],before)
        self.assertEqual(self.workspace.rows(self.company)[0]['ebs_state'],'purchase_excluded')
        self.assertEqual(Counterparties(self.erp).list(self.company,'000000001')[0]['transaction_scope'],'Αγορές (2) · εκτός EBS')
        with self.assertRaises(ValueError):self.rpa.create(self.company,[self.ids[0]],confirmed=True)
        with self.assertRaises(ValueError):self.rpa.create(self.company,self.ids,mode='fill_only',confirmed=True)

    def test_purchase_default_is_excluded_but_unknown_scope_needs_review(self):
        from app.application.counterparties import Counterparties
        card=Counterparties(self.erp).list(self.company,'000000001')[0]
        Counterparties(self.erp).save(self.company,card['id'],card['name'],['supplier'],confirmed=True,accounts=dict(purchases_account='20.01',expenses_account='',preferred_group='2'))
        scope=self.rpa.expense_scope(self.company,self.ids)
        self.assertEqual(scope['purchases'],[self.ids[0]])
        self.assertEqual(scope['needs_review'],[self.ids[1]])
        self.assertEqual(scope['expenses'],[])
        with self.assertRaises(ValueError):self.rpa.expense_scope(self.other,self.ids)

    def test_aade_transport_headers_pagination_read_only_and_safe_errors(self):
        token='<continuationToken><nextPartitionKey>P</nextPartitionKey><nextRowKey>R</nextRowKey></continuationToken>'
        opener=Opener([response(continuation=token),response(mark='10000002')])
        pages=Client('production','synthetic-user','synthetic-key',opener=opener).fetch('2026-10-01','2026-10-31')
        self.assertEqual(len(pages),2)
        request=opener.requests[0];self.assertEqual(request.get_method(),'GET');self.assertEqual(urlsplit(request.full_url).hostname,'mydatapi.aade.gr')
        self.assertEqual(parse_qs(urlsplit(request.full_url).query)['dateFrom'],['01/10/2026'])
        self.assertNotIn('entityVatNumber',request.full_url);self.assertIn('nextPartitionKey=P',opener.requests[1].full_url)
        self.assertEqual(dict((k.lower(),v) for k,v in request.header_items())['aade-user-id'],'synthetic-user')
        with self.assertRaises(ValueError):Client('production','u','k').fetch('2026-10-01','2026-10-31',method='CancelInvoice')
        with self.assertRaises(APIError):NoRedirect().redirect_request(None,None,302,'',{},'https://example.com')
        bad=Opener([HTTPError('https://mydatapi.aade.gr',401,'unauthorized',{},BytesIO(b'secret service data'))])
        with self.assertRaises(APIError) as error:Client('production','synthetic-user','synthetic-key',opener=bad).fetch('2026-10-01','2026-10-31')
        self.assertNotIn('synthetic-key',str(error.exception));self.assertNotIn('secret service data',str(error.exception))

    def test_aade_received_and_issued_are_scoped_and_never_duplicate_excel(self):
        service=MyData(self.erp);raw=response();item=parsed_page(raw)
        result=service.persist(self.company,'production','2026-10-01','2026-10-31',[(raw,item)])
        self.assertEqual(result['matched'],1);self.assertEqual(self.erp.db.execute('SELECT count(*) FROM documents').fetchone()[0],2)
        outgoing=response(mark='80000001',receiver='000000008',issuer='000000000')
        service.persist(self.company,'production','2026-10-01','2026-10-31',[(outgoing,parsed_page(outgoing))],method='RequestTransmittedDocs')
        values=service.records(self.company,'production');self.assertEqual(len(values),2)
        self.assertEqual(json.loads(values[0]['record_json'])['direction'],'outgoing')
        self.assertEqual(service.records(self.other,'production'),[]);self.assertEqual(service.records(self.company,'test'),[])
        service.persist(self.company,'production','2026-10-01','2026-10-31',[(raw,item)])
        self.assertEqual(len(service.records(self.company,'production')),2)
        self.assertEqual(service.pdf_url(self.company,self.ids[0],'production'),'https://example.com/synthetic.pdf')

    def test_pdf_from_aade_becomes_attachment_of_same_excel_document(self):
        from app.application.provider_pdf import ProviderDatabase
        raw=response();MyData(self.erp).persist(self.company,'production','2026-10-01','2026-10-31',[(raw,parsed_page(raw))])
        adapter=ProviderDatabase(self.erp,self.company,'production')
        rows=adapter.download_candidates(str(self.company));self.assertEqual(len(rows),1)
        pdf=self.root/'synthetic.pdf';pdf.write_bytes(synthetic_pdf())
        import hashlib
        source=hashlib.sha256(rows[0]['download_url'].encode()).hexdigest();digest=hashlib.sha256(pdf.read_bytes()).hexdigest()
        adapter.record_pdf(str(self.company),10000001,'saved_unverified',source,str(pdf),digest,pdf.stat().st_size)
        attachment=self.erp.attachments(self.company,self.ids[0])[0]
        self.assertEqual(attachment['source'],'provider:saved_unverified')
        self.assertEqual(self.erp.attachment_path(self.company,self.ids[0],attachment['id']).read_bytes(),pdf.read_bytes())
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM documents').fetchone()[0],2)
        self.assertEqual(ProviderDatabase(self.erp,self.other,'production').download_candidates(str(self.other)),[])

    def test_xml_dtd_wrong_root_and_repeated_pagination_fail_closed(self):
        for data in [b'<html>bad</html>',b'<!DOCTYPE a [<!ENTITY b "x">]><a>&b;</a>',b'not xml']:
            with self.assertRaises(APIError):parsed_page(data)
        token='<continuationToken><nextPartitionKey>P</nextPartitionKey><nextRowKey>R</nextRowKey></continuationToken>'
        opener=Opener([response(continuation=token),response(continuation=token)])
        with self.assertRaises(APIError):Client('test','u','k',opener=opener).fetch('2026-10-01','2026-10-31')
