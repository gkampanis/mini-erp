"""Known EBS duplicate evidence completes only its current invoice, without Save."""
import unittest
from app.application.ebs_reconciliation import EBSReconciliation
from app.infrastructure.ebs_adapter.duplicates import DuplicateExistingDocument
from tests import test_posting_actions as fixtures
from tests.test_workflow import FakeEBS


class DuplicatePostingTests(unittest.TestCase):
    setUp=fixtures.PostingActionsTests.setUp
    tearDown=fixtures.PostingActionsTests.tearDown

    def backend(self,*,dismissed=True,mismatch=False,new_failure=False):
        class Backend(FakeEBS):
            def fill(self,payload,mapping):
                super().fill(payload,mapping)
                if not getattr(self,'warned',False):
                    self.warned=True
                    raise DuplicateExistingDocument(vat='WRONG' if mismatch else payload['vat'],invoice=payload['invoice'],expected_ted=self.handle,existing_reference='TED-0-123',existing_date='16/09/2026 12:00:00 πμ',existing_amount='4,01',dismissed=dismissed)
        return Backend(fail='new' if new_failure else None)

    def test_known_duplicate_registers_only_trigger_and_continues_without_save(self):
        job=self.rpa.posting(self.company,self.ids[:2])['job'];backend=self.backend()
        first=self.rpa.advance(self.company,job,live_confirmed=True,adapter=backend)
        self.assertEqual(first['status'],'running');self.assertEqual(first['item_status'],'duplicate_existing')
        self.assertFalse(any(c[0]=='save' for c in backend.calls))
        states=EBSReconciliation(self.erp).results(self.company)
        self.assertEqual(states[self.ids[0]]['status'],'registered')
        self.assertNotEqual(states[self.ids[1]]['status'],'registered')
        last=self.rpa.advance(self.company,job,live_confirmed=True,adapter=backend)
        self.assertEqual(last['status'],'completed')
        self.assertEqual(sum(c[0]=='save' for c in backend.calls),1)
        self.assertIsNone(self.rpa.posting(self.company,self.ids[:1])['job'])

    def test_manual_dismissal_pauses_and_resume_opens_new_without_replaying(self):
        job=self.rpa.posting(self.company,self.ids[:2])['job'];backend=self.backend(dismissed=False)
        first=self.rpa.advance(self.company,job,live_confirmed=True,adapter=backend)
        self.assertTrue(first['duplicate_needs_dismissal']);self.assertEqual(first['status'],'paused')
        self.assertFalse(any(c[0] in ('save','new') for c in backend.calls))
        result=self.rpa.advance(self.company,job,live_confirmed=True,adapter=backend,continue_after_pause=True)
        self.assertEqual(result['status'],'completed')
        self.assertEqual([c[1] for c in backend.calls if c[0]=='fill'],self.ids[:2])

    def test_new_failure_keeps_duplicate_registered_and_does_not_replay_it(self):
        job=self.rpa.posting(self.company,self.ids[:2])['job'];backend=self.backend(new_failure=True)
        first=self.rpa.advance(self.company,job,live_confirmed=True,adapter=backend)
        self.assertEqual(first['status'],'paused');self.assertTrue(first['duplicate_needs_dismissal'])
        self.assertEqual(EBSReconciliation(self.erp).results(self.company)[self.ids[0]]['status'],'registered')

    def test_unmatched_identity_is_normal_issue_not_registration(self):
        job=self.rpa.posting(self.company,self.ids[:1])['job']
        result=self.rpa.advance(self.company,job,live_confirmed=True,adapter=self.backend(mismatch=True))
        self.assertEqual(result['item_status'],'uncertain')
        self.assertNotEqual(EBSReconciliation(self.erp).results(self.company)[self.ids[0]]['status'],'registered')

    def test_evidence_is_bound_to_invoice_snapshot(self):
        job=self.rpa.posting(self.company,self.ids[:1])['job']
        self.rpa.advance(self.company,job,live_confirmed=True,adapter=self.backend())
        with self.erp.db:self.erp.db.execute("UPDATE documents SET number=number||'X' WHERE id=?",(self.ids[0],))
        self.assertNotEqual(EBSReconciliation(self.erp).results(self.company)[self.ids[0]]['status'],'registered')

    def test_next_batch_after_last_duplicate_opens_a_new_form(self):
        job=self.rpa.posting(self.company,self.ids[:1])['job']
        self.rpa.advance(self.company,job,live_confirmed=True,adapter=self.backend())
        fresh=self.rpa.posting(self.company,self.ids[1:2])['job']
        self.assertEqual(self.rpa.items(self.company,fresh)[0]['need_new'],1)
        backend=FakeEBS()
        self.rpa.advance(self.company,fresh,live_confirmed=True,adapter=backend)
        self.assertEqual(backend.calls[0][0],'new')


if __name__=='__main__':unittest.main()
