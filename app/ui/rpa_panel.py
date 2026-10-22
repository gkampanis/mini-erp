"""EBS actions over the existing document list: no second upload or empty queue tab."""
import sys
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,simpledialog
from app.application.service import ERP
from app.application.rpa import RPA
from app.application.workspace import Workspace
from app.infrastructure.ebs_adapter.adapter import load_mapper
from app.infrastructure.optional_packages import install

LABELS={'purchase_excluded':'Αγορές · εκτός EBS','not_sent':'Δεν στάλθηκε','queued':'Σε αναμονή','started':'Συμπλήρωση','save_pending':'Save σε εξέλιξη','simulated':'Προσομοίωση','filled_no_save':'Συμπληρώθηκε χωρίς Save','uncertain':'Έλεγχος στο EBS','failed':'Απέτυχε','save_invoked':'Στάλθηκε Save · έλεγχος','ui_saved_review':'Save → νέο ΤΕΔ · έλεγχος','reviewed_by_operator':'Ελέγχθηκε από χειριστή'}


class RPAPanel:
    def __init__(self,owner,parent,table=None):
        self.owner,self.parent=owner,parent;self.rpa=RPA(owner.erp);self.workspace=Workspace(owner.erp)
        self.rpa.recover(owner.company)
        self.job=None;self.pause_requested=False;self.stop_requested=False;self.running=False
        self.mode=tk.StringVar(value='Προσομοίωση');self.live_ack=tk.BooleanVar(value=False)
        self.mapping=None;self.hotkeys=set();self.tree=owner.tree
        row=ttk.Frame(parent);row.pack(fill='x',pady=(4,6))
        ttk.Button(row,text='Λογαριασμοί & έγκριση',command=self.accounts).pack(side='left')
        ttk.Button(row,text='Δοκιμή 1 εγγραφής',command=self.pilot).pack(side='left',padx=6)
        ttk.Button(row,text='Έξοδα → EBS',style='Primary.TButton',command=self.post).pack(side='left')
        ttk.Button(row,text='Ρυθμίσεις EBS',command=self.settings).pack(side='right')
        row=ttk.Frame(parent);row.pack(fill='x')
        self.scope=tk.StringVar(value='Όλες της λίστας')
        ttk.Combobox(row,textvariable=self.scope,values=('Όλες της λίστας','Μόνο επιλεγμένες','Από επιλεγμένη και μετά'),state='readonly',width=26).pack(side='left')
        ttk.Button(row,text='Προσομοίωση',command=self.simulate).pack(side='left',padx=6)
        ttk.Button(row,text='Παύση',command=self.pause).pack(side='left')
        ttk.Button(row,text='Συνέχεια',command=self.start).pack(side='left',padx=6)
        ttk.Button(row,text='Διακοπή',command=self.stop).pack(side='left')
        ttk.Button(row,text='Ιστορικό / έλεγχος EBS',command=self.history).pack(side='right')
        self.state=tk.StringVar(value='Φόρτωσε Excel μία φορά. Οι εγγραφές της λίστας είναι και οι εγγραφές καταχώρισης.')
        ttk.Label(parent,textvariable=self.state,style='Subtitle.TLabel',wraplength=1100).pack(anchor='w',pady=(7,0))
        owner.root.after(170,self.poll_hotkeys)

    def ids(self):
        visible=[int(x) for x in self.owner.tree.get_children()]
        selected={int(x) for x in self.owner.tree.selection()}
        if self.scope.get()=='Μόνο επιλεγμένες':return [x for x in visible if x in selected]
        # Keep the original Excel order, independent of table sorting.
        ordered=sorted(visible,key=lambda x:self.owner._documents[x]['source_record_id'])
        if self.scope.get()=='Από επιλεγμένη και μετά':
            if not selected:raise ValueError('Επίλεξε τη γραμμή εκκίνησης στη λίστα')
            start=min(selected,key=lambda x:self.owner._documents[x]['source_record_id'])
            return ordered[ordered.index(start):]
        return ordered

    def refresh(self):
        if self.job is not None:
            meta,items=self.rpa.items(self.owner.company,self.job)
            done=sum(i['status']!='queued' for i in items)
            self.state.set(f'Πρόοδος {done}/{len(items)} · '+{'running':'Σε εξέλιξη','paused':'Σε παύση','stopped':'Διακόπηκε','completed':'Τέλος ουράς — έλεγχος στο EBS','queued':'Έτοιμη ουρά'}.get(meta['status'],meta['status']))

    def accounts(self):
        if self.owner.busy:return
        chosen=self.owner.tree.selection()
        ids=[int(x) for x in chosen] if chosen else list(self.owner._documents)
        if not ids:messagebox.showinfo('Excel','Φόρτωσε πρώτα το Excel.',parent=self.owner.root);return
        rows=[self.owner._documents[x] for x in ids]
        win=tk.Toplevel(self.owner.root);win.title('Λογαριασμοί · '+str(len(ids))+' παραστατικά');win.geometry('900x630');win.minsize(780,520)
        body=ttk.Frame(win,padding=18);body.pack(fill='both',expand=True)
        ttk.Label(body,text=f'{len(ids)} παραστατικά · Έλεγχος λογαριασμών',style='Section.TLabel').pack(anchor='w')
        ttk.Label(body,text='Κοινός λογαριασμός ή διαφορετικός ανά ΑΦΜ. Η εφαρμογή δεν μαντεύει λογαριασμούς.',style='Subtitle.TLabel').pack(anchor='w',pady=(6,12))
        shared=ttk.Frame(body);shared.pack(fill='x')
        common=tk.StringVar();group=tk.StringVar(value='6 · Έξοδα')
        ttk.Combobox(shared,textvariable=group,values=('2 · Αγορές','6 · Έξοδα'),state='readonly',width=16).pack(side='left')
        ttk.Entry(shared,textvariable=common,width=25).pack(side='left',padx=8)
        forms={}
        def apply_common():
            for g,a in forms.values():g.set(group.get());a.set(common.get())
        ttk.Button(shared,text='Εφαρμογή σε όλα εδώ',command=apply_common).pack(side='left')
        frame=ttk.Frame(body);frame.pack(fill='both',expand=True,pady=14)
        canvas=tk.Canvas(frame,highlightthickness=0,background='#f3f6fc');scroll=ttk.Scrollbar(frame,command=canvas.yview)
        inner=ttk.Frame(canvas);item=canvas.create_window((0,0),window=inner,anchor='nw')
        canvas.configure(yscrollcommand=scroll.set);canvas.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
        inner.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')));canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
        suppliers={}
        for row in rows:suppliers.setdefault(row['vat'],[]).append(row)
        for index,(vat,documents) in enumerate(suppliers.items()):
            approved={r['account_code'] for r in documents if r.get('account_code')}
            if not approved:approved={r['suggested_account'] for r in documents if r.get('suggested_account')}
            account=next(iter(approved)) if len(approved)==1 else ''
            g=tk.StringVar(value=('2 · Αγορές' if account.startswith('2') else '6 · Έξοδα'));a=tk.StringVar(value=account);forms[vat]=(g,a)
            ttk.Label(inner,text=f"{documents[0]['name']}\nΑΦΜ {vat} · {len(documents)} εγγραφές",wraplength=330).grid(row=index,column=0,sticky='w',padx=8,pady=10)
            ttk.Combobox(inner,textvariable=g,values=('2 · Αγορές','6 · Έξοδα'),state='readonly',width=16).grid(row=index,column=1,padx=8)
            ttk.Entry(inner,textvariable=a,width=25).grid(row=index,column=2,padx=8)
        remember=tk.BooleanVar(value=False)
        ttk.Checkbutton(body,text='Αποθήκευση αυτών των επιλογών ως εγκεκριμένα mappings ανά ΑΦΜ',variable=remember).pack(anchor='w')
        bottom=ttk.Frame(body);bottom.pack(fill='x',pady=(12,0))
        def suggest():
            conflicts=[]
            for vat,(g,a) in forms.items():
                candidates=self.workspace.suggestions(self.owner.company,vat)
                if len(candidates)==1:a.set(candidates[0]);g.set('2 · Αγορές' if candidates[0].startswith('2') else '6 · Έξοδα')
                elif len(candidates)>1:conflicts.append(vat)
            if conflicts:messagebox.showwarning('Διαφορετικές προηγούμενες επιλογές','Έλεγξε χειροκίνητα τα ΑΦΜ: '+', '.join(conflicts),parent=win)
        ttk.Button(bottom,text='Πρόταση από εγκεκριμένο ιστορικό',command=suggest).pack(side='left')
        def approve():
            decisions=[dict(document=r['id'],group=forms[r['vat']][0].get()[0],account=forms[r['vat']][1].get()) for r in rows]
            if not messagebox.askyesno('Έγκριση λογαριασμών',f'Έλεγξες ομάδα και λογαριασμό για τα {len(rows)} παραστατικά; Θα εγκριθούν μαζί. Δεν γίνεται ακόμη καταχώριση.',parent=win):return
            try:self.workspace.approve_many(self.owner.company,decisions,confirmed=True,remember=remember.get())
            except (ValueError,RuntimeError) as exc:messagebox.showerror('Έλεγχος',str(exc),parent=win);return
            win.destroy();self.owner.refresh();self.state.set(f'Εγκρίθηκαν {len(rows)} παραστατικά. Συνέχισε με δοκιμή ή καταχώριση στο EBS.')
        ttk.Button(bottom,text='Έγκριση λογαριασμών',style='Primary.TButton',command=approve).pack(side='right')
        return win

    def settings(self):
        if self.owner.busy:return
        win=tk.Toplevel(self.owner.root);win.title('Ρυθμίσεις EBS · αποθηκεύονται μία φορά');win.geometry('760x530')
        body=ttk.Frame(win,padding=20);body.pack(fill='both',expand=True)
        saved=self.workspace.profile(self.owner.company);profile=saved['profile'] if saved else {'mapping':{},'save':None,'new':None}
        status=tk.StringVar()
        def describe():status.set(f"Mapper: {'φορτωμένος' if profile['mapping'] else 'δεν ορίστηκε'}\nSave: {profile['save'] or 'δεν ορίστηκε'}\nΝέο ΤΕΔ: {profile['new'] or 'δεν ορίστηκε'}\nΠιλοτικός έλεγχος: {'επιβεβαιωμένος' if saved and saved['pilot_at'] else 'εκκρεμεί'}")
        ttk.Label(body,text='Mapper, Save και Νέο ΤΕΔ',style='Section.TLabel').pack(anchor='w')
        ttk.Label(body,text='Χρησιμοποίησε την ίδια διάταξη Entersoft με τον αρχικό agent. Οι θέσεις διατηρούνται για την επόμενη εκκίνηση.',wraplength=690,style='Subtitle.TLabel').pack(anchor='w',pady=10)
        def mapper():
            filename=filedialog.askopenfilename(parent=win,filetypes=[('CSV mapper','*.csv')])
            if not filename:return
            try:profile['mapping']=load_mapper(filename);describe()
            except (ValueError,OSError) as exc:messagebox.showerror('Mapper',str(exc),parent=win)
        ttk.Button(body,text='Φόρτωση υπάρχοντος CSV mapper',command=mapper).pack(anchor='w',pady=8)
        def capture(key):
            if sys.platform!='win32':messagebox.showinfo('Windows','Η καταγραφή θέσεων γίνεται στον υπολογιστή με Entersoft.',parent=win);return
            from app.infrastructure.ebs_adapter.session import WindowsSession
            try:backend=WindowsSession()
            except RuntimeError as exc:messagebox.showerror('Adapter',str(exc),parent=win);return
            messagebox.showinfo('Καταγραφή θέσης','Μετά το ΟΚ βάλε το ποντίκι πάνω στο '+('Save' if key=='save' else 'Νέο ΤΕΔ')+' του Entersoft. Σε 3 δευτερόλεπτα καταγράφεται χωρίς κλικ.',parent=win)
            win.withdraw();self.owner.root.withdraw()
            def finish():
                try:
                    point=tuple(backend.pg.position());backend.at_ebs(point);profile[key]=point;describe()
                except Exception as exc:messagebox.showerror('Θέση EBS',str(exc),parent=win)
                finally:self.owner.root.deiconify();win.deiconify()
            self.owner.root.after(3000,finish)
        line=ttk.Frame(body);line.pack(fill='x',pady=8)
        ttk.Button(line,text='Καταγραφή Save',command=lambda:capture('save')).pack(side='left')
        ttk.Button(line,text='Καταγραφή Νέο ΤΕΔ',command=lambda:capture('new')).pack(side='left',padx=8)
        ttk.Label(body,textvariable=status,style='Subtitle.TLabel',justify='left').pack(anchor='w',pady=12);describe()
        def save():
            try:self.workspace.save_profile(self.owner.company,profile)
            except ValueError as exc:messagebox.showerror('Ρυθμίσεις',str(exc),parent=win);return
            win.destroy();self.state.set('Οι θέσεις αποθηκεύτηκαν. Επόμενο: δοκιμή μίας εγγραφής και έλεγχος στο EBS.')
        ttk.Button(body,text='Εγκατάσταση RPA adapter',command=lambda:self.owner.run_worker(lambda:install('rpa'),lambda _:status.set('Ο adapter εγκαταστάθηκε.')) if messagebox.askyesno('Adapter','Να εγκατασταθεί PyAutoGUI μόνο για MiniERP;',parent=win) else None).pack(anchor='w',pady=8)
        ttk.Button(body,text='Αποθήκευση ρυθμίσεων',style='Primary.TButton',command=save).pack(side='bottom',anchor='e')
        return win

    def make(self,mode,pilot=False):
        if self.owner.busy or self.running:return
        try:
            ids=self.ids()
            if pilot:
                selected=self.owner.tree.selection()
                if not selected:raise ValueError('Επίλεξε ένα παραστατικό για πιλοτική καταχώριση')
                ids=[int(selected[0])]
            if not ids:raise ValueError('Δεν υπάρχουν εγγραφές. Φόρτωσε πρώτα Excel.')
            scope=self.rpa.expense_scope(self.owner.company,ids)
            excluded=len(scope['purchases'])
            if scope['needs_review']:raise ValueError(f"{len(scope['needs_review'])} εγγραφές χρειάζονται διαχωρισμό ή έγκριση λογαριασμού. {excluded} αγορές ομάδας 2 είναι εκτός EBS. Πάτησε «Λογαριασμοί & έγκριση».")
            ids=scope['expenses']
            if not ids:raise ValueError('Δεν υπάρχουν εγκεκριμένα έξοδα ομάδας 6 σε αυτή την επιλογή. Οι αγορές ομάδας 2 παραμένουν στη βάση, εκτός EBS.')
            real=mode=='fill_only'
            if real and sys.platform!='win32':raise ValueError('Η πραγματική καταχώριση απαιτεί Windows με Entersoft. Η προσομοίωση λειτουργεί εδώ.')
            if not messagebox.askyesno('Έναρξη '+('EBS' if real else 'προσομοίωσης'),f'{len(ids)} έξοδα ομάδας 6, με τους εγκεκριμένους λογαριασμούς τους.\n{excluded} αγορές ομάδας 2 εξαιρέθηκαν και παραμένουν στη βάση.\n'+('Θα εκτελεστεί η ροή συμπλήρωση → Save → νέο ΤΕΔ. Επιβεβαιώνεις κενό ΤΕΔ και πραγματικές καταχωρίσεις;' if real else 'Δεν θα γίνει καμία ενέργεια στο EBS. Συνέχεια;'),parent=self.owner.root):return
            self.job=self.rpa.create(self.owner.company,ids,mode,confirmed=True,execution='save_new' if real else 'fill_only',pilot=pilot)
        except ValueError as exc:messagebox.showwarning('Πριν την έναρξη',str(exc),parent=self.owner.root);return
        self.start()

    def pilot(self):self.make('fill_only',pilot=True)
    def post(self):self.make('fill_only')
    def simulate(self):self.make('simulation')
    def queue_selected(self):
        self.scope.set('Μόνο επιλεγμένες')
        try:
            scope=self.rpa.expense_scope(self.owner.company,self.ids())
            if scope['needs_review']:raise ValueError('Υπάρχουν αταξινόμητες ή μη εγκεκριμένες εγγραφές')
            self.job=self.rpa.create(self.owner.company,scope['expenses'],confirmed=True)
        except ValueError as exc:messagebox.showwarning('Έλεγχος',str(exc),parent=self.owner.root)
        self.refresh()

    def start(self):
        if self.owner.busy or self.job is None:return
        self.pause_requested=False;self.stop_requested=False;self.running=True
        self.next_item(continuing=True)

    def next_item(self,continuing=False):
        if self.owner._closing:return
        if self.stop_requested:self.rpa.stop(self.owner.company,self.job);self.running=False;self.owner.root.deiconify();self.refresh();return
        if self.pause_requested:self.rpa.pause(self.owner.company,self.job);self.running=False;self.owner.root.deiconify();self.refresh();return
        if self.job is None or self.owner.busy:return
        job=self.job;meta,_=self.rpa.items(self.owner.company,job)
        if meta['mode']=='fill_only':self.owner.root.withdraw()
        def execute():
            service=ERP(self.owner.directory)
            try:
                try:return RPA(service).advance(self.owner.company,job,live_confirmed=True,continue_after_pause=continuing)
                except (ValueError,RuntimeError) as exc:return dict(status='blocked',reason=str(exc))
            finally:service.close()
        def done(result):
            if self.owner._closing:return
            self.owner.refresh();self.refresh()
            if result.get('reason'):self.state.set(result['reason'])
            if result['status']=='running' and not self.stop_requested and not self.pause_requested:self.parent.after(350,self.next_item)
            else:
                if self.stop_requested:self.rpa.stop(self.owner.company,job)
                elif self.pause_requested:self.rpa.pause(self.owner.company,job)
                self.running=False;self.owner.root.deiconify()
        self.owner.run_worker(execute,done)

    def pause(self):
        self.pause_requested=True
        if not self.owner.busy and self.job is not None:self.rpa.pause(self.owner.company,self.job);self.running=False;self.owner.root.deiconify();self.refresh()
    def stop(self):
        self.stop_requested=True
        if not self.owner.busy and self.job is not None:self.rpa.stop(self.owner.company,self.job);self.running=False;self.owner.root.deiconify();self.refresh()

    def history(self):
        win=tk.Toplevel(self.owner.root);win.title('Ιστορικό EBS · έλεγχος και συνέχεια');win.geometry('1000x600')
        frame=ttk.Frame(win,padding=16);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Save / νέο ΤΕΔ δεν αποτελούν αυτόματη επιβεβαίωση αποθήκευσης στη βάση EBS.',style='Subtitle.TLabel').pack(anchor='w',pady=8)
        from app.ui.desktop import table
        tree=table(frame,('job','invoice','vat','state'),('Ουρά','Παραστατικό','ΑΦΜ','Ενέργεια / αποτέλεσμα'),{'state':350})
        rows=self.owner.erp.db.execute('SELECT i.*,j.mode FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? ORDER BY i.id DESC',(self.owner.company,)).fetchall()
        import json
        for row in rows:
            p=json.loads(row['payload']);tree.insert('','end',iid=str(row['id']),values=(row['job_id'],p['invoice'],p['vat'],LABELS.get(row['status'],row['status'])))
        bottom=ttk.Frame(frame);bottom.pack(fill='x',pady=10)
        def review(pilot=False):
            selected=tree.selection()
            if not selected:return
            item=int(selected[0]);row=next(r for r in rows if r['id']==item)
            note=simpledialog.askstring('Έλεγχος στο EBS','Επιβεβαίωσες ότι το παραστατικό είναι αποθηκευμένο με σωστά στοιχεία; Σημείωσε τον έλεγχο:',parent=win)
            if not note:return
            try:
                if pilot:self.workspace.confirm_pilot(self.owner.company,item,note,confirmed=True)
                else:self.rpa.reviewed(self.owner.company,row['job_id'],item,note,confirmed=True)
            except ValueError as exc:messagebox.showerror('Έλεγχος',str(exc),parent=win);return
            win.destroy();self.owner.refresh();self.state.set('Ο χειροκίνητος έλεγχος καταγράφηκε. Η πιλοτική επιβεβαίωση επιτρέπει μαζική εκτέλεση.' if pilot else 'Καταγράφηκε ο έλεγχος στο EBS.')
        ttk.Button(bottom,text='Επιβεβαίωση πιλοτικού — ενεργοποίηση batch',command=lambda:review(True)).pack(side='left')
        ttk.Button(bottom,text='Χειροκίνητος έλεγχος προσπάθειας',command=review).pack(side='left',padx=8)
        def select():
            selected=tree.selection()
            if selected:self.job=next(r['job_id'] for r in rows if r['id']==int(selected[0]));win.destroy();self.refresh()
        ttk.Button(bottom,text='Επιλογή ουράς για συνέχεια',command=select).pack(side='right')
        return win

    def poll_hotkeys(self):
        if self.owner._closing:return
        if sys.platform=='win32':
            import ctypes
            u=ctypes.windll.user32;ctrl=u.GetAsyncKeyState(0x11)&0x8000;shift=u.GetAsyncKeyState(0x10)&0x8000
            keys={name for name,vk in [('pause',0x78),('resume',0x79),('stop',0x7B)] if ctrl and shift and u.GetAsyncKeyState(vk)&0x8000}
            for key in keys-self.hotkeys:
                if key=='pause':self.pause()
                elif key=='stop':self.stop()
                elif not self.running:self.start()
            self.hotkeys=keys
        self.owner.root.after(170,self.poll_hotkeys)
