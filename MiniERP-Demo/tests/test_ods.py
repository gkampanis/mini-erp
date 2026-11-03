"""Synthetic ODS cells; the user's export is never copied into automated fixtures."""
import tempfile
from pathlib import Path
import unittest
import zipfile
from app.infrastructure.importers.excel import read_workbook


def ods(path,rows):
    content='''<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:spreadsheet><table:table table:name="Συνθετικά">'''+rows+'''</table:table></office:spreadsheet></office:body></office:document-content>'''
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('mimetype','application/vnd.oasis.opendocument.spreadsheet');archive.writestr('content.xml',content)


class ODSTests(unittest.TestCase):
    def test_header_and_group_containers_keep_physical_rows_and_formulas(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'synthetic.ods'
            ods(path,'<table:table-header-rows><table:table-row><table:table-cell><text:p>Α.Φ.Μ.</text:p></table:table-cell></table:table-row></table:table-header-rows><table:table-row-group><table:table-row><table:table-cell office:value-type="string"><text:p>000000001</text:p></table:table-cell><table:table-cell table:formula="of:=1+1" office:value-type="float" office:value="2"/></table:table-row></table:table-row-group>')
            sheet=read_workbook(path)['sheets'][0]
            self.assertEqual(sheet['rows'],[(1,{0:'Α.Φ.Μ.'}),(2,{0:'000000001',1:'2'})])
            self.assertEqual(sheet['formula_cells'],{2:{1}})
    def test_numeric_cell_types_preserve_raw_values_and_allow_exact_identifier_normalization(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'synthetic.ods'
            ods(path,'<table:table-row><table:table-cell office:value-type="float" office:value="1.0"><text:p>1</text:p></table:table-cell><table:table-cell office:value-type="float" office:value="1E+0"><text:p>000000001</text:p></table:table-cell><table:table-cell office:value-type="float" office:value="1.23456789E+8"><text:p>123456789</text:p></table:table-cell><table:table-cell office:value-type="string"><text:p>1.0</text:p></table:table-cell></table:table-row>')
            sheet=read_workbook(path)['sheets'][0];raw=sheet['rows'][0][1]
            self.assertEqual(raw,{0:'1.0',1:'000000001',2:'1.23456789E+8',3:'1.0'})
            self.assertEqual(sheet['numeric_cells'],{1:{0,1,2}})
            from app.domain.ebs_matching import normalize
            raw.update({4:'1',5:'0.24',6:'1.24',7:'2026-09-15'})
            mapping={'invoice':0,'vat':2,'net':4,'tax':5,'gross':6,'date':7}
            item,error=normalize(raw,mapping,numeric_columns=sheet['numeric_cells'][1])
            self.assertFalse(error);self.assertEqual((item['invoice'],item['vat']),('1','123456789'))
            mapping.update(invoice=3,vat=1)
            item,error=normalize(raw,mapping,numeric_columns=sheet['numeric_cells'][1])
            self.assertFalse(error);self.assertEqual((item['invoice'],item['vat']),('1.0','000000001'))
    def test_typed_values_comments_and_empty_repeats_are_read_without_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'synthetic.ods'
            ods(path,'''<table:table-row><table:table-cell office:value-type="string"><office:annotation><text:p>ΙΔΙΩΤΙΚΟ ΣΧΟΛΙΟ</text:p></office:annotation><text:p>Ημ/νία</text:p></table:table-cell><table:table-cell><text:p>Εναλ. παρ/κό</text:p></table:table-cell></table:table-row><table:table-row><table:table-cell office:value-type="date" office:date-value="2026-09-15"><text:p>15/9/2026</text:p></table:table-cell><table:table-cell office:value-type="string"><text:p>INV/00123</text:p></table:table-cell><table:table-cell office:value-type="float" office:value="124.00"><text:p>124,00</text:p></table:table-cell><table:table-cell table:number-columns-repeated="1000"/></table:table-row><table:table-row table:number-rows-repeated="1000000"><table:table-cell/></table:table-row>''')
            book=read_workbook(path);sheet=book['sheets'][0]
            self.assertEqual(len(sheet['rows']),2);self.assertEqual(sheet['rows'][0][1][0],'Ημ/νία')
            self.assertEqual(sheet['rows'][1][1],{0:'2026-09-15',1:'INV/00123',2:'124.00'})
            self.assertEqual(sheet['formula_rows'],set())
    def test_populated_repeats_and_xml_entities_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'synthetic.ods'
            ods(path,'<table:table-row table:number-rows-repeated="20001"><table:table-cell><text:p>DATA</text:p></table:table-cell></table:table-row>')
            with self.assertRaises(ValueError):read_workbook(path)
            with zipfile.ZipFile(path,'w') as archive:archive.writestr('content.xml','<!DOCTYPE x [<!ENTITY y "z">]><x/>')
            with self.assertRaises(ValueError):read_workbook(path)
    def test_formulas_are_flagged_without_evaluating_cached_result(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'synthetic.ods'
            ods(path,'<table:table-row><table:table-cell table:formula="of:=1+1" office:value-type="float" office:value="2"><text:p>2</text:p></table:table-cell></table:table-row>')
            self.assertEqual(read_workbook(path)['sheets'][0]['formula_rows'],{1})
