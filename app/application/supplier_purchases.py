"""Reversible purchase classification, independent of account approval."""
from app.domain.validation import checked_greek_vat as valid_vat
from app.domain.invoice_types import classify


def financial_expense(row,metadata=None):
    kind=metadata or {}
    return (row['kind'] not in ('delivery_note','quantity_receipt')
            and (row['direction']=='incoming' or kind.get('self_recorded_expense',False)))


class SupplierPurchases:
    def __init__(self,erp):self.erp=erp;self.db=erp.db

    def inspect(self,company,supplier):
        valid_vat(supplier)
        if not self.db.execute('SELECT 1 FROM counterparties WHERE company_id=? AND vat=?',(company,supplier)).fetchone():raise ValueError('Δεν βρέθηκε συναλλασσόμενος στην ενεργή εταιρεία')
        from app.application.ebs_reconciliation import EBSReconciliation
        evidence=EBSReconciliation(self.erp).results(company)
        types={r['document_id']:classify(r['invoice_type'],r['is_delivery_note']) for r in self.db.execute("SELECT document_id,invoice_type,is_delivery_note FROM mydata_records WHERE company_id=? ORDER BY environment='production',id",(company,))}
        attempts={}
        for r in self.db.execute('SELECT i.*,j.mode,j.status AS job_state FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=?',(company,)):attempts.setdefault(r['document_id'],[]).append(dict(r))
        eligible=[];exceptions=[]
        for row in self.erp.search(company):
            if row['vat']!=supplier or not financial_expense(row,types.get(row['id'])):continue
            state=evidence.get(row['id'],{});history=attempts.get(row['id'],[]);reason=''
            if state.get('status')=='registered':reason='Υπάρχει απόδειξη συμφωνίας ή οπτική επιβεβαίωση EBS'
            elif any(a['job_state']=='running' or a['status'] in ('started','save_pending') for a in history):reason='Ενεργή προσπάθεια ή ενεργή ουρά RPA'
            elif any(a['mode']=='fill_only' and a['status']!='queued' and a['status']!='excluded_purchase' for a in history):reason='Προηγούμενη πραγματική προσπάθεια· χρειάζεται έλεγχος στο EBS'
            elif any(a['status']=='simulated' for a in history):reason='Ολοκληρωμένος έλεγχος προσομοίωσης· η εγγραφή διατηρείται'
            if reason:exceptions.append(dict(document=row['id'],reason=reason))
            else:eligible.append(row['id'])
        rule=self.db.execute('SELECT * FROM supplier_purchase_rules WHERE company_id=? AND vat=?',(company,supplier)).fetchone()
        tagged={r[0] for r in self.db.execute('SELECT document_id FROM document_purchase_tags WHERE company_id=?',(company,))}
        return dict(eligible=eligible,exceptions=exceptions,enabled=bool(rule and rule['enabled']),tagged=tagged,version=rule['version'] if rule else 0)

    def set(self,company,supplier,enabled,*,expected_version=None):
        if type(enabled) is not bool:raise ValueError('Μη έγκυρος χαρακτηρισμός')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            scope=self.inspect(company,supplier)
            if expected_version is not None and scope['version']!=expected_version:raise ValueError('Ο χαρακτηρισμός άλλαξε· ανανέωσε τη λίστα πριν αναίρεση')
            version=scope['version']+1
            self.db.execute('INSERT INTO supplier_purchase_rules(company_id,vat,enabled,version) VALUES (?,?,?,?) ON CONFLICT(company_id,vat) DO UPDATE SET enabled=excluded.enabled,version=excluded.version',(company,supplier,int(enabled),version))
            changed=[];queues=0
            for document in scope['eligible']:
                modified=False
                if enabled and document not in scope['tagged']:
                    self.db.execute('INSERT INTO document_purchase_tags VALUES (?,?,?)',(document,company,version));changed.append(document);modified=True
                elif not enabled and document in scope['tagged']:
                    self.db.execute('DELETE FROM document_purchase_tags WHERE document_id=? AND company_id=?',(document,company));changed.append(document);modified=True
                if enabled:
                    for item in self.db.execute("SELECT i.id FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND i.document_id=? AND i.status='queued' AND j.status IN ('queued','paused')",(company,document)).fetchall():
                        self.db.execute("UPDATE rpa_items SET status='excluded_purchase',reason='Χαρακτηρίστηκε ως αγορά· εκτός RPA και προσομοίωσης',updated_at=CURRENT_TIMESTAMP WHERE id=?",(item['id'],))
                        self.erp.repository.audit(company,'rpa_purchase_excluded',document,dict(item=item['id']));queues+=1
                if modified:self.erp.repository.audit(company,'purchase_classification_changed',document,dict(vat=supplier,purchase=enabled,rule_version=version))
            self.erp.repository.audit(company,'supplier_purchase_rule_changed',None,dict(vat=supplier,before=scope['enabled'],after=enabled,version=version,changed=changed,exceptions=scope['exceptions']))
        return dict(changed=len(changed),queues=queues,exceptions=scope['exceptions'],version=version,previous=scope['enabled'])

    @staticmethod
    def apply_import(repository,company,document,values,raw):
        """Within the existing import transaction; no account or identity writes."""
        rule=repository.db.execute('SELECT version FROM supplier_purchase_rules WHERE company_id=? AND vat=? AND enabled=1',(company,values['vat'])).fetchone()
        metadata=classify(raw.get('kind','')) if raw.get('_source') else {}
        if rule and financial_expense(values,metadata):
            repository.db.execute('INSERT INTO document_purchase_tags VALUES (?,?,?)',(document,company,rule['version']))
            repository.audit(company,'purchase_classification_changed',document,dict(purchase=True,source='saved_supplier_rule',rule_version=rule['version']))
