"""P9 shared Excel interaction: synthetic workbooks and isolated local profiles."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

from app.application.service import ERP
from app.infrastructure.importers.excel import preview,read_workbook
from tests.fixtures import HEADERS,ROW,workbook


class ExcelMappingTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('app.ui.excel_mapping'),
                             'The two import stages need one shared column interaction')
        from app.ui import excel_mapping
        self.mapping=excel_mapping
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)

    def test_source_role_distinguishes_registered_ebs_from_new_documents(self):
        path=self.folder/'ebs.xlsx'
        workbook(path,[['Συνθετική σημείωση'],['Ημ/νία','Παρ/κό','Εναλ. παρ/κό','Α.Φ.Μ.','Αξία','ΦΠΑ','Σύνολο'],
                       ['2026-10-21','ΕΣΩΤ/987','ΔΟΚ/1','000000001','0,10','0,02','0,12']])
        book=read_workbook(path)
        self.assertEqual(self.mapping.classify_workbook(book),'ebs')
        layout=self.mapping.best_layout(book,'ebs')
        self.assertEqual((layout['sheet'],layout['header_row']),('Συνθετικά',2))
        self.assertEqual(layout['mapping']['invoice'],2)
        self.assertNotIn(1,layout['mapping'].values())
        workbook(path,[HEADERS,ROW]);book=read_workbook(path)
        self.assertEqual(self.mapping.classify_workbook(book),'documents')
        self.assertEqual(self.mapping.best_layout(book,'documents')['mapping']['name'],1)

    def test_common_columns_do_not_guess_whether_source_proves_ebs_registration(self):
        path=self.folder/'unknown.xlsx'
        workbook(path,[['VAT','Invoice Number','Date','Net','Tax amount','Gross'],
                       ['000000001','ΔΟΚ/1','2026-10-21','0.10','0.02','0.12']])
        self.assertIsNone(self.mapping.classify_workbook(read_workbook(path)))
        workbook(path,[['VAT','Invoice Number','Date','Net','Tax amount','Gross','Supplier name'],
                       ['000000001','ΔΟΚ/1','2026-10-21','0.10','0.02','0.12','Synthetic supplier']])
        self.assertIsNone(self.mapping.classify_workbook(read_workbook(path)))

    def test_duplicate_alternative_reference_headers_stay_unmapped(self):
        headers=dict(enumerate(['Ημ/νία','Εναλ. παρ/κό','Εναλ. παρ/κό','Παρ/κό','Α.Φ.Μ.','Αξία','ΦΠΑ','Σύνολο']))
        self.assertNotIn('invoice',self.mapping.auto_mapping(headers,'ebs'))

    def test_completed_raw_mapping_is_reused_with_company_and_environment_isolation(self):
        erp=ERP(self.folder/'data');self.addCleanup(erp.close)
        company=erp.company('000000000','Synthetic mapping company')
        other=erp.company('000000009','Synthetic other company')
        path=self.folder/'raw.xlsx';workbook(path,[HEADERS,ROW])
        item=preview(path);item.mapping.pop('name')
        erp.commit_import(company,item,confirmed=True)
        self.assertEqual(self.mapping.saved_document_mapping(erp,company,item.headers),item.mapping)
        self.assertEqual(self.mapping.saved_document_mapping(erp,other,item.headers),{})
        self.assertEqual(self.mapping.saved_document_mapping(erp,company,item.headers,'test'),{})
        changed=dict(item.headers);changed[0]='Different VAT heading'
        self.assertEqual(self.mapping.saved_document_mapping(erp,company,changed),{})
        reused=self.mapping.raw_preview(erp,company,path,read_workbook(path))
        self.assertNotIn('name',reused.mapping)
        self.assertEqual(reused.records[0]['document']['name'],'Χωρίς επωνυμία')

    def test_frozen_workbook_recheck_keeps_original_bytes_and_header_choice(self):
        path=self.folder/'raw.xlsx';workbook(path,[['Συνθετική σημείωση'],HEADERS,ROW])
        book=read_workbook(path)
        mapping=self.mapping.best_layout(book,'documents')['mapping']
        path.write_bytes(b'The original path changed after selection')
        item=preview(path,mapping,book=book,sheet='Συνθετικά',header_row=2)
        self.assertEqual(item.header_row,2)
        self.assertEqual(item.sha256,book['sha256'])
        self.assertEqual(item.records[0]['document']['vat'],'000000001')
        self.assertEqual(item.data,book['data'])

    def test_saved_custom_ebs_headers_recognize_stage_sheet_and_header_row(self):
        from app.application.ebs_reconciliation import EBSReconciliation
        erp=ERP(self.folder/'data');self.addCleanup(erp.close)
        company=erp.company('000000000','Synthetic saved evidence layout')
        path=self.folder/'custom.xlsx'
        workbook(path,[['Synthetic note'],['D','Reference','V','N','T','G'],
                       ['2026-10-21','ΔΟΚ/1','000000001','0.10','0.02','0.12']])
        service=EBSReconciliation(erp)
        columns=dict(date=0,invoice=1,vat=2,net=3,tax=4,gross=5)
        packet=service.preview(company,path,'Συνθετικά',2,columns,'2026-10-01','2026-10-31','000000000',company_confirmed=True)
        service.commit(packet,confirmed=True,remember=True)
        book=read_workbook(path)
        self.assertEqual(self.mapping.classify_workbook(book,erp,company),'ebs')
        layout=self.mapping.best_layout(book,'ebs',saved_mapping=lambda headers:service.saved_mapping(company,headers))
        self.assertEqual(layout['header_row'],2)
        self.assertEqual(layout['mapping'],columns)

    def test_saved_custom_raw_headers_recognize_stage_and_ignore_malformed_latest_profile(self):
        erp=ERP(self.folder/'data');self.addCleanup(erp.close)
        company=erp.company('000000000','Synthetic saved raw layout')
        path=self.folder/'custom.xlsx'
        headers=['A','B','C','D','E','F','G','H','I']
        workbook(path,[headers,ROW]);book=read_workbook(path)
        mapping=dict(vat=0,name=1,series=2,number=3,date=4,net=5,tax=6,gross=7,mark=8)
        item=preview(path,mapping);erp.commit_import(company,item,confirmed=True)
        self.assertEqual(self.mapping.classify_workbook(book,erp,company),'documents')
        job=erp.db.execute('SELECT max(id) FROM import_jobs').fetchone()[0]
        with erp.db:erp.repository.audit(company,'import_completed',None,dict(job=job,headers=item.headers,mapping={'vat':True}))
        self.assertEqual(self.mapping.saved_document_mapping(erp,company,item.headers),mapping)

    def test_layout_saved_for_both_stages_requires_source_role_instead_of_silent_dispatch(self):
        from app.application.ebs_reconciliation import EBSReconciliation
        erp=ERP(self.folder/'data');self.addCleanup(erp.close)
        company=erp.company('000000000','Synthetic ambiguous saved layout')
        path=self.folder/'same-layout.xlsx';workbook(path,[HEADERS,ROW])
        erp.commit_import(company,preview(path),confirmed=True)
        service=EBSReconciliation(erp)
        mapping=dict(vat=0,series=2,number=3,date=4,net=5,tax=6,gross=7,mark=8)
        packet=service.preview(company,path,'Συνθετικά',1,mapping,'2026-10-01','2026-10-31','000000000',company_confirmed=True)
        service.commit(packet,confirmed=True,remember=True)
        self.assertIsNone(self.mapping.classify_workbook(read_workbook(path),erp,company))

    def test_raw_commit_reparses_the_selected_custom_header_not_the_first_note_row(self):
        erp=ERP(self.folder/'data');self.addCleanup(erp.close)
        company=erp.company('000000000','Synthetic custom selected header')
        path=self.folder/'custom-offset.xlsx'
        workbook(path,[['Synthetic note'],list('ABCDEFGHI'),ROW])
        mapping=dict(vat=0,name=1,series=2,number=3,date=4,net=5,tax=6,gross=7,mark=8)
        item=preview(path,mapping,sheet='Συνθετικά',header_row=2)
        report=erp.commit_import(company,item,confirmed=True)
        self.assertEqual(report['inserted'],1)
        self.assertEqual(erp.search(company)[0]['vat'],'000000001')
        reused=self.mapping.raw_preview(erp,company,path,read_workbook(path))
        self.assertEqual(reused.header_row,2)
        self.assertEqual(reused.mapping,mapping)

    def test_saved_ebs_header_below_detection_window_retains_its_stored_layout(self):
        from app.application.ebs_reconciliation import EBSReconciliation
        erp=ERP(self.folder/'data');self.addCleanup(erp.close)
        company=erp.company('000000000','Synthetic deep EBS header')
        path=self.folder/'deep-header.xlsx'
        workbook(path,[['Synthetic note']]*14+[['D','R','V','N','T','G'],
                       ['2026-10-21','ΔΟΚ/1','000000001','0.10','0.02','0.12']])
        service=EBSReconciliation(erp);mapping=dict(date=0,invoice=1,vat=2,net=3,tax=4,gross=5)
        packet=service.preview(company,path,'Συνθετικά',15,mapping,'2026-10-01','2026-10-31','000000000',company_confirmed=True)
        service.commit(packet,confirmed=True,remember=True)
        book=read_workbook(path)
        self.assertEqual(self.mapping.classify_workbook(book,erp,company),'ebs')
        saved=self.mapping.saved_ebs_layout(erp,company,book)
        self.assertEqual(saved['header_row'],15)
        self.assertEqual(saved['mapping'],mapping)

    def test_saved_raw_role_precedes_an_additional_ebs_reference_heading(self):
        erp=ERP(self.folder/'data');self.addCleanup(erp.close)
        company=erp.company('000000000','Synthetic explicit raw role')
        path=self.folder/'raw-with-ebs-reference.xlsx'
        workbook(path,[HEADERS+['Εναλ. παρ/κό'],ROW+['ΔΟΚ/1']])
        erp.commit_import(company,preview(path),confirmed=True)
        self.assertEqual(self.mapping.classify_workbook(read_workbook(path),erp,company),'documents')

    def test_both_saved_roles_precede_an_ebs_reference_heading(self):
        from app.application.ebs_reconciliation import EBSReconciliation
        erp=ERP(self.folder/'data');self.addCleanup(erp.close)
        company=erp.company('000000000','Synthetic explicit conflicting roles')
        path=self.folder/'both-with-ebs-reference.xlsx'
        workbook(path,[HEADERS+['Εναλ. παρ/κό'],ROW+['ΔΟΚ/1']])
        erp.commit_import(company,preview(path),confirmed=True)
        service=EBSReconciliation(erp)
        mapping=dict(vat=0,invoice=9,date=4,net=5,tax=6,gross=7)
        packet=service.preview(company,path,'Συνθετικά',1,mapping,'2026-10-01','2026-10-31','000000000',company_confirmed=True)
        service.commit(packet,confirmed=True,remember=True)
        self.assertIsNone(self.mapping.classify_workbook(read_workbook(path),erp,company))


if __name__=='__main__':unittest.main()
