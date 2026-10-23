"""Bounded XML XLSX/XLSM reader. Never evaluates formulas or executes macros."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import io
import json
import zipfile
import xml.etree.ElementTree as ET
from app.infrastructure.importers.legacy_primitives import NS, NAMES, norm, sheets, read_sheet
from app.domain.validation import record, rounding_changes

MAX_FILE = 20 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024
MAX_ROWS = 20000
MAX_COLUMNS = 200
NAMES = {**NAMES, 'name': {norm(x) for x in ['επωνυμία', 'επωνυμία εκδότη','επωνυμία προμηθευτή','επωνυμία αντισυμβαλλομένου','ονομασία προμηθευτή','αντισυμβαλλόμενος','προμηθευτής', 'supplier name', 'issuer name','seller name','counterparty name','name','επωνυμία / ονοματεπώνυμο','επωνυμία/ονοματεπώνυμο εκδότη','επωνυμία - ονοματεπώνυμο','επωνυμία συναλλασσόμενου','επωνυμία αντισυμβαλλόμενου','επωνυμία εκδότη (προμηθευτή)','ονοματεπώνυμο / επωνυμία','ονοματεπώνυμο εκδότη']},
         'currency': {norm(x) for x in ['νόμισμα', 'currency']}}
REQUIRED = ('vat', 'date', 'net', 'tax')

@dataclass
class Preview:
    filename: str
    data: bytes
    sha256: str
    sheet: str
    headers: dict
    mapping: dict
    records: list
    rejected: list


def header_mapping(header):
    mapping={}
    for key,aliases in NAMES.items():
        matches=[i for i,label in header.items() if norm(label) in aliases]
        if len(matches)==1:mapping[key]=matches[0]
    # Name labels vary across AADE exports; select an issuer name, never recipient name.
    names=[];issuers=[]
    for index,label in header.items():
        value=norm(label)
        is_name=value.startswith(('επωνυμια','ονοματεπωνυμο','ονομασια')) or value in NAMES['name']
        recipient=any(word in value for word in ('ληπτη','πελατη','recipient','buyer','customer'))
        if is_name and not recipient:
            names.append(index)
            if any(word in value for word in ('εκδοτη','προμηθευτη','πιστωτη','issuer','supplier','seller')):issuers.append(index)
    candidates=issuers or names
    mapping.pop('name',None)
    if len(candidates)==1:mapping['name']=candidates[0]
    return mapping


def read_workbook(path, *, data=None):
    path = Path(path)
    if path.suffix.lower() not in ('.xlsx', '.xlsm', '.ods'):
        raise ValueError('Υποστηρίζονται .xlsx/.xlsm/.ods, όχι .xls')
    if data is None:
        if path.stat().st_size > MAX_FILE:raise ValueError('Μέγιστο αρχείο 20 MB')
        with path.open('rb') as stream:data=stream.read(MAX_FILE+1)
    if len(data) > MAX_FILE:
        raise ValueError("Μέγιστο αρχείο 20 MB")
    if path.suffix.lower()=='.ods':
        from app.infrastructure.importers.ods import read_ods
        return dict(filename=path.name,data=data,sha256=hashlib.sha256(data).hexdigest(),epoch1904=False,sheets=read_ods(data))
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos = z.infolist()
        if len(infos) > 1000 or sum(x.file_size for x in infos) > MAX_EXPANDED:
            raise ValueError('Υπέρβαση ορίων αποσυμπίεσης Excel')
        if len({x.filename for x in infos}) != len(infos):
            raise ValueError('Διπλές εγγραφές ZIP')
        # Reject DTDs/entities before any XML parser is invoked.
        for info in infos:
            if info.filename.lower().endswith(('.xml', '.rels')):
                xml = z.read(info)
                if b'\x00' in xml or b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
                    raise ValueError('Μη ασφαλές XML')
        strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            strings = [''.join(t.text or '' for t in si.findall('.//m:t', NS))
                       for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si', NS)]
        epoch = ET.fromstring(z.read('xl/workbook.xml')).find('m:workbookPr', NS)
        epoch1904 = epoch is not None and epoch.get('date1904') in ('1', 'true')
        worksheets = []
        for name, location in sheets(z):
            xml = ET.fromstring(z.read(location))
            elements = xml.findall('.//m:sheetData/m:row', NS)
            if len(elements) > MAX_ROWS or any(len(r) > MAX_COLUMNS for r in elements):
                raise ValueError('Όριο 20.000 γραμμών / 200 στηλών')
            rows = read_sheet(z, location, strings)
            formula_rows = {int(r.get('r', '0')) for r in elements if r.find('.//m:f', NS) is not None}
            worksheets.append(dict(name=name,rows=rows,formula_rows=formula_rows))
    if not worksheets:raise ValueError('Δεν υπάρχουν αναγνώσιμα φύλλα')
    return dict(filename=path.name,data=data,sha256=hashlib.sha256(data).hexdigest(),epoch1904=epoch1904,sheets=worksheets)


def preview(path, manual_mapping=None):
    book=read_workbook(path);choices=[]
    for worksheet in book['sheets']:
        name,rows,formula_rows=worksheet['name'],worksheet['rows'],worksheet['formula_rows']
        for pos, (_, header) in enumerate(rows[:12]):
            mapping=header_mapping(header)
            score=sum(k in mapping for k in REQUIRED)*5+sum(k in mapping for k in ('invoice','number','series'))
            choices.append((score,name,rows,pos,header,mapping,formula_rows))
    if not choices:
        raise ValueError('Δεν υπάρχουν αναγνώσιμα φύλλα')
    _, sheet, rows, pos, headers, mapping, formula_rows = max(choices, key=lambda x:x[0])
    if manual_mapping is not None:
        if any(k not in NAMES or type(v) is not int or v not in headers for k,v in manual_mapping.items()):
            raise ValueError('Μη έγκυρη αντιστοίχιση στηλών')
        mapping = dict(manual_mapping)
    missing = [k for k in REQUIRED if k not in mapping]
    if 'number' not in mapping and 'invoice' not in mapping:
        missing.append('number/invoice')
    records, rejected = [], []
    if not missing:
        for row_no, raw in rows[pos+1:]:
            if not any(raw.values()):
                continue
            try:
                if row_no in formula_rows:
                    raise ValueError('Τύπος Excel: απαιτούνται σταθερές τιμές')
                fields = {k:raw.get(v, '') for k,v in mapping.items()}
                item = record(fields, book['epoch1904'])
                records.append(dict(row=row_no, raw=raw, document=item,rounding_changes=rounding_changes(fields,item)))
            except (ValueError, OverflowError) as exc:
                rejected.append(dict(row=row_no, reason=str(exc), raw=raw))
    else:
        rejected.append(dict(row=rows[pos][0], reason='Λείπουν mappings: '+', '.join(missing), raw=headers))
    return Preview(book['filename'],book['data'],book['sha256'],sheet,headers,mapping,records,rejected)
