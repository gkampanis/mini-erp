"""Adapt the user's pinned myInvoices provider engine to the ERP's existing records."""
import json
from pathlib import Path
from app.infrastructure.optional_packages import activate
activate()
from app.infrastructure.providers.models import Client,ApplicationError
from app.infrastructure.providers.pdf_downloads import SAVED_STATES,PDFDownloader
from app.infrastructure.providers.automatic_downloads import AutomaticPDFDownloader
from app.infrastructure.providers.browser_recovery import RecoveryPDFDownloader


class ProviderDatabase:
    def __init__(self,erp,company,environment,marks=None,*,allow_income=False):
        self.erp=erp;self.company=company;self.environment=environment;self.marks=None if marks is None else {str(x) for x in marks}
        self.allow_income=allow_income and self.marks is not None and len(self.marks)==1
        self.path=erp.directory/'mini_erp.sqlite3'

    def download_candidates(self,client_id,dates=None):
        rows=[]
        for record in self.erp.db.execute('SELECT * FROM mydata_records WHERE company_id=? AND environment=? ORDER BY id',(self.company,self.environment)):
            item=json.loads(record['record_json'])
            from app.domain.invoice_types import income_record
            if income_record(item) and not self.allow_income:continue
            if self.marks is not None and item['mark'] not in self.marks:continue
            if record['match_status']=='cancelled_at_aade' or not item.get('pdf_url'):continue
            if dates and not dates[0]<=item['date']<=dates[1]:continue
            latest=self.erp.db.execute('SELECT * FROM provider_attempts WHERE company_id=? AND environment=? AND mark=? ORDER BY id DESC LIMIT 1',(self.company,self.environment,item['mark'])).fetchone()
            rows.append(dict(item,mark=int(item['mark']),download_url=item['pdf_url'],issue_date=item['date'],issuer_vat=item['vat'],recipient_vat=item['receiver'],total=item['gross'],pdf_state=latest['state'] if latest else None,pdf_source_hash=latest['source_hash'] if latest else None))
        return rows

    def failed_download_candidates(self,client_id,dates=None,table=None):
        return [r for r in self.download_candidates(client_id,dates) if r['pdf_state'] and r['pdf_state'] not in SAVED_STATES]

    def invoice(self,client_id,mark):
        return next((row for row in self.download_candidates(client_id) if row['mark']==int(mark)),None)

    def saved_pdf(self,client_id,mark,source_hash):
        row=self.erp.db.execute('SELECT * FROM provider_attempts WHERE company_id=? AND environment=? AND mark=? AND source_hash=? ORDER BY id DESC LIMIT 1',(self.company,self.environment,str(mark),source_hash)).fetchone()
        return dict(row) if row and row['state'] in SAVED_STATES else None

    def linkable(self,mark):
        row=self.erp.db.execute('SELECT document_id,record_json,match_status FROM mydata_records WHERE company_id=? AND environment=? AND mark=?',(self.company,self.environment,str(mark))).fetchone()
        if not row or not row['document_id']:return None
        identity=json.loads(row['record_json']).get('identity_verified',row['match_status']=='matched')
        return row if identity and row['match_status'] in ('matched','different') else None

    @staticmethod
    def attachment_kind(linked):
        from app.domain.invoice_types import classify
        item=json.loads(linked['record_json']);family=classify(item.get('kind',''),item.get('is_delivery_note',False))['family']
        return 'delivery_note' if family=='delivery_note' else 'invoice' if family in ('invoice','credit_note') else 'other'

    def link_cached(self,mark):
        import hashlib
        linked=self.linkable(mark)
        if linked is None:return False
        item=json.loads(linked['record_json']);source=hashlib.sha256(item.get('pdf_url','').encode()).hexdigest()
        saved=self.saved_pdf(str(self.company),mark,source)
        if not saved or not saved['path']:return False
        path=Path(saved['path'])
        if not path.is_file() or path.is_symlink() or path.stat().st_size!=saved['byte_count'] or hashlib.sha256(path.read_bytes()).hexdigest()!=saved['sha256']:return False
        kind=self.attachment_kind(linked)
        exists=self.erp.db.execute('SELECT 1 FROM attachments WHERE company_id=? AND document_id=? AND kind=? AND sha256=?',(self.company,linked['document_id'],kind,saved['sha256'])).fetchone()
        if not exists:self.erp.attach_pdf(self.company,linked['document_id'],path,kind=kind,source='provider:'+saved['state'],confirmed=True)
        return True

    def record_pdf(self,client_id,mark,state,source_hash,path=None,checksum=None,size=None):
        linked=None;blob=None
        if state in SAVED_STATES and path:
            linked=self.linkable(mark)
            if linked and linked[0]:
                self.erp.detail(self.company,linked[0])
                from app.infrastructure.pdf_archive import store,MAX_PDF
                with Path(path).open('rb') as stream:data=stream.read(MAX_PDF+1)
                blob=store(self.erp.directory,data)
                if blob[0]!=checksum:raise ApplicationError('Το PDF άλλαξε πριν τη σύνδεση με το παραστατικό')
        with self.erp.db:
            self.erp.db.execute('INSERT INTO provider_attempts(company_id,environment,mark,state,source_hash,path,sha256,byte_count) VALUES (?,?,?,?,?,?,?,?)',(self.company,self.environment,str(mark),state,source_hash,path,checksum,size))
            if blob:
                kind=self.attachment_kind(linked)
                self.erp.db.execute("INSERT INTO attachments(company_id,document_id,kind,sha256,storage_path,original_filename,source) VALUES (?,?,?,?,?,?,?) ON CONFLICT(company_id,document_id,kind,sha256) DO NOTHING",(self.company,linked[0],kind,blob[0],blob[1],Path(path).name,'provider:'+state))
                self.erp.repository.audit(self.company,'pdf_linked',linked[0],dict(kind=kind,sha256=blob[0],source='provider:'+state))
            self.erp.repository.audit(self.company,'provider_pdf_result',None,dict(mark=str(mark),environment=self.environment,state=state,sha256=checksum))


def run(erp,company,environment,destination,cancel,marks=None,recovery=False,notice=lambda _:None,observer=None,dates=None,*,allow_income=False):
    try:import pypdf
    except ImportError:raise ValueError('Πάτησε πρώτα «Εγκατάσταση browser PDF» στις ρυθμίσεις ΑΑΔΕ για τις βιβλιοθήκες λήψης/προβολής.') from None
    row=erp.db.execute('SELECT * FROM companies WHERE id=?',(company,)).fetchone()
    if row is None:raise ValueError('Δεν βρέθηκε εταιρεία')
    client=Client(str(company),row['name'],row['vat'],'production' if environment=='production' else 'development')
    adapter=ProviderDatabase(erp,company,environment,marks,allow_income=allow_income)
    backend=RecoveryPDFDownloader(adapter,notice=notice,marks=marks) if recovery else AutomaticPDFDownloader(adapter,notice=notice)
    if observer:backend.observer=observer
    for row in adapter.download_candidates(str(company),dates):adapter.link_cached(row['mark'])
    return backend.run(client,Path(destination),cancel,dates=dates)
