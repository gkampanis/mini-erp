"""Entirely synthetic workbook generator; no customer identifiers or documents."""
import zipfile
from xml.sax.saxutils import escape


def workbook(path, rows, *, epoch1904=False, formula=False):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml',f'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><workbookPr date1904="{int(epoch1904)}"/><sheets><sheet name="Συνθετικά" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/></Relationships>')
        content = []
        for i,row in enumerate(rows,1):
            cells = []
            for j,value in enumerate(row):
                if j>=26:raise ValueError('fixture supports A-Z')
                f = '<f>1+1</f>' if formula and i==2 and j==0 else ''
                cells.append(f'<c r="{chr(65+j)}{i}" t="inlineStr">{f}<is><t>{escape(str(value))}</t></is></c>')
            content.append(f'<row r="{i}">{"".join(cells)}</row>')
        z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(content)+'</sheetData></worksheet>')


HEADERS = ['ΑΦΜ','Επωνυμία','Σειρά','Αριθμός','Ημερομηνία','Καθαρή αξία','ΦΠΑ','Σύνολο','MARK']
ROW = ['000000001','ΣΥΝΘΕΤΙΚΟΣ ΠΡΟΜΗΘΕΥΤΗΣ Α','ΔΟΚ','1','21/10/2026','0,10','0,02','0,12','10000001']


def volume_workbook(path,count=2500,suppliers=300):
    """Two calendar months and synthetic VATs, for repeatable volume checks."""
    rows=[HEADERS]+[[f'{1+i%suppliers:09d}',f'ΣΥΝΘΕΤΙΚΟΣ {i%suppliers}', 'Δ',str(i+1),
                     f'2026-{9+i%2:02d}-15','10','2.40','12.40',str(100000000+i)] for i in range(count)]
    workbook(path,rows)


def demos(directory):
    directory.mkdir(parents=True,exist_ok=True)
    workbook(directory/'separate.xlsx',[HEADERS,ROW,['000000002','ΣΥΝΘΕΤΙΚΟΣ ΠΡΟΜΗΘΕΥΤΗΣ Β','Β','2','20/10/2026','100,00','24,00','124,00','10000002'],['BAD','ΑΠΟΡΡΙΠΤΕΑ','','3','21/10/2026','10','2,40','12,40','']])
    workbook(directory/'combined.xlsx',[
        ['Gross','Invoice no','Supplier VAT','VAT amount','Date','Net','Supplier name','MARK'],
        ['12.40','Γ/3','000000003','2.40','2026-10-19','10.00','ΣΥΝΘΕΤΙΚΟΣ ΠΡΟΜΗΘΕΥΤΗΣ Γ','10000003']])


def reconcile_empty(erp,company):
    """Explicit synthetic prerequisite: company attests zero EBS rows in test period."""
    from app.application.ebs_reconciliation import EBSReconciliation
    from pathlib import Path
    service=EBSReconciliation(erp);path=Path(erp.directory)/'synthetic-ebs-empty.xlsx'
    workbook(path,[HEADERS])
    mapping={'vat':0,'series':2,'number':3,'date':4,'net':5,'tax':6,'gross':7,'mark':8}
    owner=erp.db.execute('SELECT vat FROM companies WHERE id=?',(company,)).fetchone()[0]
    book=service.layout(path)
    prepared=service.preview(company,path,book['sheets'][0]['name'],1,mapping,'2000-01-01','2099-12-31',owner,complete=True,company_confirmed=True)
    return service.commit(prepared,confirmed=True)
