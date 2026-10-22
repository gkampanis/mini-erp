"""Persisted, approval-bound RPA attempts; simulation is the default."""
from datetime import datetime
from decimal import Decimal
import json
from app.infrastructure.ebs_adapter.adapter import SimulationAdapter,WindowsAdapter


def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True)


class RPA:
    def __init__(self,erp):self.erp=erp;self.db=erp.db

    def payload(self,company,document):
        row,_=self.erp.detail(company,document)
        approval=self.erp.preparation(company,document)
        if not approval:raise ValueError('Λείπει εγκεκριμένη προετοιμασία για το παραστατικό '+str(document))
        return dict(document_id=document,vat=row['vat'],name=row['name'],invoice='/'.join(x for x in (row['series'],row['number']) if x),
                    date=datetime.strptime(row['issue_date'],'%Y-%m-%d').strftime('%d/%m/%Y'),
                    net=f"{Decimal(row['net_minor'])/100:.2f}".replace('.',','),account=approval['account_code'],
                    group=approval['nature_group'],approval_at=approval['approved_at'],rounding_minor=row['rounding_minor'])

    def create(self,company,documents,mode='simulation',confirmed=False):
        if confirmed is not True:raise ValueError('Απαιτείται επιβεβαίωση ουράς RPA')
        if mode not in ('simulation','fill_only'):raise ValueError('Άγνωστη λειτουργία RPA')
        if not documents or len(set(documents))!=len(documents):raise ValueError('Επίλεξε παραστατικά χωρίς επαναλήψεις')
        payloads=[self.payload(company,doc) for doc in documents]
        if mode=='fill_only':
            if any(p['group']!='6' for p in payloads):raise ValueError('Η δοκιμασμένη ροή ΤΕΔ αφορά έξοδα ομάδας 6. Η ομάδα 2 χρειάζεται ξεχωριστή πιλοτική ροή EBS.')
            if any(p['rounding_minor'] for p in payloads):raise ValueError('Υπάρχει διαφορά στρογγυλοποίησης: χρειάζεται χειροκίνητος έλεγχος EBS πριν συμπλήρωση')
            for document in documents:
                pending=self.db.execute("SELECT 1 FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND i.document_id=? AND j.mode='fill_only' AND i.status IN ('started','filled_no_save','uncertain')",(company,document)).fetchone()
                if pending:raise ValueError('Υπάρχει προηγούμενη προσπάθεια προς χειροκίνητο έλεγχο. Δεν επιτρέπεται τυφλή επανάληψη.')
        with self.db:
            job=self.db.execute('INSERT INTO rpa_jobs(company_id,mode,status) VALUES (?,?,?)',(company,mode,'queued')).lastrowid
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
            rows=self.db.execute("SELECT i.id,i.document_id,i.job_id FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND i.status='started'",(company,)).fetchall()
            for row in rows:
                self.db.execute("UPDATE rpa_items SET status='uncertain',reason='Διακοπή πριν την επιβεβαίωση. Απαγορεύεται αυτόματο replay.' WHERE id=?",(row['id'],))
                self.db.execute("UPDATE rpa_jobs SET status='paused' WHERE id=?",(row['job_id'],))
                self.erp.repository.audit(company,'rpa_recovered_uncertain',row['document_id'],dict(item=row['id'],job=row['job_id']))
        return len(rows)

    def advance(self,company,job,mapping=None,live_confirmed=False,adapter=None):
        meta,items=self.items(company,job)
        if meta['status']=='stopped':raise ValueError('Η ουρά έχει σταματήσει')
        if any(i['status'] in ('started','uncertain','filled_no_save') for i in items):
            raise ValueError('Εκκρεμεί χειροκίνητος έλεγχος προηγούμενης προσπάθειας')
        item=next((i for i in items if i['status']=='queued'),None)
        if item is None:
            with self.db:self.db.execute("UPDATE rpa_jobs SET status='completed' WHERE id=?",(job,))
            return dict(status='completed',mode=meta['mode'])
        current=self.payload(company,item['document_id'])
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
        if item is None or item['status'] not in ('uncertain','filled_no_save'):raise ValueError('Δεν υπάρχει προσπάθεια προς έλεγχο')
        with self.db:
            self.db.execute("UPDATE rpa_items SET status='reviewed_by_operator',reason=? WHERE id=?",(note.strip()[:2000],item_id))
            self.erp.repository.audit(company,'rpa_manual_review',item['document_id'],dict(job=job,item=item_id,note=note.strip()[:2000],not_database_verified=True))

    def pause(self,company,job):
        self.items(company,job)
        with self.db:
            self.db.execute("UPDATE rpa_jobs SET status='paused' WHERE id=?",(job,))
            self.erp.repository.audit(company,'rpa_paused',None,dict(job=job))
