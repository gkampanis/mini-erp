"""One imported dataset, bulk operator decisions and company-scoped EBS profile."""
import hashlib
import json
from app.domain.preparation import preparation_values
from app.infrastructure.ebs_adapter.adapter import FIELDS


def signature(profile):return hashlib.sha256(json.dumps(profile,sort_keys=True).encode()).hexdigest()


def validate_profile(profile):
    if not isinstance(profile,dict) or set(profile)!={'mapping','save','new'}:raise ValueError('Χρειάζονται mapper, Save και Νέο ΤΕΔ')
    mapping=profile['mapping']
    if not isinstance(mapping,dict) or set(mapping)!={f for f,_ in FIELDS}:raise ValueError('Λείπουν πεδία mapper')
    for point in list(mapping.values())+[profile['save'],profile['new']]:
        if not isinstance(point,(tuple,list)) or len(point)!=2 or any(type(x)!=int or abs(x)>65535 for x in point):raise ValueError('Μη έγκυρο σημείο EBS')
    return json.loads(json.dumps(profile))


class Workspace:
    def __init__(self,erp):self.erp=erp;self.db=erp.db

    def rows(self,company,query=''):
        rows=self.erp.search(company,query)
        latest={}
        for row in self.db.execute("SELECT i.document_id,i.status,j.mode FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? ORDER BY i.id",(company,)):
            if row['mode']!='simulation':latest[row['document_id']]=row['status']
        reconciled={r['document_id']:r['match_status'] for r in self.db.execute("SELECT document_id,match_status FROM mydata_records WHERE company_id=? AND environment='production' AND document_id IS NOT NULL",(company,))}
        pdfs={r[0] for r in self.db.execute('SELECT DISTINCT document_id FROM attachments WHERE company_id=?',(company,))}
        for row in rows:
            defaults=self.db.execute('SELECT * FROM counterparty_accounts WHERE company_id=? AND counterparty_id=?',(company,row['counterparty_id'])).fetchone()
            row['suggested_group']=defaults['preferred_group'] if defaults else None
            row['suggested_account']=(defaults['purchases_account'] if defaults['preferred_group']=='2' else defaults['expenses_account'] if defaults['preferred_group']=='6' else '') if defaults else ''
            row['ebs_state']=latest.get(row['id'],'not_sent')
            if (row.get('nature_group') or row['suggested_group'])=='2' and row['ebs_state']=='not_sent':row['ebs_state']='purchase_excluded'
            row['aade_state']=reconciled.get(row['id'],'not_checked')
            row['pdf_state']='Συνδεδεμένο' if row['id'] in pdfs else 'Χωρίς PDF'
        return sorted(rows,key=lambda r:r['source_record_id'])

    def suggestions(self,company,vat):
        values=set()
        defaults=self.db.execute('SELECT a.* FROM counterparty_accounts a JOIN counterparties c ON c.id=a.counterparty_id WHERE a.company_id=? AND c.vat=?',(company,vat)).fetchone()
        if defaults:values.update(c for c in (defaults['purchases_account'],defaults['expenses_account']) if c)
        mapped=self.db.execute('SELECT m.account FROM account_mappings m JOIN counterparties c ON c.id=m.counterparty_id WHERE m.company_id=? AND c.company_id=? AND c.vat=?',(company,company,vat)).fetchone()
        if mapped:values.add(mapped[0])
        for row in self.db.execute('SELECT DISTINCT p.account_code FROM document_preparations p JOIN documents d ON d.id=p.document_id AND d.company_id=p.company_id JOIN counterparties c ON c.id=d.counterparty_id WHERE p.company_id=? AND c.vat=?',(company,vat)):values.add(row[0])
        return sorted(values)

    def approve_many(self,company,decisions,confirmed=False,remember=False):
        if confirmed is not True or not decisions:raise ValueError('Απαιτείται έλεγχος και επιβεβαίωση λογαριασμών')
        if len({d['document'] for d in decisions})!=len(decisions):raise ValueError('Διπλές εγγραφές έγκρισης')
        checked=[];vat_accounts={}
        for decision in decisions:
            row,_=self.erp.detail(company,decision['document'])
            value=preparation_values(decision['group'],decision['account'],'Μαζικός έλεγχος από ενιαία λίστα','local_operator',True)
            checked.append((row,value));vat_accounts.setdefault(row['counterparty_id'],set()).add(value['account_code'])
        if remember and any(len(v)!=1 for v in vat_accounts.values()):raise ValueError('Το ίδιο ΑΦΜ έχει διαφορετικούς λογαριασμούς. Μην αποθηκεύεις γενικό κανόνα.')
        with self.db:
            for row,value in checked:
                before=self.erp.preparation(company,row['id'])
                self.db.execute("INSERT INTO document_preparations(document_id,company_id,nature_group,account_code,note,approved_by,approved_at) VALUES (?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now')) ON CONFLICT(document_id) DO UPDATE SET nature_group=excluded.nature_group,account_code=excluded.account_code,note=excluded.note,approved_by=excluded.approved_by,approved_at=excluded.approved_at",(row['id'],company,value['nature_group'],value['account_code'],value['note'],value['approved_by']))
                self.erp.repository.audit(company,'document_prepared',row['id'],dict(before=before,after=self.erp.preparation(company,row['id'])))
            if remember:
                for cp,accounts in vat_accounts.items():
                    account=next(iter(accounts))
                    before=self.db.execute('SELECT account FROM account_mappings WHERE company_id=? AND counterparty_id=?',(company,cp)).fetchone()
                    self.db.execute("INSERT INTO account_mappings(company_id,counterparty_id,account,approved_by) VALUES (?,?,?,'local_operator') ON CONFLICT(company_id,counterparty_id) DO UPDATE SET account=excluded.account,approved_by=excluded.approved_by",(company,cp,account))
                    slot='purchases_account' if account.startswith('2') else 'expenses_account'
                    self.db.execute(f"INSERT INTO counterparty_accounts(counterparty_id,company_id,{slot},preferred_group,approved_by) VALUES (?,?,?,?,'local_operator') ON CONFLICT(counterparty_id) DO UPDATE SET {slot}=excluded.{slot},preferred_group=excluded.preferred_group,version=counterparty_accounts.version+1,approved_at=CURRENT_TIMESTAMP",(cp,company,account,account[0]))
                    self.erp.repository.audit(company,'account_rule_approved',None,dict(counterparty_id=cp,before=before[0] if before else None,after=account))
        return len(checked)

    def profile(self,company):
        row=self.db.execute('SELECT * FROM ebs_profiles WHERE company_id=?',(company,)).fetchone()
        if row is None:return None
        result=dict(row);result['profile']=json.loads(result.pop('profile_json'));return result

    def save_profile(self,company,profile):
        if not self.db.execute('SELECT 1 FROM companies WHERE id=?',(company,)).fetchone():raise ValueError('Δεν βρέθηκε εταιρεία')
        profile=validate_profile(profile);stamp=signature(profile)
        before=self.profile(company)
        with self.db:
            self.db.execute("INSERT INTO ebs_profiles(company_id,profile_json,signature) VALUES (?,?,?) ON CONFLICT(company_id) DO UPDATE SET profile_json=excluded.profile_json,signature=excluded.signature,pilot_at=CASE WHEN ebs_profiles.signature=excluded.signature THEN ebs_profiles.pilot_at ELSE NULL END,pilot_note=CASE WHEN ebs_profiles.signature=excluded.signature THEN ebs_profiles.pilot_note ELSE '' END,updated_at=CURRENT_TIMESTAMP",(company,json.dumps(profile),stamp))
            self.erp.repository.audit(company,'ebs_profile_saved',None,dict(signature=stamp,changed=before is None or before['signature']!=stamp))
        return self.profile(company)

    def confirm_pilot(self,company,item_id,note,confirmed=False):
        if confirmed is not True or not isinstance(note,str) or not note.strip():raise ValueError('Επιβεβαίωσε πραγματικό αποθηκευμένο ΤΕΔ στο EBS και σημείωσε τον έλεγχο')
        profile=self.profile(company)
        row=self.db.execute("SELECT j.profile_json,i.status FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND i.id=? AND j.mode='fill_only' AND j.execution='save_new'",(company,item_id)).fetchone()
        if not profile or not row or row['status'] not in ('save_invoked','ui_saved_review','reviewed_by_operator') or signature(json.loads(row['profile_json']))!=profile['signature']:raise ValueError('Δεν βρέθηκε πιλοτική προσπάθεια Save με τις ίδιες ρυθμίσεις')
        with self.db:
            self.db.execute('UPDATE ebs_profiles SET pilot_note=?,pilot_at=CURRENT_TIMESTAMP WHERE company_id=?',(note.strip()[:2000],company))
            self.db.execute("UPDATE rpa_items SET status='reviewed_by_operator',reason=? WHERE id=?",(note.strip()[:2000],item_id))
            self.erp.repository.audit(company,'ebs_pilot_operator_confirmed',None,dict(item=item_id,signature=profile['signature'],note=note.strip()[:2000],not_database_verified=True))
