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
                    document=self.db.execute('SELECT d.*,c.vat FROM documents d JOIN counterparties c ON c.id=d.counterparty_id WHERE d.company_id=? AND d.mark=?',(company,item['mark'])).fetchone()
                    state='unmatched'
                    if document and document['direction']!=item['direction']:document=None
                    if document:
                        try:equal=(document['vat']==item['vat'] and document['series']==item['series'] and document['number']==item['number'] and document['issue_date']==item['date'] and document['net_minor']==cents(item['net']) and document['tax_minor']==cents(item['tax']) and document['gross_minor']==cents(item['gross']))
                        except ValueError:equal=False
                        state='matched' if equal else 'different'
                    report[state]+=1
                    self.db.execute('INSERT INTO mydata_records(company_id,environment,mark,document_id,record_json,match_status,last_sync) VALUES (?,?,?,?,?,?,?) ON CONFLICT(company_id,environment,mark) DO UPDATE SET document_id=excluded.document_id,record_json=excluded.record_json,match_status=excluded.match_status,last_sync=excluded.last_sync',(company,environment,item['mark'],document['id'] if document else None,json.dumps(item,ensure_ascii=False),state,sync))
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

    def pdf_url(self,company,document,environment):
        self.erp.detail(company,document)
        row=self.db.execute('SELECT record_json FROM mydata_records WHERE company_id=? AND document_id=? AND environment=? AND match_status=?',(company,document,environment,'matched')).fetchone()
        if row is None:raise ValueError('Χρειάζεται συμφωνημένο παραστατικό ΑΑΔΕ για αυτό το περιβάλλον')
        url=json.loads(row['record_json']).get('pdf_url','')
        if not url:raise ValueError('Η ΑΑΔΕ δεν επέστρεψε downloadingInvoiceUrl. Χρειάζεται ο πάροχος ή το τοπικό PDF.')
        return url
