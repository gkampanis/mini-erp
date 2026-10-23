"""Reference/financial decision matrix, independent of GUI and customer content."""
import unittest
from app.domain.ebs_matching import compare,normalize


def document(identifier=1,series='INV',number='00123',vat='000000001',net=10000,tax=2400,total=12400):
    return dict(id=identifier,company_id=1,direction='incoming',kind='invoice',currency='EUR',vat=vat,series=series,number=number,mark=None,issue_date='2026-09-15',net_minor=net,tax_minor=tax,gross_minor=total,invoice_type='1.1',is_delivery_note=False)


def excel(ref='INV/00123',**changes):
    item=dict(vat='000000001',invoice=ref.strip().casefold(),date='2026-09-15',net_minor=10000,tax_minor=2400,gross_minor=12400)
    item.update(changes);return dict(row=2,normalized=item,error='')

class MatchingRuleTests(unittest.TestCase):
    def state(self,doc,row):return compare([doc],[row],True)[doc['id']]
    def test_five_columns_need_no_date_and_still_check_each_amount(self):
        mapping={'invoice':0,'vat':1,'net':2,'tax':3,'gross':4}
        raw={0:'00123',1:'000000001',2:'100,00',3:'24,00',4:'124,00'}
        item,error=normalize(raw,mapping)
        self.assertFalse(error);self.assertNotIn('date',item)
        row=dict(row=2,normalized=item,error=error)
        result=self.state(document(),row)
        self.assertEqual(result['status'],'registered');self.assertNotIn('ημερομηνία',result['reason'])
        for key in ('net_minor','tax_minor','gross_minor'):
            altered=dict(row,normalized=dict(item,**{key:item[key]+1}))
            with self.subTest(key=key):self.assertEqual(self.state(document(),altered)['status'],'review')
        second=document(2);second['issue_date']='2026-09-16'
        self.assertEqual([r['status'] for r in compare([document(),second],[row],True).values()],['review','review'])
    def test_exact_full_display_and_safe_format_equivalents(self):
        for ref in ('INV/00123',' inv/00123 ','INV00123','INV-00123','INV / 00123'):
            row=excel(ref);row['normalized']['invoice']=ref.strip().casefold()
            with self.subTest(ref=ref):self.assertEqual(self.state(document(),row)['status'],'registered')
    def test_zeros_different_series_remain_review(self):
        for ref in ('INV/123','OTHER/00123','000123'):
            row=excel(ref);row['normalized']['invoice']=ref.casefold()
            with self.subTest(ref=ref):self.assertEqual(self.state(document(),row)['status'],'review')
    def test_bare_number_omits_series_only_with_all_identity_checks(self):
        result=self.state(document(),excel('00123'))
        self.assertEqual(result['status'],'registered');self.assertIn('ακριβής αριθμός',result['reason'])
        for changes in (dict(net_minor=9999),dict(tax_minor=2401),dict(gross_minor=12401),dict(date='2026-09-16')):
            with self.subTest(changes=changes):self.assertEqual(self.state(document(),excel('00123',**changes))['status'],'review')
        self.assertEqual(self.state(document(),excel('123'))['status'],'review')
        self.assertEqual(self.state(document(),excel('00124'))['status'],'not_registered')
    def test_bare_number_is_ambiguous_between_series_or_duplicate_excel_rows(self):
        docs=[document(1,'INV'),document(2,'OTHER')]
        result=compare(docs,[excel('00123')],True)
        self.assertEqual([r['status'] for r in result.values()],['review','review'])
        rows=[excel('00123'),excel('INV/00123')];rows[1]['row']=3
        self.assertEqual(compare([document()],rows,True)[1]['status'],'review')
    def test_every_financial_component_is_mandatory_even_when_gross_matches(self):
        for changes in (dict(net_minor=9999),dict(tax_minor=2401),dict(gross_minor=12401),dict(net_minor=9900,tax_minor=2500)):
            with self.subTest(changes=changes):self.assertEqual(self.state(document(),excel(**changes))['status'],'review')
        row=excel();del row['normalized']['tax_minor']
        self.assertEqual(self.state(document(),row)['status'],'review')
    def test_vat_date_and_number_are_independent_identity_checks(self):
        self.assertEqual(self.state(document(),excel('INV/00999'))['status'],'not_registered')
        self.assertEqual(self.state(document(),excel(vat='000000002'))['status'],'not_registered')
        row=excel(date='2026-09-16');self.assertEqual(self.state(document(),row)['status'],'review')
        self.assertEqual(self.state(document(),excel(mark='55555'))['status'],'registered')
        doc=document();doc['mark']='44444'
        self.assertEqual(self.state(doc,excel(mark='55555'))['status'],'review')
    def test_legal_different_references_sharing_format_tokens_cannot_share_one_row(self):
        docs=[document(1,'INV','00123'),document(2,'INV-','00123')]
        result=compare(docs,[excel('INV/00123')],True)
        self.assertEqual([r['status'] for r in result.values()],['review','review'])
    def test_values_and_vat_without_reference_never_match(self):
        row=excel('');row['error']='Λείπει παραστατικό'
        self.assertNotEqual(self.state(document(),row)['status'],'registered')
    def test_normalization_preserves_reference_symbols_and_original_zeroes(self):
        mapping={'vat':0,'invoice':1,'date':2,'net':3,'tax':4,'gross':5}
        raw={0:' EL000000001 ',1:' INV/00123 ',2:'15/09/2026',3:'1.234,56',4:'296,29',5:'1.530,85'}
        item,error=normalize(raw,mapping)
        self.assertFalse(error);self.assertEqual(item['invoice'],'inv/00123')
        self.assertEqual((item['net_minor'],item['tax_minor'],item['gross_minor']),(123456,29629,153085))
        self.assertEqual(raw[1],' INV/00123 ')
