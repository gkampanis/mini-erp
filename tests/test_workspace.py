"""Synthetic checks for rounding, secure settings, PDF and approval-bound RPA."""
from pathlib import Path
import json
import socket
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from app.application.service import ERP
from app.application.rpa import RPA
from app.domain.validation import cents,record
from app.infrastructure import database
from app.infrastructure.pdf_archive import render,validate_url,download,SafeRedirect
from app.infrastructure.ebs_adapter.adapter import FIELDS,fill_sequence,load_mapper
from app.infrastructure.aade.credentials import validate,target_for,WindowsCredentialStore,VaultUnavailable
from tests.fixtures import demos,workbook,HEADERS,ROW
from app.infrastructure.importers.excel import preview


def synthetic_pdf():
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
             b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Resources << >> /Contents 4 0 R >>']
    content=b'0.1 0.3 0.7 rg 20 20 260 360 re f\n'
    objects.append(b'<< /Length '+str(len(content)).encode()+b' >>\nstream\n'+content+b'endstream')
    result=b'%PDF-1.4\n';offsets=[0]
    for number,obj in enumerate(objects,1):
        offsets.append(len(result));result+=str(number).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
    start=len(result)
    result+=b'xref\n0 5\n0000000000 65535 f \n'+b''.join(('%010d 00000 n \n'%offset).encode() for offset in offsets[1:])
    return result+b'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n'+str(start).encode()+b'\n%%EOF\n'


