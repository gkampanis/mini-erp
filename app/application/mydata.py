"""Read-only AADE snapshot/reconciliation; never posts, cancels or rewrites invoices."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from app.infrastructure.aade.client import Client
from app.domain.validation import cents


class MyData:
    def __init__(self,erp):self.erp=erp;self.db=erp.db

    def fetch(self,company,date_from,date_to,environment,represented=False,test=False,client=None,cancel=None,method='RequestDocs'):
        row=self.db.execute('SELECT vat FROM companies WHERE id=?',(company,)).fetchone()
        if row is None:raise ValueError('Δεν βρέθηκε εταιρεία')
        if client is None:
            credentials=self.erp.mydata_credentials(company,environment)
            client=Client(environment,credentials['username'],credentials['key'])
        pages=client.fetch(date_from,date_to,entity_vat=row['vat'] if represented else None,single_page=test,cancel=cancel,method=method)
        if test:return dict(pages=len(pages),records=sum(len(p[1]['records']) for p in pages),message='Η ΑΑΔΕ απάντησε επιτυχώς σε '+method+'. Δεν αποθηκεύτηκαν παραστατικά.')
        return self.persist(company,environment,date_from,date_to,pages,method)

    def persist(self,company,environment,date_from,date_to,pages,method='RequestDocs'):
        if method not in ('RequestDocs','RequestTransmittedDocs'):raise ValueError('Μη επιτρεπόμενη μέθοδος λήψης')
        if environment not in ('test','production'):raise ValueError('Μη έγκυρο περιβάλλον')
        company_vat=self.db.execute('SELECT vat FROM companies WHERE id=?',(company,)).fetchone()
        if company_vat is None:raise ValueError('Δεν βρέθηκε εταιρεία')
        directory=self.erp.directory/'mydata'/'xml';directory.mkdir(parents=True,exist_ok=True)
        archived=[]
        for data,page in pages:
            digest=hashlib.sha256(data).hexdigest();path=directory/(digest+'.xml')
            if path.exists():
                if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Αλλοιωμένο XML στην αρχειοθήκη')
            else:
                fd,temp=tempfile.mkstemp(dir=directory)
                try:
                    with os.fdopen(fd,'wb') as out:out.write(data);out.flush();os.fsync(out.fileno())
                    os.replace(temp,path)
                finally:
                    if os.path.exists(temp):os.unlink(temp)
            archived.append((digest,path.relative_to(self.erp.directory).as_posix()))
        report=dict(matched=0,different=0,unmatched=0,foreign=0,cancelled=0,out_of_period=0)
        with self.db:
            sync=self.db.execute("INSERT INTO mydata_syncs(company_id,environment,method,date_from,date_to,report) VALUES (?,?,?,?,?,?)",(company,environment,method,date_from,date_to,'{}')).lastrowid
            for digest,path in archived:self.db.execute('INSERT OR IGNORE INTO mydata_pages(sync_id,sha256,storage_path) VALUES (?,?,?)',(sync,digest,path))
            for data,page in pages:
                for item in page['records']:
                    if not date_from<=item['date']<=date_to:report['out_of_period']+=1;continue
                    # Never associate another recipient's invoices with this company's Excel.
                    owner=item['receiver'] if method=='RequestDocs' else item['vat']
                    if owner!=company_vat[0]:report['foreign']+=1;continue
                    item=dict(item,direction='incoming' if method=='RequestDocs' else 'outgoing')
                    cp_vat=item['vat'] if item['direction']=='incoming' else item['receiver']
                    cp_name=item.get('name','') if item['direction']=='incoming' else item.get('receiver_name','')
                    role='supplier' if item['direction']=='incoming' else 'customer'
                    if len(cp_vat)==9 and cp_vat.isascii() and cp_vat.isdigit():
                        self.db.execute('INSERT INTO counterparties(company_id,vat,name,role) VALUES (?,?,?,?) ON CONFLICT(company_id,vat) DO NOTHING',(company,cp_vat,cp_name or 'Χωρίς επωνυμία',role))
                        cp=self.db.execute('SELECT id,name FROM counterparties WHERE company_id=? AND vat=?',(company,cp_vat)).fetchone()
                        self.db.execute('INSERT OR IGNORE INTO counterparty_roles(counterparty_id,role) VALUES (?,?)',(cp['id'],role))
                        if cp_name and cp['name'] in ('Χωρίς επωνυμία',cp_vat):
                            self.db.execute('UPDATE counterparties SET name=? WHERE id=?',(cp_name,cp['id']))
                            self.erp.repository.audit(company,'counterparty_named',None,dict(counterparty_id=cp['id'],before=cp['name'],after=cp_name,source='myDATA',sync=sync))
                    from app.application.reconciliation import associate
                    document,state,identity=associate(self.db,company,item)
                    item=dict(item,identity_verified=identity)
                    old=self.db.execute('SELECT match_status FROM mydata_records WHERE company_id=? AND environment=? AND mark=?',(company,environment,item['mark'])).fetchone()
                    if old and old[0]=='cancelled_at_aade':state='cancelled_at_aade'
                    report[state if state!='cancelled_at_aade' else 'cancelled']+=1
                    self.db.execute('INSERT INTO mydata_records(company_id,environment,mark,document_id,record_json,match_status,last_sync,invoice_type,is_delivery_note) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(company_id,environment,mark) DO UPDATE SET document_id=excluded.document_id,record_json=excluded.record_json,match_status=excluded.match_status,last_sync=excluded.last_sync,invoice_type=excluded.invoice_type,is_delivery_note=excluded.is_delivery_note',(company,environment,item['mark'],document['id'] if document else None,json.dumps(item,ensure_ascii=False),state,sync,item.get('kind',''),int(item.get('is_delivery_note',False))))
                for mark in page['cancellations']:
                    # Cancellation is an observed event only; do not cancel the local invoice.
                    self.db.execute("UPDATE mydata_records SET match_status='cancelled_at_aade',last_sync=? WHERE company_id=? AND environment=? AND mark=?",(sync,company,environment,mark))
                    report['cancelled']+=1
                    self.erp.repository.audit(company,'mydata_cancellation_observed',None,dict(mark=mark,environment=environment,sync=sync))
            self.db.execute('UPDATE mydata_syncs SET report=? WHERE id=?',(json.dumps(report),sync))
            self.erp.repository.audit(company,'mydata_read_completed',None,dict(sync=sync,environment=environment,**report))
        return dict(sync=sync,**report)

    def records(self,company,environment):
        return [dict(r) for r in self.db.execute('SELECT * FROM mydata_records WHERE company_id=? AND environment=? ORDER BY id DESC',(company,environment))]

    def document_type(self,company,document):
        from app.domain.invoice_types import classify
        row=self.db.execute("SELECT invoice_type,is_delivery_note FROM mydata_records WHERE company_id=? AND document_id=? ORDER BY environment='production' DESC,id DESC LIMIT 1",(company,document)).fetchone()
        return classify(row['invoice_type'],row['is_delivery_note']) if row else classify('')

    def pdf_url(self,company,document,environment):
        self.erp.detail(company,document)
        row=self.db.execute("SELECT record_json FROM mydata_records WHERE company_id=? AND document_id=? AND environment=? AND match_status IN ('matched','different')",(company,document,environment)).fetchone()
        if row is None:raise ValueError('Χρειάζεται συμφωνημένο παραστατικό ΑΑΔΕ για αυτό το περιβάλλον')
        stored=json.loads(row['record_json'])
        if not stored.get('identity_verified',False):raise ValueError('Δεν επαληθεύτηκε η ταυτότητα του παραστατικού για σύνδεση PDF')
        url=stored.get('pdf_url','')
        if not url:raise ValueError('Η ΑΑΔΕ δεν επέστρεψε downloadingInvoiceUrl. Χρειάζεται ο πάροχος ή το τοπικό PDF.')
        return url


    def reconcile_stored(self,company,environment=None):
        from app.application.reconciliation import associate
        rows=self.db.execute('SELECT * FROM mydata_records WHERE company_id=?'+(' AND environment=?' if environment else ''),(company,environment) if environment else (company,)).fetchall()
        with self.db:
            for row in rows:
                item=json.loads(row['record_json']);document,state,identity=associate(self.db,company,item)
                if row['match_status']=='cancelled_at_aade':state='cancelled_at_aade'
                item['identity_verified']=identity
                self.db.execute('UPDATE mydata_records SET document_id=?,record_json=?,match_status=? WHERE id=?',(document['id'] if document else None,json.dumps(item,ensure_ascii=False),state,row['id']))
        from app.application.provider_pdf import ProviderDatabase
        for row in rows:ProviderDatabase(self.erp,company,row['environment']).link_cached(row['mark'])
        return len(rows)

    def import_incoming(self,company,environment,date_from,date_to,confirmed=False):
        return self.import_documents(company,environment,date_from,date_to,confirmed=confirmed)

    def import_documents(self,company,environment,date_from,date_to,confirmed=False,direction='incoming'):
        if confirmed is not True:raise ValueError('Απαιτείται επιλογή άντλησης στη λίστα')
        if direction not in ('incoming','outgoing'):raise ValueError('Μη έγκυρη ροή παραστατικών')
        method='RequestDocs' if direction=='incoming' else 'RequestTransmittedDocs'
        from types import SimpleNamespace
        from app.domain.validation import record,rounding_changes
        payload=[];records=[];rejected=[]
        rows=self.records(company,environment)
        for row in rows:
            item=json.loads(row['record_json'])
            if item.get('direction')!=direction or not date_from<=item['date']<=date_to or row['match_status']=='cancelled_at_aade':continue
            raw=dict(item,_source='myDATA '+method,_sync=row['last_sync'])
            payload.append(raw);index=len(payload)
            try:
                from app.domain.invoice_types import aade_document
                normalized=aade_document(item,direction)
                fields=dict(net=item['net'],tax=item['tax'],gross=item['gross'])
                records.append(dict(row=index,raw=raw,document=normalized,rounding_changes=rounding_changes(fields,normalized)))
            except ValueError as exc:rejected.append(dict(row=index,raw=raw,reason=str(exc)))
        if not payload:return dict(inserted=0,duplicates=0,rejected=[],warnings=[])
        data=json.dumps(payload,ensure_ascii=False,sort_keys=True).encode();digest=hashlib.sha256(data).hexdigest()
        path=self.erp.directory/'sources'/(digest+'.json');path.parent.mkdir(exist_ok=True)
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Αλλοιωμένη αρχειοθετημένη πηγή ΑΑΔΕ')
        else:
            fd,temp=tempfile.mkstemp(dir=path.parent)
            try:
                with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
                os.replace(temp,path)
            finally:
                if os.path.exists(temp):os.unlink(temp)
        packet=SimpleNamespace(filename='myDATA '+method+' '+date_from+' — '+date_to,sha256=digest,records=records,rejected=rejected,headers={},mapping={},source_kind='aade')
        report=self.erp.repository.persist_import(company,packet,packet)
        self.reconcile_stored(company,environment)
        return report
