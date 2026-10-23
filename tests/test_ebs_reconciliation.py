"""Synthetic accounting evidence and anti-replay checks; no customer export data."""
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from app.application.service import ERP
from app.application.ebs_reconciliation import EBSReconciliation
from app.application.rpa import RPA
from app.application.mydata import MyData
from app.infrastructure.importers.excel import preview
from app.infrastructure.aade.client import parsed_page
from tests.fixtures import demos,workbook,HEADERS,ROW,reconcile_empty
from tests.test_workflow import response

MAPPING={'vat':0,'series':2,'number':3,'date':4,'net':5,'tax':6,'gross':7,'mark':8}

class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.erp=ERP(self.root/'data')
        self.company=self.erp.company('000000000','ΣΥΝΘΕΤΙΚΗ');self.other=self.erp.company('000000009','ΑΛΛΗ ΣΥΝΘΕΤΙΚΗ')
        demos(self.root/'input');self.erp.commit_import(self.company,preview(self.root/'input/separate.xlsx'),confirmed=True)
        self.service=EBSReconciliation(self.erp);self.ids=[r['id'] for r in self.erp.search(self.company)]
        self.document=self.erp.search(self.company,'10000001')[0]['id']
    def tearDown(self):self.erp.close();self.temp.cleanup()
    def packet(self,rows,*,complete=False,mapping=None,company=None):
        path=self.root/'export.xlsx';workbook(path,[HEADERS,*rows]);company=company or self.company
        owner=self.erp.db.execute('SELECT vat FROM companies WHERE id=?',(company,)).fetchone()[0]
        return self.service.preview(company,path,'Συνθετικά',1,mapping or MAPPING,'2026-10-01','2026-10-31',owner,complete=complete,company_confirmed=True)
    def save(self,rows,**kwargs):return self.service.commit(self.packet(rows,**kwargs),confirmed=True,remember=True)
    def test_five_column_export_commits_without_date_and_keeps_selected_period(self):
        path=self.root/'five-columns.xlsx'
        workbook(path,[['Εναλ. παρ/κό','Α.Φ.Μ.','Αξία','ΦΠΑ','Σύνολο'],['1','000000001','0,10','0,02','0,12']])
        mapping={'invoice':0,'vat':1,'net':2,'tax':3,'gross':4}
        def preview(start,end):return self.service.preview(self.company,path,'Συνθετικά',1,mapping,start,end,'000000000',complete=True,company_confirmed=True)
        self.assertEqual(preview('2026-09-01','2026-09-30')['results'],{})
        packet=preview('2026-10-01','2026-10-31')
        self.assertFalse(packet['rows'][0]['error']);self.assertNotIn('date',packet['rows'][0]['normalized'])
        self.service.commit(packet,confirmed=True,remember=True)
        self.assertEqual(self.service.results(self.company)[self.document]['status'],'registered')
        self.assertEqual(self.service.saved_mapping(self.company,{i:h for i,h in enumerate(['Εναλ. παρ/κό','Α.Φ.Μ.','Αξία','ΦΠΑ','Σύνολο'])}),mapping)
        self.assertEqual(self.ids,[r['id'] for r in self.erp.search(self.company)])
    def test_exact_match_missing_vs_complete_and_mapping_persist(self):
        result=self.save([ROW]);states=self.service.results(self.company)
        self.assertEqual(states[self.document]['status'],'registered')
        other=next(r for r in states.values() if r['id']!=self.document)
        self.assertEqual(other['status'],'not_found')
        with self.assertRaises(ValueError):self.service.assert_rpa(self.company,[other['id']],required=True)
        self.save([ROW],complete=True);states=self.service.results(self.company)
        self.assertEqual(states[other['id']]['status'],'not_registered')
        self.service.assert_rpa(self.company,[other['id']],required=True)
        self.assertEqual(self.service.saved_mapping(self.company,{i:h for i,h in enumerate(HEADERS)}),MAPPING)
        self.assertEqual(len(self.erp.search(self.company)),2)
    def test_same_supplier_day_amount_different_number_is_not_matched(self):
        row=list(ROW);row[3]='DIFFERENT';row[8]='';self.save([row],complete=True)
        self.assertEqual(self.service.results(self.company)[self.document]['status'],'not_registered')
    def test_mark_conflict_date_change_and_duplicates_require_review(self):
        for rows in ([list(ROW)],[ROW,ROW]):
            if len(rows)==1:rows[0][4]='22/10/2026'
            with self.subTest(rows=len(rows)):
                p=self.packet(rows,complete=True);self.assertEqual(p['results'][self.document]['status'],'review')
                self.service.commit(p,confirmed=True)
                with self.assertRaises(ValueError):self.service.assert_rpa(self.company,[self.document])
    def test_company_period_and_missing_data_fail_closed(self):
        p=self.packet([ROW]);path=self.root/'export.xlsx'
        with self.assertRaises(ValueError):self.service.preview(self.company,path,'Συνθετικά',1,MAPPING,'2026-09-01','2026-09-30','000000000',company_confirmed=True)
        with self.assertRaises(ValueError):self.service.preview(self.company,path,'Συνθετικά',1,MAPPING,'2026-10-01','2026-10-31','000000009',company_confirmed=True)
        row=list(ROW);row[0]='123'
        blocked=self.packet([row],complete=True)
        self.assertFalse(blocked['can_commit'])
        with self.assertRaises(ValueError):self.service.commit(blocked,confirmed=True)
        self.assertTrue(self.packet([row])['rows'][0]['error'])
        self.assertEqual(self.service.results(self.other),{})
        self.assertTrue(all(r['status']=='unreconciled' for r in self.service.results(self.company).values()))
    def test_source_is_reparsed_and_rollback_preserves_history(self):
        p=self.packet([ROW],complete=True);p['rows']=[];p['results']={}
        self.service.commit(p,confirmed=True)
        self.assertEqual(self.service.results(self.company)[self.document]['status'],'registered')
        before=self.erp.db.execute('SELECT count(*) FROM ebs_reconciliation_runs').fetchone()[0]
        with patch.object(self.erp.repository,'audit',side_effect=RuntimeError('synthetic')):
            with self.assertRaises(RuntimeError):self.save([],complete=True)
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM ebs_reconciliation_runs').fetchone()[0],before)
        with self.assertRaises(sqlite3.IntegrityError),self.erp.db:self.erp.db.execute('DELETE FROM ebs_matches')
    def test_saved_counts_follow_commit_snapshot_without_stale_preview_totals(self):
        packet=self.packet([ROW],complete=True)
        self.assertEqual(packet['results'][self.document]['status'],'registered')
        with self.erp.db:self.erp.db.execute('UPDATE documents SET net_minor=net_minor+1,gross_minor=gross_minor+1 WHERE id=?',(self.document,))
        report=self.service.commit(packet,confirmed=True)
        self.assertEqual(report.get('registered',0),0);self.assertEqual(report['review'],1)
        stored=json.loads(self.erp.db.execute('SELECT report_json FROM ebs_reconciliation_runs WHERE id=?',(report['run'],)).fetchone()[0])
        self.assertEqual(stored.get('registered',0),0);self.assertEqual(stored['review'],1)
    def test_new_export_preserves_positive_evidence_and_prior_attempts(self):
        self.save([ROW],complete=True);self.save([],complete=True)
        self.assertEqual(self.service.results(self.company)[self.document]['status'],'review')
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM ebs_reconciliation_runs').fetchone()[0],2)
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM ebs_matches').fetchone()[0],4)
    def test_registered_and_reviewed_never_enter_even_old_simulation_queue(self):
        reconcile_empty(self.erp,self.company)
        self.erp.prepare_document(self.company,self.document,'6','64.03',confirmed=True)
        rpa=RPA(self.erp);job=rpa.create(self.company,[self.document],confirmed=True,reconciled_only=True)
        self.save([ROW],complete=True)
        with self.assertRaises(ValueError):rpa.create(self.company,[self.document],confirmed=True)
        with self.assertRaises(ValueError):rpa.advance(self.company,job)
        self.assertEqual(rpa.items(self.company,job)[1][0]['status'],'queued')
    def test_live_requires_full_evidence_and_only_positive_confirmation_updates_state(self):
        self.erp.prepare_document(self.company,self.document,'6','64.03',confirmed=True);rpa=RPA(self.erp)
        with self.assertRaises(ValueError):rpa.create(self.company,[self.document],mode='fill_only',confirmed=True)
        reconcile_empty(self.erp,self.company);job=rpa.create(self.company,[self.document],mode='fill_only',confirmed=True)
        item=rpa.items(self.company,job)[1][0]
        with self.erp.db:self.erp.db.execute("UPDATE rpa_items SET status='save_invoked' WHERE id=?",(item['id'],))
        self.assertEqual(self.service.results(self.company)[self.document]['status'],'review')
        rpa.reviewed(self.company,job,item['id'],'Έλεγχος χωρίς επιβεβαίωση',confirmed=True)
        self.assertEqual(self.service.results(self.company)[self.document]['status'],'review')
        rpa.reviewed(self.company,job,item['id'],'Οπτικά επιβεβαιωμένο',confirmed=True,stored_in_ebs=True)
        row=self.service.results(self.company)[self.document]
        self.assertEqual((row['status'],row['source']),('registered','rpa_operator'))
    def test_manual_confirmation_has_distinct_provenance_and_survives_new_export(self):
        self.service.confirm_manual(self.company,self.document,'Οπτικός έλεγχος συνθετικού',confirmed=True)
        self.save([],complete=True)
        row=self.service.results(self.company)[self.document]
        self.assertEqual((row['status'],row['source']),('registered','manual_operator'))
    def test_changed_document_and_new_aade_metadata_require_repeat(self):
        self.save([],complete=True)
        raw=response();MyData(self.erp).persist(self.company,'production','2026-10-01','2026-10-31',[(raw,parsed_page(raw))])
        self.assertEqual(self.service.results(self.company)[self.document]['status'],'review')
        self.save([],complete=True)
        self.assertEqual(self.service.results(self.company)[self.document]['status'],'not_registered')

    def test_missing_reference_in_full_catalog_blocks_absence_for_that_vat_only(self):
        row=list(ROW);row[2]='';row[3]='';row[8]=''
        self.save([row],complete=True)
        result=self.service.results(self.company)
        self.assertEqual(result[self.document]['status'],'review')
        other=next(r for r in result.values() if r['id']!=self.document)
        self.assertEqual(other['status'],'not_registered')
        with self.assertRaises(ValueError):self.service.assert_rpa(self.company,[self.document],required=True)

    def test_reconciliation_during_native_prepare_stops_before_typing(self):
        from app.application.workspace import Workspace
        from app.infrastructure.ebs_adapter.adapter import FIELDS
        reconcile_empty(self.erp,self.company)
        self.erp.prepare_document(self.company,self.document,'6','64.03',confirmed=True)
        Workspace(self.erp).save_profile(self.company,dict(mapping={f:[10+i,20+i] for i,(f,_) in enumerate(FIELDS)},save=[100,200],new=[300,400]))
        rpa=RPA(self.erp);job=rpa.create(self.company,[self.document],mode='fill_only',execution='save_new',pilot=True,confirmed=True)
        calls=[];service=self
        class Target:
            def prepare(self,*args):calls.append('prepare');service.save([ROW],complete=True);return 100
            def fill(self,*args):calls.append('fill')
        with self.assertRaises(ValueError):rpa.advance(self.company,job,live_confirmed=True,adapter=Target())
        self.assertEqual(calls,['prepare']);self.assertEqual(rpa.items(self.company,job)[1][0]['status'],'queued')

    def test_receiver_vat_is_checked_even_after_company_attestation(self):
        row=list(ROW)+['000000009'];mapping=dict(MAPPING,receiver=9)
        with self.assertRaises(ValueError):self.packet([row],mapping=mapping,complete=True)
