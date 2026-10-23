"""Realistic ODS cell types and actionable validation, using synthetic data only."""
from pathlib import Path
import tempfile
import unittest
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET
import zipfile
from app.application.service import ERP
from app.application.ebs_reconciliation import EBSReconciliation
from app.infrastructure.importers.excel import preview,read_workbook
from tests.fixtures import demos,workbook
from tests.test_ods import ods


MAPPING={'invoice':0,'vat':1,'net':2,'tax':3,'gross':4}
HEADERS=['Εναλ. παρ/κό','Α.Φ.Μ.','Αξία','ΦΠΑ','Σύνολο','Σημείωση']

def cell(value,*,formula=False,numeric=False):
    attributes=' office:value-type="float" office:value="'+escape(value)+'"' if numeric else ' office:value-type="string"'
    if formula:attributes+=' table:formula="of:=1+1"'
    return '<table:table-cell'+attributes+'><text:p>'+escape(value)+'</text:p></table:table-cell>'

def row(values):return '<table:table-row>'+''.join(values)+'</table:table-row>'


class ImportValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.erp=ERP(self.folder/'data');self.company=self.erp.company('000000000','ΣΥΝΘΕΤΙΚΗ')
        demos(self.folder/'input');self.erp.commit_import(self.company,preview(self.folder/'input/separate.xlsx'),confirmed=True)
        self.service=EBSReconciliation(self.erp);self.document=self.erp.search(self.company,'10000001')[0]['id']
    def tearDown(self):self.erp.close();self.temp.cleanup()
    def cells(self):return [cell(v) for v in ['ΔΟΚ/1','000000001','0,10','0,02','0,12','ΣΥΝΘΕΤΙΚΟ']]
    def source(self,rows):
        path=self.folder/'synthetic-validation.ods';ods(path,row([cell(v) for v in HEADERS])+''.join(row(r) for r in rows));return path
    def packet(self,rows,complete=True):
        return self.service.preview(self.company,self.source(rows),'Συνθετικά',1,MAPPING,'2026-10-01','2026-10-31','000000000',complete=complete,company_confirmed=True)
    def test_unknown_vat_is_visible_at_exact_cell_without_hiding_valid_matches(self):
        invalid=self.cells();invalid[1]=cell('123')
        packet=self.packet([self.cells(),invalid])
        self.assertFalse(packet['can_commit']);self.assertEqual(packet['results'][self.document]['status'],'registered')
        self.assertNotIn('not_registered',[r['status'] for r in packet['results'].values()])
        issue=next(i for i in packet['blocking_issues'] if i['field']=='vat')
        self.assertEqual((issue['row'],issue['cell'],issue['header'],issue['value']),(3,'B3','Α.Φ.Μ.','123'))
        packet['can_commit']=True;packet['blocking_issues']=[]
        with self.assertRaises(ValueError):self.service.commit(packet,confirmed=True)
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM ebs_reconciliation_runs').fetchone()[0],0)
        self.assertFalse((self.erp.directory/'ebs-excel').exists())
    def test_formula_outside_five_fields_does_not_block_a_complete_export(self):
        values=self.cells();values[5]=cell('2',formula=True,numeric=True)
        path=self.source([values]);sheet=read_workbook(path)['sheets'][0]
        self.assertEqual(sheet['formula_cells'],{2:{5}})
        packet=self.packet([values]);self.assertTrue(packet['can_commit'])
        self.assertFalse(packet['blocking_issues']);self.assertFalse(packet['rows'][0]['error'])
        self.service.commit(packet,confirmed=True)
        self.assertEqual(self.service.results(self.company)[self.document]['status'],'registered')
    def test_grouped_ods_records_cannot_be_mistaken_for_an_empty_complete_export(self):
        path=self.folder/'synthetic-grouped.ods'
        ods(path,row([cell(v) for v in HEADERS])+'<table:table-row-group>'+row(self.cells())+'</table:table-row-group>')
        packet=self.service.preview(self.company,path,'Συνθετικά',1,MAPPING,'2026-10-01','2026-10-31','000000000',complete=True,company_confirmed=True)
        self.assertEqual(len(packet['rows']),1);self.assertEqual(packet['results'][self.document]['status'],'registered')
        self.service.commit(packet,confirmed=True)
        with self.assertRaises(ValueError):self.service.assert_rpa(self.company,[self.document],required=True)
    def test_formula_inside_matching_field_is_located_and_cannot_be_authoritative(self):
        values=self.cells();values[3]=cell('0.02',formula=True,numeric=True)
        packet=self.packet([values]);self.assertFalse(packet['can_commit'])
        issue=next(i for i in packet['blocking_issues'] if i['field']=='tax')
        self.assertEqual((issue['row'],issue['cell'],issue['header']),(2,'D2','ΦΠΑ'))
        self.assertIn('υπολογισμού',issue['message'])
        self.assertEqual(packet['results'][self.document]['status'],'review')
        with self.assertRaises(ValueError):self.service.commit(packet,confirmed=True)
    def test_xlsx_checks_formulas_only_in_the_mapped_columns(self):
        namespace='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
        for coordinate in ('F2','D2'):
            with self.subTest(cell=coordinate):
                path=self.folder/'synthetic-formula.xlsx'
                workbook(path,[HEADERS,['ΔΟΚ/1','000000001','0,10','0,02','0,12','2']])
                with zipfile.ZipFile(path) as archive:files={i.filename:archive.read(i) for i in archive.infolist()}
                tree=ET.fromstring(files['xl/worksheets/sheet1.xml'])
                cell=tree.find('.//{'+namespace+'}c[@r="'+coordinate+'"]');cell.clear();cell.set('r',coordinate);cell.set('t','n')
                ET.SubElement(cell,'{'+namespace+'}f').text='1+1'
                ET.SubElement(cell,'{'+namespace+'}v').text='2' if coordinate=='F2' else '0.02'
                files['xl/worksheets/sheet1.xml']=ET.tostring(tree)
                with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as archive:
                    for name,data in files.items():archive.writestr(name,data)
                packet=self.service.preview(self.company,path,'Συνθετικά',1,MAPPING,'2026-10-01','2026-10-31','000000000',complete=True,company_confirmed=True)
                self.assertEqual(packet['can_commit'],coordinate=='F2')
                self.assertEqual(packet['results'][self.document]['status'],'registered' if coordinate=='F2' else 'review')
                if coordinate=='D2':self.assertEqual(packet['blocking_issues'][0]['cell'],'D2')
    def test_blank_amount_is_not_silently_treated_as_zero(self):
        values=self.cells();values[3]=cell('')
        packet=self.packet([values]);self.assertEqual(packet['results'][self.document]['status'],'review')
        issue=next(i for i in packet['rows'][0]['issues'] if i['field']=='tax')
        self.assertEqual((issue['cell'],issue['value']),('D2',''))
    def test_summary_like_row_is_reported_instead_of_silently_discarded(self):
        total=[cell(v) for v in ['Σύνολο','','0,10','0,02','0,12','']]
        packet=self.packet([self.cells(),total]);self.assertFalse(packet['can_commit'])
        self.assertEqual(len(packet['rows']),2)
        self.assertTrue(any(i['cell']=='B3' for i in packet['blocking_issues']))
    def test_nondata_notes_and_exact_repeated_headers_are_accounted_for(self):
        note=[cell(v) for v in ['','','','','','ΣΥΝΘΕΤΙΚΗ ΣΗΜΕΙΩΣΗ']]
        packet=self.packet([self.cells(),note,[cell(v) for v in HEADERS]])
        self.assertTrue(packet['can_commit']);self.assertEqual(len(packet['rows']),1)
        self.assertEqual([(r['row'],r['reason']) for r in packet['ignored_rows']],[(3,'Κενά όλα τα πεδία συμφωνίας'),(4,'Επανάληψη επικεφαλίδων')])
        report=self.service.commit(packet,confirmed=True)
        self.assertEqual((report['excel_rows'],report['ignored_rows']),(3,2))
        self.assertEqual(self.service.results(self.company)[self.document]['status'],'registered')
    def test_unmapped_internal_code_does_not_disguise_an_unidentifiable_record_as_a_note(self):
        path=self.folder/'synthetic-incomplete.ods'
        headers=[*HEADERS[:5],'Παρ/κό'];incomplete=[cell(v) for v in ['','','','','','SYN-TED-2']]
        ods(path,row([cell(v) for v in headers])+row(self.cells())+row(incomplete))
        packet=self.service.preview(self.company,path,'Συνθετικά',1,MAPPING,'2026-10-01','2026-10-31','000000000',complete=True,company_confirmed=True)
        self.assertFalse(packet['can_commit']);self.assertFalse(packet['ignored_rows'])
        self.assertTrue(any(i['row']==3 and i['field']=='vat' for i in packet['blocking_issues']))
