import unittest
from app.application.vat_lines import compact_rows


class CompactionDiagnostics(unittest.TestCase):
    def test_seven_source_rows_become_two_vat_account_groups_despite_cent_rounding(self):
        rows=[dict(line_number=i+1,account='64.03.0013',net_minor=n,tax_minor=(n*13+50)//100,vat_category=2,vat_exemption=None) for i,n in enumerate([101,201,301,401,501,601])]
        rows.append(dict(line_number=7,account='64.03.0024',net_minor=1000,tax_minor=240,vat_category=1,vat_exemption=None))
        result=compact_rows(rows)
        self.assertEqual(len(result),2)
        self.assertEqual(sum(r['net_minor'] for r in result),3106)
        self.assertEqual(sum(r['tax_minor'] for r in result),513)
        self.assertEqual(sorted(i for r in result for i in r['source_line_numbers']),list(range(1,8)))
        self.assertEqual((result[0]['net_minor'],result[0]['tax_minor']),(2106,273))
        self.assertEqual((result[0]['net_minor']*13+50)//100,274)


from tests import test_vat_lines as fixtures


class MappingQueueTests(unittest.TestCase):
    setUp=fixtures.VATLineTests.setUp
    tearDown=fixtures.VATLineTests.tearDown
    service=fixtures.VATLineTests.service
    rules=fixtures.VATLineTests.rules
    add_single_vat_document=fixtures.VATLineTests.add_single_vat_document

    def test_unmapped_invoice_is_reported_while_ready_invoice_can_queue(self):
        from app.application.rpa import RPA
        from app.application.workspace import Workspace
        from app.infrastructure.ebs_adapter.adapter import FIELDS
        from tests.fixtures import reconcile_empty
        self.service().save_rules(self.company,self.cp,self.rules(),confirmed=True)
        single=self.add_single_vat_document();reconcile_empty(self.erp,self.company)
        mapping={field:[10+i*30,100] for i,(field,_) in enumerate(FIELDS)}
        Workspace(self.erp).save_profile(self.company,dict(mapping=mapping,save=[1,2],new=[3,4]))
        report=RPA(self.erp).posting(self.company,[self.document,single])
        self.assertEqual(report['documents'],[single]);self.assertIsNotNone(report['job'])
        self.assertEqual(report['skipped'][0]['document'],self.document)
        reason=report['skipped'][0]['reason']
        self.assertIn(RPA(self.erp).payload(self.company,self.document)['invoice'],reason)
        self.assertIn('Γραμμή EBS 2',reason);self.assertIn('γραμμές XML',reason)
        self.assertIn('2006,00',reason);self.assertIn('64.03.00.0000',reason)
