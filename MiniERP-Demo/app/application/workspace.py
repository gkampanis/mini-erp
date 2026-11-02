"""One imported dataset, bulk operator decisions and company-scoped EBS profile."""
import hashlib
import json
from app.domain.preparation import preparation_values
from app.infrastructure.ebs_adapter.adapter import FIELDS,mapping_fields,detail_positions


def signature(profile):return hashlib.sha256(json.dumps(profile,sort_keys=True).encode()).hexdigest()


def validate_profile(profile):
    if not isinstance(profile,dict) or set(profile)!={'mapping','save','new'}:raise ValueError('Χρειάζονται mapper, Save και Νέο ΤΕΔ')
    mapping=profile['mapping']
    if not isinstance(mapping,dict):raise ValueError('Λείπουν πεδία mapper')
    mapping_fields(mapping)
    for point in list(mapping.values())+[profile['save'],profile['new']]:
        if not isinstance(point,(tuple,list)) or len(point)!=2 or any(type(x)!=int or abs(x)>65535 for x in point):raise ValueError('Μη έγκυρο σημείο EBS')
    if len(mapping)>len(FIELDS):detail_positions(mapping,1+(len(mapping)-len(FIELDS))//2)
    return json.loads(json.dumps(profile))


class Workspace:
    def __init__(self,erp):self.erp=erp;self.db=erp.db

    def rows(self,company,query='',*,month=None):
        active=self.db.execute("SELECT environment FROM aade_settings WHERE company_id=?",(company,)).fetchone();environment=active[0] if active else 'production'
        rows=self.erp.search(company,query,month=month,environment=environment)
        latest={}
        for row in self.db.execute("SELECT i.document_id,i.status,j.mode FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? ORDER BY i.id",(company,)):
            if row['mode']!='simulation':latest[row['document_id']]=row['status']
        sources={r['document_id']:dict(r) for r in self.db.execute('SELECT * FROM mydata_records WHERE company_id=? AND environment=? AND document_id IS NOT NULL',(company,environment))}
        origins={r['id']:r['environment'] for r in self.db.execute("SELECT d.id,m.environment FROM documents d JOIN source_records s ON s.id=d.source_record_id JOIN mydata_syncs m ON m.id=json_extract(s.raw_json,'$._sync') AND m.company_id=d.company_id WHERE d.company_id=?",(company,))}
        rows=[r for r in rows if r['id'] in sources or r['id'] not in origins or origins[r['id']]==environment]
        attempts={}
        for attempt in self.db.execute('SELECT mark,state FROM provider_attempts WHERE company_id=? AND environment=? ORDER BY id',(company,environment)):attempts[attempt['mark']]=attempt['state']
        reconciled={r['document_id']:r['match_status'] for r in self.db.execute("SELECT document_id,match_status FROM mydata_records WHERE company_id=? AND environment='production' AND document_id IS NOT NULL",(company,))}
        pdfs={r[0] for r in self.db.execute('SELECT DISTINCT document_id FROM attachments WHERE company_id=?',(company,))}
        accounts={r['counterparty_id']:r for r in self.db.execute('SELECT * FROM counterparty_accounts WHERE company_id=?',(company,))}
        # Keep tags and supplier exceptions in one batched read for monthly lists.
        purchase_state=self.db.execute('SELECT document_id,NULL AS vat FROM document_purchase_tags WHERE company_id=? UNION ALL SELECT NULL,vat FROM supplier_purchase_rules WHERE company_id=? AND environment=? AND enabled=1',(company,company,environment)).fetchall()
        purchases={r['document_id'] for r in purchase_state if r['document_id'] is not None}
        purchase_suppliers={r['vat'] for r in purchase_state if r['vat'] is not None}
        from app.application.supplier_accounts import account_group
        for row in rows:
            row['environment']=environment
            defaults=accounts.get(row['counterparty_id'])
            row['suggested_group']=account_group(defaults) if defaults else None
            row['suggested_account']=(defaults['purchases_account'] if row['suggested_group']=='2' else defaults['expenses_account'] if row['suggested_group']=='6' else '') if defaults else ''
            row['purchase_classified']=row['id'] in purchases
            row['ebs_state']=latest.get(row['id'],'not_sent')
            if row['direction']=='outgoing' and row['ebs_state']=='not_sent':row['ebs_state']='outgoing_excluded'
            row['aade_state']=reconciled.get(row['id'],'not_checked')
            source=sources.get(row['id']);item=json.loads(source['record_json']) if source else {}
            from app.domain.invoice_types import classify,financial_document
            row.update(classify(item.get('kind',''),item.get('is_delivery_note',False)))
            group=row.get('nature_group') or (row['suggested_group'] if row['vat'] not in purchase_suppliers else None)
            row['is_purchase']=row['purchase_classified'] or financial_document(row) is True and group=='2'
            if row['is_purchase'] and row['ebs_state']=='not_sent':row['ebs_state']='purchase_excluded'
            row.update(issuer_vat=item.get('vat',''),receiver_vat=item.get('receiver',''),
                       issuer_name=item.get('name',''),receiver_name=item.get('receiver_name',''),
                       correlated_marks=item.get('correlated_marks',[]),delivery_status=item.get('delivery_status',''))
            if row['id'] in pdfs:row['pdf_state']='Συνδεδεμένο'
            elif item.get('pdf_url'):
                from app.infrastructure.providers.pdf_downloads import state_label,SAVED_STATES
                state=attempts.get(item['mark']);row['pdf_state']='PDF: έλεγχος αντιστοίχισης' if state in SAVED_STATES else state_label(state) if state else 'Διαθέσιμο για λήψη'
            else:row['pdf_state']='Δεν δόθηκε σύνδεσμος' if source else 'Χωρίς PDF'
        return sorted(rows,key=lambda r:r['source_record_id'])

    def suggestions(self,company,vat):
        values=set()
        defaults=self.db.execute("SELECT a.* FROM counterparty_accounts a JOIN counterparties c ON c.id=a.counterparty_id WHERE a.company_id=? AND c.environment='production' AND c.vat=?",(company,vat)).fetchone()
        if defaults:values.update(c for c in (defaults['purchases_account'],defaults['expenses_account']) if c)
        mapped=self.db.execute("SELECT m.account FROM account_mappings m JOIN counterparties c ON c.id=m.counterparty_id WHERE m.company_id=? AND c.company_id=? AND c.environment='production' AND c.vat=?",(company,company,vat)).fetchone()
        if mapped:values.add(mapped[0])
        for row in self.db.execute("SELECT DISTINCT p.account_code FROM document_preparations p JOIN documents d ON d.id=p.document_id AND d.company_id=p.company_id JOIN counterparties c ON c.id=d.counterparty_id WHERE p.company_id=? AND c.environment='production' AND c.vat=?",(company,vat)):values.add(row[0])
        return sorted(values)

    def approve_many(self,company,decisions,confirmed=False,remember=False):
        if confirmed is not True or not decisions:raise ValueError('Απαιτείται έλεγχος και επιβεβαίωση λογαριασμών')
        if len({d['document'] for d in decisions})!=len(decisions):raise ValueError('Διπλές εγγραφές έγκρισης')
        checked=[];vat_accounts={}
        for decision in decisions:
            row,_=self.erp.detail(company,decision['document'])
            value=preparation_values(decision['group'],decision['account'],decision.get('note','Έλεγχος λογαριασμού'),'local_operator',True)
            checked.append((row,value));vat_accounts.setdefault(row['counterparty_id'],set()).add(value['account_code'])
        if remember and any(len(v)!=1 for v in vat_accounts.values()):raise ValueError('Το ίδιο ΑΦΜ έχει διαφορετικούς λογαριασμούς. Μην αποθηκεύεις γενικό κανόνα.')
        from app.application.supplier_accounts import SupplierAccounts
        from app.application.ebs_reconciliation import EBSReconciliation
        with self.db:
            if not self.db.in_transaction:self.db.execute('BEGIN IMMEDIATE')
            evidence=EBSReconciliation(self.erp).results(company,include_attempts=False)
            for row,value in checked:
                if evidence.get(row['id'],{}).get('status')=='registered':raise ValueError('Το παραστατικό έχει επιβεβαιωμένη καταχώριση EBS. Ο ιστορικός λογαριασμός δεν αλλάζει.')
                attempts=self.db.execute("SELECT i.status,j.status AS job_state,j.mode FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND i.document_id=?",(company,row['id'])).fetchall()
                if any(a['job_state']=='running' and a['status'] in ('queued','started','save_pending') for a in attempts):raise ValueError('Παύσε πρώτα την ενεργή ουρά RPA πριν αλλάξεις λογαριασμούς')
                before=self.erp.preparation(company,row['id'])
                self.db.execute("INSERT INTO document_preparations(document_id,company_id,nature_group,account_code,note,approved_by,approved_at) VALUES (?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now')) ON CONFLICT(document_id) DO UPDATE SET nature_group=excluded.nature_group,account_code=excluded.account_code,note=excluded.note,approved_by=excluded.approved_by,approved_at=excluded.approved_at",(row['id'],company,value['nature_group'],value['account_code'],value['note'],value['approved_by']))
                self.erp.repository.audit(company,'document_prepared',row['id'],dict(before=before,after=self.erp.preparation(company,row['id'])))
            if remember:
                for cp,accounts in vat_accounts.items():
                    account=next(iter(accounts))
                    SupplierAccounts(self.erp).save(company,[cp],account[0],account,confirmed=True,apply_pending=True,classify_supplier=False)
            for row,value in checked:SupplierAccounts(self.erp).rebind_pending(company,row['id'])
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
