"""Single user action: credentials -> expense book/details -> local rows -> provider PDF."""
from datetime import date
import hashlib
import json
import os
import tempfile
from pathlib import Path
import threading
from app.application.mydata import MyData
from app.application.names import NameRecovery


class Sync:
    def __init__(self,erp):self.erp=erp;self.db=erp.db

    def preferences(self,company,environment):
        row=self.db.execute('SELECT * FROM sync_preferences WHERE company_id=? AND environment=?',(company,environment)).fetchone()
        return dict(row) if row else dict(company_id=company,environment=environment,represented=0,auto_pdf=0)

    def save_preferences(self,company,environment,represented=False,auto_pdf=False):
        if environment not in ('test','production'):raise ValueError('Μη έγκυρο περιβάλλον')
        with self.db:self.db.execute('INSERT INTO sync_preferences(company_id,environment,represented,auto_pdf) VALUES (?,?,?,?) ON CONFLICT(company_id,environment) DO UPDATE SET represented=excluded.represented,auto_pdf=excluded.auto_pdf',(company,environment,int(represented),int(auto_pdf)))

    def expense_book(self,company,environment,start,end,represented=False,client=None,cancel=None):
        from app.infrastructure.aade.client import Client
        owner=self.db.execute('SELECT vat FROM companies WHERE id=?',(company,)).fetchone()
        if owner is None:raise ValueError('Δεν βρέθηκε εταιρεία')
        if client is None:
            keys=self.erp.mydata_credentials(company,environment);client=Client(environment,keys['username'],keys['key'])
        pages=client.fetch(start,end,entity_vat=owner['vat'] if represented else None,method='RequestMyExpenses',cancel=cancel)
        folder=self.erp.directory/'mydata'/'xml';folder.mkdir(parents=True,exist_ok=True);hashes=[];rows=[]
        for data,page in pages:
            digest=hashlib.sha256(data).hexdigest();path=folder/(digest+'.xml')
            if path.exists():
                if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Αλλοιωμένη πηγή βιβλίου εξόδων')
            else:
                fd,temp=tempfile.mkstemp(dir=folder)
                try:
                    with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
                    os.replace(temp,path)
                finally:
                    if os.path.exists(temp):os.unlink(temp)
            hashes.append(digest);rows.extend(page['rows'])
        with self.db:
            self.db.execute('INSERT INTO expense_book_snapshots(company_id,environment,date_from,date_to,rows_json,xml_hashes_json) VALUES (?,?,?,?,?,?)',(company,environment,start,end,json.dumps(rows,ensure_ascii=False),json.dumps(hashes)))
            self.erp.repository.audit(company,'expense_book_received',None,dict(environment=environment,date_from=start,date_to=end,rows=len(rows),xml_sha256=hashes))
        return dict(rows=len(rows),count=sum(int(r['count']) for r in rows))

    def run(self,company,environment,start,end,represented=False,import_incoming=True,download=True,book=True,cancel=None,client=None,destination=None,marks=None,notice=lambda _:None,methods=None):
        cancel=cancel or threading.Event();service=MyData(self.erp);result={}
        owner=self.db.execute('SELECT vat FROM companies WHERE id=?',(company,)).fetchone()
        if owner is None or owner['vat']=='000000000':raise ValueError('Όρισε το πραγματικό ΑΦΜ εταιρείας πριν την άντληση ΑΑΔΕ')
        date.fromisoformat(start);date.fromisoformat(end)
        if start>end:raise ValueError('Μη έγκυρη περίοδος')
        result['names']=NameRecovery(self.erp).run(company)
        if book:
            notice('Άντληση συνοπτικού βιβλίου εξόδων…')
            try:result['book']=self.expense_book(company,environment,start,end,represented,client,cancel)
            except (ValueError,RuntimeError) as exc:result['book_error']=str(exc)
        methods=methods or ('RequestDocs',)
        if not methods or any(m not in ('RequestDocs','RequestTransmittedDocs') for m in methods):raise ValueError('Μη επιτρεπόμενη μέθοδος άντλησης')
        imports=dict(inserted=0,duplicates=0,rejected=[],warnings=[]);sync_ids=[]
        for method in dict.fromkeys(methods):
            if cancel.is_set():return dict(result,cancelled=True,**{'import':imports})
            direction='incoming' if method=='RequestDocs' else 'outgoing'
            notice('Άντληση '+('ληφθέντων' if direction=='incoming' else 'εκδοθέντων')+' και αντιστοίχιση MARK…')
            try:
                fetched=service.fetch(company,start,end,environment,represented=represented,client=client,cancel=cancel,method=method)
                result['received' if direction=='incoming' else 'issued']=fetched;sync_ids.append(fetched['sync'])
                if import_incoming:
                    imported=service.import_documents(company,environment,start,end,confirmed=True,direction=direction)
                    for key in imports:
                        if isinstance(imports[key],list):imports[key].extend(imported.get(key,[]))
                        else:imports[key]+=imported.get(key,0)
            except (ValueError,RuntimeError) as exc:result.setdefault('errors',[]).append(dict(method=method,error=str(exc)))
        result['import']=imports
        service.reconcile_stored(company,environment)
        if download and sync_ids and not cancel.is_set():
            from app.application.provider_pdf import run
            eligible=[r['mark'] for r in service.records(company,environment) if r['last_sync'] in sync_ids and (marks is None or r['mark'] in {str(m) for m in marks})]
            notice('Λήψη και σύνδεση PDF παρόχων…')
            try:result['pdf']=run(self.erp,company,environment,destination or self.erp.directory/'pdf-archive',cancel,marks=eligible,dates=(start,end),notice=notice)
            except (ValueError,RuntimeError,OSError) as exc:result['pdf_error']=str(exc)
        return result

    def document_pdf(self,company,document,cancel=None,notice=lambda _:None):
        """No link entry. Fetch exact document day when its official source isn't cached."""
        from app.application.provider_pdf import ProviderDatabase,run
        row,_=self.erp.detail(company,document)
        if not row['mark']:raise ValueError('Λείπει MARK. Χρειάζεται πρώτα ασφαλής αντιστοίχιση με ΑΑΔΕ.')
        active=self.db.execute('SELECT environment FROM aade_settings WHERE company_id=?',(company,)).fetchone()
        if active is None:raise ValueError('Σύνδεσε πρώτα τους κωδικούς ΑΑΔΕ από το κουμπί «ΑΑΔΕ / myDATA»')
        environment=active[0];options=self.preferences(company,environment);cancel=cancel or threading.Event()
        adapter=ProviderDatabase(self.erp,company,environment,[row['mark']])
        if adapter.link_cached(row['mark']):return dict(cached=True,pdf=dict(saved=0,skipped=1,pending=0))
        record=self.db.execute('SELECT 1 FROM mydata_records WHERE company_id=? AND environment=? AND mark=?',(company,environment,row['mark'])).fetchone()
        if record is None:
            MyData(self.erp).fetch(company,row['issue_date'],row['issue_date'],environment,represented=bool(options['represented']),cancel=cancel)
        MyData(self.erp).reconcile_stored(company,environment)
        MyData(self.erp).pdf_url(company,document,environment)
        result=run(self.erp,company,environment,self.erp.directory/'pdf-archive',cancel,marks=[row['mark']],notice=notice)
        if not self.erp.attachments(company,document):raise ValueError('Το PDF παραμένει εκκρεμές στον πάροχο. Χρησιμοποίησε «Ανάκτηση εκκρεμών» στον ορατό browser της ΑΑΔΕ.')
        return dict(pdf=result,cached=False)
