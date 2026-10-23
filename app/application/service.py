from pathlib import Path
import hashlib
import os
import tempfile
from app.infrastructure.repository import Repository
from app.infrastructure.importers.excel import preview
from app.domain.preparation import preparation_values


class ERP:
    def __init__(self, directory, credential_store=None):
        self.directory = Path(directory)
        self.credential_store = credential_store
        self.repository = Repository(directory)
        self.db = self.repository.db

    def close(self):
        self.repository.close()

    def company(self, vat, name):
        return self.repository.company(vat, name)

    def search(self, company, query='', **filters):
        return self.repository.search(company, query, **filters)

    def detail(self, company, document):
        return self.repository.detail(company, document)

    def prepare_document(self, company, document, group, account_code, note='', actor='local_operator', confirmed=False):
        values = preparation_values(group, account_code, note, actor, confirmed)
        return self.repository.prepare_document(company, document, values)

    def preparation(self, company, document):
        return self.repository.preparation(company, document)

    def import_reviews(self, company):
        return self.repository.import_reviews(company)

    def _archive(self, item):
        directory = self.directory / 'sources'
        directory.mkdir(exist_ok=True)
        path = directory / (item.sha256 + '.xlsx')
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != item.sha256:
                raise ValueError('Αλλοιωμένο αρχείο προέλευσης')
            return
        fd, temp = tempfile.mkstemp(dir=directory)
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(item.data)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def commit_import(self, company, item, *, confirmed=False, fail_after=None):
        if not confirmed:
            raise ValueError('Απαιτείται ρητή επιβεβαίωση εισαγωγής')
        if hashlib.sha256(item.data).hexdigest() != item.sha256:
            raise ValueError('Αλλοιωμένο preview')
        # Reparse the original bytes using confirmed mapping; do not trust mutable preview records.
        fd, temp = tempfile.mkstemp(suffix=Path(item.filename).suffix)
        try:
            with os.fdopen(fd,'wb') as out:
                out.write(item.data)
            checked = preview(temp, item.mapping)
        finally:
            os.unlink(temp)
        if not checked.records:
            raise ValueError('Δεν υπάρχουν έγκυρες εγγραφές')
        self._archive(item)  # Content-addressed orphan on rollback is safe; never a partial DB import.
        report=self.repository.persist_import(company, item, checked, fail_after)
        from app.application.mydata import MyData
        try:
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mydata_records'").fetchone():
                MyData(self).reconcile_stored(company)
        except (ValueError,OSError) as exc:
            report['warnings'].append(dict(reason='Η εισαγωγή αποθηκεύτηκε· εκκρεμεί σύνδεση ΑΑΔΕ/PDF: '+str(exc)))
        return report

    def rename_counterparty(self, company, counterparty, name, confirmed=False):
        if confirmed is not True:raise ValueError('Απαιτείται επιβεβαίωση επωνυμίας')
        return self.repository.rename_counterparty(company,counterparty,name)

    def mydata_credentials(self, company, environment=None):
        from app.infrastructure.aade.credentials import WindowsCredentialStore,target_for
        row=self.db.execute('SELECT vat FROM companies WHERE id=?',(company,)).fetchone()
        if row is None:raise ValueError('Δεν βρέθηκε εταιρεία')
        stored=self.db.execute('SELECT environment FROM aade_settings WHERE company_id=?',(company,)).fetchone()
        environment=environment or (stored[0] if stored else 'test')
        if environment not in ('test','production'):raise ValueError('Μη έγκυρο περιβάλλον')
        vault=self.credential_store or WindowsCredentialStore()
        value=vault.read(target_for(self.directory,row['vat'],environment))
        return dict(environment=environment,username=value['username'] if value else '',key=value['key'] if value else '')

    def save_mydata_credentials(self, company, environment, username, key, confirmed=False):
        from app.infrastructure.aade.credentials import WindowsCredentialStore,target_for,validate
        if confirmed is not True:raise ValueError('Απαιτείται επιβεβαίωση αποθήκευσης κωδικών')
        value=validate(environment,username,key)
        row=self.db.execute('SELECT vat FROM companies WHERE id=?',(company,)).fetchone()
        if row is None:raise ValueError('Δεν βρέθηκε εταιρεία')
        vault=self.credential_store or WindowsCredentialStore()
        target=target_for(self.directory,row['vat'],environment)
        before=vault.read(target)
        vault.write(target,value)
        try:
            with self.db:
                self.db.execute("INSERT INTO aade_settings(company_id,environment) VALUES (?,?) ON CONFLICT(company_id) DO UPDATE SET environment=excluded.environment,updated_at=CURRENT_TIMESTAMP",(company,environment))
                self.repository.audit(company,'mydata_credentials_saved',None,dict(environment=environment,storage='Windows Credential Manager'))
        except Exception:
            if before is None:vault.delete(target)
            else:vault.write(target,before)
            raise

    def attachments(self, company, document):
        self.detail(company,document)
        return [dict(r) for r in self.db.execute('SELECT * FROM attachments WHERE company_id=? AND document_id=? ORDER BY id',(company,document))]

    def attach_pdf(self, company, document, filename, kind='invoice', data=None, source='local', confirmed=False):
        from app.infrastructure.pdf_archive import KINDS,store,MAX_PDF
        if confirmed is not True:raise ValueError('Απαιτείται επιβεβαίωση σύνδεσης PDF')
        self.detail(company,document)
        if kind not in KINDS:raise ValueError('Άγνωστο είδος αρχείου')
        if data is None:
            with Path(filename).open('rb') as stream:data=stream.read(MAX_PDF+1)
        digest,relative=store(self.directory,data)
        with self.db:
            self.db.execute('INSERT INTO attachments(company_id,document_id,kind,sha256,storage_path,original_filename,source) VALUES (?,?,?,?,?,?,?) ON CONFLICT(company_id,document_id,kind,sha256) DO NOTHING',(company,document,kind,digest,relative,Path(filename).name,source))
            row=self.db.execute('SELECT * FROM attachments WHERE company_id=? AND document_id=? AND kind=? AND sha256=?',(company,document,kind,digest)).fetchone()
            self.repository.audit(company,'pdf_linked',document,dict(attachment_id=row['id'],kind=kind,sha256=digest))
        return dict(row)

    def download_pdf(self, company, document, url, kind='invoice', confirmed=False, cancel=None):
        from app.infrastructure.pdf_archive import download
        if confirmed is not True:raise ValueError('Απαιτείται επιβεβαίωση λήψης PDF')
        self.detail(company,document)
        data,source=download(url,cancel)
        return self.attach_pdf(company,document,'download.pdf',kind,data,source,confirmed=True)

    def attachment_path(self, company, document, attachment):
        from app.infrastructure.pdf_archive import checked_path
        self.detail(company,document)
        row=self.db.execute('SELECT * FROM attachments WHERE id=? AND company_id=? AND document_id=?',(attachment,company,document)).fetchone()
        if row is None:raise ValueError('Δεν βρέθηκε συνδεδεμένο αρχείο')
        return checked_path(self.directory,row['storage_path'],row['sha256'])
