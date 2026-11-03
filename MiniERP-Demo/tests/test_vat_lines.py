import hashlib,json,tempfile,unittest
from pathlib import Path
import xml.etree.ElementTree as ET
from app.application.service import ERP
from app.application.mydata import MyData
from app.infrastructure.aade.client import parsed_page
from tests.test_mydata_lines import invoice


class VATLineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.erp=ERP(self.root/'data');self.company=self.erp.company('000000000','SYNTHETIC')
        root=ET.Element('RequestedDoc');ET.SubElement(root,'invoicesDoc').append(invoice());self.xml=ET.tostring(root)
        self.page=parsed_page(self.xml);self.api=MyData(self.erp)
        self.api.persist(self.company,'production','2026-09-30','2026-09-30',[(self.xml,self.page)])
        self.api.import_incoming(self.company,'production','2026-09-30','2026-09-30',confirmed=True)
        self.document=self.erp.search(self.company)[0]['id'];self.cp=self.erp.search(self.company)[0]['counterparty_id']
        self.erp.prepare_document(self.company,self.document,'6','64.03.00.0024',confirmed=True)
    def tearDown(self):self.erp.close();self.temp.cleanup()
    def service(self):
        from app.application.vat_lines import VATLines
        return VATLines(self.erp)
    def rules(self):return [dict(vat_category=1,vat_exemption=None,use_primary=True,account=None),dict(vat_category=7,vat_exemption=27,use_primary=False,account='64.03.00.0000')]
    def add_single_vat_document(self,category=7,exempt=27):
        values=dict(lineNumber='1',netValue='100',vatCategory=str(category),vatAmount='0' if category==7 else '13' if category==2 else '24')
        if exempt:values['vatExemptionCategory']=str(exempt)
        tax=values['vatAmount'];node=invoice([values],dict(totalNetValue='100',totalVatAmount=tax,totalGrossValue=str(100+int(tax))))
        node.find('{*}mark').text='100002';node.find('{*}invoiceHeader/{*}aa').text='2'
        root=ET.Element('RequestedDoc');ET.SubElement(root,'invoicesDoc').append(node);xml=ET.tostring(root)
        self.api.persist(self.company,'production','2026-09-30','2026-09-30',[(xml,parsed_page(xml))]);self.api.import_incoming(self.company,'production','2026-09-30','2026-09-30',confirmed=True)
        document=next(r['id'] for r in self.erp.search(self.company) if r['mark']=='100002')
        self.erp.prepare_document(self.company,document,'6','64.03.00.0024',confirmed=True)
        return document
    def test_analysis_keeps_correct_current_source_and_exact_values(self):
        value=self.service().analysis(self.company,self.document)
        self.assertEqual(value['status'],'verified');self.assertEqual(value['totals']['gross_minor'],216271)
        self.assertEqual([r['net_minor'] for r in value['lines']],[12638,200600])
    def test_old_records_recover_from_verified_own_archive_without_database_writes(self):
        row=self.erp.db.execute('SELECT id,record_json FROM mydata_records').fetchone();record=json.loads(row['record_json']);record.pop('detail_analysis')
        with self.erp.db:self.erp.db.execute('UPDATE mydata_records SET record_json=? WHERE id=?',(json.dumps(record),row['id']))
        changes=self.erp.db.total_changes
        self.assertEqual(self.service().analysis(self.company,self.document)['status'],'verified')
        self.assertEqual(self.erp.db.total_changes,changes)
        self.assertEqual(self.service().analysis(self.company,self.document)['status'],'verified')
    def test_corrupt_archive_or_identity_never_returns_verified_details(self):
        row=self.erp.db.execute('SELECT record_json FROM mydata_records').fetchone();record=json.loads(row['record_json']);record.pop('detail_analysis')
        with self.erp.db:self.erp.db.execute('UPDATE mydata_records SET record_json=?',(json.dumps(record),))
        page=self.erp.db.execute('SELECT storage_path FROM mydata_pages').fetchone()[0];(self.erp.directory/page).write_bytes(b'<RequestedDoc/>')
        self.assertEqual(self.service().analysis(self.company,self.document)['status'],'invalid')
    def test_first_use_needs_decision_then_saved_rule_reuses_primary_and_secondary(self):
        service=self.service();self.assertEqual(len(service.requirements(self.company,[self.document])),1)
        service.save_rules(self.company,self.cp,self.rules(),confirmed=True)
        self.assertEqual(service.requirements(self.company,[self.document]),[])
        rows=service.posting_lines(self.company,self.document,'64.03.00.0024')
        self.assertEqual([(r['account'],r['net_minor'],r['tax_minor']) for r in rows],[('64.03.00.0024',12638,3033),('64.03.00.0000',200600,0)])
        rows=service.posting_lines(self.company,self.document,'64.09.00.0024')
        self.assertEqual([r['account'] for r in rows],['64.09.00.0024','64.03.00.0000'])

    def test_later_single_vat_invoice_reuses_saved_secondary_without_prompt(self):
        from app.application.rpa import RPA
        service=self.service();service.save_rules(self.company,self.cp,self.rules(),confirmed=True)
        doc=self.add_single_vat_document()
        self.assertEqual(service.requirements(self.company,[doc]),[])
        payload=RPA(self.erp).payload(self.company,doc)
        self.assertEqual(payload['account'],'64.03.00.0000');self.assertNotIn('detail_lines',payload)

    def test_new_single_vat_on_configured_creditor_asks_once_for_unknown_category(self):
        service=self.service();service.save_rules(self.company,self.cp,self.rules(),confirmed=True)
        doc=self.add_single_vat_document(2,None)
        self.assertEqual(service.requirements(self.company,[doc])[0]['missing'],[(2,0)])
        with self.assertRaises(ValueError):service.posting_lines(self.company,doc,'64.03.00.0024')
        service.save_rules(self.company,self.cp,[dict(vat_category=2,vat_exemption=None,use_primary=False,account='64.03.00.0013')],confirmed=True)
        self.assertEqual(service.requirements(self.company,[doc]),[])
        self.assertEqual(service.posting_lines(self.company,doc,'64.03.00.0024')[0]['account'],'64.03.00.0013')
    def test_rule_requires_explicit_approval_and_company_boundary(self):
        service=self.service();other=self.erp.company('000000009','OTHER')
        for company,approved in ((self.company,False),(other,True)):
            with self.assertRaises(ValueError):service.save_rules(company,self.cp,self.rules(),confirmed=approved)
        self.assertEqual(service.requirements(self.company,[self.document])[0]['counterparty_id'],self.cp)
        with self.assertRaises(ValueError):service.analysis(other,self.document)
    def test_analysis_refuses_source_values_different_from_document(self):
        record=json.loads(self.erp.db.execute('SELECT record_json FROM mydata_records').fetchone()[0]);record['detail_analysis']['totals']['net_minor']=1
        with self.erp.db:self.erp.db.execute('UPDATE mydata_records SET record_json=?',(json.dumps(record),))
        self.assertEqual(self.service().analysis(self.company,self.document)['status'],'invalid')
    def test_rule_change_does_not_rewrite_financial_documents_or_previous_approval(self):
        before=tuple(self.erp.db.execute('SELECT * FROM documents').fetchone());approval=dict(self.erp.preparation(self.company,self.document))
        service=self.service();service.save_rules(self.company,self.cp,self.rules(),confirmed=True)
        rules=self.rules();rules[1]['account']='64.09.00.0000';service.save_rules(self.company,self.cp,rules,confirmed=True)
        self.assertEqual(tuple(self.erp.db.execute('SELECT * FROM documents').fetchone()),before)
        self.assertEqual(self.erp.preparation(self.company,self.document),approval)
        self.assertEqual(service.posting_lines(self.company,self.document,'64.03.00.0024')[1]['account'],'64.09.00.0000')

    def test_rule_edit_rebinds_only_queued_payload_and_preserves_previous_attempt(self):
        from app.application.rpa import RPA
        service=self.service();service.save_rules(self.company,self.cp,self.rules(),confirmed=True)
        documents=[self.document,self.add_single_vat_document()]
        rpa=RPA(self.erp);job=rpa.create(self.company,documents,mode='simulation',confirmed=True)
        before=[item['payload'] for item in rpa.items(self.company,job)[1]]
        rules=self.rules();rules[1]['account']='64.09.0000';service.save_rules(self.company,self.cp,rules,confirmed=True)
        current=[item['payload'] for item in rpa.items(self.company,job)[1]];self.assertNotEqual(before,current)
        self.assertEqual(current,[rpa.payload(self.company,doc) for doc in documents])
        with self.erp.db:self.erp.db.execute("UPDATE rpa_items SET status='uncertain' WHERE job_id=?",(job,))
        rules[1]['account']='64.08.0000';service.save_rules(self.company,self.cp,rules,confirmed=True)
        self.assertEqual([item['payload'] for item in rpa.items(self.company,job)[1]],current)

    def test_current_analysis_still_rejects_corrupt_original_archive(self):
        page=self.erp.db.execute('SELECT storage_path FROM mydata_pages').fetchone()[0]
        (self.erp.directory/page).write_bytes(b'<RequestedDoc/>')
        self.assertEqual(self.service().analysis(self.company,self.document)['status'],'invalid')

    def test_missing_verified_archive_cannot_downgrade_mixed_vat_to_total_row(self):
        service=self.service();service.save_rules(self.company,self.cp,self.rules(),confirmed=True)
        page=self.erp.db.execute('SELECT storage_path FROM mydata_pages').fetchone()[0]
        (self.erp.directory/page).unlink()
        with self.assertRaises(ValueError):service.posting_lines(self.company,self.document,'64.03.00.0024')

    def test_posting_requirements_exclude_purchases_and_registered_documents(self):
        from tests.fixtures import reconcile_empty
        from unittest.mock import patch
        reconcile_empty(self.erp,self.company)
        service=self.service()
        self.assertEqual(len(service.posting_requirements(self.company,[self.document])),1)
        with patch('app.application.ebs_reconciliation.EBSReconciliation.results',return_value={self.document:dict(status='registered')}):
            self.assertEqual(service.posting_requirements(self.company,[self.document]),[])
        self.erp.prepare_document(self.company,self.document,'2','20.01.0000',confirmed=True)
        self.assertEqual(service.posting_requirements(self.company,[self.document]),[])

    def test_conflicting_duplicate_pages_stop_before_any_snapshot_write(self):
        from app.infrastructure.aade.client import APIError
        node=invoice();node.find('invoiceDetails/lineNumber').text='19'
        root=ET.Element('RequestedDoc');ET.SubElement(root,'invoicesDoc').append(node);xml=ET.tostring(root)
        changes=self.erp.db.total_changes;files=set((self.erp.directory/'mydata/xml').glob('*'))
        with self.assertRaises(APIError):self.api.persist(self.company,'production','2026-09-30','2026-09-30',[(self.xml,self.page),(xml,parsed_page(xml))])
        self.assertEqual(self.erp.db.total_changes,changes)
        self.assertEqual(set((self.erp.directory/'mydata/xml').glob('*')),files)

    def test_identical_duplicate_pages_keep_one_record_and_correct_archive_analysis(self):
        from app.infrastructure.aade.client import unique_pages
        pages=unique_pages([(self.xml,self.page),(self.xml,self.page)])
        self.assertEqual([len(p['records']) for _,p in pages],[1,0])
        self.api.persist(self.company,'production','2026-09-30','2026-09-30',pages)
        self.assertEqual(self.service().analysis(self.company,self.document)['status'],'verified')

    def test_leading_zero_mark_persists_and_recovers_verified_archive_details(self):
        node=invoice();node.find('{*}mark').text='000100001'
        root=ET.Element('RequestedDoc');ET.SubElement(root,'invoicesDoc').append(node);xml=ET.tostring(root)
        self.api.persist(self.company,'production','2026-09-30','2026-09-30',[(xml,parsed_page(xml))])
        self.assertEqual(self.service().analysis(self.company,self.document)['status'],'verified')

    def test_refresh_without_details_never_collapses_verified_mixed_invoice(self):
        from app.application.rpa import RPA
        service=self.service();service.save_rules(self.company,self.cp,self.rules(),confirmed=True)
        self.assertEqual(len(RPA(self.erp).payload(self.company,self.document)['detail_lines']),2)
        root=ET.Element('RequestedDoc');ET.SubElement(root,'invoicesDoc').append(invoice([]));xml=ET.tostring(root)
        self.api.persist(self.company,'production','2026-09-30','2026-09-30',[(xml,parsed_page(xml))])
        with self.assertRaises(ValueError):RPA(self.erp).payload(self.company,self.document)

    def test_posting_requirements_skip_unapproved_without_default_and_rounding_review(self):
        from tests.fixtures import reconcile_empty
        reconcile_empty(self.erp,self.company)
        with self.erp.db:self.erp.db.execute('DELETE FROM document_preparations WHERE document_id=?',(self.document,))
        self.assertEqual(self.service().posting_requirements(self.company,[self.document]),[])
        self.erp.prepare_document(self.company,self.document,'6','64.03.00.0024',confirmed=True)
        with self.erp.db:self.erp.db.execute('UPDATE documents SET rounding_minor=1,gross_minor=gross_minor+1 WHERE id=?',(self.document,))
        self.assertEqual(self.service().posting_requirements(self.company,[self.document]),[])

    def test_posting_requirements_keep_approved_supplier_default_before_document_approval(self):
        from tests.fixtures import reconcile_empty
        from app.application.supplier_accounts import SupplierAccounts
        reconcile_empty(self.erp,self.company)
        SupplierAccounts(self.erp).save(self.company,[self.cp],'6','64.03.00.0024',confirmed=True,apply_pending=False)
        with self.erp.db:self.erp.db.execute('DELETE FROM document_preparations WHERE document_id=?',(self.document,))
        self.assertEqual(len(self.service().posting_requirements(self.company,[self.document])),1)

    def test_mixed_vat_document_reconciles_by_invoice_totals(self):
        from app.domain.ebs_matching import compare
        doc,_=self.erp.detail(self.company,self.document)
        item=dict(vat=doc['vat'],date=doc['issue_date'],invoice='test/1',invoice_original='TEST/1',net_minor=213238,tax_minor=3033,gross_minor=216271)
        result=compare([doc],[dict(row=2,normalized=item,error='')],True)[self.document]
        self.assertEqual(result['status'],'registered')

    def test_split_ebs_rows_require_review_instead_of_false_absence_or_guessed_registration(self):
        from app.domain.ebs_matching import compare
        doc,_=self.erp.detail(self.company,self.document);rows=[]
        for index,(net,tax) in enumerate(((12638,3033),(200600,0)),2):
            item=dict(vat=doc['vat'],date=doc['issue_date'],invoice='test/1',invoice_original='TEST/1',net_minor=net,tax_minor=tax,gross_minor=net+tax)
            rows.append(dict(row=index,normalized=item,error=''))
        result=compare([doc],rows,True)[self.document]
        self.assertEqual(result['status'],'review');self.assertEqual(result['excel_rows'],[2,3])

    def test_pdf_url_refresh_keeps_unchanged_financial_queue_payload(self):
        from app.application.rpa import RPA
        self.service().save_rules(self.company,self.cp,self.rules(),confirmed=True)
        before=RPA(self.erp).payload(self.company,self.document)
        node=invoice();ET.SubElement(node,'downloadingInvoiceUrl').text='https://example.com/refreshed-synthetic.pdf'
        root=ET.Element('RequestedDoc');ET.SubElement(root,'invoicesDoc').append(node);xml=ET.tostring(root)
        self.api.persist(self.company,'production','2026-09-30','2026-09-30',[(xml,parsed_page(xml))])
        self.assertEqual(RPA(self.erp).payload(self.company,self.document),before)

    def test_equivalent_duplicate_pages_keep_each_raw_archive_without_false_financial_conflict(self):
        node=invoice();ET.SubElement(node,'downloadingInvoiceUrl').text='https://example.com/refreshed-synthetic.pdf'
        root=ET.Element('RequestedDoc');ET.SubElement(root,'invoicesDoc').append(node);xml=ET.tostring(root)
        self.api.persist(self.company,'production','2026-09-30','2026-09-30',[(self.xml,self.page),(xml,parsed_page(xml))])
        self.assertEqual(self.service().analysis(self.company,self.document)['status'],'verified')
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM mydata_pages WHERE sync_id=(SELECT max(id) FROM mydata_syncs)').fetchone()[0],2)

    def test_single_vat_uses_one_account_even_when_source_rounding_differs(self):
        from decimal import Decimal
        from tempfile import TemporaryDirectory
        from app.application.vat_lines import VATLines
        cases=[([('0.03','0.01'),('0.03','0.01')],[]),([('1.00','0.24'),('2.00','0.48')],[])]
        for values,expected in cases:
            with self.subTest(values=values),TemporaryDirectory() as temp:
                lines=[dict(lineNumber=str(i),netValue=n,vatCategory='1',vatAmount=t) for i,(n,t) in enumerate(values,1)]
                net=sum(Decimal(n) for n,t in values);tax=sum(Decimal(t) for n,t in values)
                node=invoice(lines,dict(totalNetValue=str(net),totalVatAmount=str(tax),totalGrossValue=str(net+tax)))
                root=ET.Element('RequestedDoc');ET.SubElement(root,'invoicesDoc').append(node);xml=ET.tostring(root)
                erp=ERP(Path(temp)/'data')
                try:
                    company=erp.company('000000000','SYNTHETIC');api=MyData(erp)
                    api.persist(company,'production','2026-09-30','2026-09-30',[(xml,parsed_page(xml))]);api.import_incoming(company,'production','2026-09-30','2026-09-30',confirmed=True)
                    doc=erp.search(company)[0];erp.prepare_document(company,doc['id'],'6','64.03.00.0024',confirmed=True)
                    service=VATLines(erp);self.assertEqual(service.requirements(company,[doc['id']]),[])
                    rows=service.posting_lines(company,doc['id'],'64.03.00.0024')
                    self.assertEqual([(r['net_minor'],r['tax_minor']) for r in rows],expected)
                    self.assertTrue(all(r['account']=='64.03.00.0024' for r in rows))
                finally:erp.close()



