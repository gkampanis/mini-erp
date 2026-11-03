"""Bound query growth and preserve company/calendar scopes on synthetic volume."""
from pathlib import Path
import tempfile
import unittest
from app.application.service import ERP
from app.application.workspace import Workspace
from app.application.counterparties import Counterparties
from app.application.supplier_accounts import SupplierAccounts
from app.application.rpa import RPA
from app.infrastructure.importers.excel import preview
from tests.fixtures import volume_workbook


class VolumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.folder=Path(cls.temp.name)
        cls.erp=ERP(cls.folder/'data');cls.company=cls.erp.company('000000000','ΣΥΝΘΕΤΙΚΗ')
        cls.other=cls.erp.company('000000009','ΑΛΛΗ ΣΥΝΘΕΤΙΚΗ')
        volume_workbook(cls.folder/'volume.xlsx')
        cls.erp.commit_import(cls.company,preview(cls.folder/'volume.xlsx'),confirmed=True)

    @classmethod
    def tearDownClass(cls):cls.erp.close();cls.temp.cleanup()

    def counted(self,fn):
        calls=[];self.erp.db.set_trace_callback(calls.append)
        try:result=fn()
        finally:self.erp.db.set_trace_callback(None)
        return result,len(calls)

    def test_lists_do_not_query_once_per_document_or_supplier(self):
        rows,queries=self.counted(lambda:Workspace(self.erp).rows(self.company))
        self.assertEqual(len(rows),2500);self.assertLessEqual(queries,10)
        cards,queries=self.counted(lambda:SupplierAccounts(self.erp).rows(self.company))
        self.assertEqual(len(cards),300);self.assertLessEqual(queries,10)
        self.assertEqual(sum(c['document_count'] for c in cards),2500)
        cp=cards[0]['id'];(_,docs),queries=self.counted(lambda:Counterparties(self.erp).detail(self.company,cp))
        self.assertLessEqual(queries,5);self.assertTrue(docs)
        self.assertTrue(all(d['counterparty_id']==cp for d in docs))
        self.assertEqual(SupplierAccounts(self.erp).rows(self.other),[])

    def test_month_query_filters_before_rpa_without_changing_sources(self):
        september=Workspace(self.erp).rows(self.company,month='2026-09')
        october=Workspace(self.erp).rows(self.company,month='2026-10')
        self.assertEqual((len(september),len(october)),(1250,1250))
        self.assertTrue(all(r['issue_date']=='2026-09-15' for r in september))
        self.assertFalse({r['id'] for r in september}&{r['id'] for r in october})
        scope,queries=self.counted(lambda:RPA(self.erp).expense_scope(self.company,[r['id'] for r in september]))
        self.assertLessEqual(queries,4);self.assertEqual(len(scope['needs_review']),1250)  # One additional batched purchase-tag query.
        self.assertEqual(len(self.erp.search(self.company)),2500)
        self.assertEqual(self.erp.search(self.other,month='2026-09'),[])
        self.assertEqual(self.erp.search(self.company,month='2026-12'),[])
        with self.assertRaises(ValueError):self.erp.search(self.company,month='2026-13')
        with self.assertRaises(ValueError):Counterparties(self.erp).detail(self.other,september[0]['counterparty_id'])
