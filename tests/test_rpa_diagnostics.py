"""Offline posting failure reports: actionable phase data, no invoice payloads."""
import ctypes
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from app.application.service import ERP
from app.application.rpa import RPA
from app.application.workspace import Workspace
from app.infrastructure.crashlog import export
from app.infrastructure.ebs_adapter.adapter import FIELDS
from app.infrastructure.ebs_adapter.diagnostics import native_snapshot,write_report
from app.infrastructure.importers.excel import preview
from tests.fixtures import HEADERS,ROW,workbook,reconcile_empty
from tests.test_workflow import FakeEBS


class RPAFailureReportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.erp=ERP(self.root/'data');self.company=self.erp.company('000000008','SECRET COMPANY')
        rows=[HEADERS]
        for index in range(2):
            row=list(ROW);row[3]='PRIVATE-DOCUMENT-'+str(index);row[8]=str(10000001+index);rows.append(row)
        workbook(self.root/'sample.xlsx',rows)
        self.erp.commit_import(self.company,preview(self.root/'sample.xlsx'),confirmed=True)
        reconcile_empty(self.erp,self.company)
        self.ids=[r['id'] for r in self.erp.search(self.company)]
        self.profile=dict(mapping={f:[10,20] for f,_ in FIELDS},save=[100,200],new=[300,400])
        ws=Workspace(self.erp);ws.save_profile(self.company,self.profile)
        ws.approve_many(self.company,[dict(document=d,group='6',account='64.03') for d in self.ids],confirmed=True)
        with self.erp.db:self.erp.db.execute('UPDATE ebs_profiles SET pilot_at=CURRENT_TIMESTAMP WHERE company_id=?',(self.company,))
        self.rpa=RPA(self.erp)
    def tearDown(self):self.erp.close();self.temp.cleanup()
    def reports(self):return sorted((self.erp.directory/'diagnostics').glob('ebs-failure-*.json'))
    def run_first(self,fail,documents=None):
        job=self.rpa.posting(self.company,documents or self.ids)['job']
        backend=FakeEBS(fail=fail)
        return job,backend,self.rpa.advance(self.company,job,adapter=backend,live_confirmed=True)
    def test_prepare_report_keeps_original_error_and_no_input_or_replay(self):
        job=self.rpa.posting(self.company,self.ids)['job'];backend=FakeEBS(fail='prepare')
        with self.assertRaisesRegex(RuntimeError,'synthetic target mismatch') as raised:
            self.rpa.advance(self.company,job,adapter=backend,live_confirmed=True)
        self.assertEqual([c[0] for c in backend.calls],['prepare'])
        self.assertEqual(len(self.reports()),1)
        report=json.loads(self.reports()[0].read_text())
        self.assertEqual(raised.exception.diagnostic_report,self.reports()[0].name)
        self.assertEqual(report['phase'],'prepare');self.assertFalse(report['input_claimed'])
        self.assertEqual(report['profile_points']['AFM_CREDITOR'],[10,20])
        self.assertEqual(report['queue_counts'],{'queued':2});self.assertFalse(report['save_may_have_been_sent'])
        self.assertEqual(report['native']['status'],'NOT_AVAILABLE')
    def assert_failure_stage(self,stage):
        job=self.rpa.posting(self.company,self.ids)['job']
        backend=FakeEBS(fail=stage)
        result=self.rpa.advance(self.company,job,adapter=backend,live_confirmed=True)
        report=json.loads(self.reports()[-1].read_text())
        self.assertEqual(result['item_status'],'uncertain');self.assertIn('diagnostics/ebs-failure-',result['reason'])
        self.assertEqual(report['phase'],stage);self.assertTrue(report['input_claimed'])
        self.assertEqual(report['save_pending_recorded'],stage in ('save','new'))
        self.assertEqual(report['save_returned_recorded'],stage=='new')
        self.assertEqual(report['save_may_have_been_sent'],stage in ('save','new'))
    def test_fill_failure_report_has_no_save_evidence(self):self.assert_failure_stage('fill')
    def test_save_failure_report_marks_possible_save_without_acknowledgement(self):self.assert_failure_stage('save')
    def test_new_failure_report_proves_save_returned_without_asserting_storage(self):self.assert_failure_stage('new')
    def test_report_export_omits_exception_secrets_and_payload_but_keeps_safe_failure(self):
        job=self.rpa.posting(self.company,self.ids)['job'];item=self.rpa.items(self.company,job)[1][0]
        unsafe='SECRET key=credentials https://private.example/ PRIVATE-DOCUMENT-0'
        path=write_report(self.erp,self.company,job,item['id'],'prepare',RuntimeError(unsafe),profile=self.profile)
        safe='Δεν επαληθεύτηκε ο MDIClient του νέου ΤΕΔ.'
        write_report(self.erp,self.company,job,item['id'],'prepare',RuntimeError(safe))
        destination=self.root/'support.txt';export(self.erp.directory,destination);text=destination.read_text()
        for private in ('SECRET','credentials','https://','PRIVATE-DOCUMENT','000000008',str(self.root)):
            self.assertNotIn(private,text)
        self.assertIn(safe,text);self.assertIn('queue_counts',text);self.assertIn('pointer_bits',text)
        self.assertEqual(json.loads(path.read_text())['exception']['message'],'Non-allowlisted message omitted')
    def test_pyautogui_panic_keeps_identifiable_type_without_private_message(self):
        panic=type('FailSafeException',(Exception,),{'__module__':'pyautogui'})
        job=self.rpa.posting(self.company,self.ids)['job'];backend=FakeEBS()
        backend.fill=Mock(side_effect=panic('private failsafe context'))
        result=self.rpa.advance(self.company,job,adapter=backend,live_confirmed=True)
        report=json.loads(self.reports()[0].read_text())
        self.assertEqual(result['item_status'],'uncertain')
        self.assertIn('διακοπή ασφαλείας του ποντικιού',result['reason'])
        self.assertEqual(report['exception']['type'],'FailSafeException')
        self.assertEqual(report['exception']['code'],'pyautogui_failsafe')
        self.assertNotIn('private failsafe context',self.reports()[0].read_text())
        self.assertFalse(any(call[0]=='save' for call in backend.calls))
    def test_unwritable_diagnostics_never_changes_original_exception(self):
        (self.erp.directory/'diagnostics').write_text('occupied path')
        job=self.rpa.posting(self.company,self.ids)['job']
        with self.assertRaisesRegex(RuntimeError,'synthetic target mismatch') as raised:
            self.rpa.advance(self.company,job,adapter=FakeEBS(fail='prepare'),live_confirmed=True)
        self.assertFalse(hasattr(raised.exception,'diagnostic_report'))
    def test_report_failure_cannot_mask_prepare_exception_and_retention_is_bounded(self):
        job=self.rpa.posting(self.company,self.ids)['job'];item=self.rpa.items(self.company,job)[1][0]
        for _ in range(23):self.assertIsNotNone(write_report(self.erp,self.company,job,item['id'],'preflight',RuntimeError()))
        self.assertEqual(len(self.reports()),20)
        with patch('app.infrastructure.ebs_adapter.diagnostics.native_snapshot',side_effect=RuntimeError('private')):
            file=write_report(self.erp,self.company,job,item['id'],'prepare',RuntimeError('private'))
            self.assertEqual(json.loads(file.read_text())['native']['status'],'PARTIAL')
        with patch('app.infrastructure.ebs_adapter.diagnostics.write_report',return_value=None):
            with self.assertRaisesRegex(RuntimeError,'synthetic target mismatch'):
                self.rpa.advance(self.company,job,adapter=FakeEBS(fail='prepare'),live_confirmed=True)


