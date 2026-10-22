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
        from app.application.workspace import Workspace
        rows={r['id']:r for r in Workspace(self.erp).rows(company)}
        result=dict(expenses=[],purchases=[],needs_review=[])
        for document in documents:
            if document not in rows:raise ValueError('Δεν βρέθηκε παραστατικό στην εταιρεία')
            row=rows[document];group=row.get('nature_group') or row.get('suggested_group')
            if group=='2':result['purchases'].append(document)
            elif group=='6' and row.get('prepared_at'):result['expenses'].append(document)
            else:result['needs_review'].append(document)
        return result

    def payload(self,company,document):
        row,_=self.erp.detail(company,document)
        reconciliation=self.db.execute("SELECT match_status FROM mydata_records WHERE company_id=? AND document_id=? AND environment='production'",(company,document)).fetchone()
        if reconciliation and reconciliation[0] in ('different','cancelled_at_aade'):raise ValueError('Το παραστατικό έχει διαφορά ή αναφορά ακύρωσης στην ΑΑΔΕ. Έλεγξε τη συμφωνία πριν EBS.')
        approval=self.erp.preparation(company,document)
        if not approval:raise ValueError('Λείπει εγκεκριμένη προετοιμασία για το παραστατικό '+str(document))
        return dict(document_id=document,vat=row['vat'],name=row['name'],invoice='/'.join(x for x in (row['series'],row['number']) if x),
                    date=datetime.strptime(row['issue_date'],'%Y-%m-%d').strftime('%d/%m/%Y'),
                    net=f"{Decimal(row['net_minor'])/100:.2f}".replace('.',','),account=approval['account_code'],
                    group=approval['nature_group'],approval_at=approval['approved_at'],rounding_minor=row['rounding_minor'])

    def create(self,company,documents,mode='simulation',confirmed=False,execution='fill_only',pilot=False):
        if confirmed is not True:raise ValueError('Απαιτείται επιβεβαίωση ουράς RPA')
        if mode not in ('simulation','fill_only'):raise ValueError('Άγνωστη λειτουργία RPA')
        if not documents or len(set(documents))!=len(documents):raise ValueError('Επίλεξε παραστατικά χωρίς επαναλήψεις')
        if execution not in ('fill_only','save_new'):raise ValueError('Άγνωστη ροή EBS')
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
                pending=self.db.execute("SELECT 1 FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND i.document_id=? AND j.mode='fill_only' AND (i.status IN ('started','save_pending','filled_no_save','uncertain') OR (j.execution='save_new' AND i.status IN ('save_invoked','ui_saved_review','reviewed_by_operator')))",(company,document)).fetchone()
                if pending:raise ValueError('Υπάρχει προηγούμενη προσπάθεια προς χειροκίνητο έλεγχο. Δεν επιτρέπεται τυφλή επανάληψη.')
        with self.db:
            job=self.db.execute('INSERT INTO rpa_jobs(company_id,mode,status,execution,profile_json) VALUES (?,?,?,?,?)',(company,mode,'queued',execution,encoded(profile))).lastrowid
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

    def recover(self,company):
        with self.db:
            rows=self.db.execute("SELECT i.id,i.document_id,i.job_id FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND i.status IN ('started','save_pending')",(company,)).fetchall()
            for row in rows:
                self.db.execute("UPDATE rpa_items SET status='uncertain',reason='Διακοπή πριν την επιβεβαίωση. Απαγορεύεται αυτόματο replay.' WHERE id=?",(row['id'],))
                self.db.execute("UPDATE rpa_jobs SET status='paused' WHERE id=?",(row['job_id'],))
                self.erp.repository.audit(company,'rpa_recovered_uncertain',row['document_id'],dict(item=row['id'],job=row['job_id']))
        return len(rows)

    def advance(self,company,job,mapping=None,live_confirmed=False,adapter=None,continue_after_pause=False):
        meta,items=self.items(company,job)
        if meta['status']=='stopped':raise ValueError('Η ουρά έχει σταματήσει')
        if any(i['status'] in ('started','uncertain','filled_no_save') for i in items):
            raise ValueError('Εκκρεμεί χειροκίνητος έλεγχος προηγούμενης προσπάθειας')
        item=next((i for i in items if i['status']=='queued'),None)
        if item is None:
            with self.db:self.db.execute("UPDATE rpa_jobs SET status='completed' WHERE id=?",(job,))
            return dict(status='completed',mode=meta['mode'])
        if meta['mode']=='fill_only' and meta['execution']=='save_new':
            return self._advance_saved(company,job,meta,items,item,live_confirmed,adapter,continue_after_pause)
        current=self.payload(company,item['document_id'])
        if current['group']!='6':raise ValueError('Η ομάδα 2 είναι εκτός καταχώρισης EBS, ακόμη και σε παλαιότερη ουρά.')
        if current!=item['payload']:raise ValueError('Άλλαξε η εγκεκριμένη προετοιμασία. Δημιούργησε νέα ουρά μετά από έλεγχο.')
        if meta['mode']=='fill_only':
            if live_confirmed is not True:raise ValueError('Απαιτείται ρητή επιβεβαίωση δοκιμασμένου mapper και κενού ΤΕΔ')
            if not mapping:raise ValueError('Απαιτείται CSV mapper')
            backend=adapter or WindowsAdapter()
        else:backend=adapter or SimulationAdapter()
        with self.db:
            claimed=self.db.execute("UPDATE rpa_items SET status='started',updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='queued'",(item['id'],))
            if claimed.rowcount!=1:raise ValueError('Η προσπάθεια έχει ήδη ξεκινήσει. Δεν επαναλαμβάνεται.')
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

    def stop(self,company,job):
        self.items(company,job)
        with self.db:
            self.db.execute("UPDATE rpa_jobs SET status='stopped' WHERE id=?",(job,))
            self.erp.repository.audit(company,'rpa_stopped',None,dict(job=job))

    def reviewed(self,company,job,item_id,note,confirmed=False):
        _,items=self.items(company,job)
        item=next((i for i in items if i['id']==item_id),None)
        if confirmed is not True or not isinstance(note,str) or not note.strip():raise ValueError('Απαιτείται ρητός χειροκίνητος έλεγχος και σημείωση')
        if item is None or item['status'] not in ('uncertain','filled_no_save','save_invoked','ui_saved_review'):raise ValueError('Δεν υπάρχει προσπάθεια προς έλεγχο')
        with self.db:
            self.db.execute("UPDATE rpa_items SET status='reviewed_by_operator',reason=? WHERE id=?",(note.strip()[:2000],item_id))
            self.db.execute("UPDATE rpa_jobs SET need_new=CASE WHEN execution='save_new' THEN 1 ELSE need_new END,expected_ted=NULL WHERE id=?",(job,))
            self.erp.repository.audit(company,'rpa_manual_review',item['document_id'],dict(job=job,item=item_id,note=note.strip()[:2000],not_database_verified=True))

    def pause(self,company,job):
        self.items(company,job)
        with self.db:
            self.db.execute("UPDATE rpa_jobs SET status='paused' WHERE id=?",(job,))
            self.erp.repository.audit(company,'rpa_paused',None,dict(job=job))


    def _advance_saved(self,company,job,meta,items,item,confirmed,adapter,continue_after_pause):
        from app.application.workspace import Workspace,signature
        from app.infrastructure.ebs_adapter.session import WindowsSession
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
        backend=adapter or WindowsSession()
        if meta['need_new']:
            if continue_after_pause is not True:raise ValueError('Παύση: έλεγξε το τελευταίο Save και πάτησε Συνέχεια για νέο ΤΕΔ')
            # Opening a new empty form cannot replay the preceding invoice.
            fresh=backend.open_new(profile['new'])
            with self.db:self.db.execute('UPDATE rpa_jobs SET need_new=0,expected_ted=? WHERE id=?',(fresh,job))
            meta['expected_ted']=fresh
        expected=backend.prepare(profile,meta['expected_ted'])
        with self.db:
            claim=self.db.execute("UPDATE rpa_items SET status='started',updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='queued'",(item['id'],))
            if claim.rowcount!=1:raise ValueError('Η προσπάθεια έχει ήδη ξεκινήσει')
            self.db.execute("UPDATE rpa_jobs SET status='running',expected_ted=? WHERE id=?",(expected,job))
            self.erp.repository.audit(company,'rpa_started',item['document_id'],dict(job=job,item=item['id'],mode='save_new'))
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
            # Do not retain arbitrary native messages/window titles in public logs.
        with self.db:
            self.db.execute('UPDATE rpa_items SET status=?,reason=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(status,reason,item['id']))
            self.db.execute('UPDATE rpa_jobs SET status=? WHERE id=?',(state,job))
            self.erp.repository.audit(company,'rpa_'+status,item['document_id'],dict(job=job,item=item['id'],phase=phase,not_database_verified=True))
        return dict(status=state,item_status=status,mode='fill_only',execution='save_new',reason=reason)
