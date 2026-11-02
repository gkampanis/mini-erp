import unittest
from app.domain.ebs_matching import normalize,financial_differences
from app.infrastructure.importers.ods import displayed_money


class DecimalRepresentationTests(unittest.TestCase):
    def test_numeric_serialization_recovers_cents_without_display_text(self):
        mapping=dict(vat=0,invoice=1,date=2,net=3,tax=4,gross=5)
        raw={0:'000000001',1:'INV/1',2:'2026-09-09',3:'80.650000000000006',4:'19.349999999999998',5:'100'}
        item,error=normalize(raw,mapping,numeric_columns={3,4,5})
        self.assertFalse(error)
        doc=dict(vat='000000001',issue_date='2026-09-09',net_minor=8065,tax_minor=1935,gross_minor=10000)
        self.assertEqual(financial_differences(item,doc),[])
        self.assertEqual(raw[3],'80.650000000000006')

    def test_adjacent_float_serialization_accepts_exact_cent_display(self):
        self.assertEqual(displayed_money('80.650000000000006','80,65'),'80.65')
        self.assertEqual(displayed_money('19.349999999999998','19,35'),'19.35')

    def test_real_fraction_and_text_precision_are_not_tolerated(self):
        for value in ('80.65001','80.654','80.66'):
            self.assertIsNone(displayed_money(value,'80,65'))
        mapping=dict(vat=0,invoice=1,date=2,net=3,tax=4,gross=5)
        raw={0:'000000001',1:'INV/1',2:'2026-09-09',3:'80.650000000000006',4:'19.35',5:'100'}
        item,_=normalize(raw,mapping)
        self.assertIn('ακριβή δεκαδικά καθαρής',financial_differences(item,dict(vat='000000001',issue_date='2026-09-09',net_minor=8065,tax_minor=1935,gross_minor=10000)))


from tests import test_ebs_import_validation as fixtures
cell=fixtures.cell


class ReconciliationExclusionTests(unittest.TestCase):
    setUp=fixtures.ImportValidationTests.setUp
    tearDown=fixtures.ImportValidationTests.tearDown
    cells=fixtures.ImportValidationTests.cells
    source=fixtures.ImportValidationTests.source
    packet=fixtures.ImportValidationTests.packet

    def test_blank_identity_rows_are_ignored_without_quarantining_expense(self):
        for column in (0,1):
            values=self.cells();values[column]=cell('')
            packet=self.packet([values])
            self.assertEqual(packet['results'][self.document]['status'],'not_registered')
            self.assertEqual(len(packet['ignored_rows']),1)
            self.assertFalse(packet['blocking_issues'])
        report=self.service.commit(packet,confirmed=True)
        self.assertEqual(report['ignored_rows'],1)
        self.service.assert_rpa(self.company,[self.document],required=True)

    def test_group2_vat_rows_are_ignored_using_company_card_not_export_category(self):
        cp=self.erp.detail(self.company,self.document)[0]['counterparty_id']
        from app.application.supplier_accounts import SupplierAccounts
        with self.erp.db:self.erp.db.execute("UPDATE counterparties SET environment='production' WHERE id=?",(cp,))
        SupplierAccounts(self.erp).save(self.company,[cp],'2','20.01.0000',confirmed=True,classify_supplier=False)
        packet=self.packet([self.cells()])
        self.assertEqual(len(packet['ignored_rows']),1)
        self.assertEqual(packet['rows'],[])

    def test_other_company_and_test_purchase_rules_do_not_exclude_current_expenses(self):
        other=self.erp.company('000000009','OTHER')
        with self.erp.db:
            self.erp.db.execute("INSERT INTO supplier_purchase_rules(company_id,environment,vat,enabled) VALUES (?,'production','000000001',1)",(other,))
            self.erp.db.execute("INSERT INTO supplier_purchase_rules(company_id,environment,vat,enabled) VALUES (?,'test','000000001',1)",(self.company,))
        packet=self.packet([self.cells()])
        self.assertFalse(packet['ignored_rows'])
        self.assertEqual(packet['results'][self.document]['status'],'registered')

    def test_current_production_purchase_rule_is_excluded_without_account(self):
        with self.erp.db:self.erp.db.execute("INSERT INTO supplier_purchase_rules(company_id,environment,vat,enabled) VALUES (?,'production','000000001',1)",(self.company,))
        packet=self.packet([self.cells()])
        self.assertEqual(packet['rows'],[])
        self.assertEqual(len(packet['ignored_rows']),1)

    def test_numeric_scientific_vat_uses_same_identity_for_purchase_exclusion(self):
        with self.erp.db:self.erp.db.execute("INSERT INTO supplier_purchase_rules(company_id,environment,vat,enabled) VALUES (?,'production','123456789',1)",(self.company,))
        values=self.cells();values[1]=cell('1.23456789E+8',numeric=True)
        packet=self.packet([values])
        self.assertEqual(packet['rows'],[])
        self.assertEqual(len(packet['ignored_rows']),1)
