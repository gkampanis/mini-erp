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


def displayed_money(value,text):
    """Recover a displayed cent amount only within binary serialization noise.

    Raw numeric cells remain intact; real subcent differences remain exact.
    """
    from app.domain.validation import money,spreadsheet_cent
    try:
        original=Decimal(value);shown=money(text)
        if not original.is_finite() or not shown.is_finite() or max(abs(original),abs(shown))>Decimal('1000000000000'):return None
        if shown!=shown.quantize(Decimal('.01')) or original==shown:return None
        if shown==0 and original!=0:return None
        # No arithmetic/comparison of accounting amounts uses binary floats.
        if spreadsheet_cent(original)==shown:return format(shown,'.2f')
    except (InvalidOperation,ValueError,OverflowError):pass
    return None


def read_ods(data):
    from app.infrastructure.importers.excel import MAX_EXPANDED,MAX_ROWS,MAX_COLUMNS
    attr=lambda ns,name:'{'+NS[ns]+'}'+name
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos=archive.infolist()
        if len(infos)>1000 or sum(i.file_size for i in infos)>MAX_EXPANDED or len({i.filename for i in infos})!=len(infos):raise ValueError('Υπέρβαση ορίων / διπλές εγγραφές ODS')
        xml=archive.read('content.xml')
        if b'\x00' in xml or b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():raise ValueError('Μη ασφαλές XML ODS')
        root=ET.fromstring(xml);result=[]
        def table_rows(container):
            for child in container:
                if child.tag==attr('table','table-row'):yield child
                elif child.tag in (attr('table','table-header-rows'),attr('table','table-row-group'),attr('table','table-rows')):yield from table_rows(child)
        for sheet in root.findall('./office:body/office:spreadsheet/table:table',NS):
            rows=[];formulas={};numerics={};money_cells={};line=1
            for row in table_rows(sheet):
                raw={};column=0;formula=set();numeric=set();displayed={}
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
                    recovered=displayed_money(value,text) if kind in ('float','currency') and text and not has_formula else None
                    if value or has_formula:
                        if column+count>MAX_COLUMNS:raise ValueError('Όριο 200 στηλών ODS')
                        for index in range(column,column+count):
                            raw[index]=value
                            if has_formula:formula.add(index)
                            if kind in ('float','currency','percentage'):numeric.add(index)
                            if recovered is not None:displayed[index]=recovered
                    column+=count
                count=int(row.get(attr('table','number-rows-repeated'),'1'))
                if count<1:raise ValueError('Μη έγκυρη επανάληψη γραμμών ODS')
                if raw or formula:
                    if line+count-1>MAX_ROWS:raise ValueError('Όριο 20.000 γραμμών ODS')
                    for number in range(line,line+count):
                        rows.append((number,dict(raw)))
                        if formula:formulas[number]=set(formula)
                        if numeric:numerics[number]=set(numeric)
                        if displayed:money_cells[number]=dict(displayed)
                line+=count
            result.append(dict(name=sheet.get(attr('table','name'),''),rows=rows,formula_rows=set(formulas),formula_cells=formulas,numeric_cells=numerics,money_cells=money_cells))
    if not result:raise ValueError('Δεν υπάρχουν αναγνώσιμα φύλλα ODS')
    return result