class MemoryVault:
    def __init__(self):self.values={}
    def read(self,target):return self.values.get(target)
    def write(self,target,value):self.values[target]=value.copy()
    def delete(self,target):self.values.pop(target,None)


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.vault=MemoryVault();self.erp=ERP(self.root/'data',self.vault)
        self.company=self.erp.company('000000000','ΣΥΝΘΕΤΙΚΗ ΕΤΑΙΡΕΙΑ')
        demos(self.root/'input')
        self.erp.commit_import(self.company,preview(self.root/'input/separate.xlsx'),confirmed=True)
        from tests.fixtures import reconcile_empty
        reconcile_empty(self.erp,self.company)
        self.document=self.erp.search(self.company,'000000001')[0]['id']
        self.other=self.erp.company('000000009','ΑΛΛΗ ΕΤΑΙΡΕΙΑ')

    def tearDown(self):self.erp.close();self.temp.cleanup()

    def approve(self,document=None,group='6'):
        self.erp.prepare_document(self.company,document or self.document,group,'64.03' if group=='6' else '20.01',confirmed=True)

    def test_half_up_and_rounding_preserve_raw_audit_and_consistency(self):
        self.assertEqual([cents(x) for x in ['1.234','1.235','-1.235','0.001']],[123,124,-124,0])
        row=list(ROW);row[3]='ROUND';row[5:9]=['0.105','0.025','0.130','90000001']
        headers=list(HEADERS);headers[1]='Επωνυμία προμηθευτή'
        workbook(self.root/'rounded.xlsx',[headers,row])
        item=preview(self.root/'rounded.xlsx');self.assertEqual(item.rejected,[])
        self.assertEqual(item.records[0]['document']['rounding_minor'],-1)
        result=self.erp.commit_import(self.company,item,confirmed=True)
        self.assertEqual(result['inserted'],1)
        rounded=self.erp.search(self.company,'ROUND')[0]
        self.assertEqual((rounded['net_minor'],rounded['tax_minor'],rounded['gross_minor'],rounded['rounding_minor']),(11,3,13,-1))
        _,events=self.erp.detail(self.company,rounded['id'])
        self.assertIn('amounts_rounded',[e['action'] for e in events])
        self.assertIn('0.105',self.erp.db.execute('SELECT raw_json FROM source_records ORDER BY id DESC').fetchone()[0])
        self.assertEqual((self.root/'data/sources'/ (item.sha256+'.xlsx')).read_bytes(),item.data)
        fields=dict(vat='000000001',number='1',date='2026-10-22',net='1.234',tax='0.246',gross='1.48')
        self.assertEqual(record(fields)['gross_minor'],148)
        for change in [dict(gross='10.00'),dict(net='1.23',tax='0.24',gross='1.48'),dict(net='-0.001')]:
            with self.assertRaises(ValueError):record(dict(fields,**change))

    def test_company_name_correction_is_scoped_and_audited(self):
        row,_=self.erp.detail(self.company,self.document)
        counterparty=row['counterparty_id']
        with self.assertRaises(ValueError):self.erp.rename_counterparty(self.other,counterparty,'ΑΛΛΗ',confirmed=True)
        with self.assertRaises(ValueError):self.erp.rename_counterparty(self.company,counterparty,'ΝΕΑ')
        self.erp.rename_counterparty(self.company,counterparty,'ΝΕΑ ΕΠΩΝΥΜΙΑ',confirmed=True)
        changed=self.erp.search(self.company,'ΝΕΑ ΕΠΩΝΥΜΙΑ')[0]
        self.assertEqual(changed['vat'],row['vat'])
        self.assertEqual(self.erp.db.execute("SELECT count(*) FROM audit_events WHERE action='counterparty_renamed'").fetchone()[0],1)

    def test_credentials_never_enter_database_and_environments_are_separate(self):
        self.erp.save_mydata_credentials(self.company,'test','synthetic-user','synthetic-key',confirmed=True)
        self.assertEqual(self.erp.mydata_credentials(self.company)['key'],'synthetic-key')
        self.assertEqual(self.erp.mydata_credentials(self.company,'production')['key'],'')
        self.assertEqual(self.erp.mydata_credentials(self.other)['key'],'')
        dump='\n'.join(self.erp.db.iterdump())
        self.assertNotIn('synthetic-key',dump);self.assertNotIn('synthetic-user',dump)
        self.assertNotEqual(target_for(self.root,'000000000','test'),target_for(self.root/'other','000000000','test'))
        with patch.object(self.erp.repository,'audit',side_effect=RuntimeError('synthetic audit failure')):
            with self.assertRaises(RuntimeError):self.erp.save_mydata_credentials(self.company,'test','new-user','new-key',confirmed=True)
        self.assertEqual(self.erp.mydata_credentials(self.company)['key'],'synthetic-key')
        for key in ['a\nb','a\0b','a b']:
            with self.assertRaises(ValueError):validate('test','synthetic',key)
        with patch('app.infrastructure.aade.credentials.sys.platform','linux'):
            with self.assertRaises(VaultUnavailable):WindowsCredentialStore().read('synthetic')

    def test_pdf_archive_render_roles_deduplication_and_tenant_boundary(self):
        data=synthetic_pdf()
        first=self.erp.attach_pdf(self.company,self.document,'synthetic.pdf',data=data,confirmed=True)
        again=self.erp.attach_pdf(self.company,self.document,'other-name.pdf',data=data,confirmed=True)
        note=self.erp.attach_pdf(self.company,self.document,'note.pdf','delivery_note',data=data,confirmed=True)
        self.assertEqual(first['id'],again['id']);self.assertNotEqual(first['id'],note['id'])
        path=self.erp.attachment_path(self.company,self.document,first['id'])
        result=render(path)
        self.assertEqual(result['pages'],1);self.assertTrue(result['ppm'].startswith(b'P6\n'))
        with self.assertRaises(ValueError):self.erp.attachment_path(self.other,self.document,first['id'])
        with self.assertRaises(ValueError):self.erp.attach_pdf(self.company,self.document,'bad.pdf',data=b'HTML',confirmed=True)
        path.write_bytes(b'%PDF-tampered')
        with self.assertRaises(ValueError):self.erp.attachment_path(self.company,self.document,first['id'])

    def test_pdf_https_validation_and_download_do_not_persist_signed_query(self):
        public=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))]
        with patch('app.infrastructure.pdf_archive.socket.getaddrinfo',return_value=public):
            for url in ['http://example.com/a.pdf','https://u:p@example.com/a.pdf','https://localhost/a.pdf','https://example.com:8443/a.pdf']:
                with self.assertRaises(ValueError):validate_url(url)
            self.assertEqual(validate_url('https://example.com/a.pdf').hostname,'example.com')
            from io import BytesIO
            response=BytesIO(synthetic_pdf());response.headers={}
            with patch('app.infrastructure.pdf_archive.urllib.request.build_opener') as factory:
                factory.return_value.open.return_value=response
                data,source=download('https://example.com/a.pdf?token=synthetic')
                self.assertEqual(source,'https:example.com');self.assertEqual(data,synthetic_pdf())
        private=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))]
        with patch('app.infrastructure.pdf_archive.socket.getaddrinfo',return_value=private):
            with self.assertRaises(ValueError):validate_url('https://example.com/a.pdf')
            with self.assertRaises(ValueError):SafeRedirect().redirect_request(None,None,302,'',{},'https://example.com/private')

    def test_rpa_requires_approval_and_simulation_is_persisted(self):
        rpa=RPA(self.erp)
        with self.assertRaises(ValueError):rpa.create(self.company,[self.document],confirmed=True)
        self.approve();job=rpa.create(self.company,[self.document],confirmed=True)
        with patch('app.infrastructure.ebs_adapter.adapter.WindowsAdapter',side_effect=AssertionError('native input forbidden')):
            result=rpa.advance(self.company,job)
        self.assertEqual(result['item_status'],'simulated')
        self.assertEqual(rpa.items(self.company,job)[0]['status'],'completed')
        with self.assertRaises(ValueError):rpa.items(self.other,job)
        job=rpa.create(self.company,[self.document],confirmed=True)
        self.approve(group='2')
        with self.assertRaises(ValueError):rpa.advance(self.company,job)
        with self.assertRaises(ValueError):rpa.create(self.company,[self.document],mode='fill_only',confirmed=True)

    def test_real_attempt_requires_live_confirmation_and_never_replays_uncertain(self):
        self.approve();rpa=RPA(self.erp)
        job=rpa.create(self.company,[self.document],mode='fill_only',confirmed=True)
        with self.assertRaises(ValueError):rpa.advance(self.company,job,mapping={'synthetic':(1,1)})
        class Broken:
            def fill(self,*args):raise RuntimeError('synthetic interrupted input')
        result=rpa.advance(self.company,job,mapping={'synthetic':(1,1)},live_confirmed=True,adapter=Broken())
        self.assertEqual(result['item_status'],'uncertain')
        with self.assertRaises(ValueError):rpa.advance(self.company,job)
        with self.assertRaises(ValueError):rpa.create(self.company,[self.document],mode='fill_only',confirmed=True)
        item=rpa.items(self.company,job)[1][0]
        rpa.reviewed(self.company,job,item['id'],'Χειροκίνητος έλεγχος συνθετικής προσπάθειας',confirmed=True)
        with self.assertRaises(ValueError):rpa.create(self.company,[self.document],mode='fill_only',confirmed=True)
        with self.erp.db:self.erp.db.execute("UPDATE rpa_items SET status='started' WHERE id=?",(item['id'],))
        self.assertEqual(rpa.recover(self.company),1)
        self.assertEqual(rpa.items(self.company,job)[1][0]['status'],'uncertain')

    def test_rpa_mapper_and_date_keystrokes_preserve_baseline(self):
        path=self.root/'mapper.csv'
        path.write_text('Field,MouseX,MouseY,RectX,RectY,RectH\n'+''.join(f'{field},10,20,30,40,20\n' for field,_ in FIELDS))
        mapping=load_mapper(path);self.assertEqual(mapping['INVOICE_DATE'],(35,50))
        calls=[]
        class Driver:
            def validate_target(self,field,point):calls.append(('field',field));return point
            def __getattr__(self,name):return lambda *args,**kwargs:calls.append((name,args))
        self.approve();fill_sequence(Driver(),RPA(self.erp).payload(self.company,self.document),mapping)
        dates=[i for i,c in enumerate(calls) if c==('field','INVOICE_DATE')]
        segment=calls[dates[0]:next(i for i in range(dates[0]+1,len(calls)) if calls[i][0]=='field')]
        self.assertIn(('write',('21102026',)),segment)
        self.assertFalse(any(c[0]=='hotkey' for c in segment))
        self.assertFalse(any('save' in str(c).lower() for c in calls))

    def test_rpa_batch_pauses_at_40_and_stop_is_persisted(self):
        rows=[HEADERS]
        for index in range(41):
            row=list(ROW);row[3]='BATCH'+str(index);row[8]=str(91000000+index);rows.append(row)
        workbook(self.root/'batch.xlsx',rows)
        self.erp.commit_import(self.company,preview(self.root/'batch.xlsx'),confirmed=True)
        from tests.fixtures import reconcile_empty
        reconcile_empty(self.erp,self.company)
        ids=[r['id'] for r in self.erp.search(self.company) if r['number'].startswith('BATCH')]
        for document in ids:self.approve(document)
        rpa=RPA(self.erp);job=rpa.create(self.company,ids,confirmed=True)
        for index in range(40):result=rpa.advance(self.company,job)
        self.assertEqual(result['status'],'paused')
        self.assertEqual(sum(i['status']=='queued' for i in rpa.items(self.company,job)[1]),1)
        rpa.stop(self.company,job)
        with self.assertRaises(ValueError):rpa.advance(self.company,job)
        self.assertEqual(rpa.items(self.company,job)[0]['status'],'stopped')

    def test_real_fill_is_paused_for_manual_review_without_save_claim(self):
        self.approve();rpa=RPA(self.erp);job=rpa.create(self.company,[self.document],mode='fill_only',confirmed=True)
        calls=[]
        class Fake:
            def fill(self,payload,mapping):calls.append(payload)
        result=rpa.advance(self.company,job,mapping={'synthetic':(1,1)},live_confirmed=True,adapter=Fake())
        self.assertEqual(result['status'],'paused');self.assertEqual(result['item_status'],'filled_no_save')
        self.assertEqual(len(calls),1)
        with self.assertRaises(ValueError):rpa.advance(self.company,job)
        from app.infrastructure.ebs_adapter.adapter import SimulationAdapter
        unsafe=dict(calls[0],invoice='ABC\n')
        with self.assertRaises(ValueError):SimulationAdapter().fill(unsafe,{})

    def test_upgrade_from_002_preserves_documents_raw_approvals_and_audit(self):
        old=self.root/'old';old.mkdir();migrations=self.root/'migrations';migrations.mkdir()
        for name in ['001_initial.sql','002_preparation.sql']:(migrations/name).write_bytes((database.MIGRATIONS/name).read_bytes())
        with patch.object(database,'MIGRATIONS',migrations):
            erp=ERP(old)
            try:
                company=erp.company('000000000','ΣΥΝΘΕΤΙΚΗ')
                item=preview(self.root/'input/separate.xlsx')
                for entry in item.records:entry['document'].pop('rounding_minor')
                erp.repository.persist_import(company,item,item)
                doc=erp.search(company)[0]['id'];erp.prepare_document(company,doc,'6','64.03',confirmed=True)
                original=dict(erp.detail(company,doc)[0]);approval=erp.preparation(company,doc)
                raw=[tuple(r) for r in erp.db.execute('SELECT * FROM source_records')]
                audit=[tuple(r) for r in erp.db.execute('SELECT * FROM audit_events')]
            finally:erp.close()
        erp=ERP(old)
        try:
            after=dict(erp.detail(company,doc)[0]);self.assertEqual(after.pop('rounding_minor'),0)
            self.assertEqual(original,after);self.assertEqual(erp.preparation(company,doc),approval)
            self.assertEqual([tuple(r) for r in erp.db.execute('SELECT * FROM source_records')],raw)
            self.assertEqual([tuple(r) for r in erp.db.execute('SELECT * FROM audit_events')],audit)
            self.assertEqual(erp.db.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(erp.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        finally:erp.close()