class VATGroupingTests(unittest.TestCase):
    def rows(self,amounts):return [dict(line_number=i+1,account='64.03',vat_category=1,vat_exemption=None,net_minor=n,tax_minor=t,source_sha256='synthetic') for i,(n,t) in enumerate(amounts)]
    def compact(self,rows):
        from app.application.vat_lines import compact_rows
        return compact_rows(rows)
    def test_equivalent_rows_combine_preserving_source_sums(self):
        rows=self.rows([(12638,3033),(3962,951)])
        result=self.compact(rows)
        self.assertEqual(len(result),1);self.assertEqual((result[0]['net_minor'],result[0]['tax_minor']),(16600,3984))
        self.assertEqual(result[0]['source_line_numbers'],[1,2]);self.assertNotIn('source_line_numbers',rows[0])
    def test_rounding_difference_does_not_create_an_extra_account_row(self):
        rows=self.rows([(3,1),(3,1)]);result=self.compact(rows)
        self.assertEqual(len(result),1);self.assertEqual(sum(r['tax_minor'] for r in result),2)
    def test_distinct_accounts_or_vat_exemptions_never_combine(self):
        for key,value in [('account','64.09'),('vat_category',7),('vat_exemption',27)]:
            rows=self.rows([(12638,3033),(3962,951)]);rows[1][key]=value
            self.assertEqual(len(self.compact(rows)),2)

if __name__=='__main__':unittest.main(verbosity=2)
