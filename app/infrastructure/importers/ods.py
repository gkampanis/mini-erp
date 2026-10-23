"""Bounded read-only ODS grids; no macros, formulas or external references run."""
import io
import zipfile
import xml.etree.ElementTree as ET
from decimal import Decimal,InvalidOperation

NS={
 'table':'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
 'text':'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
 'office':'urn:oasis:names:tc:opendocument:xmlns:office:1.0',
}


def read_ods(data):
    from app.infrastructure.importers.excel import MAX_EXPANDED,MAX_ROWS,MAX_COLUMNS
    attr=lambda ns,name:'{'+NS[ns]+'}'+name
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos=archive.infolist()
        if len(infos)>1000 or sum(i.file_size for i in infos)>MAX_EXPANDED or len({i.filename for i in infos})!=len(infos):raise ValueError('Υπέρβαση ορίων / διπλές εγγραφές ODS')
        xml=archive.read('content.xml')
        if b'\x00' in xml or b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():raise ValueError('Μη ασφαλές XML ODS')
        root=ET.fromstring(xml);result=[]
        for sheet in root.findall('./office:body/office:spreadsheet/table:table',NS):
            rows=[];formulas=set();line=1
            for row in sheet.findall('table:table-row',NS):
                raw={};column=0;formula=False
                for cell in row:
                    if cell.tag not in (attr('table','table-cell'),attr('table','covered-table-cell')):continue
                    count=int(cell.get(attr('table','number-columns-repeated'),'1'))
                    if count<1:raise ValueError('Μη έγκυρη επανάληψη στηλών ODS')
                    kind=cell.get(attr('office','value-type'),'')
                    # Direct paragraphs exclude comments/annotations containing personal notes.
                    text='\n'.join(''.join(p.itertext()) for p in cell.findall('text:p',NS)).strip()
                    value=cell.get(attr('office','date-value'),'')[:10] if kind=='date' else cell.get(attr('office','value'),text) if kind in ('float','currency','percentage') else text
                    if kind=='float' and text.isascii() and text.isdigit() and text.startswith('0'):
                        try:
                            if Decimal(text)==Decimal(value):value=text
                        except InvalidOperation:pass
                    has_formula=cell.get(attr('table','formula')) is not None
                    if value or has_formula:
                        if column+count>MAX_COLUMNS:raise ValueError('Όριο 200 στηλών ODS')
                        for index in range(column,column+count):raw[index]=value
                    column+=count;formula=formula or has_formula
                count=int(row.get(attr('table','number-rows-repeated'),'1'))
                if count<1:raise ValueError('Μη έγκυρη επανάληψη γραμμών ODS')
                if raw or formula:
                    if line+count-1>MAX_ROWS:raise ValueError('Όριο 20.000 γραμμών ODS')
                    for number in range(line,line+count):
                        rows.append((number,dict(raw)))
                        if formula:formulas.add(number)
                line+=count
            result.append(dict(name=sheet.get(attr('table','name'),''),rows=rows,formula_rows=formulas))
    if not result:raise ValueError('Δεν υπάρχουν αναγνώσιμα φύλλα ODS')
    return result
