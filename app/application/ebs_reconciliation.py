"""Append-only Excel/EBS evidence, scoped to company+period, never an EBS write."""
from collections import Counter
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import tempfile
from app.infrastructure.importers.excel import read_workbook
from app.domain.ebs_matching import FIELDS,normalize,compare,fingerprint,vat
from app.domain.invoice_types import classify


def encode(value):return json.dumps(value,ensure_ascii=False,sort_keys=True)

class EBSReconciliation:
    def __init__(self,erp):self.erp=erp;self.db=erp.db

    def documents(self,company):
        rows=self.erp.search(company);types={}
        for r in self.db.execute("SELECT document_id,invoice_type,is_delivery_note FROM mydata_records WHERE company_id=? AND document_id IS NOT NULL ORDER BY environment='production',id",(company,)):types[r['document_id']]=dict(r)
        for row in rows:
            kind=types.get(row['id'],{})
            row.update(classify(kind.get('invoice_type',''),kind.get('is_delivery_note',False)))
        return rows

    def layout(self,path,*,data=None):return read_workbook(path,data=data)

    def preview(self,company,path,sheet,header_row,mapping,start,end,company_vat,*,complete=False,company_confirmed=False,data=None):
        owner=self.db.execute('SELECT vat FROM companies WHERE id=?',(company,)).fetchone()
        if owner is None or vat(company_vat)!=owner['vat']:raise ValueError('Το ΑΦΜ της εξαγωγής δεν συμφωνεί με την εταιρεία')
        date.fromisoformat(start);date.fromisoformat(end)
        if start>end:raise ValueError('Μη έγκυρη περίοδος')
        if not company_confirmed:raise ValueError('Επιβεβαίωσε την εταιρεία και την περίοδο της εξαγωγής EBS')
        book=self.layout(path,data=data);selected=next((s for s in book['sheets'] if s['name']==sheet),None)
        if selected is None:raise ValueError('Δεν βρέθηκε το επιλεγμένο φύλλο')
        headers=next((raw for line,raw in selected['rows'] if line==header_row),None)
        if headers is None:raise ValueError('Δεν βρέθηκε η γραμμή επικεφαλίδων')
        if not mapping or any(k not in FIELDS or type(v) is not int or v not in headers for k,v in mapping.items()) or len(set(mapping.values()))!=len(mapping):raise ValueError('Έλεγξε την αντιστοίχιση στηλών· κάθε στήλη χρησιμοποιείται μία φορά')
        if 'vat' not in mapping or not any(k in mapping for k in ('mark','number','invoice')):raise ValueError('Χρειάζεται ΑΦΜ προμηθευτή και MARK ή αριθμός παραστατικού')
        rows=[];fatal=[]
        for line,raw in selected['rows']:
            if line<=header_row or not any(raw.values()):continue
            item,error=normalize(raw,mapping,book['epoch1904'])
            if line in selected['formula_rows']:error='Τύπος Excel: απαιτείται εξαγωγή σταθερών τιμών'
            if 'receiver' in mapping and (item.get('receiver')!=owner['vat']):fatal.append(f'Γραμμή {line}: διαφορετικό ή κενό ΑΦΜ εταιρείας')
            if item.get('date') and not start<=item['date']<=end:fatal.append(f'Γραμμή {line}: ημερομηνία εκτός περιόδου')
            rows.append(dict(row=line,raw=raw,normalized=item,error=error))
        if fatal:raise ValueError('\n'.join(fatal[:10]))
        if complete and any(not r['normalized'].get('vat') or r['row'] in selected['formula_rows'] for r in rows):raise ValueError('Δεν μπορεί να τεκμηριωθεί πλήρης κατάλογος με άγνωστο ΑΦΜ ή τύπους υπολογισμού. Χρειάζονται ΑΦΜ και σταθερές τιμές.')
        documents=[r for r in self.documents(company) if r['direction']=='incoming' and start<=r['issue_date']<=end]
        results=compare(documents,rows,complete)
        return dict(company=company,company_vat=owner['vat'],start=start,end=end,complete=bool(complete),sheet=sheet,header_row=header_row,mapping=dict(mapping),headers=headers,rows=rows,results=results,filename=book['filename'],data=book['data'],sha256=book['sha256'])

    def commit(self,preview,*,confirmed=False,remember=False):
        if confirmed is not True:raise ValueError('Απαιτείται ρητή επιβεβαίωση συμφωνίας')
        if hashlib.sha256(preview['data']).hexdigest()!=preview['sha256']:raise ValueError('Άλλαξε η πηγή της προεπισκόπησης')
        # Parse the frozen source again; never trust mutable normalized preview/results.
        p=self.preview(preview['company'],preview['filename'],preview['sheet'],preview['header_row'],preview['mapping'],preview['start'],preview['end'],preview['company_vat'],complete=preview['complete'],company_confirmed=True,data=preview['data'])
        folder=self.erp.directory/'ebs-excel';folder.mkdir(exist_ok=True)
        path=folder/(p['sha256']+Path(p['filename']).suffix.lower())
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest()!=p['sha256']:raise ValueError('Αλλοιωμένη πηγή συμφωνίας')
        else:
            fd,temp=tempfile.mkstemp(dir=folder)
            try:
                with os.fdopen(fd,'wb') as stream:stream.write(p['data']);stream.flush();os.fsync(stream.fileno())
                os.replace(temp,path)
            finally:
                if os.path.exists(temp):os.unlink(temp)
        report=dict(Counter(r['status'] for r in p['results'].values()));report['excel_rows']=len(p['rows']);report['invalid_rows']=sum(bool(r['error']) for r in p['rows'])
        with self.db:
            # Freeze decisions and append history in the same write transaction.
            self.db.execute('BEGIN IMMEDIATE')
            if self.db.execute("SELECT 1 FROM rpa_jobs WHERE company_id=? AND status='running'",(p['company'],)).fetchone():raise ValueError('Παύσε πρώτα το RPA πριν νέα συμφωνία EBS')
            docs=[r for r in self.documents(p['company']) if r['direction']=='incoming' and p['start']<=r['issue_date']<=p['end']]
            results=compare(docs,p['rows'],p['complete'])
            report.update(Counter(r['status'] for r in results.values()))
            run=self.db.execute('INSERT INTO ebs_reconciliation_runs(company_id,company_vat,date_from,date_to,filename,sha256,storage_path,sheet,header_row,mapping_json,complete,report_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(p['company'],p['company_vat'],p['start'],p['end'],p['filename'],p['sha256'],path.relative_to(self.erp.directory).as_posix(),p['sheet'],p['header_row'],encode(p['mapping']),int(p['complete']),encode(report))).lastrowid
            self.db.executemany('INSERT INTO ebs_excel_rows(run_id,row_number,raw_json,normalized_json,error) VALUES (?,?,?,?,?)',[(run,r['row'],encode(r['raw']),encode(r['normalized']),r['error']) for r in p['rows']])
            self.db.executemany('INSERT INTO ebs_matches(run_id,document_id,status,reason,excel_rows_json,snapshot_hash) VALUES (?,?,?,?,?,?)',[(run,document,r['status'],r['reason'],encode(r['excel_rows']),r['snapshot_hash']) for document,r in results.items()])
            if remember:
                layout=self.layout_hash(p['headers'])
                self.db.execute('INSERT INTO ebs_column_mappings(company_id,layout_hash,sheet,header_row,mapping_json) VALUES (?,?,?,?,?) ON CONFLICT(company_id,layout_hash) DO UPDATE SET sheet=excluded.sheet,header_row=excluded.header_row,mapping_json=excluded.mapping_json',(p['company'],layout,p['sheet'],p['header_row'],encode(p['mapping'])))
            self.erp.repository.audit(p['company'],'ebs_excel_reconciled',None,dict(run=run,source='excel_ebs',sha256=p['sha256'],company_vat=p['company_vat'],company_attested=True,period=[p['start'],p['end']],complete=p['complete'],report=report))
        return dict(run=run,**report)

    @staticmethod
    def layout_hash(headers):return hashlib.sha256(encode(headers).encode()).hexdigest()

    def saved_mapping(self,company,headers):
        row=self.db.execute('SELECT mapping_json FROM ebs_column_mappings WHERE company_id=? AND layout_hash=?',(company,self.layout_hash(headers))).fetchone()
        return json.loads(row[0]) if row else {}

    def results(self,company,*,ignore_items=()):
        docs=self.documents(company)
        runs=[dict(r) for r in self.db.execute('SELECT r.* FROM ebs_reconciliation_runs r JOIN companies c ON c.id=r.company_id AND c.vat=r.company_vat WHERE r.company_id=? ORDER BY r.id DESC',(company,))]
        matches={(r['run_id'],r['document_id']):dict(r) for r in self.db.execute('SELECT m.* FROM ebs_matches m JOIN ebs_reconciliation_runs r ON r.id=m.run_id JOIN companies c ON c.id=r.company_id AND c.vat=r.company_vat WHERE r.company_id=?',(company,))}
        previous={r['document_id'] for r in matches.values() if r['status']=='registered'}
        items=[dict(r) for r in self.db.execute('SELECT i.id,i.document_id,i.status,j.mode FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=?',(company,))]
        item_documents={r['id']:r['document_id'] for r in items}
        attempted={r['document_id'] for r in items if r['id'] not in ignore_items and r['mode']=='fill_only' and r['status']!='queued'}
        confirmations={}
        for event in self.db.execute("SELECT * FROM audit_events WHERE company_id=? AND action IN ('ebs_storage_operator_confirmed','ebs_pilot_operator_confirmed','ebs_storage_manual_confirmed') AND id>coalesce((SELECT max(id) FROM audit_events WHERE company_id=? AND action='company_identified'),0) ORDER BY id",(company,company)):
            payload=json.loads(event['payload']);document=event['entity_id'] or item_documents.get(payload.get('item'))
            if document:confirmations[document]=dict(source='manual_operator' if event['action']=='ebs_storage_manual_confirmed' else 'rpa_operator',reason='Επιβεβαιώθηκε οπτικά από τον χειριστή στο EBS',when=event['created_at'],filename='',run=None)
        result={}
        for doc in docs:
            state=dict(status='unreconciled',reason='Δεν έχει γίνει συμφωνία για την εταιρεία και την περίοδο',source='',run=None,filename='',when='')
            run=next((r for r in runs if r['date_from']<=doc['issue_date']<=r['date_to']),None)
            if run:
                match=matches.get((run['id'],doc['id']))
                state.update(source='excel_ebs',run=run['id'],filename=run['filename'],when=run['created_at'])
                if match and match['snapshot_hash']==fingerprint(doc):state.update(status=match['status'],reason=match['reason'])
                else:state.update(status='review',reason='Νέα ή μεταβλημένη εγγραφή μετά τη συμφωνία· επανάλαβε με το Excel')
                if state['status'] in ('not_registered','not_found') and doc['id'] in previous:state.update(status='review',reason='Προηγούμενο Excel την περιλάμβανε· χρειάζεται έλεγχος πριν νέα καταχώριση')
            if doc['id'] in confirmations:state.update(status='registered',**confirmations[doc['id']])
            elif doc['id'] in attempted and state['status']!='registered':state.update(status='review',reason='Υπάρχει προηγούμενη προσπάθεια RPA· απαιτείται οπτικός έλεγχος στο EBS',source='rpa_attempt')
            result[doc['id']]=dict(doc,**state)
        return result

    def assert_rpa(self,company,documents,*,required=False,ignore_items=()):
        rows=self.results(company,ignore_items=ignore_items)
        for document in documents:
            row=rows.get(document)
            if row is None:raise ValueError('Δεν βρέθηκε παραστατικό στην εταιρεία')
            if row['status'] in ('registered','review') or (required and row['status']!='not_registered'):
                raise ValueError('Συμφωνία EBS: '+row['reason'])

    def confirm_manual(self,company,document,note,*,confirmed=False):
        row=next((r for r in self.documents(company) if r['id']==document),None)
        if row is None:raise ValueError('Δεν βρέθηκε παραστατικό στην εταιρεία')
        if confirmed is not True or not isinstance(note,str) or not note.strip():raise ValueError('Επιβεβαίωσε οπτικά την αποθήκευση και πρόσθεσε σημείωση')
        with self.db:self.erp.repository.audit(company,'ebs_storage_manual_confirmed',document,dict(source='manual_operator',note=note.strip()[:2000],snapshot_hash=fingerprint(row),verification='visual_operator',not_database_verified=True))

    def evidence(self,company,document):
        result=self.results(company).get(document)
        if result is None:raise ValueError('Δεν βρέθηκε παραστατικό στην εταιρεία')
        if not result['run']:return result,[]
        match=self.db.execute('SELECT excel_rows_json FROM ebs_matches WHERE run_id=? AND document_id=?',(result['run'],document)).fetchone()
        numbers=set(json.loads(match[0])) if match else set()
        rows=[dict(r) for r in self.db.execute('SELECT * FROM ebs_excel_rows WHERE run_id=? ORDER BY row_number',(result['run'],)) if r['row_number'] in numbers]
        run=self.db.execute('SELECT mapping_json FROM ebs_reconciliation_runs WHERE id=? AND company_id=?',(result['run'],company)).fetchone()
        mapping=json.loads(run[0])
        for row in rows:
            row['normalized']=json.loads(row['normalized_json']);raw=json.loads(row['raw_json'])
            row['original_reference']=raw.get(str(mapping['invoice']),'') if 'invoice' in mapping else '/'.join(raw.get(str(mapping[k]),'') for k in ('series','number') if k in mapping and raw.get(str(mapping[k]),''))
        return result,rows
