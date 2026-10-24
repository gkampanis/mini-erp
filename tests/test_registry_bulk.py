"""Explicit, cancellable blank-name batches with simulated registry responses."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from app.application.service import ERP
from app.application.registry import Registry
from app.infrastructure.aade.client import APIError
from app.infrastructure.aade.registry import RegistryAccessError,RegistryLimited,RegistryNotFound,parse,lookup,ENDPOINT
from tests.test_workspace import MemoryVault
from tests.test_supplier_purchases import synthetic_vat
from tests.test_registry import synthetic_response


class RegistryBulkTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.vault=MemoryVault()
        self.erp=ERP(self.root,self.vault);self.company=self.erp.company('000000008','ΣΥΝΘΕΤΙΚΗ')
        self.other=self.erp.company('000000009','ΑΛΛΗ');self.registry=Registry(self.erp)
        self.registry.save_credentials(self.company,'synthetic-reg-user','synthetic-reg-key',confirmed=True)
    def tearDown(self):self.erp.close();self.temp.cleanup()
    def card(self,number,name='',company=None):
        with self.erp.db:
            return self.erp.db.execute('INSERT INTO counterparties(company_id,vat,name) VALUES (?,?,?)',(company or self.company,synthetic_vat(number),name)).lastrowid
    def test_only_blank_names_unique_valid_vats_failures_continue_without_pdf(self):
        for i in range(1,6):self.card(i,' \t\u2003' if i==1 else '')
        named=self.card(6,'ΥΠΑΡΧΟΥΣΑ');self.card(1,'',self.other)
        with self.erp.db:
            self.erp.db.execute("INSERT INTO counterparties(company_id,vat,name) VALUES (?,'ABCDEFGHI','')",(self.company,))
            self.erp.db.execute("INSERT INTO counterparty_accounts(counterparty_id,company_id,expenses_account,preferred_group,approved_by) VALUES (?,?,'64.03','6','local_operator')",(named,self.company))
        before=[tuple(r) for r in self.erp.db.execute('SELECT id,vat,code FROM counterparties')];calls=[];progress=[]
        def response(user,key,caller,called):
            calls.append(called)
            if called==synthetic_vat(2):raise APIError('synthetic-reg-user synthetic-reg-key arbitrary exception')
            if called==synthetic_vat(3):raise RegistryNotFound('synthetic')
            if called==synthetic_vat(4):return dict(afm=synthetic_vat(9),onomasia='ΔΕΝ ΠΡΕΠΕΙ ΝΑ ΓΡΑΦΤΕΙ')
            return dict(afm=called,onomasia='ΣΥΝΘΕΤΙΚΗ ΕΠΩΝΥΜΙΑ')
        result=self.registry.fill_missing(self.company,transport=response,notice=progress.append)
        self.assertEqual((result['filled'],result['skipped'],result['not_found'],result['failed']),(2,1,1,2))
        self.assertEqual(len(calls),5);self.assertEqual(len(set(calls)),5);self.assertEqual(len(progress),6)
        self.assertEqual([tuple(r) for r in self.erp.db.execute('SELECT id,vat,code FROM counterparties')],before)
        self.assertEqual(self.erp.db.execute('SELECT name FROM counterparties WHERE id=?',(named,)).fetchone()[0],'ΥΠΑΡΧΟΥΣΑ')
        self.assertEqual(self.erp.db.execute('SELECT name FROM counterparties WHERE company_id=?',(self.other,)).fetchone()[0],'')
        self.assertEqual(self.erp.db.execute('SELECT expenses_account FROM counterparty_accounts').fetchone()[0],'64.03')
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM provider_attempts').fetchone()[0],0)
        dump='\n'.join(self.erp.db.iterdump())
        for secret in ('synthetic-reg-user','synthetic-reg-key','arbitrary exception'):self.assertNotIn(secret,dump)
        events=[json.loads(r[0]) for r in self.erp.db.execute("SELECT payload FROM audit_events WHERE action='registry_details_applied'")]
        self.assertEqual(len(events),2);self.assertTrue(all(e['blank_only'] and e['source']=='AADE RgWsPublic2' for e in events))
    def test_concurrent_name_edit_is_never_overwritten(self):
        cp=self.card(1)
        def response(*args):
            other=ERP(self.root,self.vault)
            try:
                with other.db:other.db.execute("UPDATE counterparties SET name='ΣΥΜΠΛΗΡΩΘΗΚΕ ΣΤΟ ΜΕΤΑΞΥ' WHERE id=?",(cp,))
            finally:other.close()
            return dict(afm=synthetic_vat(),onomasia='ΑΠΑΝΤΗΣΗ ΜΗΤΡΩΟΥ')
        report=self.registry.fill_missing(self.company,transport=response)
        self.assertEqual(report['skipped'],1);self.assertEqual(report['filled'],0)
        self.assertEqual(self.erp.db.execute('SELECT name FROM counterparties WHERE id=?',(cp,)).fetchone()[0],'ΣΥΜΠΛΗΡΩΘΗΚΕ ΣΤΟ ΜΕΤΑΞΥ')
    def test_access_and_rate_errors_stop_further_requests_and_keep_successes(self):
        for error in (RegistryAccessError,RegistryLimited):
            with self.subTest(error=error):
                with self.erp.db:
                    self.erp.db.execute('DELETE FROM counterparty_roles');self.erp.db.execute('DELETE FROM counterparties')
                for i in range(1,5):self.card(i)
                calls=[]
                def response(*args):
                    calls.append(args[-1])
                    if len(calls)==2:raise error('unsafe remote text')
                    return dict(afm=args[-1],onomasia='ΕΠΙΤΥΧΙΑ')
                report=self.registry.fill_missing(self.company,transport=response)
                self.assertEqual((report['filled'],report['failed'],report['skipped']),(1,1,2));self.assertTrue(report['stopped'])
                self.assertEqual(len(calls),2);self.assertNotIn('unsafe remote text',json.dumps(report))
                with self.erp.db:self.erp.db.execute('DELETE FROM counterparty_registry')
    def test_cancel_between_requests_keeps_completed_results(self):
        self.card(1);self.card(2);cancel=threading.Event();calls=[]
        def response(*args):
            calls.append(args[-1]);cancel.set();return dict(afm=args[-1],onomasia='ΣΥΝΘΕΤΙΚΗ ΕΠΙΤΥΧΙΑ')
        report=self.registry.fill_missing(self.company,transport=response,cancel=cancel)
        self.assertEqual(len(calls),1);self.assertEqual(report['filled'],1);self.assertEqual(report['skipped'],1);self.assertTrue(report['cancelled'])
    def test_invalid_response_names_and_mismatched_vat_are_rejected(self):
        self.card(1)
        for values in [dict(afm=synthetic_vat(),onomasia=' '),dict(afm=synthetic_vat(),onomasia='X\nY'),dict(afm=synthetic_vat(),onomasia=123),dict(afm=synthetic_vat(2),onomasia='ΛΑΘΟΣ')]:
            report=self.registry.fill_missing(self.company,transport=lambda *args:values)
            self.assertEqual(report['filled'],0);self.assertEqual(report['failed'],1)
        with self.assertRaises(RegistryNotFound):parse(synthetic_response(vat='',name=''),synthetic_vat())
    def test_http_access_and_limit_failures_are_sanitized_and_typed(self):
        for status,error in [(401,RegistryAccessError),(403,RegistryAccessError),(429,RegistryLimited),(503,RegistryLimited),(500,APIError)]:
            class Unavailable:
                def open(self,*args,**kwargs):raise HTTPError(ENDPOINT,status,'synthetic-reg-key',{},None)
            with self.assertRaises(error) as caught:lookup('synthetic-reg-user','synthetic-reg-key','000000008',synthetic_vat(),opener=Unavailable())
            self.assertNotIn('synthetic-reg-key',str(caught.exception))
