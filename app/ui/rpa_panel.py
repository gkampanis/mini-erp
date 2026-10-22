"""Integrated queue controls; no Save button or hidden ERP posting."""
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,simpledialog
from app.application.service import ERP
from app.application.rpa import RPA
from app.infrastructure.ebs_adapter.adapter import load_mapper
from app.infrastructure.optional_packages import install

JOBS={'queued':'Σε αναμονή','running':'Σε εξέλιξη','paused':'Σε παύση','stopped':'Διακόπηκε','completed':'Ολοκληρώθηκε'}

LABELS={'queued':'Σε αναμονή','started':'Ξεκίνησε','simulated':'Προσομοίωση','filled_no_save':'Συμπληρώθηκε · χωρίς Save','uncertain':'Αβέβαιο · έλεγχος','failed':'Απέτυχε','reviewed_by_operator':'Χειροκίνητος έλεγχος'}


class RPAPanel:
    def __init__(self,owner,parent,table):
        self.owner,self.parent=owner,parent;self.mapping=None;self.job=None;self.pause_requested=False;self.stop_requested=False
        self.rpa=RPA(owner.erp)
        self.rpa.recover(owner.company)
        saved=owner.erp.db.execute('SELECT id FROM rpa_jobs WHERE company_id=? ORDER BY id DESC LIMIT 1',(owner.company,)).fetchone()
        if saved:self.job=saved[0]
        ttk.Label(parent,text='RPA → EBS',style='Section.TLabel').pack(anchor='w')
        ttk.Label(parent,text='1. Εγκεκριμένα παραστατικά → 2. Προεπισκόπηση ουράς → 3. Προσομοίωση ή ελεγχόμενη συμπλήρωση',style='Subtitle.TLabel',wraplength=1050).pack(anchor='w',pady=(6,12))
        row=ttk.Frame(parent);row.pack(fill='x')
        self.mode=tk.StringVar(value='Προσομοίωση')
        ttk.Combobox(row,textvariable=self.mode,values=('Προσομοίωση','Windows · συμπλήρωση χωρίς Save'),state='readonly',width=36).pack(side='left')
        ttk.Button(row,text='Φόρτωση CSV mapper',command=self.mapper).pack(side='left',padx=8)
        ttk.Button(row,text='Ρύθμιση Windows adapter',command=self.setup).pack(side='left')
        self.mapper_status=tk.StringVar(value='Δεν έχει φορτωθεί mapper. Η προσομοίωση δεν χρειάζεται EBS.')
        ttk.Label(parent,textvariable=self.mapper_status,style='Subtitle.TLabel').pack(anchor='w',pady=8)
        self.jobs=ttk.Combobox(parent,state='readonly',width=65)
        self.jobs.pack(anchor='w',pady=(0,8))
        self.jobs.bind('<<ComboboxSelected>>',self.select_job)
        self.live_ack=tk.BooleanVar(value=False)
        ttk.Checkbutton(parent,text='Για πραγματική συμπλήρωση: επαλήθευσα πιλοτικά τον mapper και έχω ανοιχτό κενό ΤΕΔ δαπάνης.',variable=self.live_ack).pack(anchor='w',pady=(0,10))
        controls=ttk.Frame(parent);controls.pack(fill='x',pady=(0,10))
        ttk.Button(controls,text='Ουρά από επιλεγμένα',command=self.queue_selected).pack(side='left')
        ttk.Button(controls,text='Από επιλεγμένο και μετά',command=self.queue_from_selected).pack(side='left',padx=6)
        ttk.Button(controls,text='Εγκεκριμένα της λίστας',command=self.queue_visible).pack(side='left')
        self.state=tk.StringVar(value='Δεν δημιουργήθηκε ουρά.')
        ttk.Label(parent,textvariable=self.state,style='Subtitle.TLabel',wraplength=1100).pack(anchor='w',pady=(0,8))
        bottom=ttk.Frame(parent);bottom.pack(side='bottom',fill='x',pady=(10,0))
        ttk.Button(bottom,text='Έναρξη / Συνέχεια',style='Primary.TButton',command=self.start).pack(side='left')
        ttk.Button(bottom,text='Παύση μετά το τρέχον',command=self.pause).pack(side='left',padx=6)
        ttk.Button(bottom,text='Διακοπή ουράς',command=self.stop).pack(side='left')
        ttk.Button(bottom,text='Χειροκίνητος έλεγχος προσπάθειας',command=self.review).pack(side='right')
        self.tree=table(parent,('invoice','name','vat','account','status'),('Παραστατικό','Επωνυμία','ΑΦΜ','Λογαριασμός','Κατάσταση RPA'),{'name':240,'status':260})
        self.refresh()

    def mapper(self):
        if self.owner.busy:return
        path=filedialog.askopenfilename(parent=self.owner.root,filetypes=[('CSV','*.csv')])
        if not path:return
        try:self.mapping=load_mapper(path)
        except (ValueError,OSError) as exc:messagebox.showerror('Mapper',str(exc),parent=self.owner.root);return
        self.mapper_status.set('CSV mapper: 5 πεδία φορτώθηκαν. Η ημερομηνία γράφεται από το πρώτο ψηφίο, χωρίς διαχωριστικά.')

    def setup(self):
        if self.owner.busy:return
        if messagebox.askyesno('Windows adapter','Να εγκατασταθεί ο προαιρετικός PyAutoGUI adapter σε ξεχωριστό φάκελο MiniERP; Δεν θα εκτελεστεί RPA.',parent=self.owner.root):
            self.owner.run_worker(lambda:install('rpa'),lambda _:self.mapper_status.set('Ο adapter εγκαταστάθηκε. Απαιτούνται Windows και πιλοτικά επαληθευμένος mapper.'))

    def queue_selected(self):self.create([int(x) for x in self.owner.tree.selection()])
    def queue_visible(self):self.create([x for x,r in self.owner._documents.items() if r.get('prepared_at')])
    def queue_from_selected(self):
        selected=self.owner.tree.selection()
        if not selected:self.create([]);return
        start=int(selected[0])
        visible=[int(x) for x in self.owner.tree.get_children()]
        self.create([x for x in visible[visible.index(start):] if self.owner._documents[x].get('prepared_at')])

    def create(self,ids):
        if self.owner.busy:return
        if not ids:messagebox.showinfo('Επιλογή','Επίλεξε εγκεκριμένα παραστατικά στην καρτέλα Παραστατικά.',parent=self.owner.root);return
        mode='simulation' if self.mode.get()=='Προσομοίωση' else 'fill_only'
        if mode=='fill_only' and (not self.live_ack.get() or self.mapping is None):
            messagebox.showwarning('Προέλεγχος','Απαιτούνται mapper και ρητή επιβεβαίωση πιλοτικού ελέγχου.',parent=self.owner.root);return
        if not messagebox.askyesno('Προεπισκόπηση ουράς',f'{len(ids)} παραστατικά.\nΛειτουργία: {self.mode.get()}.\nΔεν θα σταλεί Save. Δημιουργία ουράς;',parent=self.owner.root):return
        try:self.job=self.rpa.create(self.owner.company,ids,mode,confirmed=True)
        except ValueError as exc:messagebox.showerror('Δεν δημιουργήθηκε ουρά',str(exc),parent=self.owner.root);return
        self.refresh()

    def select_job(self,event=None):
        self.job=self.job_choices[self.jobs.get()];self.refresh()

    def refresh(self):
        rows=self.owner.erp.db.execute('SELECT id,mode,status FROM rpa_jobs WHERE company_id=? ORDER BY id DESC LIMIT 100',(self.owner.company,)).fetchall()
        self.job_choices={f"Ουρά {r['id']} · {'Προσομοίωση' if r['mode']=='simulation' else 'Συμπλήρωση'} · {JOBS.get(r['status'],r['status'])}":r['id'] for r in rows}
        self.jobs.configure(values=tuple(self.job_choices))
        self.jobs.set(next((label for label,value in self.job_choices.items() if value==self.job),''))
        self.tree.delete(*self.tree.get_children())
        if self.job is None:return
        meta,items=self.rpa.items(self.owner.company,self.job)
        for item in items:
            p=item['payload'];self.tree.insert('','end',iid=str(item['id']),values=(p['invoice'],p['name'],p['vat'],p['account'],LABELS.get(item['status'],item['status'])))
        self.state.set(f"Ουρά {self.job} · {'Προσομοίωση' if meta['mode']=='simulation' else 'Windows / χωρίς Save'} · {JOBS.get(meta['status'],meta['status'])} · {sum(i['status']!='queued' for i in items)}/{len(items)} προσπάθειες")

    def start(self):
        if self.owner.busy or self.job is None:return
        self.pause_requested=False;self.stop_requested=False
        meta,_=self.rpa.items(self.owner.company,self.job)
        if meta['mode']=='fill_only':
            if not self.live_ack.get() or self.mapping is None:
                messagebox.showwarning('Προέλεγχος','Φόρτωσε mapper και επιβεβαίωσε τον πιλοτικό έλεγχο.',parent=self.owner.root);return
            if not messagebox.askyesno('Συμπλήρωση EBS χωρίς Save','Κενό ΤΕΔ στην επαληθευμένη θέση; Θα πληκτρολογηθούν 5 πεδία. Έπειτα θα γίνει παύση για έλεγχο. Κανένα Save ή αυτόματη επανάληψη.',parent=self.owner.root):return
        self.next_item()

    def next_item(self):
        if self.stop_requested:
            self.rpa.stop(self.owner.company,self.job);self.refresh();return
        if self.pause_requested:self.state.set('Παύση μετά την τρέχουσα προσπάθεια.');return
        if self.job is None or self.owner.busy:return
        job=self.job;mapping=self.mapping;confirmed=self.live_ack.get()
        def execute():
            service=ERP(self.owner.directory)
            try:
                try:return RPA(service).advance(self.owner.company,job,mapping,live_confirmed=confirmed)
                except (ValueError,RuntimeError) as exc:return dict(status='blocked',reason=str(exc))
            finally:service.close()
        def done(result):
            if self.owner._closing:return
            self.owner.root.deiconify();self.refresh()
            if result.get('reason'):self.state.set(result['reason'])
            if self.pause_requested:self.rpa.pause(self.owner.company,job);self.refresh()
            if self.stop_requested:self.rpa.stop(self.owner.company,job);self.refresh();return
            if result.get('mode')=='simulation' and result['status']=='running' and not self.pause_requested:
                self.parent.after(50,self.next_item)
        meta,_=self.rpa.items(self.owner.company,job)
        if meta['mode']=='fill_only':self.owner.root.withdraw()
        self.owner.run_worker(execute,done)

    def pause(self):
        self.pause_requested=True
        if not self.owner.busy and self.job is not None:self.rpa.pause(self.owner.company,self.job);self.refresh()
    def stop(self):
        self.stop_requested=True
        if not self.owner.busy and self.job is not None:self.rpa.stop(self.owner.company,self.job);self.refresh()

    def review(self):
        if self.owner.busy or self.job is None:return
        selected=self.tree.selection()
        if not selected:return
        note=simpledialog.askstring('Χειροκίνητος έλεγχος','Τι επαλήθευσες στο EBS; Η εγγραφή δεν χαρακτηρίζεται ως επιβεβαιωμένη από API.',parent=self.owner.root)
        if not note:return
        if not messagebox.askyesno('Επιβεβαίωση ελέγχου','Έλεγξες την προηγούμενη προσπάθεια και μπορείς με ασφάλεια να συνεχίσεις σε κενό ΤΕΔ;',parent=self.owner.root):return
        try:self.rpa.reviewed(self.owner.company,self.job,int(selected[0]),note,confirmed=True)
        except ValueError as exc:messagebox.showerror('Έλεγχος',str(exc),parent=self.owner.root);return
        self.refresh()
