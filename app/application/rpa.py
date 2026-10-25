"""Persisted, approval-bound RPA attempts; simulation is the default."""
from datetime import datetime
from decimal import Decimal
import json
from app.infrastructure.ebs_adapter.adapter import SimulationAdapter,WindowsAdapter


def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True)


class RPA:
    def __init__(self,erp):self.erp=erp;self.db=erp.db

    def expense_scope(self,company,documents):
        """Partition the same list; purchase cards remain visible but never enter EBS."""
        rows={r['id']:r for r in self.erp.search(company)}
        defaults={r['counterparty_id']:r['preferred_group'] for r in self.db.execute('SELECT counterparty_id,preferred_group FROM counterparty_accounts WHERE company_id=?',(company,))}
        purchases={r[0] for r in self.db.execute('SELECT document_id FROM document_purchase_tags WHERE company_id=?',(company,))}
        result=dict(expenses=[],purchases=[],needs_review=[],outgoing=[],excluded_types=[])
        from app.domain.invoice_types import classify
        types={r['document_id']:classify(r['invoice_type'],r['is_delivery_note']) for r in self.db.execute("SELECT document_id,invoice_type,is_delivery_note FROM mydata_records WHERE company_id=? AND document_id IS NOT NULL ORDER BY environment='production',id",(company,))}
        for document in documents:
            if document not in rows:raise ValueError('Δεν βρέθηκε παραστατικό στην εταιρεία')
            row=rows[document]
            if document in purchases:result['purchases'].append(document);continue
            if row['direction']!='incoming':result['outgoing'].append(document);continue
            if row['kind']!='invoice' or (document in types and not types[document]['rpa_allowed']):result['excluded_types'].append(document);continue
            group=row.get('nature_group') or defaults.get(row['counterparty_id'])
            if group=='2':result['purchases'].append(document)
            elif group=='6' and row.get('prepared_at'):result['expenses'].append(document)
            else:result['needs_review'].append(document)
        return result

    def payload(self,company,document):
        row,_=self.erp.detail(company,document)
        if self.db.execute('SELECT 1 FROM document_purchase_tags WHERE company_id=? AND document_id=?',(company,document)).fetchone():raise ValueError('Χαρακτηρίστηκε ως αγορά· εκτός RPA και προσομοίωσης')
        if row['direction']!='incoming':raise ValueError('Τα εκδοθέντα δεν ανήκουν στη ροή εξόδων EBS')
        kind=self.db.execute("SELECT invoice_type,is_delivery_note FROM mydata_records WHERE company_id=? AND document_id=? ORDER BY environment='production' DESC,id DESC LIMIT 1",(company,document)).fetchone()
        from app.domain.invoice_types import classify
        if (kind and not classify(kind['invoice_type'],kind['is_delivery_note'])['rpa_allowed']) or row['kind']!='invoice':raise ValueError('Το είδος παραστατικού δεν υποστηρίζεται από τη ροή ΤΕΔ αξίας')
        reconciliation=self.db.execute("SELECT match_status FROM mydata_records WHERE company_id=? AND document_id=? AND environment='production'",(company,document)).fetchone()
        if reconciliation and reconciliation[0] in ('different','cancelled_at_aade'):raise ValueError('Το παραστατικό έχει διαφορά ή αναφορά ακύρωσης στην ΑΑΔΕ. Έλεγξε τη συμφωνία πριν EBS.')
        approval=self.erp.preparation(company,document)
        if not approval:raise ValueError('Λείπει εγκεκριμένη προετοιμασία για το παραστατικό '+str(document))
        return dict(document_id=document,vat=row['vat'],name=row['name'],invoice='/'.join(x for x in (row['series'],row['number']) if x),
                    date=datetime.strptime(row['issue_date'],'%Y-%m-%d').strftime('%d/%m/%Y'),
                    net=f"{Decimal(row['net_minor'])/100:.2f}".replace('.',','),account=approval['account_code'],
                    group=approval['nature_group'],approval_at=approval['approved_at'],rounding_minor=row['rounding_minor'])

    def live_source(self,company,document):
        row,_=self.erp.detail(company,document);source=json.loads(row['raw_json']).get('_sync')
        if source is not None:
            snapshot=self.db.execute('SELECT environment FROM mydata_syncs WHERE id=? AND company_id=?',(source,company)).fetchone()
            if snapshot is None or snapshot[0]!='production':raise ValueError('Παραστατικό δοκιμαστικής ή μη επαληθευμένης πηγής ΑΑΔΕ: επιτρέπεται μόνο προσομοίωση, όχι πραγματική καταχώριση EBS.')

    def plan(self,company,documents,*,limit=None,replacing=()):
        """Plan in caller's table order, reusing only explicitly saved supplier rules.

        This is not a new execution engine: create/advance still enforce every gate.
        """
        from app.application.ebs_reconciliation import EBSReconciliation
        from app.application.supplier_accounts import SupplierAccounts,account_group
        if len(set(documents))!=len(documents):raise ValueError('Διπλή επιλογή παραστατικών')
        unresolved=self.db.execute("SELECT 1 FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND j.mode='fill_only' AND i.status IN ('started','save_pending') LIMIT 1",(company,)).fetchone()
        if unresolved:raise ValueError('Χρειάζεται έλεγχος στο EBS προηγούμενης προσπάθειας από το Ιστορικό. Δεν γίνεται αυτόματη επανάληψη.')
        rows={r['id']:r for r in self.erp.search(company)}
        if any(d not in rows for d in documents):raise ValueError('Δεν βρέθηκε παραστατικό στην ενεργή εταιρεία')
        evidence=EBSReconciliation(self.erp).results(company)
        reserved={r['document_id'] for r in self.db.execute("SELECT i.document_id,i.status,j.id AS job_id FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND j.mode='fill_only' AND (i.status IN ('started','save_pending','uncertain','filled_no_save','save_invoked','ui_saved_review','reviewed_by_operator') OR (i.status='queued' AND j.status IN ('queued','paused','running')))",(company,)) if not (r['status']=='queued' and r['job_id'] in replacing)}
        defaults={r['counterparty_id']:dict(r) for r in self.db.execute('SELECT * FROM counterparty_accounts WHERE company_id=?',(company,))}
        eligible=[];skipped=[];accounts=SupplierAccounts(self.erp)
        scope=self.expense_scope(company,documents)
        excluded=set(scope['purchases']+scope['outgoing']+scope['excluded_types'])
        with self.db:
            for document in documents:
                if limit is not None and len(eligible)>=limit:break
                row=rows[document];reason=None
                if document in reserved:reason='Προηγούμενη προσπάθεια ή εκκρεμής ουρά EBS'
                elif document in excluded:reason='Αγορές, έσοδα ή μη υποστηριζόμενο είδος · εκτός RPA'
                elif evidence[document]['status']!='not_registered':reason=evidence[document]['reason']
                if reason is None:
                    try:
                        self.live_source(company,document)
                        values=defaults.get(row['counterparty_id'])
                        if values and values['expenses_account'] and account_group(values)=='6':
                            accounts.apply_pending(company,row['counterparty_id'],values,{'6'},evidence=evidence,documents={document})
                        payload=self.payload(company,document)
                        if payload['group']!='6':raise ValueError('Δεν υπάρχει λογαριασμός εξόδων ομάδας 6')
                        if payload['rounding_minor']:raise ValueError('Χρειάζεται έλεγχος στρογγυλοποίησης EBS')
                    except ValueError as exc:reason=str(exc)
                if reason is not None:skipped.append(dict(document=document,reason=reason));continue
                eligible.append(document)
            self.erp.repository.audit(company,'rpa_selection_planned',None,dict(documents=eligible,skipped=skipped,limit=limit))
        return dict(documents=eligible,skipped=skipped)

    def posting(self,company,documents,*,limit=None):
        from app.application.workspace import Workspace
        active=self.db.execute("SELECT j.id,j.status,j.execution FROM rpa_jobs j WHERE company_id=? AND mode='fill_only' AND status IN ('queued','running','paused') AND EXISTS(SELECT 1 FROM rpa_items i WHERE i.job_id=j.id AND i.status='queued') ORDER BY j.id",(company,)).fetchall()
        if any(j['status']=='running' or j['execution']!='save_new' for j in active):
            raise ValueError('Υπάρχει εκκρεμής παρτίδα EBS. Χρησιμοποίησε Συνέχεια ή Διακοπή από το ιστορικό.')
        if self.db.execute("SELECT 1 FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND j.mode='fill_only' AND i.status IN ('started','save_pending') LIMIT 1",(company,)).fetchone():
            raise ValueError('Χρειάζεται έλεγχος στο EBS προηγούμενης προσπάθειας. Δεν επαναλαμβάνεται αυτόματα.')
        saved=Workspace(self.erp).profile(company)
        if saved is None:raise ValueError('Όρισε πρώτα τις θέσεις στις Ρυθμίσεις EBS.')
        pilot=not saved['pilot_at']
        if len(active)==1:
            meta,items=self.items(company,active[0]['id'])
            pending=[i['document_id'] for i in items if i['status']=='queued']
            same=pending==documents if limit is None else pending==documents[:len(pending)]
            if same and not any(i['status'] in ('uncertain','filled_no_save') for i in items) and json.loads(meta['profile_json'])==saved['profile']:
                with self.db:self.erp.repository.audit(company,'rpa_existing_scope_selected',None,dict(job=meta['id'],documents=pending))
                return dict(job=meta['id'],documents=pending,skipped=[],pilot=pilot,resumed=True)
        replacing=tuple(j['id'] for j in active)
        report=self.plan(company,documents,limit=1 if pilot else limit,replacing=replacing)
        if not report['documents']:return dict(report,job=None,pilot=pilot)
        job=self.create(company,report['documents'],mode='fill_only',execution='save_new',confirmed=True,pilot=pilot,replacing=replacing,fresh_after_previous=True)
        with self.db:
            self.erp.repository.audit(company,'rpa_posting_scope',None,dict(job=job,skipped=report['skipped'],pilot=pilot))
        return dict(report,job=job,pilot=pilot)

    def create(self,company,documents,mode='simulation',confirmed=False,execution='fill_only',pilot=False,reconciled_only=False,replacing=(),fresh_after_previous=False):
        if confirmed is not True:raise ValueError('Απαιτείται επιβεβαίωση ουράς RPA')
        if mode not in ('simulation','fill_only'):raise ValueError('Άγνωστη λειτουργία RPA')
        if not documents or len(set(documents))!=len(documents):raise ValueError('Επίλεξε παραστατικά χωρίς επαναλήψεις')
        if execution not in ('fill_only','save_new'):raise ValueError('Άγνωστη ροή EBS')
        from app.application.ebs_reconciliation import EBSReconciliation
        required=mode=='fill_only' or reconciled_only
        EBSReconciliation(self.erp).assert_rpa(company,documents,required=required)
        profile={}
        if mode=='fill_only' and execution=='save_new':
            from app.application.workspace import Workspace
            saved=Workspace(self.erp).profile(company)
            if saved is None:raise ValueError('Ρύθμισε mapper, Save και Νέο ΤΕΔ μία φορά')
            if not saved['pilot_at'] and not (pilot is True and len(documents)==1):raise ValueError('Πρώτα δοκίμασε μία εγγραφή και επιβεβαίωσε την αποθήκευσή της στο EBS')
            profile=saved['profile']
        payloads=[self.payload(company,doc) for doc in documents]
        if any(p['group']!='6' for p in payloads):raise ValueError('Στο EBS καταχωρούνται μόνο έξοδα ομάδας 6. Οι αγορές ομάδας 2 διατηρούνται για διαχωρισμό, εκτός RPA.')
        if mode=='fill_only':
            if any(p['rounding_minor'] for p in payloads):raise ValueError('Υπάρχει διαφορά στρογγυλοποίησης: χρειάζεται χειροκίνητος έλεγχος EBS πριν συμπλήρωση')
            for document in documents:
                self.live_source(company,document)
                pending=self.db.execute("SELECT 1 FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND i.document_id=? AND j.mode='fill_only' AND (i.status IN ('started','save_pending','filled_no_save','uncertain') OR (j.execution='save_new' AND i.status IN ('save_invoked','ui_saved_review','reviewed_by_operator')))",(company,document)).fetchone()
                if pending:raise ValueError('Υπάρχει προηγούμενη προσπάθεια προς χειροκίνητο έλεγχο. Δεν επιτρέπεται τυφλή επανάληψη.')
        with self.db:
            if replacing:
                if mode!='fill_only' or execution!='save_new':raise ValueError('Μη έγκυρη αντικατάσταση εύρους ουράς')
                if not self.db.in_transaction:self.db.execute('BEGIN IMMEDIATE')
                old=self.db.execute("SELECT id,status,execution FROM rpa_jobs WHERE company_id=? AND mode='fill_only' AND status IN ('queued','paused','running') AND EXISTS(SELECT 1 FROM rpa_items i WHERE i.job_id=rpa_jobs.id AND i.status='queued')",(company,)).fetchall()
                if {r['id'] for r in old}!=set(replacing) or any(r['status']=='running' or r['execution']!='save_new' for r in old):raise ValueError('Άλλαξε η ενεργή ουρά. Δεν ξεκίνησε νέα καταχώριση.')
                if self.db.execute("SELECT 1 FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND j.mode='fill_only' AND i.status IN ('started','save_pending') LIMIT 1",(company,)).fetchone():raise ValueError('Προηγούμενη προσπάθεια χρειάζεται έλεγχο EBS.')
                # Replace scheduling only. All old item IDs, payloads, attempted
                # states and receipts remain in history; hidden rows are not run.
                for previous in replacing:
                    self.db.execute("UPDATE rpa_jobs SET status='stopped' WHERE id=? AND company_id=?",(previous,company))
                    self.erp.repository.audit(company,'rpa_scope_superseded',None,dict(job=previous,documents=documents,reason='Νέα ρητή επιλογή ορατών ή επιλεγμένων γραμμών'))
            # Persist the fresh-form checkpoint with the queue itself, so a
            # restart cannot type over a previous batch's last saved document.
            need_new=0
            if fresh_after_previous:
                previous=self.db.execute("SELECT i.status,j.profile_json FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND j.mode='fill_only' AND j.execution='save_new' AND i.status IN ('save_invoked','ui_saved_review','reviewed_by_operator') ORDER BY i.id DESC LIMIT 1",(company,)).fetchone()
                isolation=self.db.execute("SELECT 1 FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND j.mode='fill_only' AND i.status IN ('uncertain','filled_no_save','not_saved_confirmed') LIMIT 1",(company,)).fetchone()
                need_new=int(bool(isolation or (previous and previous['status'] in ('save_invoked','reviewed_by_operator') and json.loads(previous['profile_json'])==profile)))
            job=self.db.execute('INSERT INTO rpa_jobs(company_id,mode,status,execution,profile_json,reconciled_only,need_new) VALUES (?,?,?,?,?,?,?)',(company,mode,'queued',execution,encoded(profile),int(required),need_new)).lastrowid
            for payload in payloads:
                self.db.execute('INSERT INTO rpa_items(job_id,document_id,payload) VALUES (?,?,?)',(job,payload['document_id'],encoded(payload)))
            self.erp.repository.audit(company,'rpa_queued',None,dict(job=job,mode=mode,count=len(payloads)))
        return job

    def items(self,company,job):
        row=self.db.execute('SELECT * FROM rpa_jobs WHERE id=? AND company_id=?',(job,company)).fetchone()
        if row is None:raise ValueError('Δεν βρέθηκε ουρά RPA')
        result=[]
        for item in self.db.execute('SELECT * FROM rpa_items WHERE job_id=? ORDER BY id',(job,)):
            value=dict(item);value['payload']=json.loads(value['payload']);result.append(value)
        return dict(row),result

    def progress(self,company,job):
        meta,items=self.items(company,job)
        counts={state:sum(i['status']==state for i in items) for state in {i['status'] for i in items}}
        current=next((i for i in items if i['status'] in ('started','save_pending')),next((i for i in items if i['status']=='queued'),items[-1] if items else None))
        receipts=set();save_commands=set();item_ids={i['id'] for i in items};documents={i['document_id'] for i in items}
        for event in self.db.execute("SELECT action,entity_id,payload FROM audit_events WHERE company_id=? AND action IN ('ebs_storage_operator_confirmed','ebs_pilot_operator_confirmed','rpa_save_invoked')",(company,)):
            payload=json.loads(event['payload'])
            if event['action']=='rpa_save_invoked':
                if payload.get('job')==job and event['entity_id'] in documents:save_commands.add(event['entity_id'])
            elif payload.get('item') in item_ids:receipts.add(payload['item'])
        preflight=self.db.execute("SELECT payload FROM audit_events WHERE company_id=? AND action='rpa_posting_scope' AND json_extract(payload,'$.job')=? ORDER BY id DESC LIMIT 1",(company,job)).fetchone()
        excluded=len(json.loads(preflight[0])['skipped']) if preflight else 0
        return dict(processed=sum(i['status'] not in ('queued','started','save_pending') for i in items),skipped=excluded+sum(i['status']=='excluded_purchase' for i in items),reason=next((i['reason'] for i in items if i['status']=='queued' and i['reason'].startswith('Αποκλείστηκε')),next((i['reason'] for i in reversed(items) if i['reason']),'')),total=len(items),queued=counts.get('queued',0),simulated=counts.get('simulated',0),save_requested=len(save_commands),operator_reviewed=counts.get('reviewed_by_operator',0),verified_in_ebs=len(receipts),automatically_verified=0,failed=sum(counts.get(s,0) for s in ('failed','uncertain')),current=current['payload']['invoice'] if current else '—',mode=meta['mode'],state=meta['status'])

    def recover(self,company):
        with self.db:
            rows=self.db.execute("SELECT i.id,i.document_id,i.job_id FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND i.status IN ('started','save_pending')",(company,)).fetchall()
            for row in rows:
                self.db.execute("UPDATE rpa_items SET status='uncertain',reason='Διακοπή πριν την επιβεβαίωση. Απαγορεύεται αυτόματο replay.' WHERE id=?",(row['id'],))
                self.db.execute("UPDATE rpa_jobs SET status='paused' WHERE id=?",(row['job_id'],))
                self.erp.repository.audit(company,'rpa_recovered_uncertain',row['document_id'],dict(item=row['id'],job=row['job_id']))
            batches=self.db.execute("SELECT id FROM rpa_jobs WHERE company_id=? AND status='running'",(company,)).fetchall()
            for batch in batches:
                self.db.execute("UPDATE rpa_jobs SET status='paused' WHERE id=?",(batch['id'],))
                self.erp.repository.audit(company,'rpa_batch_recovered_paused',None,dict(job=batch['id']))
            # Native HWNDs are not durable identity across application sessions.
            stale=self.db.execute("SELECT id FROM rpa_jobs WHERE company_id=? AND mode='fill_only' AND execution='save_new' AND status IN ('queued','paused') AND expected_ted IS NOT NULL AND EXISTS(SELECT 1 FROM rpa_items i WHERE i.job_id=rpa_jobs.id AND i.status='queued')",(company,)).fetchall()
            for row in stale:
                self.db.execute('UPDATE rpa_jobs SET expected_ted=NULL,need_new=1 WHERE id=?',(row['id'],))
                self.erp.repository.audit(company,'rpa_native_context_reset',None,dict(job=row['id']))
        return len(rows)

    def advance(self,company,job,mapping=None,live_confirmed=False,adapter=None,continue_after_pause=False):
        meta,items=self.items(company,job)
        if meta['status']=='stopped':raise ValueError('Η ουρά έχει σταματήσει')
        if meta['status']=='paused' and continue_after_pause is not True:raise ValueError('Η ουρά βρίσκεται σε παύση. Πάτησε Συνέχεια.')
        if any(i['status'] in ('started','save_pending','uncertain','filled_no_save') for i in items):
            raise ValueError('Εκκρεμεί χειροκίνητος έλεγχος προηγούμενης προσπάθειας')
        item=next((i for i in items if i['status']=='queued'),None)
        if item is None:
            with self.db:self.db.execute("UPDATE rpa_jobs SET status='completed' WHERE id=?",(job,))
            return dict(status='completed',mode=meta['mode'])
        from app.application.ebs_reconciliation import EBSReconciliation
        pending_ids=[i['document_id'] for i in items if i['status']=='queued']
        EBSReconciliation(self.erp).assert_rpa(company,pending_ids,required=meta['mode']=='fill_only' or meta['reconciled_only'])
        if meta['mode']=='fill_only':
            for pending in items:
                if pending['status']=='queued':self.live_source(company,pending['document_id'])
        if meta['mode']=='fill_only' and meta['execution']=='save_new':
            try:return self._advance_saved(company,job,meta,items,item,live_confirmed,adapter,continue_after_pause)
            except Exception as exc:
                if not getattr(exc,'diagnostic_report',None):
                    from app.infrastructure.ebs_adapter.diagnostics import write_report
                    report=write_report(self.erp,company,job,item['id'],'preflight',exc,adapter,json.loads(meta['profile_json']))
                    if report is not None:exc.diagnostic_report=report.name
                raise
        current=self.payload(company,item['document_id'])
        if current['group']!='6':raise ValueError('Η ομάδα 2 είναι εκτός καταχώρισης EBS, ακόμη και σε παλαιότερη ουρά.')
        if current!=item['payload']:raise ValueError('Άλλαξε η εγκεκριμένη προετοιμασία. Δημιούργησε νέα ουρά μετά από έλεγχο.')
        if meta['mode']=='fill_only':
            if live_confirmed is not True:raise ValueError('Απαιτείται ρητή επιβεβαίωση δοκιμασμένου mapper και κενού ΤΕΔ')
            if not mapping:raise ValueError('Απαιτείται CSV mapper')
            backend=adapter or WindowsAdapter()
        else:backend=adapter or SimulationAdapter()
        with self.db:
            claimed=self.db.execute("UPDATE rpa_items SET status='started',updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='queued' AND EXISTS(SELECT 1 FROM rpa_jobs WHERE id=rpa_items.job_id AND status NOT IN ('stopped','completed'))",(item['id'],))
            if claimed.rowcount!=1:raise ValueError('Η προσπάθεια έχει ήδη ξεκινήσει. Δεν επαναλαμβάνεται.')
            if self.payload(company,item['document_id'])!=item['payload']:raise ValueError('Άλλαξαν τα στοιχεία πριν την εκτέλεση. Έλεγξε την ουρά.')
            EBSReconciliation(self.erp).assert_rpa(company,[item['document_id']],required=meta['mode']=='fill_only' or meta['reconciled_only'],ignore_items=(item['id'],))
            if meta['mode']=='fill_only' and self.db.execute("SELECT 1 FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND j.mode='fill_only' AND i.document_id=? AND i.id<>? AND i.status IN ('started','save_pending','filled_no_save','uncertain','save_invoked','ui_saved_review')",(company,item['document_id'],item['id'])).fetchone():raise ValueError('Άλλη πραγματική προσπάθεια χρειάζεται έλεγχο. Δεν στάλθηκαν νέες εντολές.')
            self.db.execute("UPDATE rpa_jobs SET status='running' WHERE id=?",(job,))
            self.erp.repository.audit(company,'rpa_started',item['document_id'],dict(job=job,item=item['id'],mode=meta['mode']))
        try:
            backend.fill(current,mapping or {})
            status='simulated' if meta['mode']=='simulation' else 'filled_no_save'
            reason='Προσομοίωση: καμία ενέργεια στο EBS' if status=='simulated' else 'Στάλθηκαν εντολές συμπλήρωσης. Δεν στάλθηκε Save. Έλεγχος στο EBS.'
        except Exception:
            status='failed' if meta['mode']=='simulation' else 'uncertain'
            reason='Η προσπάθεια διακόπηκε. Έλεγξε τη φόρμα EBS πριν επανάληψη. Δεν στάλθηκε Save.'
        with self.db:
            self.db.execute('UPDATE rpa_items SET status=?,reason=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(status,reason,item['id']))
            remaining=self.db.execute("SELECT count(*) FROM rpa_items WHERE job_id=? AND status='queued'",(job,)).fetchone()[0]
            completed=self.db.execute("SELECT count(*) FROM rpa_items WHERE job_id=? AND status='simulated'",(job,)).fetchone()[0]
            job_state='paused' if status!='simulated' or (remaining and completed%40==0) else 'running' if remaining else 'completed'
            self.db.execute('UPDATE rpa_jobs SET status=? WHERE id=?',(job_state,job))
            self.erp.repository.audit(company,'rpa_'+status,item['document_id'],dict(job=job,item=item['id'],mode=meta['mode']))
        return dict(status=job_state,item_status=status,mode=meta['mode'],reason=reason)

    def blocked(self,company,job,reason):
        _,items=self.items(company,job)
        item=next((i for i in items if i['status']=='queued'),None)
        with self.db:
            changed=self.db.execute("UPDATE rpa_jobs SET status='paused' WHERE id=? AND status NOT IN ('stopped','completed')",(job,))
            if changed.rowcount!=1:
                self.erp.repository.audit(company,'rpa_blocked_terminal',None,dict(job=job))
                return
            if item:self.db.execute("UPDATE rpa_items SET reason=? WHERE id=?",('Αποκλείστηκε πριν τη συμπλήρωση: '+reason[:1000],item['id']))
            self.erp.repository.audit(company,'rpa_blocked',item['document_id'] if item else None,dict(job=job,reason=reason[:1000]))

    def stop(self,company,job):
        self.items(company,job)
        with self.db:
            self.db.execute("UPDATE rpa_jobs SET status='stopped' WHERE id=?",(job,))
            self.erp.repository.audit(company,'rpa_stopped',None,dict(job=job))

    def reviewed(self,company,job,item_id,note,confirmed=False,stored_in_ebs=False):
        _,items=self.items(company,job)
        item=next((i for i in items if i['id']==item_id),None)
        if confirmed is not True or not isinstance(note,str) or not note.strip():raise ValueError('Απαιτείται ρητός χειροκίνητος έλεγχος και σημείωση')
        if item is None or (item['status'] not in ('uncertain','filled_no_save','save_invoked','ui_saved_review') and not (stored_in_ebs and item['status']=='reviewed_by_operator')):raise ValueError('Δεν υπάρχει προσπάθεια προς έλεγχο')
        with self.db:
            self.db.execute("UPDATE rpa_items SET status='reviewed_by_operator',reason=? WHERE id=?",(note.strip()[:2000],item_id))
            self.db.execute("UPDATE rpa_jobs SET need_new=CASE WHEN execution='save_new' THEN 1 ELSE need_new END,expected_ted=NULL WHERE id=?",(job,))
            self.erp.repository.audit(company,'rpa_manual_review',item['document_id'],dict(job=job,item=item_id,note=note.strip()[:2000],not_database_verified=True))
            if stored_in_ebs is True:self.erp.repository.audit(company,'ebs_storage_operator_confirmed',item['document_id'],dict(job=job,item=item_id,note=note.strip()[:2000],verification='visual_operator',not_database_verified=True))

    def confirm_not_saved(self,company,document):
        from app.application.ebs_reconciliation import EBSReconciliation
        if EBSReconciliation(self.erp).results(company).get(document,{}).get('status')=='registered':raise ValueError('Υπάρχει επιβεβαιωμένη καταχώριση· δεν επιτρέπεται επαναφορά για νέα αποστολή.')
        row=self.db.execute("SELECT i.*,j.status AS job_status FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND j.mode='fill_only' AND i.document_id=? ORDER BY i.id DESC LIMIT 1",(company,document)).fetchone()
        if not row or row['status'] not in ('uncertain','filled_no_save') or row['job_status']=='running':raise ValueError('Δεν υπάρχει διακοπείσα προσπάθεια προς επιβεβαίωση.')
        with self.db:
            changed=self.db.execute("UPDATE rpa_items SET status='not_saved_confirmed',reason='Ο χειριστής επιβεβαίωσε ότι δεν αποθηκεύτηκε στο EBS',updated_at=CURRENT_TIMESTAMP WHERE id=? AND status=?",(row['id'],row['status']))
            if changed.rowcount!=1:raise ValueError('Άλλαξε η προσπάθεια· ανανέωσε την προβολή.')
            self.db.execute("UPDATE rpa_jobs SET need_new=1,expected_ted=NULL WHERE id=?",(row['job_id'],))
            self.erp.repository.audit(company,'ebs_not_saved_operator_confirmed',document,dict(job=row['job_id'],item=row['id'],previous=row['status'],verification='visual_operator'))

    def pause(self,company,job):
        self.items(company,job)
        with self.db:
            self.db.execute("UPDATE rpa_jobs SET status='paused' WHERE id=?",(job,))
            self.erp.repository.audit(company,'rpa_paused',None,dict(job=job))


    def _advance_saved(self,company,job,meta,items,item,confirmed,adapter,continue_after_pause):
        from app.application.workspace import Workspace,signature
        from app.infrastructure.ebs_adapter.session import WindowsSession,TEDContextChanged
        if confirmed is not True:raise ValueError('Απαιτείται ρητή έναρξη πραγματικής καταχώρισης')
        saved=Workspace(self.erp).profile(company);profile=json.loads(meta['profile_json'])
        if not saved or signature(profile)!=saved['signature']:raise ValueError('Άλλαξαν οι θέσεις EBS. Χρειάζεται νέα ουρά και πιλοτικός έλεγχος.')
        # Full-queue preflight before the first EBS action, including resume.
        for pending in items:
            if pending['status']=='queued' and self.payload(company,pending['document_id'])!=pending['payload']:raise ValueError('Άλλαξαν λογαριασμοί ή στοιχεία ουράς. Έλεγξε ξανά πριν έναρξη.')
        current=self.payload(company,item['document_id'])
        previous=self.db.execute("SELECT 1 FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND j.mode='fill_only' AND j.execution='save_new' AND i.document_id=? AND i.id<>? AND i.status IN ('started','save_pending','uncertain','save_invoked','ui_saved_review','reviewed_by_operator')",(company,item['document_id'],item['id'])).fetchone()
        if previous:raise ValueError('Το παραστατικό έχει προηγούμενη πραγματική προσπάθεια. Έλεγξε το ιστορικό, χωρίς επανάληψη.')
        if adapter is None:
            vat=self.db.execute('SELECT vat FROM companies WHERE id=?',(company,)).fetchone()[0]
            if vat=='000000000' or any(i['payload']['vat'] in ('000000001','000000002','000000003') for i in items if i['status']=='queued'):
                raise ValueError('Δεν στέλνονται συνθετικά δείγματα DEMO στο EBS. Όρισε πραγματική εταιρεία και επίλεξε πραγματικά παραστατικά.')
        if current['group']!='6':raise ValueError('Η ομάδα 2 είναι εκτός καταχώρισης EBS')
        backend=adapter;phase='preflight'
        try:
            backend=adapter or WindowsSession()
            def open_empty():
                nonlocal phase
                phase='new'
                # Durable before the New command. No invoice input has been claimed.
                with self.db:self.db.execute('UPDATE rpa_jobs SET need_new=1,expected_ted=NULL WHERE id=?',(job,))
                fresh=backend.open_new(profile['new'])
                with self.db:self.db.execute('UPDATE rpa_jobs SET need_new=0,expected_ted=? WHERE id=?',(fresh,job))
                meta['expected_ted']=fresh
            if meta['need_new']:
                if continue_after_pause is not True:raise ValueError('Παύση: έλεγξε το τελευταίο Save και πάτησε Συνέχεια για νέο ΤΕΔ')
                open_empty()
            phase='prepare'
            try:expected=backend.prepare(profile,meta['expected_ted'])
            except TEDContextChanged:
                # A previously queued HWND may still exist but refer to an old tab.
                # Open a NEW form once, instead of typing into that arbitrary tab.
                open_empty()
                phase='prepare'
                expected=backend.prepare(profile,meta['expected_ted'])
                with self.db:self.erp.repository.audit(company,'rpa_native_context_rebound',None,dict(job=job))
            phase='claim'
            with self.db:
                claim=self.db.execute("UPDATE rpa_items SET status='started',updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='queued' AND EXISTS(SELECT 1 FROM rpa_jobs WHERE id=rpa_items.job_id AND status NOT IN ('stopped','completed'))",(item['id'],))
                if claim.rowcount!=1:raise ValueError('Η προσπάθεια έχει ήδη ξεκινήσει')
                from app.application.ebs_reconciliation import EBSReconciliation
                EBSReconciliation(self.erp).assert_rpa(company,[p['document_id'] for p in items if p['status']=='queued'],required=True,ignore_items=(item['id'],))
                if self.db.execute("SELECT 1 FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND j.mode='fill_only' AND i.document_id=? AND i.id<>? AND i.status IN ('started','save_pending','filled_no_save','uncertain','save_invoked','ui_saved_review','reviewed_by_operator')",(company,item['document_id'],item['id'])).fetchone():raise ValueError('Υπάρχει άλλη πραγματική προσπάθεια για το ίδιο παραστατικό. Δεν στάλθηκαν εντολές.')
                for pending in items:
                    if pending['status']=='queued' and self.payload(company,pending['document_id'])!=pending['payload']:raise ValueError('Άλλαξαν λογαριασμοί πριν τη συμπλήρωση. Χρειάζεται έλεγχος ουράς.')
                self.db.execute("UPDATE rpa_jobs SET status='running',expected_ted=? WHERE id=?",(expected,job))
                self.erp.repository.audit(company,'rpa_started',item['document_id'],dict(job=job,item=item['id'],mode='save_new'))
        except Exception as exc:
            from app.infrastructure.ebs_adapter.diagnostics import write_report
            report=write_report(self.erp,company,job,item['id'],phase,exc,backend,profile)
            if report is not None:exc.diagnostic_report=report.name
            raise
        phase='fill';reason=''
        try:
            backend.fill(current,profile['mapping'])
            # Durable before Save: every error/crash from this point requires review.
            with self.db:
                self.db.execute("UPDATE rpa_items SET status='save_pending' WHERE id=?",(item['id'],))
                self.erp.repository.audit(company,'rpa_save_pending',item['document_id'],dict(job=job,item=item['id']))
            phase='save';backend.save(profile['save'])
            remaining=sum(i['status']=='queued' and i['id']!=item['id'] for i in items)
            completed=sum(i['status'] in ('ui_saved_review','save_invoked','reviewed_by_operator') for i in items)+1
            status='save_invoked';state='completed' if not remaining else 'paused' if completed%40==0 else 'running'
            # Persist successful click before attempting New; do not confuse it with a commit.
            with self.db:
                self.db.execute("UPDATE rpa_items SET status='save_invoked' WHERE id=?",(item['id'],))
                self.db.execute('UPDATE rpa_jobs SET need_new=? WHERE id=?',(int(bool(remaining)),job))
                self.erp.repository.audit(company,'rpa_save_invoked',item['document_id'],dict(job=job,not_database_verified=True))
            if remaining and state=='running':
                phase='new';fresh=backend.open_new(profile['new']);status='ui_saved_review'
                with self.db:self.db.execute('UPDATE rpa_jobs SET need_new=0,expected_ted=? WHERE id=?',(fresh,job))
            reason='Στάλθηκε Save. Απαιτείται έλεγχος αποθήκευσης στο EBS.'
            if remaining and state=='paused':reason='Παύση 40: έλεγξε το τελευταίο Save και κλείσε μόνο τις αποθηκευμένες καρτέλες. Η Συνέχεια ανοίγει νέο ΤΕΔ.'
        except Exception as exc:
            status='uncertain';state='paused'
            reason='Διακοπή στη φάση '+phase+'. Έλεγξε το EBS πριν συνέχεια. Δεν επιτρέπεται αυτόματη επανάληψη.'
            # Preserve actionable, application-owned field errors, never arbitrary
            # native exception messages/window titles or invoice data.
            from app.infrastructure.ebs_adapter.adapter import FIELDS
            safe={f'Δεν επαληθεύτηκε το EBS στο πεδίο {field}. Δεν στάλθηκε Save.' for field,_ in FIELDS}
            safe.update(f'Η θέση του πεδίου {field} δεν ανήκει στο ενεργό ΤΕΔ της ουράς. Έλεγξε το mapping πριν καταχώριση.' for field,_ in FIELDS)
            safe.update(('Άλλαξε η διεργασία EBS. Η συμπλήρωση διακόπηκε.','Άλλαξε το ενεργό ΤΕΔ πριν το Save','Δεν αναγνωρίστηκε νέο ΤΕΔ. Δεν επιτρέπεται επανάληψη παραστατικού.','Δεν αναγνωρίστηκε σταθερό νέο ΤΕΔ. Δεν επιτρέπεται επανάληψη παραστατικού.','Διακόπηκε η εισαγωγή Unicode στο EBS'))
            if str(exc) in safe:reason+=' '+str(exc)
            from app.infrastructure.ebs_adapter.diagnostics import failure_hint
            if failure_hint(exc):reason+=' '+failure_hint(exc)
            from app.infrastructure.crashlog import record
            record(self.erp.directory,exc,'worker')
            from app.infrastructure.ebs_adapter.diagnostics import write_report
            report=write_report(self.erp,company,job,item['id'],phase,exc,backend,profile)
            if report is not None:reason+=' Αναφορά: diagnostics/'+report.name
        with self.db:
            self.db.execute('UPDATE rpa_items SET status=?,reason=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(status,reason,item['id']))
            self.db.execute('UPDATE rpa_jobs SET status=? WHERE id=?',(state,job))
            self.erp.repository.audit(company,'rpa_'+status,item['document_id'],dict(job=job,item=item['id'],phase=phase,not_database_verified=True))
        return dict(status=state,item_status=status,mode='fill_only',execution='save_new',reason=reason)
