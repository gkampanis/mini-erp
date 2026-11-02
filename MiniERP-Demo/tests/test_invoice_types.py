"""Official category recognition and non-value EBS exclusion using synthetic XML."""
import tempfile
from pathlib import Path
import unittest
from app.application.service import ERP
from app.application.mydata import MyData
from app.application.rpa import RPA
from app.domain.invoice_types import classify,TYPES
from app.infrastructure.aade.client import parsed_page
from tests.test_workflow import response

class InvoiceTypeTests(unittest.TestCase):
    def test_catalog_covers_official_2_0_2_enum_without_reserved_placeholders(self):
        codes='1.1 1.2 1.3 1.4 1.5 1.6 2.1 2.2 2.3 2.4 3.1 3.2 5.1 5.2 6.1 6.2 7.1 8.1 8.2 8.4 8.5 8.6 9.1 9.2 9.3 10.1 10.2 11.1 11.2 11.3 11.4 11.5 13.1 13.2 13.3 13.4 13.30 13.31 14.1 14.2 14.3 14.4 14.5 14.30 14.31 15.1 16.1 17.1 17.2 17.3 17.4 17.5 17.6'
        self.assertEqual(set(TYPES),set(codes.split()))
        self.assertEqual(classify('99.99')['description'],'Μη αναγνωρισμένο είδος')
        self.assertNotEqual(classify('13.30')['description'],classify('13.3')['description'])
    def test_invoice_delivery_flag_does_not_turn_invoice_into_dispatch(self):
        item=classify('1.1',True)
        self.assertEqual(item['family'],'invoice');self.assertIn('με διακίνηση',item['description']);self.assertTrue(item['rpa_allowed'])
        for code in ('5.1','5.2','9.1','9.2','9.3','10.1','10.2','99.99'):
            self.assertFalse(classify(code,True)['rpa_allowed'])
    def test_xml_type_flag_persistence_main_list_and_rpa_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            erp=ERP(Path(temp)/'data');company=erp.company('000000000','ΣΥΝΘΕΤΙΚΗ')
            try:
                service=MyData(erp)
                for index,code in enumerate(('1.1','5.1','9.3','99.99')):
                    raw=response(mark=str(70000000+index),number=str(index+1)).replace(b'<invoiceType>1.1</invoiceType>',f'<invoiceType>{code}</invoiceType><isDeliveryNote>true</isDeliveryNote>'.encode())
                    if code=='9.3':raw=raw.replace(b'0.10',b'0.00').replace(b'0.02',b'0.00').replace(b'0.12',b'0.00')
                    service.persist(company,'production','2026-10-01','2026-10-31',[(raw,parsed_page(raw))])
                result=service.import_incoming(company,'production','2026-10-01','2026-10-31',confirmed=True)
                self.assertEqual(result['inserted'],4)
                records=service.records(company,'production');self.assertEqual({r['invoice_type'] for r in records},{'1.1','5.1','9.3','99.99'})
                self.assertTrue(all(r['is_delivery_note']==1 for r in records))
                for row in records:
                    doc=row['document_id'];kind=service.document_type(company,doc)
                    erp.prepare_document(company,doc,'6','64.03',confirmed=True)
                    if row['invoice_type']=='1.1':self.assertEqual(RPA(erp).payload(company,doc)['group'],'6')
                    else:
                        with self.assertRaises(ValueError):RPA(erp).payload(company,doc)
                    self.assertEqual(kind['invoice_type'],row['invoice_type'])
                scope=RPA(erp).expense_scope(company,[d['id'] for d in erp.search(company)])
                self.assertEqual(len(scope['expenses']),1);self.assertEqual(len(scope['excluded_types']),3)
                self.assertEqual(len(erp.search(company)),4)
            finally:erp.close()
