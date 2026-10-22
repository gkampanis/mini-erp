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
    def __init__(self,erp,company,environment,marks=None):
        self.erp=erp;self.company=company;self.environment=environment;self.marks=None if marks is None else {str(x) for x in marks}
        self.path=erp.directory/'mini_erp.sqlite3'

    def download_candidates(self,client_id,dates=None):
        rows=[]
        for record in self.erp.db.execute('SELECT * FROM mydata_records WHERE company_id=? AND environment=? ORDER BY id',(self.company,self.environment)):
            item=json.loads(record['record_json'])
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

    def record_pdf(self,client_id,mark,state,source_hash,path=None,checksum=None,size=None):
        linked=None;blob=None
        if state in SAVED_STATES and path:
            linked=self.erp.db.execute('SELECT document_id FROM mydata_records WHERE company_id=? AND environment=? AND mark=? AND match_status=?',(self.company,self.environment,str(mark),'matched')).fetchone()
            if linked and linked[0]:
                self.erp.detail(self.company,linked[0])
                from app.infrastructure.pdf_archive import store,MAX_PDF
                with Path(path).open('rb') as stream:data=stream.read(MAX_PDF+1)
                blob=store(self.erp.directory,data)
                if blob[0]!=checksum:raise ApplicationError('Το PDF άλλαξε πριν τη σύνδεση με το παραστατικό')
        with self.erp.db:
            self.erp.db.execute('INSERT INTO provider_attempts(company_id,environment,mark,state,source_hash,path,sha256,byte_count) VALUES (?,?,?,?,?,?,?,?)',(self.company,self.environment,str(mark),state,source_hash,path,checksum,size))
            if blob:
                self.erp.db.execute("INSERT INTO attachments(company_id,document_id,kind,sha256,storage_path,original_filename,source) VALUES (?,?,'invoice',?,?,?,?) ON CONFLICT(company_id,document_id,kind,sha256) DO NOTHING",(self.company,linked[0],blob[0],blob[1],Path(path).name,'provider:'+state))
                self.erp.repository.audit(self.company,'pdf_linked',linked[0],dict(kind='invoice',sha256=blob[0],source='provider:'+state))
            self.erp.repository.audit(self.company,'provider_pdf_result',None,dict(mark=str(mark),environment=self.environment,state=state,sha256=checksum))


def run(erp,company,environment,destination,cancel,marks=None,recovery=False,notice=lambda _:None,observer=None,dates=None):
    try:import pypdf
    except ImportError:raise ValueError('Πάτησε πρώτα «Εγκατάσταση browser PDF» στις ρυθμίσεις ΑΑΔΕ για τις βιβλιοθήκες λήψης/προβολής.') from None
    row=erp.db.execute('SELECT * FROM companies WHERE id=?',(company,)).fetchone()
    if row is None:raise ValueError('Δεν βρέθηκε εταιρεία')
    client=Client(str(company),row['name'],row['vat'],'production' if environment=='production' else 'development')
    adapter=ProviderDatabase(erp,company,environment,marks)
    backend=RecoveryPDFDownloader(adapter,notice=notice,marks=marks) if recovery else AutomaticPDFDownloader(adapter,notice=notice)
    if observer:backend.observer=observer
    return backend.run(client,Path(destination),cancel,dates=dates)
