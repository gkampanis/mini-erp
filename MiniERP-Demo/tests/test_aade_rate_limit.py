"""Synthetic HTTP429 must stop the batch and respect the service cooldown."""
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from app.infrastructure.aade.client import Client,RateLimitError
from app.application.service import ERP
from app.application.sync import Sync
from tests.test_workflow import Opener

class RateLimitTests(unittest.TestCase):
    def setUp(self):Client._cooldowns.clear()
    def tearDown(self):Client._cooldowns.clear()
    def test_retry_after_blocks_all_methods_and_new_clients_without_network(self):
        opener=Opener([HTTPError('https://example.com',429,'synthetic',{'Retry-After':'120'},None)])
        waits=[];client=Client('production','synthetic','synthetic',opener=opener,sleep=waits.append)
        with self.assertRaises(RateLimitError) as caught:client.fetch('2026-09-01','2026-09-30')
        self.assertEqual(caught.exception.retry_after,120)
        other=Client('production','synthetic','synthetic',opener=opener)
        with self.assertRaises(RateLimitError):other.fetch('2026-09-01','2026-09-30',method='RequestTransmittedDocs')
        self.assertEqual(len(opener.requests),1);self.assertEqual(waits,[])
    def test_book_rate_limit_stops_details_and_pdf_and_preserves_existing_data(self):
        with tempfile.TemporaryDirectory() as directory:
            erp=ERP(Path(directory));company=erp.company('000000008','SYNTHETIC')
            try:
                opener=Opener([HTTPError('https://example.com',429,'synthetic',{},None)])
                client=Client('production','synthetic','synthetic',opener=opener)
                result=Sync(erp).run(company,'production','2026-09-01','2026-09-30',client=client,methods=['RequestDocs','RequestTransmittedDocs'])
                self.assertTrue(result['rate_limited']);self.assertGreater(result['retry_after'],0)
                self.assertEqual(len(opener.requests),1);self.assertNotIn('received',result);self.assertNotIn('pdf',result)
                self.assertEqual(erp.db.execute('SELECT count(*) FROM mydata_syncs').fetchone()[0],0)
            finally:erp.close()
