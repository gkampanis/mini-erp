"""Synthetic P9 regressions for shared AADE cooldowns and atomic reads."""
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from app.application.mydata import MyData
from app.application.service import ERP
from app.application.sync import Sync
from app.infrastructure.aade.client import Client,RateLimitError
from tests.test_workflow import Opener,response
from tests.test_workspace import MemoryVault


START=END='2026-10-21'
CONTINUATION='<continuationToken><nextPartitionKey>p2</nextPartitionKey><nextRowKey>r2</nextRowKey></continuationToken>'


def limited(seconds='120'):
    return HTTPError('https://example.invalid/synthetic',429,'synthetic',{'Retry-After':seconds},None)


def client(opener,username='synthetic',environment='production',**kwargs):
    return Client(environment,username,'synthetic',opener=opener,**kwargs)


def page(mark='10000001',continuation=''):
    return response(mark=mark,receiver='000000008',continuation=continuation,number=str(int(mark)-10000000))


def snapshot(erp):
    return '\n'.join(erp.db.iterdump()),{p.relative_to(erp.directory).as_posix():p.read_bytes()
        for p in erp.directory.rglob('*') if p.is_file() and p.suffix not in ('.db','.sqlite','.sqlite3')}


class SharedCooldownTests(unittest.TestCase):
    def setUp(self):
        Client._cooldowns.clear()
        self.addCleanup(Client._cooldowns.clear)
        network=patch.object(socket,'create_connection',side_effect=AssertionError('Live network forbidden'))
        network.start();self.addCleanup(network.stop)
        self.clock=patch('app.infrastructure.aade.client.time.monotonic',return_value=100)
        self.now=self.clock.start();self.addCleanup(self.clock.stop)

    def test_equivalent_authenticated_usernames_share_the_same_cooldown(self):
        opener=Opener([limited(),page()])
        with self.assertRaises(RateLimitError):client(opener,username=' synthetic ').fetch(START,END)
        with self.assertRaises(RateLimitError) as caught:client(opener).fetch(START,END)
        self.assertEqual(caught.exception.retry_after,120)
        self.assertEqual(len(opener.requests),1)

    def test_parallel_429_stops_the_next_page_of_an_inflight_fetch(self):
        entered=threading.Event();release=threading.Event();errors=[];returned=[]

        class InflightOpener(Opener):
            def open(inner,request,timeout):
                if not inner.requests:
                    entered.set()
                    if not release.wait(5):raise AssertionError('Synthetic 429 was not released')
                return super().open(request,timeout)

        first=InflightOpener([page(continuation=CONTINUATION),page(mark='10000002')])
        second=Opener([limited()])
        def fetch():
            try:returned.append(client(first).fetch(START,END))
            except Exception as exc:errors.append(exc)
        worker=threading.Thread(target=fetch)
        worker.start()
        try:
            self.assertTrue(entered.wait(5),'First request did not start')
            with self.assertRaises(RateLimitError):client(second).fetch(START,END)
        finally:
            release.set();worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(returned,[])
        self.assertEqual(len(errors),1)
        self.assertIsInstance(errors[0],RateLimitError)
        self.assertEqual(errors[0].retry_after,120)
        self.assertEqual((len(first.requests),len(second.requests)),(1,1))

    def test_shared_429_during_backoff_stops_the_pending_retry(self):
        second=Opener([limited()]);waits=[]
        def backoff(seconds):
            waits.append(seconds)
            with self.assertRaises(RateLimitError):client(second).fetch(START,END)
        first=Opener([HTTPError('https://example.invalid',503,'synthetic',{},None),page()])
        with self.assertRaises(RateLimitError) as caught:client(first,sleep=backoff).fetch(START,END)
        self.assertEqual(caught.exception.retry_after,120)
        self.assertEqual(waits,[1])
        self.assertEqual((len(first.requests),len(second.requests)),(1,1))

    def test_shorter_inflight_429_keeps_the_longer_deadline_and_reported_wait(self):
        second=Opener([limited()])
        class InflightOpener(Opener):
            def open(inner,request,timeout):
                with self.assertRaises(RateLimitError):client(second).fetch(START,END)
                return super().open(request,timeout)
        first=InflightOpener([limited('1')])
        with self.assertRaises(RateLimitError) as caught:client(first).fetch(START,END)
        self.assertEqual(caught.exception.retry_after,120)
        later=Opener([page()]);self.now.return_value=219
        with self.assertRaises(RateLimitError) as caught:client(later).fetch(START,END)
        self.assertEqual(caught.exception.retry_after,1)
        self.assertEqual(len(later.requests),0)
        self.now.return_value=220
        self.assertEqual(len(client(later).fetch(START,END)),1)
        self.assertEqual(len(later.requests),1)

    def test_cooldown_is_scoped_to_authenticated_account_and_environment(self):
        with self.assertRaises(RateLimitError):client(Opener([limited()])).fetch(START,END)
        for username,environment in [('other','production'),('synthetic','test')]:
            with self.subTest(username=username,environment=environment):
                opener=Opener([page()])
                self.assertEqual(len(client(opener,username,environment).fetch(START,END)),1)
                self.assertEqual(len(opener.requests),1)

    def test_initial_and_later_page_429_preserve_all_preexisting_data_without_retry(self):
        for later_page in (False,True):
            with self.subTest(later_page=later_page),tempfile.TemporaryDirectory() as directory:
                Client._cooldowns.clear();erp=ERP(Path(directory),MemoryVault())
                try:
                    company=erp.company('000000008','SYNTHETIC')
                    MyData(erp).fetch(company,START,END,'production',client=client(Opener([page()])))
                    before=snapshot(erp);waits=[]
                    bodies=([page(mark='10000002',continuation=CONTINUATION)] if later_page else [])+[limited()]
                    opener=Opener(bodies)
                    with self.assertRaises(RateLimitError):
                        MyData(erp).fetch(company,START,END,'production',client=client(opener,sleep=waits.append))
                    self.assertEqual(snapshot(erp),before)
                    self.assertEqual(len(opener.requests),2 if later_page else 1)
                    self.assertEqual(waits,[])
                finally:erp.close()

    def test_full_sync_preserves_completed_direction_and_stops_details_and_pdf_on_429(self):
        for completed in (False,True):
            with self.subTest(completed=completed),tempfile.TemporaryDirectory() as directory:
                Client._cooldowns.clear();erp=ERP(Path(directory),MemoryVault())
                try:
                    company=erp.company('000000008','SYNTHETIC')
                    opener=Opener(([page()] if completed else [])+[limited()])
                    with patch('app.application.provider_pdf.run',side_effect=AssertionError('PDF must stop after 429')):
                        result=Sync(erp).run(company,'production',START,END,book=False,client=client(opener),methods=['RequestDocs','RequestTransmittedDocs'])
                    self.assertTrue(result['rate_limited'])
                    self.assertEqual(result['retry_after'],120)
                    self.assertNotIn('pdf',result)
                    self.assertEqual(result['import']['inserted'],int(completed))
                    self.assertEqual(len(opener.requests),2 if completed else 1)
                    self.assertEqual(erp.db.execute('SELECT count(*) FROM documents').fetchone()[0],int(completed))
                    self.assertEqual(erp.db.execute('SELECT count(*) FROM mydata_records').fetchone()[0],int(completed))
                finally:erp.close()


if __name__=='__main__':unittest.main()
