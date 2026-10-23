"""Registry lookup is read-only remotely; applying a preview is an explicit local edit."""
import json
from app.infrastructure.aade.credentials import WindowsCredentialStore,target_for
from app.infrastructure.aade.registry import credentials,lookup
from app.application.counterparties import Counterparties


class Registry:
    def __init__(self,erp):self.erp=erp;self.db=erp.db
    def identity(self,company):
        row=self.db.execute('SELECT vat FROM companies WHERE id=?',(company,)).fetchone()
        if row is None:raise ValueError('Δεν βρέθηκε εταιρεία')
        return row['vat'],target_for(self.erp.directory,row['vat'],'registry')
    def read_credentials(self,company):
        _,target=self.identity(company)
        return (self.erp.credential_store or WindowsCredentialStore()).read(target)
    def save_credentials(self,company,username,password,confirmed=False):
        if confirmed is not True:raise ValueError('Απαιτείται επιβεβαίωση κωδικών Μητρώου')
        value=credentials(username,password);_,target=self.identity(company);vault=self.erp.credential_store or WindowsCredentialStore();before=vault.read(target);vault.write(target,value)
        try:
            with self.db:self.erp.repository.audit(company,'registry_credentials_saved',None,dict(storage='Windows Credential Manager'))
        except Exception:
            if before is None:vault.delete(target)
            else:vault.write(target,before)
            raise
    def preview(self,company,counterparty,transport=lookup):
        card,_=Counterparties(self.erp).detail(company,counterparty);called_by,_=self.identity(company)
        if called_by=='000000000':raise ValueError('Όρισε πρώτα το πραγματικό ΑΦΜ εταιρείας στις ρυθμίσεις ΑΑΔΕ')
        value=self.read_credentials(company)
        if value is None:raise ValueError('Λείπουν ειδικοί κωδικοί Μητρώου. Άνοιξε Ρυθμίσεις → Συνδέσεις → Μητρώο ΑΑΔΕ. Δεν είναι οι κωδικοί myDATA.')
        return transport(value['username'],value['key'],called_by,card['vat'])
    def apply(self,company,counterparty,values,confirmed=False):
        if confirmed is not True:raise ValueError('Απαιτείται έλεγχος στοιχείων Μητρώου')
        card,_=Counterparties(self.erp).detail(company,counterparty)
        if values.get('afm')!=card['vat'] or not values.get('onomasia','').strip() or len(values['onomasia'])>256:raise ValueError('Τα στοιχεία δεν αντιστοιχούν στην καρτέλα')
        allowed=('afm','onomasia','commer_title','doy','doy_descr','postal_address','postal_address_no','postal_zip_code','postal_area_description','deactivation_flag_descr','firm_flag_descr')
        safe={k:str(values.get(k,''))[:512] for k in allowed}
        with self.db:
            self.db.execute('UPDATE counterparties SET name=? WHERE company_id=? AND id=?',(values['onomasia'].strip(),company,counterparty))
            self.db.execute('INSERT INTO counterparty_registry(counterparty_id,company_id,data_json) VALUES (?,?,?) ON CONFLICT(counterparty_id) DO UPDATE SET data_json=excluded.data_json,updated_at=CURRENT_TIMESTAMP',(counterparty,company,json.dumps(safe,ensure_ascii=False)))
            self.erp.repository.audit(company,'registry_details_applied',None,dict(counterparty_id=counterparty,before=card['name'],after=values['onomasia'].strip(),vat=card['vat']))
