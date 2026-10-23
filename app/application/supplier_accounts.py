"""Explicit supplier decisions propagate atomically to eligible pending documents."""
import json
from app.application.account_defaults import defaults_values
from app.application.counterparties import Counterparties

class SupplierAccounts:
    def __init__(self,erp):self.erp=erp;self.db=erp.db

    def rows(self,company,query=''):
        cards=Counterparties(self.erp);result=[];api={}
        documents={}
        for doc in self.erp.search(company):
            if doc['direction']=='incoming':documents.setdefault(doc['counterparty_id'],[]).append(doc)
        accounts={r['counterparty_id']:dict(r) for r in self.db.execute('SELECT * FROM counterparty_accounts WHERE company_id=?',(company,))}
        for source in self.db.execute('SELECT mark,record_json FROM mydata_records WHERE company_id=?',(company,)):
            item=json.loads(source['record_json'])
            if item.get('direction')=='incoming':api.setdefault(item['vat'],set()).add(source['mark'])
            elif item.get('direction')=='outgoing':
                from app.domain.invoice_types import classify
                if classify(item.get('kind',''))['self_recorded_expense']:api.setdefault(item.get('receiver',''),set()).add(source['mark'])
        for card in cards.list(company,query):
            incoming=documents.get(card['id'],[])
            if not incoming and card['vat'] not in api:continue
            values=accounts.get(card['id'],dict(purchases_account='',expenses_account='',preferred_group=None));group=values['preferred_group']
            account=values['purchases_account' if group=='2' else 'expenses_account'] if group else ''
            pending=any(not d.get('prepared_at') or (d.get('nature_group')==group and d.get('account_code')!=account) for d in incoming)
            state='Εκκρεμή προς έγκριση / ενημέρωση' if account and pending else 'Αντιστοιχισμένος' if account else 'Χρειάζεται λογαριασμό'
            if not incoming:state='ΑΑΔΕ: έλεγχος τύπου / στοιχείων'
            count=len({d['mark'] or 'local:'+str(d['id']) for d in incoming}|api.get(card['vat'],set()))
            result.append(dict(card,group=group,account=account,account_state=state,document_count=count))
        return result

    def save(self,company,ids,group,account,confirmed=False,apply_pending=True):
        if confirmed is not True or not ids or len(set(ids))!=len(ids):raise ValueError('Επίλεξε προμηθευτές και επιβεβαίωσε την αντιστοίχιση')
        checked=[]
        for cp in ids:
            card,_=Counterparties(self.erp).detail(company,cp);values=card['accounts']
            checked.append((cp,defaults_values(account if group=='2' else values['purchases_account'],account if group=='6' else values['expenses_account'],group)))
        report=dict(updated=0,protected=[],needs_review=[],queues=0)
        from app.application.ebs_reconciliation import EBSReconciliation
        evidence=EBSReconciliation(self.erp).results(company) if apply_pending else {}
        with self.db:
            for cp,values in checked:
                self.write(company,cp,values)
                if apply_pending:
                    result=self.apply_pending(company,cp,values,{group},evidence=evidence)
                    for key in report:
                        if isinstance(report[key],list):report[key].extend(result[key])
                        else:report[key]+=result[key]
        return report

    def write(self,company,cp,values):
        """Participates in the caller's transaction, including card edits."""
        if not self.db.execute('SELECT 1 FROM counterparties WHERE id=? AND company_id=?',(cp,company)).fetchone():raise ValueError('Δεν βρέθηκε προμηθευτής στην εταιρεία')
        before=self.db.execute('SELECT * FROM counterparty_accounts WHERE company_id=? AND counterparty_id=?',(company,cp)).fetchone()
        self.db.execute("INSERT INTO counterparty_accounts(counterparty_id,company_id,purchases_account,expenses_account,preferred_group,approved_by) VALUES (?,?,?,?,?,'local_operator') ON CONFLICT(counterparty_id) DO UPDATE SET purchases_account=excluded.purchases_account,expenses_account=excluded.expenses_account,preferred_group=excluded.preferred_group,approved_by=excluded.approved_by,approved_at=CURRENT_TIMESTAMP,version=counterparty_accounts.version+1",(cp,company,values['purchases_account'],values['expenses_account'],values['preferred_group']))
        group=values['preferred_group']
        if group:
            account=values['purchases_account' if group=='2' else 'expenses_account']
            self.db.execute("INSERT INTO account_mappings(company_id,counterparty_id,account,approved_by) VALUES (?,?,?,'local_operator') ON CONFLICT(company_id,counterparty_id) DO UPDATE SET account=excluded.account,approved_by=excluded.approved_by",(company,cp,account))
        else:self.db.execute('DELETE FROM account_mappings WHERE company_id=? AND counterparty_id=?',(company,cp))
        self.erp.repository.audit(company,'account_rule_approved',None,dict(counterparty_id=cp,before=dict(before) if before else None,after=values))

    def apply_pending(self,company,cp,values,groups=('2','6'),*,evidence=None):
        from app.application.rpa import RPA,encoded
        from app.application.ebs_reconciliation import EBSReconciliation
        from app.domain.invoice_types import classify
        if evidence is None:evidence=EBSReconciliation(self.erp).results(company)
        report=dict(updated=0,protected=[],needs_review=[],queues=0)
        types={r['document_id']:classify(r['invoice_type']) for r in self.db.execute("SELECT document_id,invoice_type FROM mydata_records WHERE company_id=? AND document_id IS NOT NULL ORDER BY environment='production',id",(company,))}
        for doc in self.db.execute("SELECT id,kind FROM documents WHERE company_id=? AND counterparty_id=? AND direction='incoming'",(company,cp)).fetchall():
            document=doc['id']
            if evidence.get(document,{}).get('status')=='registered':report['protected'].append(document);continue
            if doc['kind']!='invoice' or (document in types and not types[document]['rpa_allowed']):report['needs_review'].append(document);continue
            attempts=self.db.execute('SELECT i.*,j.mode,j.status AS job_state FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND i.document_id=?',(company,document)).fetchall()
            if any(a['job_state']=='running' and a['status']=='queued' for a in attempts):raise ValueError('Παύσε πρώτα την ενεργή ουρά RPA πριν αλλάξεις λογαριασμούς')
            if any(a['mode']=='fill_only' and a['status']!='queued' for a in attempts):report['protected'].append(document);continue
            approval=self.erp.preparation(company,document);group=approval['nature_group'] if approval else values['preferred_group']
            if group not in groups:continue
            account=values['purchases_account' if group=='2' else 'expenses_account']
            if not account:report['needs_review'].append(document);continue
            mismatch=self.db.execute("SELECT 1 FROM mydata_records WHERE company_id=? AND document_id=? AND environment='production' AND match_status IN ('different','cancelled_at_aade')",(company,document)).fetchone()
            if mismatch:report['needs_review'].append(document);continue
            if approval and approval['account_code']==account:continue
            self.db.execute("INSERT INTO document_preparations(document_id,company_id,nature_group,account_code,note,approved_by,approved_at) VALUES (?,?,?,?,?,'local_operator',strftime('%Y-%m-%dT%H:%M:%fZ','now')) ON CONFLICT(document_id) DO UPDATE SET nature_group=excluded.nature_group,account_code=excluded.account_code,note=excluded.note,approved_by=excluded.approved_by,approved_at=excluded.approved_at",(document,company,group,account,'Εγκεκριμένη εφαρμογή αντιστοίχισης προμηθευτή'))
            self.erp.repository.audit(company,'supplier_account_applied',document,dict(counterparty_id=cp,before=approval,after=self.erp.preparation(company,document)))
            payload=RPA(self.erp).payload(company,document)
            for attempt in attempts:
                if attempt['status']=='queued' and attempt['job_state'] in ('queued','paused'):
                    self.db.execute('UPDATE rpa_items SET payload=?,reason=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(encoded(payload),'Ενημερώθηκε εγκεκριμένος λογαριασμός πριν την εκτέλεση',attempt['id']))
                    self.erp.repository.audit(company,'rpa_queue_rebound',document,dict(item=attempt['id'],before=json.loads(attempt['payload']),after=payload))
                    report['queues']+=1
            report['updated']+=1
        return report