class NativeFailureSnapshotTests(unittest.TestCase):
    def test_observes_mapped_field_parent_owner_rect_focus_without_reading_window_text(self):
        user=SimpleNamespace()
        user.GetForegroundWindow=Mock(return_value=100)
        user.GetParent=Mock(side_effect=lambda h:{220:200,200:150,150:100}.get(h,0))
        user.GetAncestor=Mock(return_value=100);user.GetWindow=Mock(return_value=0)
        user.WindowFromPoint=Mock(return_value=220);user.IsWindowVisible=Mock(return_value=1)
        def process(h,result):result._obj.value=77;return 12
        user.GetWindowThreadProcessId=Mock(side_effect=process)
        def cls(h,result,size):result.value='MDIClient' if h==150 else 'WindowsForms10.Window';return len(result.value)
        user.GetClassNameW=Mock(side_effect=cls)
        def rect(h,result):
            result._obj.left=5;result._obj.top=8;result._obj.right=800;result._obj.bottom=600;return 1
        user.GetWindowRect=Mock(side_effect=rect)
        def gui(tid,result):result._obj.hwndFocus=220;result._obj.hwndActive=200;return 1
        user.GetGUIThreadInfo=Mock(side_effect=gui)
        backend=SimpleNamespace(expected_ted=200,_mdi_forms=lambda:{200})
        profile=dict(mapping={'AFM_CREDITOR':[40,50]},save=[60,70],new=[80,90])
        with patch('app.infrastructure.ebs_adapter.diagnostics.sys.platform','win32'),patch.object(ctypes,'windll',SimpleNamespace(user32=user),create=True):
            report=native_snapshot(backend,profile)
        self.assertEqual(report['status'],'OBSERVED');self.assertEqual(report['expected_ted'],200)
        self.assertEqual(report['points']['AFM_CREDITOR']['parent_chain'],[220,200,150,100])
        self.assertEqual(report['points']['AFM_CREDITOR']['point'],[40,50])
        self.assertEqual(report['focus']['focused'],220)
        self.assertFalse(hasattr(user,'GetWindowTextW'));self.assertFalse(hasattr(user,'SendMessageTimeoutW'))
        self.assertEqual(len(report['windows']),4)
