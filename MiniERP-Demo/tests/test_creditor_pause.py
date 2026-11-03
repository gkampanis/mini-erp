"""A stalled VAT editor pauses this invoice before later fields or Save."""
import unittest
from tests import test_posting_actions as fixtures
from tests.test_workflow import FakeEBS
from app.infrastructure.ebs_adapter.duplicates import CreditorResolutionRequired
from app.application.ebs_reconciliation import EBSReconciliation


class CreditorPauseTests(unittest.TestCase):
    setUp=fixtures.PostingActionsTests.setUp
    tearDown=fixtures.PostingActionsTests.tearDown

    def test_resume_retries_same_invoice_without_new_or_false_registration(self):
        class Backend(FakeEBS):
            blocked=False
            def fill(self,payload,mapping):
                super().fill(payload,mapping)
                if not self.blocked:
                    self.blocked=True
                    raise CreditorResolutionRequired(vat=payload['vat'],invoice=payload['invoice'],expected_ted=self.handle)
        job=self.rpa.posting(self.company,self.ids[:2])['job'];backend=Backend()
        result=self.rpa.advance(self.company,job,live_confirmed=True,adapter=backend)
        self.assertTrue(result['creditor_resolution_required'])
        self.assertFalse(any(c[0] in ('save','new') for c in backend.calls))
        meta,items=self.rpa.items(self.company,job)
        self.assertEqual(meta['need_new'],0);self.assertEqual(items[0]['status'],'queued')
        self.assertNotEqual(EBSReconciliation(self.erp).results(self.company)[self.ids[0]]['status'],'registered')
        result=self.rpa.advance(self.company,job,live_confirmed=True,adapter=backend,continue_after_pause=True)
        self.assertEqual(result['item_status'],'ui_saved_review')
        self.assertEqual([c[1] for c in backend.calls if c[0]=='fill'],[self.ids[0],self.ids[0]])
        self.assertEqual(sum(c[0]=='save' for c in backend.calls),1)


if __name__=='__main__':unittest.main()
