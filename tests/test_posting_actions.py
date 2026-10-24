"""One shared posting queue, scoped mappings and native-free batch regressions."""
import tempfile
import unittest
from pathlib import Path
from app.application.service import ERP
from app.application.workspace import Workspace
from app.application.rpa import RPA
from app.application.supplier_accounts import SupplierAccounts
from app.application.ebs_reconciliation import EBSReconciliation
from app.infrastructure.ebs_adapter.adapter import FIELDS
from app.infrastructure.importers.excel import preview
from tests.fixtures import HEADERS,ROW,workbook,reconcile_empty
from tests.test_workflow import FakeEBS

class PostingActionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.erp=ERP(self.root/'data');self.company=self.erp.company('000000008','SYNTHETIC')
        rows=[HEADERS]
        for index in range(43):
            row=list(ROW);row[3]='POST'+str(index);row[8]=str(99000000+index);rows.append(row)
        workbook(self.root/'batch.xlsx',rows);self.erp.commit_import(self.company,preview(self.root/'batch.xlsx'),confirmed=True)
        reconcile_empty(self.erp,self.company)
        self.rows=self.erp.search(self.company);self.ids=[r['id'] for r in self.rows];self.cp=self.rows[0]['counterparty_id']
        # Save an approved rule, without eagerly preparing other documents.
        SupplierAccounts(self.erp).save(self.company,[self.cp],'6','64.09',confirmed=True,apply_pending=False)
        self.workspace=Workspace(self.erp);self.rpa=RPA(self.erp)
        self.profile=dict(mapping={f:[10,20] for f,_ in FIELDS},save=[100,200],new=[300,400])
        self.workspace.save_profile(self.company,self.profile)
        # A previous explicitly verified pilot is represented synthetically.
        with self.erp.db:self.erp.db.execute("UPDATE ebs_profiles SET pilot_at=CURRENT_TIMESTAMP WHERE company_id=?",(self.company,))
    def tearDown(self):self.erp.close();self.tmp.cleanup()
    def run_job(self,job,backend,*,resume=False):
        first=True
        while True:
            result=self.rpa.advance(self.company,job,live_confirmed=True,adapter=backend,continue_after_pause=resume if first else False)
            first=False
            if result['status']!='running':return result
    def test_40_visible_order_mapping_and_next_batch_do_not_replay(self):
        order=list(reversed(self.ids));report=self.rpa.posting(self.company,order,limit=40)
        self.assertEqual(report['documents'],order[:40]);fake=FakeEBS()
        result=self.run_job(report['job'],fake)
        self.assertEqual(result['status'],'completed')
        self.assertEqual([x[1] for x in fake.calls if x[0]=='fill'],order[:40])
        items=self.rpa.items(self.company,report['job'])[1]
        self.assertTrue(all(i['payload']['account']=='64.09' for i in items))
        self.assertTrue(all(self.erp.preparation(self.company,d) is None for d in order[40:]))
        next_batch=self.rpa.posting(self.company,order,limit=40)
        self.assertEqual(next_batch['documents'],order[40:]);second=FakeEBS()
        self.run_job(next_batch['job'],second,resume=True)
        self.assertEqual(second.calls[0][0],'new')
        self.assertEqual([x[1] for x in second.calls if x[0]=='fill'],order[40:])
        p=self.rpa.progress(self.company,next_batch['job']);self.assertEqual(p['processed'],3)
        self.assertEqual(p['verified_in_ebs'],0);self.assertEqual(p['save_requested'],3)
    def test_selected_41_preserves_checkpoint_and_requires_explicit_resume(self):
        report=self.rpa.posting(self.company,self.ids[:41]);fake=FakeEBS()
        result=self.run_job(report['job'],fake);self.assertEqual(result['status'],'paused')
        self.assertEqual(len([x for x in fake.calls if x[0]=='fill']),40)
        with self.assertRaises(ValueError):self.rpa.advance(self.company,report['job'],live_confirmed=True,adapter=fake)
        result=self.run_job(report['job'],fake,resume=True)
        self.assertEqual(result['status'],'completed');self.assertEqual(len([x for x in fake.calls if x[0]=='fill']),41)
        self.assertEqual(self.rpa.progress(self.company,report['job'])['processed'],41)
    def test_registered_missing_mapping_and_other_company_do_not_contaminate_selection(self):
        registered=self.ids[0];EBSReconciliation(self.erp).confirm_manual(self.company,registered,'Synthetic visual check',confirmed=True)
        with self.erp.db:self.erp.db.execute('DELETE FROM counterparty_accounts WHERE company_id=?',(self.company,))
        report=self.rpa.posting(self.company,self.ids[:2]);self.assertIsNone(report['job']);self.assertEqual(len(report['skipped']),2)
        other=self.erp.company('000000009','OTHER')
        with self.assertRaises(ValueError):self.rpa.plan(other,self.ids[:1])
        self.assertIsNone(self.erp.preparation(self.company,self.ids[1]))
    def test_one_missing_rule_is_skipped_while_safe_selected_entry_continues(self):
        with self.erp.db:self.erp.db.execute('DELETE FROM counterparty_accounts WHERE company_id=?',(self.company,))
        self.erp.prepare_document(self.company,self.ids[1],'6','64.03',confirmed=True)
        report=self.rpa.posting(self.company,self.ids[:2])
        self.assertEqual(report['documents'],[self.ids[1]])
        self.assertEqual([r['document'] for r in report['skipped']],[self.ids[0]])
        fake=FakeEBS();self.run_job(report['job'],fake)
        self.assertEqual([r[1] for r in fake.calls if r[0]=='fill'],[self.ids[1]])
        self.assertEqual(self.rpa.progress(self.company,report['job'])['skipped'],1)

    def test_single_and_pilot_gate_keep_first_attempt_to_one(self):
        with self.erp.db:self.erp.db.execute('UPDATE ebs_profiles SET pilot_at=NULL WHERE company_id=?',(self.company,))
        report=self.rpa.posting(self.company,self.ids,limit=40)
        self.assertTrue(report['pilot']);self.assertEqual(report['documents'],self.ids[:1])
        fake=FakeEBS();self.run_job(report['job'],fake)
        self.assertEqual([c[0] for c in fake.calls],['prepare','fill','save'])
        self.assertIsNone(self.workspace.profile(self.company)['pilot_at'])
    def test_uncertain_save_persists_and_blocks_new_batch_until_review(self):
        report=self.rpa.posting(self.company,self.ids[:1]);fake=FakeEBS(fail='save')
        result=self.run_job(report['job'],fake);self.assertEqual(result['item_status'],'uncertain')
        self.erp.close();self.erp=ERP(self.root/'data');self.rpa=RPA(self.erp);self.rpa.recover(self.company)
        with self.assertRaises(ValueError):self.rpa.posting(self.company,self.ids[1:2])
        self.assertEqual(self.rpa.items(self.company,report['job'])[1][0]['status'],'uncertain')
    def test_new_filtered_scope_keeps_old_unattempted_items_in_history(self):
        report=self.rpa.posting(self.company,self.ids[:2]);job=report['job']
        self.rpa.pause(self.company,job);before=self.rpa.items(self.company,job)[1]
        selected=self.rpa.posting(self.company,self.ids[2:3])
        self.assertNotEqual(selected['job'],job)
        self.assertEqual(selected['documents'],self.ids[2:3])
        self.assertEqual(self.rpa.items(self.company,job)[1],before)
        self.assertEqual(self.rpa.items(self.company,job)[0]['status'],'stopped')
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM rpa_jobs').fetchone()[0],2)

    def test_fill_failure_keeps_safe_field_reason_and_shareable_stack_without_secrets(self):
        from unittest.mock import Mock
        report=self.rpa.posting(self.company,self.ids[:1]);fake=FakeEBS()
        fake.fill=Mock(side_effect=RuntimeError('Δεν επαληθεύτηκε το EBS στο πεδίο AFM_CREDITOR. Δεν στάλθηκε Save.'))
        result=self.run_job(report['job'],fake)
        self.assertEqual(result['item_status'],'uncertain')
        self.assertIn('AFM_CREDITOR',result['reason'])
        self.assertFalse(any(call[0]=='save' for call in fake.calls))
        log=(self.erp.directory/'diagnostics'/'crashlog.jsonl').read_text()
        self.assertIn('app/application/rpa.py',log);self.assertNotIn('AFM_CREDITOR',log)
        self.assertNotIn('POST0',log)

    def test_primary_action_resumes_matching_paused_queue_without_creating_new_job(self):
        first=self.rpa.posting(self.company,self.ids[:2],limit=40);job=first['job']
        self.rpa.pause(self.company,job);before=self.rpa.items(self.company,job)
        resumed=self.rpa.posting(self.company,self.ids,limit=40)
        self.assertEqual(resumed['job'],job);self.assertTrue(resumed['resumed'])
        self.assertEqual(self.rpa.items(self.company,job),before)
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM rpa_jobs').fetchone()[0],1)
        fake=FakeEBS();self.run_job(job,fake,resume=True)
        self.assertEqual([r[1] for r in fake.calls if r[0]=='fill'],self.ids[:2])
    def test_filtered_subset_and_reordered_view_never_run_hidden_old_queue_items(self):
        old=self.rpa.posting(self.company,self.ids[:3])['job'];self.rpa.pause(self.company,old)
        before=self.rpa.items(self.company,old)[1]
        chosen=[self.ids[2],self.ids[0]]
        report=self.rpa.posting(self.company,chosen)
        self.assertEqual(report['documents'],chosen)
        self.assertEqual(self.rpa.items(self.company,old)[1],before)
        fake=FakeEBS();self.run_job(report['job'],fake)
        self.assertEqual([r[1] for r in fake.calls if r[0]=='fill'],chosen)
        self.assertIsNone(self.erp.preparation(self.company,self.ids[3]))
        planned=self.rpa.plan(self.company,self.ids[:4])
        self.assertEqual(planned['documents'],[self.ids[1],self.ids[3]])

    def test_scope_replacement_is_atomic_and_cannot_replace_running_or_uncertain_jobs(self):
        from unittest.mock import patch
        old=self.rpa.posting(self.company,self.ids[:2])['job'];self.rpa.pause(self.company,old)
        before=self.rpa.items(self.company,old);audit=self.erp.repository.audit
        def failing(company,action,*args,**kwargs):
            if action=='rpa_queued':raise RuntimeError('Synthetic transaction failure')
            return audit(company,action,*args,**kwargs)
        with patch.object(self.erp.repository,'audit',side_effect=failing):
            with self.assertRaises(RuntimeError):self.rpa.posting(self.company,self.ids[2:3])
        self.assertEqual(self.rpa.items(self.company,old),before)
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM rpa_jobs').fetchone()[0],1)
        with self.erp.db:self.erp.db.execute("UPDATE rpa_jobs SET status='running' WHERE id=?",(old,))
        with self.assertRaises(ValueError):self.rpa.posting(self.company,self.ids[2:3])
        with self.erp.db:
            self.erp.db.execute("UPDATE rpa_jobs SET status='paused' WHERE id=?",(old,))
            self.erp.db.execute("UPDATE rpa_items SET status='uncertain' WHERE job_id=? AND document_id=?",(old,self.ids[0]))
        with self.assertRaises(ValueError):self.rpa.posting(self.company,self.ids[2:3])
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM rpa_jobs').fetchone()[0],1)

    def test_stop_during_prepare_prevents_a_stale_worker_from_claiming_the_old_queue(self):
        job=self.rpa.posting(self.company,self.ids[:1])['job'];fake=FakeEBS();prepare=fake.prepare
        def stop_before_claim(*args):
            result=prepare(*args);self.rpa.stop(self.company,job);return result
        fake.prepare=stop_before_claim
        with self.assertRaises(ValueError):self.run_job(job,fake)
        self.assertEqual([r[0] for r in fake.calls],['prepare'])
        self.assertEqual(self.rpa.items(self.company,job)[1][0]['status'],'queued')
        self.rpa.blocked(self.company,job,'Late worker returned after stop')
        self.assertEqual(self.rpa.items(self.company,job)[0]['status'],'stopped')
