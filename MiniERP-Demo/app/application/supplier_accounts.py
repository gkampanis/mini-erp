"""Explicit supplier decisions propagate atomically to eligible pending documents."""
import json
from contextlib import nullcontext
from app.application.account_defaults import defaults_values
from app.application.counterparties import Counterparties

def account_group(values):
    if values['preferred_group']:return values['preferred_group']
    if bool(values['expenses_account']) != bool(values['purchases_account']):
        return '6' if values['expenses_account'] else '2'
    return None


class SupplierAccounts:
    def __init__(self,erp):self.erp=erp;self.db=erp.db

    def display_accounts(self,company,*,environment='production'):
        """Read-only current mapping, indexed by company-scoped VAT identity."""
        return {r['vat']:r['account'] for r in self.db.execute('SELECT c.vat,m.account FROM account_mappings m JOIN counterparties c ON c.id=m.counterparty_id AND c.company_id=m.company_id WHERE m.company_id=? AND c.environment=?',(company,environment))}

    def rows(self,company,query='',*,environment='production'):
        cards=Counterparties(self.erp);result=[];api={};display=self.display_accounts(company,environment=environment)
        documents={}
        for doc in self.erp.search(company,environment=environment):
            if doc['direction']=='incoming':documents.setdefault(doc['counterparty_id'],[]).append(doc)
        accounts={r['counterparty_id']:dict(r) for r in self.db.execute('SELECT * FROM counterparty_accounts WHERE company_id=?',(company,))}
        purchase_suppliers={r[0] for r in self.db.execute('SELECT vat FROM supplier_purchase_rules WHERE company_id=? AND environment="production" AND enabled=1',(company,))}
        if environment!='production':purchase_suppliers=set()
        for source in self.db.execute('SELECT mark,record_json FROM mydata_records WHERE company_id=? AND environment=?',(company,environment)):
            item=json.loads(source['record_json'])
            if item.get('direction')=='incoming':api.setdefault(item['vat'],set()).add(source['mark'])
            elif item.get('direction')=='outgoing':
                from app.domain.invoice_types import classify
                if classify(item.get('kind',''))['self_recorded_expense']:api.setdefault(item.get('receiver',''),set()).add(source['mark'])
        for card in cards.list(company,query,environment=environment):
            incoming=documents.get(card['id'],[])
            if not incoming and card['vat'] not in api and card['id'] not in accounts and card['vat'] not in purchase_suppliers:continue
            values=accounts.get(card['id'],dict(purchases_account='',expenses_account='',preferred_group=None));group=account_group(values)
            group='2' if card['vat'] in purchase_suppliers else group
            account=display.get(card['vat'],'')
            pending=any(not d.get('prepared_at') or (d.get('nature_group')==group and d.get('account_code')!=account) for d in incoming)
            state='Εκκρεμή προς έγκριση / ενημέρωση' if account and pending else 'Αντιστοιχισμένος' if account else 'Χρειάζεται λογαριασμό'
            if not incoming:state='ΑΑΔΕ: έλεγχος τύπου / στοιχείων' if card['vat'] in api else 'Χωρίς παραστατικά'
            if card['vat'] in purchase_suppliers:state='Προμηθευτής αγορών · χωρίς απαίτηση λογαριασμού'
            count=len({d['mark'] or 'local:'+str(d['id']) for d in incoming}|api.get(card['vat'],set()))
            result.append(dict(card,group=group,account=account,account_state=state,document_count=count))
        return result

    def save(self,company,ids,group,account,confirmed=False,apply_pending=True,*,classify_supplier=True):
        if confirmed is not True or not ids or len(set(ids))!=len(ids):raise ValueError('Επίλεξε προμηθευτές και επιβεβαίωσε την αντιστοίχιση')
        checked=[]
        for cp in ids:
            card,_=Counterparties(self.erp).detail(company,cp);values=card['accounts']
            checked.append((card,defaults_values(account if group=='2' else values['purchases_account'],account if group=='6' else values['expenses_account'],group)))
        report=dict(updated=0,protected=[],needs_review=[],purchases=[],queues=0)
        from app.application.ebs_reconciliation import EBSReconciliation
        evidence=EBSReconciliation(self.erp).results(company) if apply_pending else {}
        with (nullcontext() if self.db.in_transaction else self.db):
            if not self.db.in_transaction:self.db.execute('BEGIN IMMEDIATE')
            for card,values in checked:
                cp=card['id'];classification=self.classify_group_change(company,card,values) if classify_supplier else None
                protected={r['document'] for r in classification['exceptions']} if classification else set()
                if classification:
                    report['protected'].extend(sorted(protected));report['queues']+=classification['queues']
                self.write(company,cp,values)
                if apply_pending:
                    documents={r['id'] for r in self.erp.search(company,counterparty=cp)}-protected if classification else None
                    result=self.apply_pending(company,cp,values,{group},evidence=evidence,documents=documents)
                    for key in report:
                        if isinstance(report[key],list):report[key].extend(result[key])
                        else:report[key]+=result[key]
        return report

    def classify_group_change(self,company,card,values):
        """Explicit group changes reuse purchase rules; account edits keep them."""
        before=card['accounts']['preferred_group'];after=values['preferred_group']
        if card['environment']!='production':return None
        if before==after:
            if after!='2':return None
            rule=self.db.execute("SELECT enabled FROM supplier_purchase_rules WHERE company_id=? AND environment='production' AND vat=?",(company,card['vat'])).fetchone()
            if rule and rule['enabled']:return None
        if after=='2' or before=='2' and after=='6':
            from app.application.supplier_purchases import SupplierPurchases
            return SupplierPurchases(self.erp).set(company,card['vat'],after=='2')
        return None

    def write(self,company,cp,values):
        """Participates in the caller's transaction, including card edits."""
        if not self.db.execute('SELECT 1 FROM counterparties WHERE id=? AND company_id=?',(cp,company)).fetchone():raise ValueError('Δεν βρέθηκε προμηθευτής στην εταιρεία')
        before=self.db.execute('SELECT * FROM counterparty_accounts WHERE company_id=? AND counterparty_id=?',(company,cp)).fetchone()
        self.db.execute("INSERT INTO counterparty_accounts(counterparty_id,company_id,purchases_account,expenses_account,preferred_group,approved_by) VALUES (?,?,?,?,?,'local_operator') ON CONFLICT(counterparty_id) DO UPDATE SET purchases_account=excluded.purchases_account,expenses_account=excluded.expenses_account,preferred_group=excluded.preferred_group,approved_by=excluded.approved_by,approved_at=CURRENT_TIMESTAMP,version=counterparty_accounts.version+1",(cp,company,values['purchases_account'],values['expenses_account'],values['preferred_group']))
        group=account_group(values)
        if group:
            account=values['purchases_account' if group=='2' else 'expenses_account']
            self.db.execute("INSERT INTO account_mappings(company_id,counterparty_id,account,approved_by) VALUES (?,?,?,'local_operator') ON CONFLICT(company_id,counterparty_id) DO UPDATE SET account=excluded.account,approved_by=excluded.approved_by",(company,cp,account))
        else:self.db.execute('DELETE FROM account_mappings WHERE company_id=? AND counterparty_id=?',(company,cp))
        self.erp.repository.audit(company,'account_rule_approved',None,dict(counterparty_id=cp,before=dict(before) if before else None,after=values))

    def rebind_pending(self,company,document):
        """Refresh unstarted snapshots only; caller owns the approval transaction."""
        from app.application.rpa import RPA,encoded
        attempts=self.db.execute("SELECT i.*,j.status AS job_state FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND i.document_id=? AND i.status='queued' AND j.status IN ('queued','paused','running')",(company,document)).fetchall()
        if any(a['job_state']=='running' for a in attempts):raise ValueError('Παύσε πρώτα την ενεργή ουρά RPA πριν αλλάξεις λογαριασμούς')
        if not attempts:return 0
        approval=self.erp.preparation(company,document)
        if approval and approval['nature_group']=='2':
            for attempt in attempts:
                self.db.execute("UPDATE rpa_items SET status='excluded_purchase',reason='Χαρακτηρίστηκε ως αγορά· εκτός RPA και προσομοίωσης',updated_at=CURRENT_TIMESTAMP WHERE id=?",(attempt['id'],))
                self.erp.repository.audit(company,'rpa_purchase_excluded',document,dict(item=attempt['id']))
            return len(attempts)
        payload=RPA(self.erp).payload(company,document)
        count=0
        for attempt in attempts:
            before=json.loads(attempt['payload'])
            if before==payload:continue
            self.db.execute('UPDATE rpa_items SET payload=?,reason=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(encoded(payload),'Ενημερώθηκε εγκεκριμένος λογαριασμός πριν την εκτέλεση',attempt['id']))
            self.erp.repository.audit(company,'rpa_queue_rebound',document,dict(item=attempt['id'],before=before,after=payload))
            count+=1
        return count

    def apply_pending(self,company,cp,values,groups=('2','6'),*,evidence=None,documents=None):
        from app.application.ebs_reconciliation import EBSReconciliation
        from app.domain.invoice_types import classify
        if evidence is None:evidence=EBSReconciliation(self.erp).results(company)
        report=dict(updated=0,protected=[],needs_review=[],purchases=[],queues=0)
        purchases={r[0] for r in self.db.execute('SELECT document_id FROM document_purchase_tags WHERE company_id=?',(company,))}
        types={r['document_id']:classify(r['invoice_type']) for r in self.db.execute("SELECT document_id,invoice_type FROM mydata_records WHERE company_id=? AND document_id IS NOT NULL ORDER BY environment='production',id",(company,))}
        for doc in self.db.execute("SELECT id,kind FROM documents WHERE company_id=? AND counterparty_id=? AND direction='incoming'",(company,cp)).fetchall():
            document=doc['id']
            if documents is not None and document not in documents:continue
            if document in purchases:report['purchases'].append(document);continue
            if evidence.get(document,{}).get('status')=='registered':report['protected'].append(document);continue
            if doc['kind']!='invoice' or (document in types and not types[document]['rpa_allowed']):report['needs_review'].append(document);continue
            attempts=self.db.execute('SELECT i.*,j.mode,j.status AS job_state FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND i.document_id=?',(company,document)).fetchall()
            if any(a['job_state']=='running' and a['status'] in ('queued','started','save_pending') for a in attempts):raise ValueError('Παύσε πρώτα την ενεργή ουρά RPA πριν αλλάξεις λογαριασμούς')
            approval=self.erp.preparation(company,document);group=approval['nature_group'] if approval else account_group(values)
            if group not in groups:continue
            account=values['purchases_account' if group=='2' else 'expenses_account']
            if not account:report['needs_review'].append(document);continue
            mismatch=self.db.execute("SELECT 1 FROM mydata_records WHERE company_id=? AND document_id=? AND match_status IN ('different','cancelled_at_aade')",(company,document)).fetchone()
            if mismatch:report['needs_review'].append(document);continue
            if approval and approval['account_code']==account:
                report['queues']+=self.rebind_pending(company,document)
                continue
            self.db.execute("INSERT INTO document_preparations(document_id,company_id,nature_group,account_code,note,approved_by,approved_at) VALUES (?,?,?,?,?,'local_operator',strftime('%Y-%m-%dT%H:%M:%fZ','now')) ON CONFLICT(document_id) DO UPDATE SET nature_group=excluded.nature_group,account_code=excluded.account_code,note=excluded.note,approved_by=excluded.approved_by,approved_at=excluded.approved_at",(document,company,group,account,'Εγκεκριμένη εφαρμογή αντιστοίχισης προμηθευτή'))
            self.erp.repository.audit(company,'supplier_account_applied',document,dict(counterparty_id=cp,before=approval,after=self.erp.preparation(company,document)))
            report['queues']+=self.rebind_pending(company,document)
            report['updated']+=1
        return report
