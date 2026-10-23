"""Independent reader and suggestion checks are developer-only dependencies."""
from pathlib import Path
import tempfile
import unittest
import zipfile
from scripts.audit_reconciliation import audit_readers,reference_suggestions
from app.domain.ebs_matching import strict_key
from tests.fixtures import workbook
from tests.test_ebs_matching_rules import document,excel
from tests.test_ods import ods
from xml.sax.saxutils import escape

class QualityToolTests(unittest.TestCase):
    def test_calamine_and_bounded_importer_agree_on_ods_and_xlsx_without_mutating_source(self):
        headers=['Ημ/νία','Εναλ. παρ/κό','Α.Φ.Μ.','Αξία','ΦΠΑ','Σύνολο']
        values=['2026-09-15','INV/00123','000000001','100.00','24.00','124.00']
        with tempfile.TemporaryDirectory() as t:
            for extension in ('ods','xlsx'):
                path=Path(t)/('synthetic.'+extension)
                if extension=='xlsx':workbook(path,[headers,values])
                else:
                    rows=''.join('<table:table-row>'+''.join('<table:table-cell office:value-type="string"><text:p>'+escape(v)+'</text:p></table:table-cell>' for v in row)+'</table:table-row>' for row in (headers,values))
                    ods(path,rows)
                    with zipfile.ZipFile(path,'a') as archive:
                        archive.writestr('META-INF/manifest.xml','<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"><manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.spreadsheet"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>')
                original=path.read_bytes();report=audit_readers(path)
                self.assertEqual(report['mismatches'],[]);self.assertEqual(report['valid_rows'],1)
                self.assertEqual(report['compared_fields'],6);self.assertEqual(path.read_bytes(),original)
                self.assertNotIn('INV/00123',str(report));self.assertNotIn('000000001',str(report))
    def test_rapidfuzz_suggestions_cannot_cross_strict_blocks_or_change_a_decision(self):
        doc=document();candidate=excel('INV/00124');wrong=excel('INV/00123',vat='000000002');wrong['row']=3
        key=strict_key(doc,True);index={key:[candidate,wrong]}
        suggestions=reference_suggestions(doc,index)
        self.assertEqual([n for n,score in suggestions],[2])
        self.assertEqual(candidate['normalized']['invoice'],'inv/00124');self.assertNotIn(3,[n for n,score in suggestions])
