"""Synthetic cancellations must survive invoice arrival and database reopening."""
import tempfile
import unittest
from pathlib import Path

from app.application.service import ERP
from app.application.mydata import MyData
from app.application.rpa import RPA
from app.infrastructure.aade.client import parsed_page
from tests.test_workflow import response
from tests.fixtures import demos
from app.infrastructure.importers.excel import preview


class CancellationRetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.erp=ERP(self.root/'data');self.company=self.erp.company('000000000','SYNTHETIC')
        self.mark='10000001';self.dates=('2026-10-01','2026-10-31')

    def tearDown(self):
        self.erp.close();self.tmp.cleanup()

    def cancelled(self):
        return b'<RequestedDoc/>',dict(records=[],cancellations=[self.mark])

    def invoice(self):
        xml=response();return xml,parsed_page(xml)

    def test_cancellation_before_invoice_same_or_later_sync(self):
        for separate in (False,True):
            with self.subTest(separate=separate):
                environment='test' if separate else 'production'
                service=MyData(self.erp)
                if separate:
                    service.persist(self.company,environment,*self.dates,[self.cancelled()])
                    self.erp.close();self.erp=ERP(self.root/'data');service=MyData(self.erp)
                    service.persist(self.company,environment,*self.dates,[self.invoice()])
                else:service.persist(self.company,environment,*self.dates,[self.cancelled(),self.invoice()])
                self.assertEqual(service.records(self.company,environment)[0]['match_status'],'cancelled_at_aade')
                result=service.import_documents(self.company,environment,*self.dates,confirmed=True)
                self.assertEqual(result['inserted'],0)
                service.reconcile_stored(self.company,environment)
                self.assertEqual(service.records(self.company,environment)[0]['match_status'],'cancelled_at_aade')

    def test_cancellation_isolated_by_company_and_environment(self):
        service=MyData(self.erp)
        service.persist(self.company,'test',*self.dates,[self.cancelled()])
        service.persist(self.company,'production',*self.dates,[self.invoice()])
        self.assertNotEqual(service.records(self.company,'production')[0]['match_status'],'cancelled_at_aade')
        other=self.erp.company('000000009','OTHER')
        xml=response(receiver='000000009');service.persist(other,'test',*self.dates,[(xml,parsed_page(xml))])
        self.assertNotEqual(service.records(other,'test')[0]['match_status'],'cancelled_at_aade')

    def test_late_excel_cannot_bypass_observed_cancellation(self):
        MyData(self.erp).persist(self.company,'production',*self.dates,[self.cancelled()])
        demos(self.root/'input');self.erp.commit_import(self.company,preview(self.root/'input/separate.xlsx'),confirmed=True)
        document=next(row['id'] for row in self.erp.search(self.company) if row['mark']==self.mark)
        self.erp.prepare_document(self.company,document,'6','64.03',confirmed=True)
        with self.assertRaisesRegex(ValueError,'ακύρωσης'):
            RPA(self.erp).payload(self.company,document)

    def test_existing_cancellation_audit_backfilled_without_rewriting_history(self):
        service=MyData(self.erp)
        service.persist(self.company,'production',*self.dates,[self.cancelled()])
        # Simulate an older database that has only the immutable event.
        with self.erp.db:
            if self.erp.db.execute("SELECT 1 FROM sqlite_master WHERE name='mydata_cancellations'").fetchone():
                self.erp.db.execute('DROP TABLE mydata_cancellations')
            self.erp.db.execute("DELETE FROM schema_migrations WHERE version='015_cancellation_observations.sql'")
        before=[tuple(r) for r in self.erp.db.execute('SELECT * FROM audit_events')]
        self.erp.close();self.erp=ERP(self.root/'data');service=MyData(self.erp)
        self.assertEqual([tuple(r) for r in self.erp.db.execute('SELECT * FROM audit_events')],before)
        service.persist(self.company,'production',*self.dates,[self.invoice()])
        self.assertEqual(service.records(self.company,'production')[0]['match_status'],'cancelled_at_aade')
