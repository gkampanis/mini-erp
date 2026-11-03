"""Synthetic numeric ODS storage noise, retaining source bytes and strict amounts."""
from pathlib import Path
import tempfile
import unittest
from xml.sax.saxutils import escape
from app.application.service import ERP
from app.application.ebs_reconciliation import EBSReconciliation
from app.infrastructure.importers.excel import preview,read_workbook
from tests.fixtures import HEADERS,ROW,workbook
from tests.test_ods import ods


class ODSMoneyDisplayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.erp=ERP(self.folder/'data');self.addCleanup(self.erp.close)
        self.company=self.erp.company('000000008','SYNTHETIC')
        row=list(ROW);row[2:8]=['INV','17','2026-09-15','37.30','8.95','46.25'];row[8]=''
        path=self.folder/'local.xlsx';workbook(path,[HEADERS,row]);self.erp.commit_import(self.company,preview(path),confirmed=True)
        self.service=EBSReconciliation(self.erp)

    def packet(self,net='37.299999999999997',display='37,30',kind='float'):
        headers=['Ημ/νία','Εναλ. παρ/κό','Α.Φ.Μ.','Αξία','ΦΠΑ','Σύνολο']
        header='<table:table-row>'+''.join('<table:table-cell><text:p>'+h+'</text:p></table:table-cell>' for h in headers)+'</table:table-row>'
        cells=''.join('<table:table-cell><text:p>'+v+'</text:p></table:table-cell>' for v in ['2026-09-15','/17','000000001'])
        cells+=f'<table:table-cell office:value-type="{kind}" office:value="{escape(net)}"><text:p>{escape(display if kind=="float" else net)}</text:p></table:table-cell>'
        cells+='<table:table-cell office:value-type="float" office:value="8.9499999999999993"><text:p>8,95</text:p></table:table-cell><table:table-cell office:value-type="float" office:value="46.25"><text:p>46,25</text:p></table:table-cell>'
        path=self.folder/'source.ods';ods(path,header+'<table:table-row>'+cells+'</table:table-row>')
        return self.service.preview(self.company,path,'Συνθετικά',1,dict(date=0,invoice=1,vat=2,net=3,tax=4,gross=5),'2026-09-01','2026-09-30','000000008',complete=True,company_confirmed=True)

    def test_numeric_binary_storage_noise_uses_equivalent_displayed_cents(self):
        p=self.packet();item=p['rows'][0]
        self.assertEqual(item['raw'][3],'37.299999999999997')
        self.assertEqual(item['normalized']['net_exact'],'37.30')
        self.assertEqual(item['normalized']['tax_exact'],'8.95')
        self.assertEqual(next(iter(p['results'].values()))['match_kind'],'normalized')
        self.assertEqual(p['data'],(self.folder/'source.ods').read_bytes())
        self.assertEqual(len(item['storage_corrections']),2)

    def test_real_subcent_difference_and_actual_cent_difference_remain_conflicts(self):
        for value,display in [('37.3001','37,30'),('37.29','37,30')]:
            with self.subTest(value=value):
                p=self.packet(value,display)
                from decimal import Decimal
                self.assertEqual(Decimal(p['rows'][0]['normalized']['net_exact']),Decimal(value))
                self.assertEqual(next(iter(p['results'].values()))['match_kind'],'conflict')

    def test_numeric_source_value_is_authoritative_over_inconsistent_display(self):
        p=self.packet('37.299999999999997','37,29')
        self.assertEqual(p['rows'][0]['normalized']['net_exact'],'37.30')
        self.assertEqual(p['rows'][0]['raw'][3],'37.299999999999997')
        self.assertEqual(next(iter(p['results'].values()))['match_kind'],'normalized')

    def test_text_decimal_is_never_treated_as_binary_storage_noise(self):
        p=self.packet(kind='string')
        self.assertEqual(p['rows'][0]['normalized']['net_exact'],'37.299999999999997')
        self.assertEqual(next(iter(p['results'].values()))['match_kind'],'conflict')

    def test_reimport_keeps_original_raw_and_never_creates_documents(self):
        p=self.packet();self.service.commit(p,confirmed=True);self.service.commit(p,confirmed=True)
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM documents').fetchone()[0],1)
        self.assertTrue(all(row['match_kind']=='normalized' for row in self.service.results(self.company).values()))
        self.assertEqual(read_workbook(self.folder/'source.ods')['sheets'][0]['rows'][1][1][3],'37.299999999999997')

    def test_recovered_cents_do_not_resolve_competing_documents_arbitrarily(self):
        row=list(ROW);row[2:8]=['OTHER','17','2026-09-15','37.30','8.95','46.25'];row[8]=''
        path=self.folder/'competing.xlsx';workbook(path,[HEADERS,row]);self.erp.commit_import(self.company,preview(path),confirmed=True)
        p=self.packet()
        self.assertEqual([r['match_kind'] for r in p['results'].values()],['ambiguous','ambiguous'])
