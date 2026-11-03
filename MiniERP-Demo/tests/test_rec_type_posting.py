"""Supported AADE special rows retain source evidence and exact posting totals."""
import json
from decimal import Decimal
import unittest
import xml.etree.ElementTree as ET
from app.infrastructure.aade.lines import extract_lines
from tests.test_mydata_lines import invoice
from tests import test_vat_lines


def special_invoice(rec_type=2,net='20',tax='4.80'):
    return invoice([dict(lineNumber='1',netValue='100',vatCategory='1',vatAmount='24'),
                    dict(lineNumber='2',netValue=net,vatCategory='1',vatAmount=tax,recType=str(rec_type))],
                   dict(totalNetValue=str(100+Decimal(net)),totalVatAmount=str(24+Decimal(tax)),totalGrossValue=str(124+Decimal(net)+Decimal(tax))))


class RecTypeParserTests(unittest.TestCase):
    def test_vat_fees_and_other_taxes_are_ordinary_exact_net_value_rows(self):
        for rec_type in (2,3):
            with self.subTest(rec_type=rec_type):
                analysis=extract_lines(special_invoice(rec_type))
                self.assertEqual(analysis['status'],'verified')
                self.assertEqual(analysis['totals']['net_minor'],12000)
                self.assertEqual(analysis['lines'][1]['rec_type'],rec_type)
                self.assertEqual(analysis['lines'][1]['raw']['netValue'],'20')
    def test_special_rows_still_require_exact_sums_and_no_alternative_amounts(self):
        node=special_invoice();node.find('invoiceSummary/totalNetValue').text='119'
        self.assertEqual(extract_lines(node)['status'],'invalid')
        for field in ('feesAmount','otherTaxesAmount','stampDutyAmount','withheldAmount','deductionsAmount'):
            node=special_invoice();ET.SubElement(node.findall('invoiceDetails')[1],field).text='1'
            self.assertEqual(extract_lines(node)['status'],'unsupported')
    def test_zero_informational_row_is_verified_but_other_semantics_stay_unsupported(self):
        self.assertEqual(extract_lines(special_invoice(6,'0','0'))['status'],'verified')
        for rec_type,net,tax in ((6,'20','4.80'),(7,'20','4.80'),(4,'20','4.80')):
            self.assertEqual(extract_lines(special_invoice(rec_type,net,tax))['status'],'unsupported')


class RecTypeServiceTests(unittest.TestCase):
    setUp=test_vat_lines.VATLineTests.setUp
    tearDown=test_vat_lines.VATLineTests.tearDown
    service=test_vat_lines.VATLineTests.service
    def install(self,node,legacy=False):
        from app.infrastructure.aade.client import parsed_page
        node.find('{*}mark').text='100002';node.find('{*}invoiceHeader/{*}aa').text='2'
        root=ET.Element('RequestedDoc');ET.SubElement(root,'invoicesDoc').append(node);xml=ET.tostring(root)
        self.api.persist(self.company,'production','2026-09-30','2026-09-30',[(xml,parsed_page(xml))])
        self.api.import_incoming(self.company,'production','2026-09-30','2026-09-30',confirmed=True)
        self.document=next(r['id'] for r in self.erp.search(self.company) if r['mark']=='100002')
        self.erp.prepare_document(self.company,self.document,'6','64.03.00.0024',confirmed=True)
        if legacy:
            row=self.erp.db.execute('SELECT id,record_json FROM mydata_records ORDER BY id DESC LIMIT 1').fetchone()
            record=json.loads(row['record_json']);record['detail_analysis']['status']='unsupported'
            with self.erp.db:self.erp.db.execute('UPDATE mydata_records SET record_json=? WHERE id=?',(json.dumps(record),row['id']))
    def test_old_unsupported_analysis_recovers_from_archive_without_writes(self):
        self.install(special_invoice(),legacy=True);changes=self.erp.db.total_changes
        analysis=self.service().analysis(self.company,self.document)
        self.assertEqual(analysis['status'],'verified');self.assertEqual(self.erp.db.total_changes,changes)
        self.assertEqual(self.service().requirements(self.company,[self.document]),[])
        self.assertEqual(self.service().posting_lines(self.company,self.document,'64.03.00.0024'),[])
    def test_zero_informational_row_never_adds_a_vat_requirement_or_posting_row(self):
        node=special_invoice(6,'0','0');node.findall('invoiceDetails')[1].find('vatCategory').text='2'
        self.install(node)
        analysis=self.service().analysis(self.company,self.document)
        self.assertEqual(analysis['status'],'verified')
        self.assertEqual(analysis['lines'][1]['raw']['recType'],'6')
        self.assertEqual(self.service().requirements(self.company,[self.document]),[])
        self.assertEqual(self.service().posting_lines(self.company,self.document,'64.03.00.0024'),[])
    def test_supported_fee_uses_existing_vat_rule_and_preserves_exact_split(self):
        node=special_invoice(3);line=node.findall('invoiceDetails')[1]
        line.find('vatCategory').text='2';line.find('vatAmount').text='2.60'
        node.find('invoiceSummary/totalVatAmount').text='26.60'
        node.find('invoiceSummary/totalGrossValue').text='146.60'
        self.install(node)
        service=self.service()
        service.save_rules(self.company,self.cp,[dict(vat_category=1,vat_exemption=None,use_primary=True,account=None),
                           dict(vat_category=2,vat_exemption=None,use_primary=False,account='64.03.00.0013')],confirmed=True)
        self.assertEqual(service.requirements(self.company,[self.document]),[])
        rows=service.posting_lines(self.company,self.document,'64.03.00.0024')
        self.assertEqual([(r['net_minor'],r['tax_minor'],r['account']) for r in rows],[(10000,2400,'64.03.00.0024'),(2000,260,'64.03.00.0013')])
    def test_recovery_still_requires_hash_checked_archive(self):
        self.install(special_invoice(),legacy=True)
        path=self.erp.db.execute('SELECT storage_path FROM mydata_pages ORDER BY id DESC LIMIT 1').fetchone()[0]
        (self.erp.directory/path).write_bytes(b'<RequestedDoc/>')
        self.assertEqual(self.service().analysis(self.company,self.document)['status'],'invalid')


