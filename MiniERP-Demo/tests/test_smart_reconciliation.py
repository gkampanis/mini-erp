"""Properties of identity normalization and append-only matching decisions."""
from datetime import date
from pathlib import Path
import tempfile
import unittest
from hypothesis import given,settings,strategies as st
from app.domain.ebs_matching import compare,normalize,canonical_reference,fingerprint
from app.application.service import ERP
from app.application.ebs_reconciliation import EBSReconciliation
from tests.test_ebs_matching_rules import document,excel
from tests.fixtures import workbook,HEADERS,demos
from app.infrastructure.importers.excel import preview

PROPERTY=settings(max_examples=150,deadline=None,derandomize=True)

class SmartMatchingProperties(unittest.TestCase):
    @PROPERTY
    @given(number=st.integers(1,999999),zeros=st.integers(0,5),separator=st.sampled_from(['/','-',' ',' / ',' - ']),series=st.sampled_from(['ΤΙΜ','Α','ΤΠ','INV']))
    def test_normalized_unique_identity_is_partial_and_never_eligible_for_rpa(self,number,zeros,separator,series):
        doc=document(series=series,number=str(number));row=excel(series+separator+'0'*zeros+str(number))
        row['normalized']['invoice_original']=series+separator+'0'*zeros+str(number)
        result=compare([doc],[row],True)[1]
        exact=series+separator+'0'*zeros+str(number)==series+'/'+str(number)
        self.assertEqual(result['match_kind'],'exact' if exact else 'normalized')
        self.assertEqual(result['status'],'registered' if exact else 'review')
        self.assertNotEqual(result['status'],'not_registered')
    @PROPERTY
    @given(day=st.dates(date(2020,1,1),date(2030,12,31)),fmt=st.sampled_from(['%Y-%m-%d','%d/%m/%Y','%d-%m-%Y','%d.%m.%Y']))
    def test_equivalent_dates_normalize_and_other_days_do_not_match(self,day,fmt):
        mapping={'invoice':0,'vat':1,'date':2,'net':3,'tax':4,'gross':5}
        raw={0:'INV/00123',1:'000000001',2:day.strftime(fmt),3:'100',4:'24',5:'124'}
        item,error=normalize(raw,mapping);self.assertFalse(error)
        doc=document();doc['issue_date']=day.isoformat()
        self.assertEqual(compare([doc],[dict(row=2,normalized=item,error='')],True)[1]['status'],'registered')
        item['date']='1999-01-01'
        self.assertEqual(compare([doc],[dict(row=2,normalized=item,error='')],True)[1]['status'],'review')
    @PROPERTY
    @given(net=st.integers(1,10000000),tax=st.integers(0,3000000),field=st.sampled_from(['net_minor','tax_minor','gross_minor']))
    def test_each_cent_component_is_compared_exactly(self,net,tax,field):
        doc=document(net=net,tax=tax,total=net+tax)
        row=excel(net_minor=net,tax_minor=tax,gross_minor=net+tax)
        self.assertEqual(compare([doc],[row],True)[1]['status'],'registered')
        row['normalized'][field]+=1
        self.assertEqual(compare([doc],[row],True)[1]['status'],'review')
    @PROPERTY
    @given(number=st.integers(1,999999),gap=st.integers(1,100))
    def test_same_amounts_different_invoices_and_vats_do_not_become_matches(self,number,gap):
        docs=[document(1,number=str(number)),document(2,number=str(number+gap)),document(3,number=str(number),vat='000000002')]
        row=excel('INV/'+str(number));result=compare(docs,[row],True)
        self.assertEqual(result[1]['status'],'registered');self.assertEqual(result[2]['status'],'not_registered');self.assertEqual(result[3]['status'],'not_registered')
    @PROPERTY
    @given(number=st.integers(1,999999),zeros=st.integers(1,5))
    def test_one_excel_row_cannot_be_owned_by_two_invoices(self,number,zeros):
        docs=[document(1,'Α',str(number)),document(2,'Α','0'*zeros+str(number)),document(3,'OTHER','99999999')]
        result=compare(docs,[excel('Α-'+str(number))],True)
        self.assertEqual(result[1]['match_kind'],'ambiguous');self.assertEqual(result[2]['match_kind'],'ambiguous')
        self.assertEqual(result[3]['status'],'not_registered')
    @PROPERTY
    @given(number=st.integers(1,999999))
    def test_duplicate_excel_rows_do_not_block_an_unrelated_document(self,number):
        rows=[excel('Α/'+str(number)),excel('Α-'+str(number))];rows[1]['row']=3
        results=compare([document(1,'Α',str(number)),document(2,'OTHER','99999999')],rows,True)
        self.assertEqual(results[1]['match_kind'],'ambiguous');self.assertEqual(results[2]['status'],'not_registered')
    def test_numeric_series_and_meaningful_characters_are_not_removed(self):
        for left,right in [('01/125','1/125'),('Α*/125','Α/125'),('Α.125','Α/125'),('Α/125','A/125')]:
            self.assertNotEqual(canonical_reference(left),canonical_reference(right))
        suffix=compare([document(number='00123A')],[excel('INV-123A')],True)[1]
        self.assertEqual(suffix['match_kind'],'normalized')
        self.assertNotEqual(canonical_reference('INV/123A'),canonical_reference('INV/123B'))
    @PROPERTY
    @given(day=st.dates(date(2020,1,1),date(2030,12,31)),epoch1904=st.booleans())
    def test_excel_date_systems_normalize_to_the_same_issue_date(self,day,epoch1904):
        base=date(1904,1,1) if epoch1904 else date(1899,12,30)
        raw={0:'INV/00123',1:'000000001',2:str((day-base).days),3:'100',4:'24',5:'124'}
        item,error=normalize(raw,dict(invoice=0,vat=1,date=2,net=3,tax=4,gross=5),epoch1904)
        self.assertFalse(error);self.assertEqual(item['date'],day.isoformat())
    def test_subcent_amounts_do_not_match_merely_because_rounding_hides_them(self):
        raw={0:'INV/00123',1:'000000001',2:'2026-09-15',3:'100.004',4:'24',5:'124'}
        item,error=normalize(raw,dict(invoice=0,vat=1,date=2,net=3,tax=4,gross=5))
        self.assertFalse(error)
        self.assertEqual(compare([document()],[dict(row=2,normalized=item,error='')],True)[1]['status'],'review')
    @PROPERTY
    @given(missing=st.sets(st.sampled_from(['date','net_minor','tax_minor','gross_minor'])),number=st.integers(1,999999))
    def test_unknown_supplier_rows_protect_every_compatible_strict_scope(self,missing,number):
        row=excel('',vat=None);row['error']='Συνθετικό ελλιπές ΑΦΜ και παραστατικό'
        for field in missing:row['normalized'].pop(field,None)
        doc=document(number=str(number))
        result=compare([doc],[row],True)[doc['id']]
        self.assertEqual(result['status'],'review');self.assertEqual(result['excel_rows'],[2])
    def test_missing_reference_does_not_hold_other_expenses_from_the_same_supplier(self):
        row=excel('');row['error']='Συνθετικό ελλιπές παραστατικό'
        docs=[document(1),document(2,number='999',net=20000,tax=4800,total=24800)]
        results=compare(docs,[row],True)
        self.assertEqual(results[1]['status'],'review')
        self.assertEqual(results[2]['status'],'not_registered')

class PartialPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.erp=ERP(self.root/'data');self.company=self.erp.company('000000000','ΣΥΝΘΕΤΙΚΗ');demos(self.root/'inputs')
        self.erp.commit_import(self.company,preview(self.root/'inputs/separate.xlsx'),confirmed=True)
        self.service=EBSReconciliation(self.erp);self.doc=self.erp.search(self.company,'10000001')[0]
    def tearDown(self):self.erp.close();self.temp.cleanup()
    def reconcile(self,reference='ΔΟΚ-0001'):
        path=self.root/'export.xlsx'
        workbook(path,[['Ημ/νία','Εναλ. παρ/κό','Α.Φ.Μ.','Αξία','ΦΠΑ','Σύνολο'],['2026-10-21',reference,'000000001','0.10','0.02','0.12']])
        packet=self.service.preview(self.company,path,'Συνθετικά',1,dict(date=0,invoice=1,vat=2,net=3,tax=4,gross=5),'2026-10-01','2026-10-31','000000000',complete=True,company_confirmed=True)
        return self.service.commit(packet,confirmed=True)
    def test_partial_is_automatically_saved_without_manual_approval_and_others_continue(self):
        self.reconcile();rows=self.service.results(self.company)
        self.assertEqual(rows[self.doc['id']]['match_kind'],'normalized')
        with self.assertRaises(ValueError):self.service.assert_rpa(self.company,[self.doc['id']],required=True)
        other=next(d for d in rows if d!=self.doc['id']);self.service.assert_rpa(self.company,[other],required=True)
    def test_inline_confirmation_survives_same_excel_and_restart_but_not_changed_identity(self):
        self.reconcile();self.service.confirm_partial(self.company,self.doc['id']);self.reconcile()
        self.assertEqual(self.service.results(self.company)[self.doc['id']]['match_kind'],'normalized_confirmed')
        again=ERP(self.erp.directory)
        try:self.assertEqual(EBSReconciliation(again).results(self.company)[self.doc['id']]['status'],'registered')
        finally:again.close()
        self.reconcile('ΔΟΚ-00001')
        self.assertEqual(self.service.results(self.company)[self.doc['id']]['match_kind'],'normalized_confirmed')
        self.reconcile('ΔΟΚ-00009')
        self.assertEqual(self.service.results(self.company)[self.doc['id']]['status'],'review')
        self.assertNotEqual(self.service.results(self.company)[self.doc['id']]['match_kind'],'normalized_confirmed')
    def test_old_evidence_without_date_policy_is_preserved_but_cannot_unlock_rpa(self):
        with self.erp.db:
            run=self.erp.db.execute("INSERT INTO ebs_reconciliation_runs(company_id,company_vat,date_from,date_to,filename,sha256,storage_path,sheet,header_row,mapping_json,complete,report_json) VALUES (?,'000000000','2026-10-01','2026-10-31','synthetic-old.xlsx','synthetic','synthetic','sheet',1,'{}',1,'{}')",(self.company,)).lastrowid
            doc=next(r for r in self.service.documents(self.company) if r['id']==self.doc['id'])
            self.erp.db.execute("INSERT INTO ebs_matches(run_id,document_id,status,reason,excel_rows_json,snapshot_hash) VALUES (?,?,'registered','synthetic old proof','[2]',?)",(run,self.doc['id'],fingerprint(doc)))
        state=self.service.results(self.company)[self.doc['id']]
        self.assertEqual(state['status'],'review');self.assertEqual(state['match_kind'],'legacy')
        with self.assertRaises(ValueError):self.service.assert_rpa(self.company,[self.doc['id']],required=True)
        self.assertEqual(self.erp.db.execute('SELECT status FROM ebs_matches WHERE run_id=?',(run,)).fetchone()[0],'registered')
    @settings(max_examples=20,deadline=None,derandomize=True)
    @given(repeats=st.integers(1,4))
    def test_reimports_are_repeatable_and_cannot_affect_another_company(self,repeats):
        # Each generated case has its own isolated database; unittest setUp is
        # not rerun by Hypothesis between examples.
        with tempfile.TemporaryDirectory() as t:
            erp=ERP(Path(t)/'data');owner=erp.company('000000000','ΣΥΝΘΕΤΙΚΗ');other=erp.company('000000009','ΑΛΛΗ')
            demos(Path(t)/'input');erp.commit_import(owner,preview(Path(t)/'input/separate.xlsx'),confirmed=True)
            service=EBSReconciliation(erp);path=Path(t)/'empty.xlsx';workbook(path,[HEADERS])
            try:
                for _ in range(repeats):
                    packet=service.preview(owner,path,'Συνθετικά',1,dict(vat=0,series=2,number=3,date=4,net=5,tax=6,gross=7),'2026-10-01','2026-10-31','000000000',complete=True,company_confirmed=True)
                    service.commit(packet,confirmed=True)
                self.assertTrue(all(r['status']=='not_registered' for r in service.results(owner).values()))
                self.assertEqual(service.results(other),{});self.assertEqual(len(erp.search(owner)),2)
            finally:erp.close()
