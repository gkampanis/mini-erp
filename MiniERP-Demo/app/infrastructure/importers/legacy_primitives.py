"""Selected EBS v2.9 pure primitives; see docs/AUDIT.md for provenance. Not an RPA adapter."""
import datetime as dt

import decimal

import re

import unicodedata

import zipfile

import xml.etree.ElementTree as ET

from pathlib import Path

NS = {'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
      'p':'http://schemas.openxmlformats.org/package/2006/relationships'}

ALIASES = {
 'mark': ['μαρκ','mark','mydata mark','μοναδικος αριθμος καταχωρισης'],
 'date':['ημερομηνια εκδοσης','ημερομηνια','ημ νια','ημνια','invoice date','date','ημ εκδοσης'],
 'vat':['αφμ εκδοτη','αφμ προμηθευτη','αφμ πιστωτη','αφμ','supplier vat','supplier vat number','vat number','vat'],
 'invoice':['αρ παραστατικου','αριθμος παραστατικου','α α παραστατικου','τιμολογιο','invoice number','invoice no','παραστατικο'],
 'series':['σειρα','σειρα παραστατικου','series','invoice series'],
 'number':['αριθμος','αριθμος τιμολογιου','αριθμος παραστατικου','invoice number','invoice no'],
 'net':['καθαρη αξια','καθαρη','net amount','net value','net'],
 'tax':['φπα','φ π α','αξια φπα','vat amount','vat value','tax amount'],
 'gross':['συνολικη αξια','συνολο','μικτη αξια','gross amount','total amount','gross','total'],
 'description':['περιγραφη','τυπος παραστατικου','description','invoice type description'],
 'kind':['τυπος','ειδος παραστατικου','invoice type','type'],
}

def norm(s):
 s=unicodedata.normalize('NFKD',str(s or ''))
 s=''.join(c for c in s if not unicodedata.combining(c)).lower()
 return re.sub(r'[^a-z0-9α-ω]+',' ',s).strip()

NAMES={k:{norm(v) for v in labels} for k,labels in ALIASES.items()}

def column_index(ref):
 letters=re.match(r'[A-Z]+',ref or '')
 if not letters:return None
 n=0
 for x in letters.group():n=n*26+ord(x)-64
 return n-1

def sheets(z):
 # Resolve workbook relationship identifiers instead of assuming sheet1.xml.
 wb=ET.fromstring(z.read('xl/workbook.xml'))
 rels=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
 relmap={r.get('Id'):r.get('Target') for r in rels}
 for sh in wb.findall('.//m:sheet',NS):
  target=relmap.get(sh.get('{'+NS['r']+'}id'))
  if not target:continue
  target=target.lstrip('/')
  name=target if target.startswith('xl/') else 'xl/'+target
  if name in z.namelist():yield sh.get('name',''),name

def read_sheet(z,path,strings):
 root=ET.fromstring(z.read(path))
 result=[]
 for row in root.findall('.//m:sheetData/m:row',NS):
  data={}
  for c in row.findall('m:c',NS):
   idx=column_index(c.get('r'))
   if idx is None:continue
   v=c.find('m:v',NS); inline=c.find('m:is',NS)
   raw=(v.text or '') if v is not None else ''.join(t.text or '' for t in inline.findall('.//m:t',NS)) if inline is not None else ''
   if c.get('t')=='s' and raw: raw=strings[int(raw)]
   data[idx]=str(raw).strip()
  if data:result.append((int(row.get('r','0')),data))
 return result

def detect(header):
 result={}; taken=set()
 for key in ('mark','date','vat','net','tax','gross','description','kind','series','invoice','number'):
  for idx,value in header.items():
   if idx not in taken and norm(value) in NAMES[key]:
    result[key]=idx;taken.add(idx);break
 return result

def money(value):
 v=str(value or '').strip().replace('€','').replace(' ','').replace('\u00a0','')
 if ',' in v and '.' in v:
  v=v.replace('.','').replace(',','.') if v.rfind(',')>v.rfind('.') else v.replace(',','')
 elif ',' in v:v=v.replace(',','.')
 return decimal.Decimal(v or '0')
