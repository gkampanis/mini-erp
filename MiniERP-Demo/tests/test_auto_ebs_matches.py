"""Automatic positive EBS evidence; synthetic sources and no posting calls."""
import unittest
from app.infrastructure.importers.excel import read_workbook
from app.application.service import ERP
from tests import test_ebs_reconciliation as fixtures
from tests.fixtures import HEADERS,ROW,workbook


class AutomaticMatchesTests(unittest.TestCase):
    setUp=fixtures.ReconciliationTests.setUp
    tearDown=fixtures.ReconciliationTests.tearDown
    packet=fixtures.ReconciliationTests.packet
    save=fixtures.ReconciliationTests.save

    def automatic(self,rows):
        path=self.root/'automatic.xlsx';workbook(path,[HEADERS,*rows])
        book=read_workbook(path)
        layout=dict(sheet=book['sheets'][0]['name'],header_row=1,mapping=fixtures.MAPPING)
        return self.service.apply_matches(self.company,book,layout,month='2026-10')

    def test_selection_applies_positive_matches_and_preserves_document_identity(self):
        before=[tuple(r) for r in self.erp.db.execute('SELECT * FROM documents')]
        report=self.automatic([ROW])
        self.assertEqual(report['exact_matches'],1)
        self.assertTrue(self.service.results(self.company)[self.document]['file_matched'])
        self.assertEqual([tuple(r) for r in self.erp.db.execute('SELECT * FROM documents')],before)
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM rpa_jobs').fetchone()[0],0)

    def test_partial_positive_import_keeps_previous_complete_readiness(self):
        self.save([],complete=True);self.save([ROW])
        result=self.service.results(self.company)
        other=next(d for d in self.ids if d!=self.document)
        self.assertEqual(result[other]['status'],'not_registered')
        self.service.assert_rpa(self.company,[other],required=True)

    def test_a_later_partial_file_does_not_resurrect_previous_matches(self):
        self.save([ROW],complete=True);self.save([]);self.save([])
        self.assertEqual(self.service.results(self.company)[self.document]['status'],'registered')

    def test_no_previous_complete_evidence_is_not_invented_by_automatic_import(self):
        self.automatic([ROW]);other=next(d for d in self.ids if d!=self.document)
        self.assertNotEqual(self.service.results(self.company)[other]['status'],'not_registered')
        with self.assertRaises(ValueError):self.service.assert_rpa(self.company,[other],required=True)

    def test_automatic_repeated_import_survives_restart_without_duplicate_documents(self):
        self.automatic([ROW]);self.automatic([ROW])
        other=ERP(self.root/'data')
        try:
            from app.application.ebs_reconciliation import EBSReconciliation
            self.assertTrue(EBSReconciliation(other).results(self.company)[self.document]['file_matched'])
            self.assertEqual(len(other.search(self.company)),2)
        finally:other.close()

    def test_financial_conflicts_are_never_claimed_as_matched(self):
        self.save([],complete=True)
        row=list(ROW);row[5]='0.11';row[7]='0.13';self.automatic([row])
        result=self.service.results(self.company)[self.document]
        self.assertFalse(result['file_matched']);self.assertEqual(result['status'],'review')
        with self.assertRaises(ValueError):self.service.assert_rpa(self.company,[self.document],required=True)

    def test_automatic_import_is_scoped_to_the_active_company(self):
        path=self.root/'other.xlsx';workbook(path,[HEADERS,ROW]);book=read_workbook(path)
        layout=dict(sheet=book['sheets'][0]['name'],header_row=1,mapping=fixtures.MAPPING)
        self.service.apply_matches(self.other,book,layout,month='2026-10')
        self.assertTrue(all(r['status']=='unreconciled' for r in self.service.results(self.company).values()))
        self.assertEqual(self.service.results(self.other),{})
