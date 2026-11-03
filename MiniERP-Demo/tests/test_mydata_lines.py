"""Exact source-line ingestion, using synthetic invoice identities only."""
from copy import deepcopy
import html
import unittest
import xml.etree.ElementTree as ET
from app.infrastructure.aade.client import parsed_page


def invoice(lines=None,summary=None):
    lines=lines if lines is not None else [dict(lineNumber='1',netValue='126.38',vatCategory='1',vatAmount='30.33'),dict(lineNumber='2',netValue='2006',vatCategory='7',vatAmount='0',vatExemptionCategory='27')]
    summary=summary or dict(totalNetValue='2132.38',totalVatAmount='30.33',totalGrossValue='2162.71')
    node=ET.fromstring('<invoice xmlns="http://www.aade.gr/myDATA/invoice/v1.0"><mark>100001</mark><issuer><vatNumber>000000001</vatNumber></issuer><counterpart><vatNumber>000000000</vatNumber></counterpart><invoiceHeader><issueDate>2026-09-30</issueDate><invoiceType>2.1</invoiceType><series>TEST</series><aa>1</aa><currency>EUR</currency></invoiceHeader></invoice>')
    for values in lines:
        row=ET.SubElement(node,'invoiceDetails')
        for key,value in values.items():ET.SubElement(row,key).text=value
    totals=ET.SubElement(node,'invoiceSummary')
    for key,value in summary.items():ET.SubElement(totals,key).text=value
    return node


