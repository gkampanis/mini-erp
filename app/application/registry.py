"""Registry lookup is read-only remotely; applying a preview is an explicit local edit."""
import json
import threading
from app.infrastructure.aade.credentials import WindowsCredentialStore,target_for
from app.infrastructure.aade.registry import credentials,lookup,RegistryAccessError,RegistryLimited,RegistryNotFound
from app.application.counterparties import Counterparties
from app.domain.validation import checked_greek_vat


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
    def apply(self,company,counterparty,values,confirmed=False,*,only_if_blank=False):
        if confirmed is not True:raise ValueError('Απαιτείται έλεγχος στοιχείων Μητρώου')
        card,_=Counterparties(self.erp).detail(company,counterparty)
        name=values.get('onomasia')
        if values.get('afm')!=card['vat'] or not isinstance(name,str) or not name.strip() or len(name)>256 or name.strip()==card['vat'] or any(ord(c)<32 for c in name):raise ValueError('Τα στοιχεία δεν αντιστοιχούν στην καρτέλα ή δεν έχουν έγκυρη επωνυμία')
        allowed=('afm','onomasia','commer_title','doy','doy_descr','postal_address','postal_address_no','postal_zip_code','postal_area_description','deactivation_flag_descr','firm_flag_descr')
        safe={k:str(values.get(k,''))[:512] for k in allowed}
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            card,_=Counterparties(self.erp).detail(company,counterparty)
            if only_if_blank and card['name'].strip():return False
            self.db.execute('UPDATE counterparties SET name=? WHERE company_id=? AND id=?',(values['onomasia'].strip(),company,counterparty))
            self.db.execute('INSERT INTO counterparty_registry(counterparty_id,company_id,data_json) VALUES (?,?,?) ON CONFLICT(counterparty_id) DO UPDATE SET data_json=excluded.data_json,updated_at=CURRENT_TIMESTAMP',(counterparty,company,json.dumps(safe,ensure_ascii=False)))
            self.erp.repository.audit(company,'registry_details_applied',None,dict(counterparty_id=counterparty,before=card['name'],after=values['onomasia'].strip(),vat=card['vat'],source='AADE RgWsPublic2',blank_only=only_if_blank))
        return True

    def fill_missing(self,company,*,transport=lookup,cancel=None,notice=lambda _:None):
        """One explicit batch approval; successes commit individually, never PDF."""
        cancel=cancel or threading.Event();called_by,_=self.identity(company)
        if called_by=='000000000':raise ValueError('Όρισε πρώτα το πραγματικό ΑΦΜ εταιρείας στις ρυθμίσεις ΑΑΔΕ')
        keys=self.read_credentials(company)
        if keys is None:raise ValueError('Λείπουν ειδικοί κωδικοί Μητρώου. Άνοιξε Ρυθμίσεις → Συνδέσεις → Μητρώο ΑΑΔΕ.')
        pending=[dict(r) for r in self.db.execute('SELECT id,vat,name FROM counterparties WHERE company_id=? ORDER BY id',(company,)) if not r['name'].strip()]
        report=dict(filled=0,skipped=0,not_found=0,failed=0,total=len(pending),cancelled=False,stopped='');seen=set()
        for index,card in enumerate(pending):
            if cancel.is_set():report.update(cancelled=True);report['skipped']+=len(pending)-index;break
            current=self.db.execute('SELECT name FROM counterparties WHERE company_id=? AND id=?',(company,card['id'])).fetchone()
            try:checked_greek_vat(card['vat'])
            except ValueError:report['skipped']+=1;notice(dict(done=index+1,total=len(pending)));continue
            if current is None or current['name'].strip() or card['vat']=='000000000' or card['vat'] in seen:
                report['skipped']+=1;notice(dict(done=index+1,total=len(pending)));continue
            seen.add(card['vat'])
            try:
                values=transport(keys['username'],keys['key'],called_by,card['vat'])
                changed=self.apply(company,card['id'],values,confirmed=True,only_if_blank=True)
                report['filled' if changed else 'skipped']+=1
            except RegistryNotFound:report['not_found']+=1
            except (RegistryAccessError,RegistryLimited) as exc:
                report['failed']+=1;report['skipped']+=len(pending)-index-1
                report['stopped']='Έλεγξε κωδικούς και δικαιώματα Μητρώου' if isinstance(exc,RegistryAccessError) else 'Περιορισμός ή προσωρινή μη διαθεσιμότητα υπηρεσίας'
                notice(dict(done=index+1,total=len(pending)));break
            except Exception:
                # Do not retain transport exception text or credential-bearing URLs.
                report['failed']+=1
            notice(dict(done=index+1,total=len(pending)))
        with self.db:self.erp.repository.audit(company,'registry_blank_names_batch',None,dict(report,source='AADE RgWsPublic2'))
        return report
