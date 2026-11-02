"""Operator-selected retries and explicit continuation after posting issues."""
import unittest
from app.application.ebs_reconciliation import EBSReconciliation
from tests import test_posting_actions as fixtures
from tests.test_workflow import FakeEBS

class PostingIssueContinuationTests(unittest.TestCase):
    setUp=fixtures.PostingActionsTests.setUp
    tearDown=fixtures.PostingActionsTests.tearDown
    run_job=fixtures.PostingActionsTests.run_job

    def test_explicit_selection_retries_failed_document_without_unlocking_history(self):
        old=self.rpa.posting(self.company,self.ids[:1])['job']
        self.run_job(old,FakeEBS(fail='save'))
        before=self.rpa.items(self.company,old)[1]
        fresh=self.rpa.posting(self.company,self.ids[:1])
        self.assertEqual(fresh['documents'],self.ids[:1])
        self.assertIsNotNone(fresh['job'])
        fake=FakeEBS();result=self.run_job(fresh['job'],fake)
        self.assertEqual(result['status'],'completed')
        self.assertEqual([c[1] for c in fake.calls if c[0]=='fill'],self.ids[:1])
        self.assertEqual(self.rpa.items(self.company,old)[1],before)

    def test_old_running_database_state_does_not_lock_new_selection(self):
        old=self.rpa.posting(self.company,self.ids[:2])['job']
        with self.erp.db:self.erp.db.execute("UPDATE rpa_jobs SET status='running' WHERE id=?",(old,))
        report=self.rpa.posting(self.company,self.ids[2:3])
        self.assertEqual(report['documents'],self.ids[2:3])
        self.assertIsNotNone(report['job'])

    def test_continuation_skips_failed_item_and_fills_next_once(self):
        job=self.rpa.posting(self.company,self.ids[:2])['job']
        result=self.run_job(job,FakeEBS(fail='save'))
        item=self.rpa.items(self.company,job)[1][0]
        self.rpa.continue_after_issue(self.company,job,item['id'])
        fake=FakeEBS();last=self.run_job(job,fake,resume=True)
        self.assertEqual(last['status'],'completed')
        self.assertEqual(fake.calls[0][0],'new')
        self.assertEqual([c[1] for c in fake.calls if c[0]=='fill'],self.ids[1:2])
        self.assertEqual(self.rpa.items(self.company,job)[1][0]['status'],'uncertain')
        state=EBSReconciliation(self.erp).results(self.company)[self.ids[0]]
        self.assertFalse(state['submitted']);self.assertNotEqual(state['status'],'registered')

    def test_preflight_issue_continuation_does_not_repeat_same_queued_item(self):
        job=self.rpa.posting(self.company,self.ids[:2])['job']
        with self.assertRaises(RuntimeError):self.run_job(job,FakeEBS(fail='prepare'))
        item=self.rpa.items(self.company,job)[1][0]
        self.rpa.continue_after_issue(self.company,job,item['id'])
        self.assertEqual(self.rpa.items(self.company,job)[1][0]['status'],'failed')
        fake=FakeEBS();self.run_job(job,fake,resume=True)
        self.assertEqual([c[1] for c in fake.calls if c[0]=='fill'],self.ids[1:2])

    def test_failed_new_reports_that_save_was_sent_and_stays_pending(self):
        job=self.rpa.posting(self.company,self.ids[:2])['job']
        result=self.run_job(job,FakeEBS(fail='new'))
        self.assertEqual(result['issue_phase'],'new')
        self.assertTrue(result['save_may_have_been_sent'])
        self.assertEqual(result['item_id'],self.rpa.items(self.company,job)[1][0]['id'])
        state=EBSReconciliation(self.erp).results(self.company)[self.ids[0]]
        self.assertFalse(state['submitted']);self.assertNotEqual(state['status'],'registered')

    def test_selected_batch_has_no_automatic_pause_at_forty(self):
        report=self.rpa.posting(self.company,self.ids[:41]);fake=FakeEBS()
        result=self.run_job(report['job'],fake)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(len([c for c in fake.calls if c[0]=='fill']),41)

    def test_later_registered_document_does_not_fail_healthy_current_item(self):
        job=self.rpa.posting(self.company,self.ids[:3])['job']
        EBSReconciliation(self.erp).confirm_manual(self.company,self.ids[1],'Synthetic later registration',confirmed=True)
        fake=FakeEBS();result=self.rpa.advance(self.company,job,live_confirmed=True,adapter=fake)
        self.assertEqual(result['item_status'],'ui_saved_review')
        self.assertEqual([c[1] for c in fake.calls if c[0]=='fill'],self.ids[:1])
        with self.assertRaises(ValueError):self.rpa.advance(self.company,job,live_confirmed=True,adapter=fake)

    def test_later_changed_payload_is_checked_only_when_its_turn_arrives(self):
        job=self.rpa.posting(self.company,self.ids[:2])['job']
        with self.erp.db:self.erp.db.execute("UPDATE document_preparations SET account_code='64.99' WHERE company_id=? AND document_id=?",(self.company,self.ids[1]))
        fake=FakeEBS();result=self.rpa.advance(self.company,job,live_confirmed=True,adapter=fake)
        self.assertEqual(result['item_status'],'ui_saved_review')
        self.assertEqual([c[1] for c in fake.calls if c[0]=='fill'],self.ids[:1])
        with self.assertRaises(ValueError):self.rpa.advance(self.company,job,live_confirmed=True,adapter=fake)

    def test_profile_change_is_a_queue_issue_not_a_failed_document(self):
        job=self.rpa.posting(self.company,self.ids[:2])['job']
        changed=dict(self.profile,save=[101,200]);self.workspace.save_profile(self.company,changed)
        fake=FakeEBS()
        with self.assertRaises(ValueError) as caught:self.rpa.advance(self.company,job,live_confirmed=True,adapter=fake)
        self.assertTrue(getattr(caught.exception,'queue_issue',False))
        self.assertEqual(fake.calls,[])
        self.assertEqual([i['status'] for i in self.rpa.items(self.company,job)[1]],['queued','queued'])

    def test_ancient_failure_does_not_force_new_after_a_later_fresh_form(self):
        old=self.rpa.posting(self.company,self.ids[:1])['job'];self.run_job(old,FakeEBS(fail='save'))
        current=self.rpa.posting(self.company,self.ids[1:3])['job'];fake=FakeEBS()
        result=self.rpa.advance(self.company,current,live_confirmed=True,adapter=fake,continue_after_pause=True)
        self.assertEqual(result['item_status'],'ui_saved_review')
        self.rpa.pause(self.company,current)
        fresh=self.rpa.posting(self.company,self.ids[3:4])['job']
        self.assertEqual(self.rpa.items(self.company,fresh)[0]['need_new'],0)

    def test_new_issue_does_not_announce_obsolete_replay_lock(self):
        job=self.rpa.posting(self.company,self.ids[:2])['job'];fake=FakeEBS()
        def failed_new(point):raise RuntimeError('Δεν αναγνωρίστηκε σταθερό νέο ΤΕΔ. Δεν επιτρέπεται επανάληψη παραστατικού.')
        fake.open_new=failed_new;result=self.run_job(job,fake)
        self.assertNotIn('Δεν επιτρέπεται επανάληψη',result['reason'])
        self.assertIn('Δεν αναγνωρίστηκε σταθερό νέο ΤΕΔ',result['reason'])

    def test_real_registered_evidence_still_excludes_document(self):
        EBSReconciliation(self.erp).confirm_manual(self.company,self.ids[0],'Synthetic confirmed registration',confirmed=True)
        report=self.rpa.posting(self.company,self.ids[:1])
        self.assertIsNone(report['job'])

if __name__=='__main__':unittest.main()
