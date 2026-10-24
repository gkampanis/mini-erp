"""Append-only Excel/EBS evidence, scoped to company+period, never an EBS write."""
from collections import Counter
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import tempfile
from app.infrastructure.importers.excel import read_workbook
from app.infrastructure.importers.legacy_primitives import norm,NAMES
from app.domain.validation import iso_date
from app.domain.ebs_matching import FIELDS,normalize,compare,fingerprint,vat
from app.domain.invoice_types import classify


def encode(value):return json.dumps(value,ensure_ascii=False,sort_keys=True)

def cell_address(column,row):
    if column is None:return '—'
    letters='';number=column+1
    while number:number,remainder=divmod(number-1,26);letters=chr(65+remainder)+letters
    return letters+str(row)

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

    @staticmethod
    def date_column(headers):
        columns=[c for c,label in headers.items() if norm(label) in NAMES['date']]
        return columns[0] if len(columns)==1 else None

    @classmethod
    def source_months(cls,sheet,header_row,epoch1904=False):
        headers=next((raw for line,raw in sheet['rows'] if line==header_row),{})
        column=cls.date_column(headers);months=set()
        if column is None:return months
        for line,raw in sheet['rows']:
            if line<=header_row or not raw.get(column):continue
            if column in sheet['formula_cells'].get(line,set()):continue
            try:months.add(iso_date(raw[column],epoch1904)[:7])
            except ValueError:pass
        return months

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
        mapping=dict(mapping)
        if 'date' not in mapping and self.date_column(headers) is not None:mapping['date']=self.date_column(headers)
        if 'date' not in mapping:raise ValueError('Χρειάζεται ημερομηνία έκδοσης στην εξαγωγή EBS. Δεν τεκμηριώνεται συμφωνία χωρίς ημερομηνία.')
        if not mapping or any(k not in FIELDS or type(v) is not int or v not in headers for k,v in mapping.items()) or len(set(mapping.values()))!=len(mapping):raise ValueError('Έλεγξε την αντιστοίχιση στηλών· κάθε στήλη χρησιμοποιείται μία φορά')
        if 'vat' not in mapping or not any(k in mapping for k in ('mark','number','invoice')):raise ValueError('Χρειάζεται ΑΦΜ προμηθευτή και MARK ή αριθμός παραστατικού')
        rows=[];ignored=[];fatal=[];blocking=[];period_column=self.date_column(headers)
        note_columns={c for c,label in headers.items() if norm(label) in ('σημειωση','σημειωσεις','παρατηρησεις','σχολιο','σχολια','note','notes','comments')}
        for line,raw in selected['rows']:
            formulas=selected['formula_cells'].get(line,set()) & set(mapping.values())
            if line<=header_row or (not any(raw.values()) and not formulas):continue
            empty=not any(str(raw.get(c,'')).strip() for c in mapping.values())
            note=empty and {c for c,value in raw.items() if str(value).strip()}<=note_columns
            repeated=all(norm(raw.get(c,''))==norm(headers[c]) for c in mapping.values())
            if not formulas and (note or repeated):
                ignored.append(dict(row=line,raw=raw,reason='Κενά όλα τα πεδία συμφωνίας' if note else 'Επανάληψη επικεφαλίδων'))
                continue
            if period_column is not None and raw.get(period_column):
                if period_column in selected['formula_cells'].get(line,set()):
                    fatal.append(f'{cell_address(period_column,line)}: η περίοδος προέρχεται από τύπο υπολογισμού· χρειάζεται σταθερή ημερομηνία στην εξαγωγή')
                    continue
                try:
                    source_date=iso_date(raw[period_column],book['epoch1904'])
                    if not start<=source_date<=end:fatal.append(f'{cell_address(period_column,line)}: το αρχείο περιέχει περίοδο {source_date[:7]}, ενώ επιλέχθηκε {start[:7]}')
                except ValueError:pass  # Report invalid dates per row, without stopping unrelated records.
            issues=[]
            item,error=normalize(raw,mapping,book['epoch1904'],numeric_columns=selected['numeric_cells'].get(line,set()),issues=issues)
            for field,column in mapping.items():
                if column in formulas:
                    item.pop(field+'_minor' if field in ('net','tax','gross') else field,None)
                    issues.append(dict(field=field,column=column,value=raw.get(column,''),message='Τύπος υπολογισμού σε πεδίο συμφωνίας· απαιτείται εξαγωγή σταθερής τιμής',formula=True))
            for issue in issues:
                issue.update(row=line,cell=cell_address(issue['column'],line),header=headers.get(issue['column'],issue['field']))
                if issue.get('formula') or (issue['field']=='vat' and not item.get('vat')):blocking.append(issue)
            error=' · '.join(dict.fromkeys(i['cell']+' · '+i['header']+': '+i['message'] for i in issues))
            if 'receiver' in mapping and (item.get('receiver')!=owner['vat']):fatal.append(f'Γραμμή {line}: διαφορετικό ή κενό ΑΦΜ εταιρείας')
            if item.get('date') and not start<=item['date']<=end:fatal.append(f'Γραμμή {line}: ημερομηνία εκτός περιόδου')
            rows.append(dict(row=line,raw=raw,normalized=item,error=error,issues=issues))
        if fatal:raise ValueError('\n'.join(fatal[:10]))
        # Keep defective rows as evidence and isolate their possible matches;
        # they must not prevent unrelated ready expenses from progressing.
        can_commit=True
        documents=[r for r in self.documents(company) if r['direction']=='incoming' and start<=r['issue_date']<=end]
        results=compare(documents,rows,bool(complete and can_commit))
        return dict(company=company,company_vat=owner['vat'],start=start,end=end,complete=bool(complete),can_commit=can_commit,blocking_issues=blocking,ignored_rows=ignored,sheet=sheet,header_row=header_row,mapping=dict(mapping),headers=headers,rows=rows,results=results,filename=book['filename'],data=book['data'],sha256=book['sha256'])

    def commit(self,preview,*,confirmed=False,remember=False):
        if confirmed is not True:raise ValueError('Απαιτείται ρητή επιβεβαίωση συμφωνίας')
        if hashlib.sha256(preview['data']).hexdigest()!=preview['sha256']:raise ValueError('Άλλαξε η πηγή της προεπισκόπησης')
        # Parse the frozen source again; never trust mutable normalized preview/results.
        p=self.preview(preview['company'],preview['filename'],preview['sheet'],preview['header_row'],preview['mapping'],preview['start'],preview['end'],preview['company_vat'],complete=preview['complete'],company_confirmed=True,data=preview['data'])
        if not p['can_commit']:
            details='\n'.join(i['cell']+' · '+i['header']+': '+i['message'] for i in p['blocking_issues'][:10])
            raise ValueError('Δεν αποθηκεύτηκε πλήρης συμφωνία. Διόρθωσε τα παρακάτω κελιά ή κάνε νέα προεπισκόπηση ως μερικού καταλόγου:\n'+details)
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
        with self.db:
            # Freeze decisions and append history in the same write transaction.
            self.db.execute('BEGIN IMMEDIATE')
            if self.db.execute("SELECT 1 FROM rpa_jobs WHERE company_id=? AND status='running'",(p['company'],)).fetchone():raise ValueError('Παύσε πρώτα το RPA πριν νέα συμφωνία EBS')
            docs=[r for r in self.documents(p['company']) if r['direction']=='incoming' and p['start']<=r['issue_date']<=p['end']]
            results=compare(docs,p['rows'],p['complete'])
            report=dict(Counter(r['status'] for r in results.values()),excel_rows=len(p['rows'])+len(p['ignored_rows']),ignored_rows=len(p['ignored_rows']),invalid_rows=sum(bool(r['error']) for r in p['rows']))
            report.update(exact_matches=sum(r['match_kind']=='exact' for r in results.values()),normalized_matches=sum(r['match_kind']=='normalized' for r in results.values()))
            run=self.db.execute('INSERT INTO ebs_reconciliation_runs(company_id,company_vat,date_from,date_to,filename,sha256,storage_path,sheet,header_row,mapping_json,complete,report_json,match_policy) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,2)',(p['company'],p['company_vat'],p['start'],p['end'],p['filename'],p['sha256'],path.relative_to(self.erp.directory).as_posix(),p['sheet'],p['header_row'],encode(p['mapping']),int(p['complete']),encode(report))).lastrowid
            self.db.executemany('INSERT INTO ebs_excel_rows(run_id,row_number,raw_json,normalized_json,error) VALUES (?,?,?,?,?)',[(run,r['row'],encode(r['raw']),encode(r['normalized']),r['error']) for r in p['rows']])
            self.db.executemany('INSERT INTO ebs_matches(run_id,document_id,status,reason,excel_rows_json,snapshot_hash,match_kind,match_signature) VALUES (?,?,?,?,?,?,?,?)',[(run,document,r['status'],r['reason'],encode(r['excel_rows']),r['snapshot_hash'],r['match_kind'],r['match_signature']) for document,r in results.items()])
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
        previous={r['document_id'] for r in matches.values() if r['status']=='registered' or r['match_kind']=='normalized'}
        items=[dict(r) for r in self.db.execute('SELECT i.id,i.job_id,i.document_id,i.status,j.mode,j.execution FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? ORDER BY i.id',(company,))]
        item_documents={r['id']:r['document_id'] for r in items}
        attempted={r['document_id'] for r in items if r['id'] not in ignore_items and r['mode']=='fill_only' and r['status'] not in ('queued','not_saved_confirmed')}
        latest={r['document_id']:r for r in items if r['id'] not in ignore_items and r['mode']=='fill_only' and r['status']!='queued'}
        saves={(r['entity_id'],json.loads(r['payload']).get('job')) for r in self.db.execute("SELECT entity_id,payload FROM audit_events WHERE company_id=? AND action='rpa_save_invoked' AND id>coalesce((SELECT max(id) FROM audit_events WHERE company_id=? AND action='company_identified'),0)",(company,company))}
        submitted={doc for doc,r in latest.items() if r['execution']=='save_new' and r['status'] in ('save_invoked','ui_saved_review','reviewed_by_operator') and (doc,r['job_id']) in saves}
        confirmations={}
        partial_confirmations={}
        for event in self.db.execute("SELECT entity_id,payload FROM audit_events WHERE company_id=? AND action='ebs_partial_confirmed' AND id>coalesce((SELECT max(id) FROM audit_events WHERE company_id=? AND action='company_identified'),0) ORDER BY id",(company,company)):
            payload=json.loads(event['payload']);partial_confirmations.setdefault(event['entity_id'],set()).add(payload.get('match_signature'))
        for event in self.db.execute("SELECT * FROM audit_events WHERE company_id=? AND action IN ('ebs_storage_operator_confirmed','ebs_pilot_operator_confirmed','ebs_storage_manual_confirmed') AND id>coalesce((SELECT max(id) FROM audit_events WHERE company_id=? AND action='company_identified'),0) ORDER BY id",(company,company)):
            payload=json.loads(event['payload']);document=event['entity_id'] or item_documents.get(payload.get('item'))
            if document:confirmations[document]=dict(source='manual_operator' if event['action']=='ebs_storage_manual_confirmed' else 'rpa_operator',reason='Επιβεβαιώθηκε οπτικά από τον χειριστή στο EBS',when=event['created_at'],filename='',run=None)
        result={}
        for doc in docs:
            state=dict(status='unreconciled',match_kind='',match_signature='',reason='Δεν έχει γίνει συμφωνία για την εταιρεία και την περίοδο',source='',run=None,filename='',when='')
            run=next((r for r in runs if r['date_from']<=doc['issue_date']<=r['date_to']),None)
            if run:
                match=matches.get((run['id'],doc['id']))
                state.update(source='excel_ebs',run=run['id'],filename=run['filename'],when=run['created_at'])
                if match and match['snapshot_hash']==fingerprint(doc):state.update(status=match['status'],reason=match['reason'],match_kind=match['match_kind'],match_signature=match['match_signature'])
                else:state.update(status='review',reason='Νέα ή μεταβλημένη εγγραφή μετά τη συμφωνία· επανάλαβε με το Excel')
                if run['match_policy']<2:state.update(status='review',match_kind='legacy',reason='Παλαιότερη συμφωνία: χρειάζεται επανέλεγχος με υποχρεωτική ημερομηνία έκδοσης')
                elif state['match_kind']=='normalized' and state['match_signature'] in partial_confirmations.get(doc['id'],set()):state.update(status='registered',match_kind='normalized_confirmed',reason='Καταχωρισμένο — Επιβεβαιωμένη μερική συμφωνία',source='normalization_operator')
                if state['status'] in ('not_registered','not_found') and doc['id'] in previous:state.update(status='review',reason='Προηγούμενο Excel την περιλάμβανε· χρειάζεται έλεγχος πριν νέα καταχώριση')
            if doc['id'] in confirmations:state.update(status='registered',**confirmations[doc['id']])
            elif doc['id'] in attempted and state['status']!='registered':state.update(status='review',match_kind='attempt',match_signature='',reason='Υπάρχει προηγούμενη προσπάθεια RPA· απαιτείται οπτικός έλεγχος στο EBS',source='rpa_attempt')
            result[doc['id']]=dict(doc,**state,submitted=doc['id'] in submitted,storage_verified=state['status']=='registered')
        return result

    def confirm_partial(self,company,document):
        """One inline action, bound to the exact document and frozen Excel evidence."""
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row=self.results(company).get(document)
            if row is None or row['status']!='review' or row['match_kind']!='normalized' or not row['match_signature']:raise ValueError('Δεν υπάρχει μοναδική μερική συμφωνία προς επιβεβαίωση')
            self.erp.repository.audit(company,'ebs_partial_confirmed',document,dict(match_signature=row['match_signature'],snapshot_hash=fingerprint(row),run=row['run'],verification='operator_identity_confirmation',not_database_verified=True))

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
