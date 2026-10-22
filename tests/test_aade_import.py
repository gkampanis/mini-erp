"""Synthetic coverage for automatic imports and original-source name repair."""
import tempfile
import unittest
from pathlib import Path
from app.application.service import ERP
from app.application.mydata import MyData
from app.application.names import NameRecovery
from app.infrastructure.importers.excel import preview,header_mapping
from app.infrastructure.aade.client import Client,APIError
from app.infrastructure.aade.book import parse_book
from tests.fixtures import workbook,HEADERS,ROW
from tests.test_workflow import Opener,response

class AutomaticImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.erp=ERP(self.root/'data');self.company=self.erp.company('000000000','ΣΥΝΘΕΤΙΚΗ')
    def tearDown(self):self.erp.close();self.tmp.cleanup()
    def test_api_without_excel_creates_one_unapproved_document_and_reuses_it(self):
        service=MyData(self.erp)
        client=Client('test','synthetic','synthetic',opener=Opener([response()]))
        service.fetch(self.company,'2026-10-21','2026-10-21','test',client=client)
        result=service.import_incoming(self.company,'test','2026-10-21','2026-10-21',confirmed=True)
        self.assertEqual(result['inserted'],1)
        self.assertEqual(service.records(self.company,'test')[0]['match_status'],'matched')
        again=service.import_incoming(self.company,'test','2026-10-21','2026-10-21',confirmed=True)
        self.assertEqual(again['duplicates'],1)
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM document_preparations').fetchone()[0],0)
    def test_repair_existing_names_preserves_document_and_raw(self):
        headers=list(HEADERS);headers[1]='Επωνυμία / Ονοματεπώνυμο Εκδότη'
        path=self.root/'book.xlsx';workbook(path,[headers,ROW])
        self.erp.commit_import(self.company,preview(path),confirmed=True)
        original=tuple(self.erp.db.execute('SELECT * FROM documents').fetchone())
        with self.erp.db:self.erp.db.execute('UPDATE counterparties SET name=vat')
        result=NameRecovery(self.erp).run(self.company)
        self.assertEqual(result['updated'],1)
        self.assertEqual(self.erp.db.execute('SELECT name FROM counterparties').fetchone()[0],ROW[1])
        self.assertEqual(tuple(self.erp.db.execute('SELECT * FROM documents').fetchone()),original)
        self.assertEqual(NameRecovery(self.erp).run(self.company)['updated'],0)
    def test_issuer_mapping_does_not_use_recipient_or_fixed_position(self):
        mapping=header_mapping(dict(enumerate(['Επωνυμία Λήπτη','ΑΦΜ','Επωνυμία Εκδότη'])))
        self.assertEqual(mapping['name'],2)
    def test_aggregate_book_is_separate_and_get_has_no_mark(self):
        xml=b'<RequestedBookInfo><bookInfo><counterVatNumber>000000001</counterVatNumber><issueDate>2026-10-21</issueDate><invType>1.1</invType><count>3</count><netValue>30</netValue></bookInfo></RequestedBookInfo>'
        opener=Opener([xml]);client=Client('test','synthetic','synthetic',opener=opener)
        pages=client.fetch('2026-10-21','2026-10-21',method='RequestMyExpenses')
        self.assertEqual(pages[0][1]['rows'][0]['count'],'3')
        self.assertNotIn('mark=',opener.requests[0].full_url)
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM documents').fetchone()[0],0)
        with self.assertRaises(APIError):parse_book(xml.replace(b'<count>3',b'<count>0'))
    def test_pdf_downloaded_before_excel_is_linked_after_import(self):
        import hashlib
        from app.application.provider_pdf import ProviderDatabase
        from tests.test_workspace import synthetic_pdf
        service=MyData(self.erp)
        service.fetch(self.company,'2026-10-21','2026-10-21','test',client=Client('test','synthetic','synthetic',opener=Opener([response()])))
        data=synthetic_pdf();file=self.root/'synthetic.pdf';file.write_bytes(data)
        adapter=ProviderDatabase(self.erp,self.company,'test')
        adapter.record_pdf(str(self.company),'10000001','saved_unverified',hashlib.sha256(b'https://example.com/synthetic.pdf').hexdigest(),str(file),hashlib.sha256(data).hexdigest(),len(data))
        path=self.root/'book.xlsx';workbook(path,[HEADERS,ROW])
        self.erp.commit_import(self.company,preview(path),confirmed=True)
        document=self.erp.search(self.company)[0]['id']
        self.assertEqual(len(self.erp.attachments(self.company,document)),1)
        adapter.link_cached('10000001')
        self.assertEqual(len(self.erp.attachments(self.company,document)),1)
