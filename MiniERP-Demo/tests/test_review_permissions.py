"""Explicit review permission changes scheduling, never evidence or native history."""
import json
import unittest
from unittest.mock import patch
from app.application.ebs_reconciliation import EBSReconciliation
from tests import test_posting_actions as fixtures
from tests.fixtures import workbook,HEADERS,ROW
from tests.test_workflow import FakeEBS


class ReviewPermissionTests(unittest.TestCase):
    setUp=fixtures.PostingActionsTests.setUp
    tearDown=fixtures.PostingActionsTests.tearDown

    def service(self):
        from app.application.review_permissions import ReviewPermissions
        return ReviewPermissions(self.erp)
    def ambiguous(self):
        row=list(ROW);row[3]=self.rows[0]['number'];row[8]=self.rows[0]['mark']
        path=self.root/'ambiguous.xlsx';workbook(path,[HEADERS,row,row])
        service=EBSReconciliation(self.erp)
        self.packet=service.preview(self.company,path,'Συνθετικά',1,dict(vat=0,series=2,number=3,date=4,net=5,tax=6,gross=7,mark=8),'2026-10-01','2026-10-31','000000008',complete=True,company_confirmed=True)
        service.commit(self.packet,confirmed=True)
    def authorize(self,documents=None):
        documents=documents or self.ids[:1];rows=self.service().inspect(self.company,documents)
        return self.service().authorize(self.company,documents,{r['document']:r['signature'] for r in rows},confirmed=True)
    def legacy_blank_reference(self):
        """Emulate append-only pre-P941 evidence; current imports ignore this row."""
        from app.domain.ebs_matching import normalize,compare
        headers=['Ημερομηνία','Σχόλιο','Εναλ. παρ/κό','Άλλο','ΑΦΜ','Άλλο 2','Άλλο 3','Καθαρή αξία','ΦΠΑ','Σύνολο']
        raw={0:ROW[4],2:'',4:ROW[0],7:ROW[5],8:ROW[6],9:ROW[7]}
        mapping=dict(date=0,invoice=2,vat=4,net=7,tax=8,gross=9)
        path=self.root/'legacy.xlsx';workbook(path,[headers,[],[],[],[],[raw.get(i,'') for i in range(10)]])
        service=EBSReconciliation(self.erp)
        packet=service.preview(self.company,path,'Συνθετικά',1,mapping,'2026-10-01','2026-10-31','000000008',complete=True,company_confirmed=True)
        self.assertEqual(packet['rows'],[])
        self.assertTrue(any(r['row']==6 for r in packet['ignored_rows']))
        source=service.commit(packet,confirmed=True)['run']
        fields='company_id,company_vat,date_from,date_to,filename,sha256,storage_path,sheet,header_row,mapping_json,complete,report_json,match_policy'
        normalized,error=normalize(raw,mapping)
        error='C6 · Εναλ. παρ/κό: '+error
        document=next(r for r in service.documents(self.company) if r['id']==self.ids[0])
        frozen=compare([document],[dict(row=6,raw=raw,normalized=normalized,error=error)],True)[document['id']]
        self.assertEqual(frozen['status'],'review')
        with self.erp.db:
            legacy=self.erp.db.execute('INSERT INTO ebs_reconciliation_runs('+fields+') SELECT '+fields+' FROM ebs_reconciliation_runs WHERE id=?',(source,)).lastrowid
            self.erp.db.execute('INSERT INTO ebs_excel_rows(run_id,row_number,raw_json,normalized_json,error) VALUES (?,6,?,?,?)',(legacy,json.dumps(raw),json.dumps(normalized),error))
            self.erp.db.execute('INSERT INTO ebs_matches(run_id,document_id,status,reason,excel_rows_json,snapshot_hash,match_kind,match_signature) VALUES (?,?,?,?,?,?,?,?)',
                (legacy,document['id'],frozen['status'],frozen['reason'],json.dumps(frozen['excel_rows']),frozen['snapshot_hash'],frozen['match_kind'],frozen['match_signature']))
        return error
    def test_legacy_blank_C6_review_allows_explicit_attempt_and_preserves_frozen_error(self):
        error=self.legacy_blank_reference();document=self.ids[0];review=self.service().inspect(self.company,[document])[0]
        self.assertIn('C6',review['reason']);self.assertEqual(review['excel_issues'],[dict(row=6,error=error)])
        self.authorize();job=self.rpa.posting(self.company,[document])['job'];backend=FakeEBS()
        result=self.rpa.advance(self.company,job,live_confirmed=True,adapter=backend)
        self.assertEqual(result['item_status'],'save_invoked')
        self.assertEqual(sum(c[0]=='save' for c in backend.calls),1)
        self.assertEqual(self.erp.db.execute('SELECT error FROM ebs_excel_rows WHERE row_number=6 ORDER BY id DESC LIMIT 1').fetchone()[0],error)
    def test_legacy_blank_C6_permission_preserves_known_duplicate_handling_without_save(self):
        from app.infrastructure.ebs_adapter.duplicates import DuplicateExistingDocument
        self.legacy_blank_reference();self.authorize();document=self.ids[0]
        class Backend(FakeEBS):
            def fill(self,payload,mapping):
                super().fill(payload,mapping)
                raise DuplicateExistingDocument(vat=payload['vat'],invoice=payload['invoice'],expected_ted=self.handle,existing_reference='SYNTHETIC-TED-1',existing_date='21/10/2026 12:00:00 πμ',existing_amount='0,12',dismissed=True)
        job=self.rpa.posting(self.company,[document])['job'];backend=Backend()
        result=self.rpa.advance(self.company,job,live_confirmed=True,adapter=backend)
        self.assertEqual(result['item_status'],'duplicate_existing');self.assertFalse(any(c[0]=='save' for c in backend.calls))
        self.assertEqual(EBSReconciliation(self.erp).results(self.company)[document]['status'],'registered')
        self.assertEqual(self.service().inspect(self.company,[document]),[])
    def test_explicit_permission_allows_plan_and_assert_but_keeps_review_status(self):
        self.ambiguous();document=self.ids[0];before=EBSReconciliation(self.erp).results(self.company)[document]
        self.assertEqual(before['status'],'review')
        self.assertFalse(before.get('posting_permitted',False))
        self.assertEqual(self.rpa.plan(self.company,[document])['documents'],[])
        self.authorize()
        after=EBSReconciliation(self.erp).results(self.company)[document]
        self.assertEqual(after['status'],'review');self.assertTrue(after['posting_permitted'])
        self.assertEqual(self.rpa.posting(self.company,[document])['documents'],[document])
        EBSReconciliation(self.erp).assert_rpa(self.company,[document],required=True)
    def test_permission_requires_confirmation_and_exact_atomic_snapshot(self):
        self.ambiguous();service=self.service();rows=service.inspect(self.company,self.ids[:1])
        signatures={r['document']:r['signature'] for r in rows}
        with self.assertRaises(ValueError):service.authorize(self.company,self.ids[:1],signatures,confirmed=False)
        signatures[self.ids[0]]='stale'
        with self.assertRaises(ValueError):service.authorize(self.company,self.ids[:1],signatures,confirmed=True)
        self.assertEqual(self.erp.db.execute("SELECT count(*) FROM audit_events WHERE action='ebs_review_posting_authorized'").fetchone()[0],0)
    def test_identical_reimport_keeps_permission_but_changed_excel_revokes_it(self):
        self.ambiguous();self.authorize();service=EBSReconciliation(self.erp)
        service.commit(self.packet,confirmed=True)
        self.assertTrue(service.results(self.company)[self.ids[0]]['posting_permitted'])
        changed=dict(self.packet);changed['mapping']=dict(changed['mapping'],series=None)
        # Re-map a formerly mapped optional column using the same archived bytes.
        changed['mapping'].pop('series')
        service.commit(changed,confirmed=True)
        self.assertFalse(service.results(self.company)[self.ids[0]]['posting_permitted'])
    def test_changed_document_and_company_identity_revoke_permission(self):
        self.ambiguous();self.authorize();document=self.ids[0]
        with self.erp.db:self.erp.db.execute('UPDATE documents SET net_minor=net_minor+1,gross_minor=gross_minor+1 WHERE id=?',(document,))
        self.assertFalse(EBSReconciliation(self.erp).results(self.company)[document]['posting_permitted'])
        with self.erp.db:self.erp.repository.audit(self.company,'company_identified',None,dict())
        self.assertEqual(self.service().inspect(self.company,[document])[0]['posting_permitted'],False)
    def test_registered_and_outgoing_are_not_reviewable(self):
        self.ambiguous();document=self.ids[0]
        EBSReconciliation(self.erp).confirm_manual(self.company,document,'Synthetic check',confirmed=True)
        self.assertEqual(self.service().inspect(self.company,[document]),[])
        document=self.ids[1]
        with self.erp.db:self.erp.db.execute("UPDATE documents SET direction='outgoing' WHERE id=?",(document,))
        self.assertEqual(self.service().inspect(self.company,[document]),[])
    def test_xml_or_mydata_gate_cannot_be_overridden(self):
        self.ambiguous()
        with patch('app.application.vat_lines.VATLines.analysis',return_value=dict(status='invalid',errors=['source_integrity'])):
            self.assertEqual(self.service().inspect(self.company,self.ids[:1]),[])
        with patch('app.application.rpa.RPA.live_source',side_effect=ValueError('cancelled or different source')):
            self.assertEqual(self.service().inspect(self.company,self.ids[:1]),[])
    def test_purchase_never_receives_permission_but_missing_account_remains_independent_gate(self):
        self.ambiguous();document=self.ids[0]
        with self.erp.db:self.erp.db.execute("INSERT INTO document_purchase_tags(company_id,document_id,rule_version) VALUES (?,?,1)",(self.company,document))
        self.assertEqual(self.service().inspect(self.company,[document]),[])
        with self.erp.db:
            self.erp.db.execute('DELETE FROM document_purchase_tags WHERE company_id=?',(self.company,))
            self.erp.db.execute('DELETE FROM counterparty_accounts WHERE company_id=?',(self.company,))
        self.authorize();self.assertTrue(EBSReconciliation(self.erp).results(self.company)[document]['posting_permitted'])
        self.assertIsNone(self.rpa.posting(self.company,[document])['job'])
    def test_missing_profile_does_not_prevent_excel_permission_but_still_blocks_posting(self):
        self.ambiguous();document=self.ids[0]
        with self.erp.db:self.erp.db.execute('DELETE FROM ebs_profiles WHERE company_id=?',(self.company,))
        self.authorize();self.assertTrue(EBSReconciliation(self.erp).results(self.company)[document]['posting_permitted'])
        with self.assertRaises(ValueError):self.rpa.posting(self.company,[document])
    def test_submitted_or_positive_duplicate_never_receive_permission(self):
        self.ambiguous();self.authorize();document=self.ids[0]
        job=self.rpa.posting(self.company,[document])['job']
        self.rpa.advance(self.company,job,live_confirmed=True,adapter=FakeEBS())
        self.assertTrue(EBSReconciliation(self.erp).results(self.company)[document]['submitted'])
        self.assertEqual(self.service().inspect(self.company,[document]),[])
    def test_stale_permission_blocks_already_queued_work_before_any_native_call(self):
        self.ambiguous();self.authorize();document=self.ids[0]
        job=self.rpa.posting(self.company,[document])['job']
        changed=dict(self.packet);changed['mapping']=dict(changed['mapping']);changed['mapping'].pop('series')
        EBSReconciliation(self.erp).commit(changed,confirmed=True)
        backend=FakeEBS()
        with self.assertRaises(ValueError):self.rpa.advance(self.company,job,live_confirmed=True,adapter=backend)
        self.assertEqual(backend.calls,[])
    def test_other_company_cannot_authorize_or_use_permission(self):
        self.ambiguous();rows=self.service().inspect(self.company,self.ids[:1]);self.authorize()
        other=self.erp.company('000000009','OTHER SYNTHETIC')
        self.assertEqual(self.service().inspect(other,self.ids[:1]),[])
        with self.assertRaises(ValueError):self.service().authorize(other,self.ids[:1],{r['document']:r['signature'] for r in rows},confirmed=True)
    def test_changed_vat_detail_distribution_invalidates_permission_even_if_header_totals_match(self):
        self.ambiguous()
        analysis=dict(status='verified',currency='EUR',totals=dict(net_minor=10,tax_minor=2,gross_minor=12),
                      lines=[dict(line_number=1,net_minor=10,tax_minor=2,vat_category=1)])
        with patch('app.application.vat_lines.VATLines.analysis',return_value=analysis):self.authorize()
        changed=dict(analysis,lines=[dict(line_number=1,net_minor=10,tax_minor=2,vat_category=2)])
        with patch('app.application.vat_lines.VATLines.analysis',return_value=changed):
            self.assertFalse(EBSReconciliation(self.erp).results(self.company)[self.ids[0]]['posting_permitted'])
    def test_multiline_mapping_remains_a_hard_posting_gate_after_excel_permission(self):
        self.ambiguous();self.authorize()
        lines=[dict(net_minor=5,tax_minor=1,account='64.09',vat_category=1,line_number=1),dict(net_minor=5,tax_minor=1,account='64.03',vat_category=2,line_number=2)]
        with patch('app.application.vat_lines.VATLines.posting_lines',return_value=lines):
            self.assertTrue(self.service().inspect(self.company,self.ids[:1])[0]['posting_permitted'])
            self.assertIsNone(self.rpa.posting(self.company,self.ids[:1])['job'])
    def test_permission_for_no_covering_export_allows_attempt_without_claiming_absence(self):
        document=self.ids[0]
        with self.erp.db:self.erp.db.execute("UPDATE documents SET issue_date='2100-01-01' WHERE id=?",(document,))
        self.authorize();row=EBSReconciliation(self.erp).results(self.company)[document]
        self.assertEqual(row['status'],'unreconciled');self.assertTrue(row['posting_permitted'])
        self.assertEqual(self.rpa.posting(self.company,[document])['documents'],[document])
    def test_inspection_is_read_only_and_audit_failure_rolls_back(self):
        self.ambiguous();changes=self.erp.db.total_changes;rows=self.service().inspect(self.company,self.ids[:1])
        self.assertEqual(self.erp.db.total_changes,changes)
        with patch.object(self.erp.repository,'audit',side_effect=RuntimeError('synthetic audit failure')):
            with self.assertRaises(RuntimeError):self.service().authorize(self.company,self.ids[:1],{r['document']:r['signature'] for r in rows},confirmed=True)
        self.assertEqual(self.erp.db.execute("SELECT count(*) FROM audit_events WHERE action='ebs_review_posting_authorized'").fetchone()[0],0)
    def test_partial_export_absence_can_be_waived_without_marking_registered(self):
        document=self.ids[0]
        with self.erp.db:self.erp.db.execute("UPDATE documents SET issue_date='2100-01-01' WHERE id=?",(document,))
        path=self.root/'partial.xlsx';workbook(path,[HEADERS])
        service=EBSReconciliation(self.erp)
        packet=service.preview(self.company,path,'Συνθετικά',1,dict(vat=0,series=2,number=3,date=4,net=5,tax=6,gross=7,mark=8),'2100-01-01','2100-01-31','000000008',complete=False,company_confirmed=True)
        service.commit(packet,confirmed=True)
        self.assertEqual(service.results(self.company)[document]['status'],'not_found')
        self.authorize();row=service.results(self.company)[document]
        self.assertEqual(row['status'],'not_found');self.assertTrue(row['posting_permitted'])
    def test_outer_transaction_permission_batch_is_atomic_on_second_audit_failure(self):
        document1,document2=self.ids[:2]
        with self.erp.db:self.erp.db.execute("UPDATE documents SET issue_date='2100-01-01' WHERE id IN (?,?)",(document1,document2))
        rows=self.service().inspect(self.company,[document1,document2]);original=self.erp.repository.audit;calls=[]
        def audit(*args,**kwargs):
            calls.append(args)
            if len(calls)==2:raise RuntimeError('second audit failed')
            return original(*args,**kwargs)
        self.erp.db.execute('BEGIN IMMEDIATE')
        try:
            with patch.object(self.erp.repository,'audit',side_effect=audit):
                with self.assertRaises(RuntimeError):self.service().authorize(self.company,[document1,document2],{r['document']:r['signature'] for r in rows},confirmed=True)
            self.assertTrue(self.erp.db.in_transaction)
            self.assertEqual(self.erp.db.execute("SELECT count(*) FROM audit_events WHERE action='ebs_review_posting_authorized'").fetchone()[0],0)
        finally:self.erp.db.rollback()