class MyDataLineTests(unittest.TestCase):
    def extract(self,node):
        from app.infrastructure.aade.lines import extract_lines
        return extract_lines(node)
    def test_exact_two_rate_lines_keep_raw_values_numbers_exemption_and_totals(self):
        value=self.extract(invoice())
        self.assertEqual(value['status'],'verified');self.assertEqual(value['version'],1)
        self.assertEqual([(r['line_number'],r['net_minor'],r['tax_minor'],r['vat_category'],r['vat_exemption']) for r in value['lines']],[(1,12638,3033,1,None),(2,200600,0,7,27)])
        self.assertEqual(value['lines'][1]['raw']['netValue'],'2006')
        self.assertEqual(value['totals'],dict(net_minor=213238,tax_minor=3033,gross_minor=216271))
        self.assertEqual(value['currency'],'EUR');self.assertEqual(value['errors'],[])
    def test_live_parser_exposes_analysis_in_namespaced_and_escaped_responses(self):
        node=invoice();page=ET.Element('RequestedDoc');container=ET.SubElement(page,'invoicesDoc');container.append(node)
        xml=ET.tostring(page)
        for body in (xml,('<string>'+html.escape(xml.decode())+'</string>').encode()):
            record=parsed_page(body)['records'][0]
            self.assertEqual(record['detail_analysis']['status'],'verified')
            self.assertEqual(len(record['detail_analysis']['lines']),2)
            self.assertEqual(record['net'],'2132.38')

    def test_numeric_mark_spelling_keeps_its_own_detail_analysis(self):
        node=invoice();node.find('{*}mark').text='000100001'
        page=ET.Element('RequestedDoc');ET.SubElement(page,'invoicesDoc').append(node)
        record=parsed_page(ET.tostring(page))['records'][0]
        self.assertEqual(record['mark'],'100001')
        self.assertEqual([r['net_minor'] for r in record['detail_analysis']['lines']],[12638,200600])

    def test_duplicate_canonical_mark_cannot_attach_another_invoices_details(self):
        from app.infrastructure.aade.client import APIError
        page=ET.Element('RequestedDoc');container=ET.SubElement(page,'invoicesDoc')
        container.append(invoice());other=invoice();other.find('{*}mark').text='000100001'
        other.find('invoiceDetails/lineNumber').text='19';container.append(other)
        with self.assertRaises(APIError):parsed_page(ET.tostring(page))

    def test_identical_duplicate_mark_is_one_record(self):
        page=ET.Element('RequestedDoc');container=ET.SubElement(page,'invoicesDoc')
        container.append(invoice());container.append(invoice())
        self.assertEqual(len(parsed_page(ET.tostring(page))['records']),1)

    def test_inline_cancellation_uses_same_canonical_mark_as_invoice(self):
        node=invoice();node.find('{*}mark').text='000100001'
        ET.SubElement(node,'cancelledByMark').text='200001'
        page=ET.Element('RequestedDoc');ET.SubElement(page,'invoicesDoc').append(node)
        parsed=parsed_page(ET.tostring(page))
        self.assertEqual(parsed['cancellations'],['100001'])
        self.assertEqual(parsed['records'][0]['mark'],'100001')

    def test_paginated_duplicate_conflict_is_rejected_before_fetch_returns(self):
        from app.infrastructure.aade.client import Client,APIError
        from tests.test_workflow import Opener
        pages=[]
        for index in range(2):
            root=ET.Element('RequestedDoc')
            if index==0:
                token=ET.SubElement(root,'continuationToken');ET.SubElement(token,'nextPartitionKey').text='P';ET.SubElement(token,'nextRowKey').text='R'
            node=invoice()
            if index:node.find('invoiceDetails/lineNumber').text='19'
            ET.SubElement(root,'invoicesDoc').append(node);pages.append(ET.tostring(root))
        opener=Opener(pages)
        with self.assertRaises(APIError):Client('test','synthetic','synthetic',opener=opener).fetch('2026-09-30','2026-09-30')
        self.assertEqual(len(opener.requests),2)

    def test_paginated_exact_duplicate_is_not_counted_twice(self):
        from app.infrastructure.aade.client import Client
        from tests.test_workflow import Opener
        root=ET.Element('RequestedDoc');token=ET.SubElement(root,'continuationToken')
        ET.SubElement(token,'nextPartitionKey').text='P';ET.SubElement(token,'nextRowKey').text='R'
        ET.SubElement(root,'invoicesDoc').append(invoice());first=ET.tostring(root);root.remove(token)
        pages=Client('test','synthetic','synthetic',opener=Opener([first,ET.tostring(root)])).fetch('2026-09-30','2026-09-30')
        self.assertEqual([len(p['records']) for _,p in pages],[1,0])
    def test_missing_details_are_distinct_and_do_not_invent_a_line(self):
        value=self.extract(invoice([]));self.assertEqual(value['status'],'missing');self.assertEqual(value['lines'],[])
    def test_bad_detail_is_retained_but_not_certified(self):
        for key,bad in [('lineNumber','0'),('lineNumber','abc'),('netValue','126.381'),('netValue','126.38000000000000000000000000001'),('netValue','NaN'),('netValue','1E2'),('vatCategory','999'),('vatAmount','-1')]:
            with self.subTest(key=key,bad=bad):
                node=invoice();node.findall('invoiceDetails')[0].find(key).text=bad
                value=self.extract(node);self.assertEqual(value['status'],'invalid');self.assertTrue(value['errors']);self.assertEqual(len(value['lines']),2)
                self.assertEqual(value['lines'][0]['raw'][key],bad)
    def test_duplicate_line_number_and_missing_or_duplicate_field_fail_analysis_only(self):
        for mode in ('number','missing','duplicate'):
            node=invoice();first,second=node.findall('invoiceDetails')
            if mode=='number':second.find('lineNumber').text='1'
            elif mode=='missing':first.remove(first.find('vatAmount'))
            else:ET.SubElement(first,'netValue').text='999'
            value=self.extract(node);self.assertEqual(value['status'],'invalid');self.assertTrue(value['errors'])
    def test_zero_percent_exemption_and_non_vat_category_stay_distinct(self):
        node=invoice();row=node.findall('invoiceDetails')[1];row.find('vatCategory').text='8';row.remove(row.find('vatExemptionCategory'))
        value=self.extract(node);self.assertEqual(value['status'],'verified');self.assertEqual(value['lines'][1]['vat_category'],8)
        node=invoice();row=node.findall('invoiceDetails')[1];row.remove(row.find('vatExemptionCategory'))
        self.assertEqual(self.extract(node)['status'],'invalid')
    def test_summary_mismatch_never_gets_silently_rounded_or_repaired(self):
        node=invoice();node.find('invoiceSummary/totalVatAmount').text='30.32'
        value=self.extract(node);self.assertEqual(value['status'],'invalid');self.assertEqual(value['lines'][0]['tax_minor'],3033)
    def test_special_line_preserves_rec_type_and_requires_supported_interpretation(self):
        node=invoice();ET.SubElement(node.findall('invoiceDetails')[1],'recType').text='6'
        value=self.extract(node);self.assertEqual(value['status'],'unsupported');self.assertEqual(value['lines'][1]['rec_type'],6)
    def test_summary_additional_taxes_are_kept_for_exact_gross_reconciliation(self):
        node=invoice();summary=node.find('invoiceSummary');ET.SubElement(summary,'totalFeesAmount').text='1.25';summary.find('totalGrossValue').text='2163.96'
        value=self.extract(node);self.assertEqual(value['status'],'verified');self.assertEqual(value['summary_raw']['totalFeesAmount'],'1.25')
    def test_credit_document_keeps_positive_source_values_and_type(self):
        node=invoice();node.find('{*}invoiceHeader/{*}invoiceType').text='5.1'
        value=self.extract(node);self.assertEqual(value['status'],'verified');self.assertEqual(value['invoice_type'],'5.1');self.assertEqual(value['lines'][0]['net_minor'],12638)


if __name__=='__main__':unittest.main(verbosity=2)
