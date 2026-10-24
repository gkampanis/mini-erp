"""EBS actions over the existing document list: no second upload or empty queue tab."""
import sys
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,simpledialog
from app.application.service import ERP
from app.application.rpa import RPA
from app.application.workspace import Workspace
from app.infrastructure.ebs_adapter.adapter import load_mapper

LABELS={'outgoing_excluded':'Εκδοθέν · εκτός εξόδων','purchase_excluded':'Αγορές · εκτός EBS','excluded_purchase':'Αγορές · αποκλείστηκε πριν εκτέλεση','not_sent':'Χωρίς προσπάθεια','queued':'Σε αναμονή','started':'Συμπλήρωση','save_pending':'Save σε εξέλιξη','simulated':'Ελέγχθηκε χωρίς καταχώριση','filled_no_save':'Συμπληρώθηκε χωρίς Save','uncertain':'Χρειάζεται έλεγχος στο EBS','failed':'Απέτυχε','save_invoked':'Εντολή Save · οπτικός έλεγχος','ui_saved_review':'Save → νέο ΤΕΔ · έλεγχος','reviewed_by_operator':'Ελέγχθηκε από χειριστή'}


class RPAPanel:
    def __init__(self,owner,parent,table=None):
        self.owner,self.parent=owner,parent;self.rpa=RPA(owner.erp);self.workspace=Workspace(owner.erp)
        self.rpa.recover(owner.company)
        self._next_after=None;self._preview=None;self.buttons={}
        self._notice=''
        self.job=None;self.pause_requested=False;self.stop_requested=False;self.running=False
        self.mode=tk.StringVar(value='Προσομοίωση');self.live_ack=tk.BooleanVar(value=False)
        self.mapping=None;self.hotkeys=set();self.tree=owner.tree
        row=ttk.Frame(parent);row.pack(fill='x',pady=(4,6))
        self.buttons['accounts']=ttk.Button(row,text='Έλεγχος λογαριασμών',command=self.accounts);self.buttons['accounts'].pack_forget()
        self.buttons['simulation']=ttk.Button(row,text='Έλεγχος χωρίς καταχώριση',command=self.simulate);self.buttons['simulation'].pack_forget()
        self.buttons['post']=ttk.Button(row,text='Καταχώριση έως 40',style='Primary.TButton',command=self.post);self.buttons['post'].pack(side='left')
        self.buttons['selected']=ttk.Button(row,text='Καταχώριση επιλεγμένων',command=self.post_selected);self.buttons['selected'].pack(side='left',padx=6)
        self.buttons['one']=ttk.Button(row,text='Μεμονωμένη καταχώριση',command=self.post_one);self.buttons['one'].pack(side='left')
        options=ttk.Menubutton(row,text='Ρυθμίσεις & ιστορικό')
        self.options_menu=tk.Menu(options,tearoff=False)
        self.options_menu.add_command(label='Ρυθμίσεις EBS',command=self.settings)
        self.options_menu.add_command(label='Προβολή ουράς',command=self.preview)
        self.options_menu.add_command(label='Ιστορικό / οπτικός έλεγχος EBS',command=self.history)
        self.options_menu.add_command(label='Προαιρετικός έλεγχος χωρίς καταχώριση',command=self.simulate)
        self.options_menu.add_command(label='Αλλαγή λογαριασμών επιλεγμένων',command=self.accounts)
        self.scope=tk.StringVar(value='Εκκρεμή προς EBS')
        options.configure(menu=self.options_menu);options.pack(side='right')
        row=ttk.Frame(parent);self.execution_controls=row
        self.buttons['pause']=ttk.Button(row,text='Παύση',width=8,command=self.pause);self.buttons['pause'].pack(side='left')
        self.buttons['resume']=ttk.Button(row,text='Συνέχεια',width=8,command=self.start);self.buttons['resume'].pack(side='left',padx=6)
        self.buttons['stop']=ttk.Button(row,text='Διακοπή',width=8,command=self.stop);self.buttons['stop'].pack(side='left')
        self.state=tk.StringVar(value='Καταχώριση έως 40 από την ορατή λίστα ή μόνο των επιλεγμένων. Αποθήκευση: οπτικός έλεγχος EBS.')
        state_label=ttk.Label(parent,textvariable=self.state,style='Subtitle.TLabel',wraplength=1100);state_label.pack(anchor='w',pady=(7,0))
        parent.bind('<Configure>',lambda event:state_label.configure(wraplength=max(200,event.width-8)),add='+')
        from app.ui.help import tooltip
        tooltip(self.buttons['simulation'],'Προβάλλει και ελέγχει τα δεδομένα της ουράς χωρίς πληκτρολόγηση ή Save στο EBS.')
        tooltip(self.buttons['pause'],'Ολοκληρώνει την τρέχουσα εγγραφή και παγώνει πριν από την επόμενη. Η θέση διατηρείται.')
        tooltip(self.buttons['resume'],'Συνεχίζει μόνο τις εκκρεμείς εγγραφές. Αβέβαιη προηγούμενη προσπάθεια απαιτεί πρώτα χειροκίνητο έλεγχο.')
        tooltip(self.buttons['stop'],'Τερματίζει την ουρά μετά την τρέχουσα εγγραφή. Δεν είναι προσωρινή παύση.')
        self.restore_job()
        owner.root.after(170,self.poll_hotkeys)

    def notify(self,message,*,error=False):
        self._notice=message;self.state.set(message)
        if error:messagebox.showerror('Καταχώριση EBS',message,parent=self.owner.root)

    def restore_job(self):
        self._notice=''
        self.rpa.recover(self.owner.company)
        row=self.owner.erp.db.execute("SELECT id FROM rpa_jobs WHERE company_id=? AND status IN ('queued','paused') ORDER BY mode='fill_only' DESC,id DESC LIMIT 1",(self.owner.company,)).fetchone()
        self.job=row['id'] if row else None

    def ids(self):
        visible=[int(x) for x in self.owner.tree.get_children()]
        selected={int(x) for x in self.owner.tree.selection()}
        if self.scope.get()=='Μόνο επιλεγμένες':return [x for x in visible if x in selected]
        # Keep the original Excel order, independent of table sorting.
        ordered=sorted(visible,key=lambda x:self.owner._documents[x]['source_record_id'])
        if self.scope.get()=='Εκκρεμή προς EBS':
            attempted={r[0] for r in self.owner.erp.db.execute("SELECT i.document_id FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND j.mode='fill_only' AND i.status<>'queued'",(self.owner.company,))}
            return [d for d in ordered if d not in attempted and (not selected or d in selected)]
        if self.scope.get()=='Από επιλεγμένη και μετά':
            if not selected:raise ValueError('Επίλεξε τη γραμμή εκκίνησης στη λίστα')
            start=min(selected,key=lambda x:self.owner._documents[x]['source_record_id'])
            return ordered[ordered.index(start):]
        return ordered

    def update_selection_actions(self):
        has_rows=bool(self.owner._documents)
        for key in ('accounts','post','simulation'):self.buttons[key].state(['disabled'] if self.owner.busy or self.running or not has_rows else ['!disabled'])
        selected=self.owner.tree.selection()
        for key,available in (('selected',bool(selected)),('one',len(selected)==1)):
            self.buttons[key].state(['!disabled'] if available and not self.owner.busy and not self.running else ['disabled'])
        self.options_menu.entryconfigure(3,state='disabled' if self.owner.busy or self.running or not has_rows else 'normal')

    def refresh(self):
        meta=None;items=[]
        if self.job is not None:
            meta,items=self.rpa.items(self.owner.company,self.job);p=self.rpa.progress(self.owner.company,self.job)
            mode='Έλεγχος χωρίς καταχώριση' if meta['mode']=='simulation' else 'Εκτέλεση EBS'
            state={'running':'Σε εξέλιξη','paused':'Σε παύση','stopped':'Διακόπηκε','completed':'Τέλος ουράς','queued':'Έτοιμη ουρά'}.get(meta['status'],meta['status'])
            self.state.set(f"{mode} · {state} · {p['processed']}/{p['total']} · Τρέχον {p['current']} · Επιβεβαιωμένα οπτικά {p['verified_in_ebs']} · Εντολές Save {p['save_requested']} · Αποτυχίες/αβέβαια {p['failed']} · Παραλείψεις {p['skipped']}. "+('Καμία ενέργεια στο EBS.' if meta['mode']=='simulation' else 'Η αποθήκευση ελέγχεται οπτικά στο EBS. ')+(p['reason'] if meta['status'] in ('paused','completed') else ''))
        if self._notice:self.state.set(self._notice+('\n'+self.state.get() if meta else ''))
        blocked=any(i['status'] in ('started','save_pending','uncertain','filled_no_save') for i in items)
        self.update_selection_actions()
        if meta and meta['status'] in ('running','queued','paused'):self.execution_controls.pack(fill='x',before=self.parent.winfo_children()[-1])
        else:self.execution_controls.pack_forget()
        for key,visible in (('pause',self.running),('resume',bool(meta and meta['status'] in ('queued','paused') and not self.running)),('stop',bool(meta and meta['status'] in ('running','queued','paused')))):
            if visible:self.buttons[key].pack(side='left',padx=4)
            else:self.buttons[key].pack_forget()
        self.buttons['pause'].state(['!disabled'] if self.running and not self.pause_requested else ['disabled'])
        self.buttons['resume'].state(['!disabled'] if meta and meta['status'] in ('queued','paused') and not blocked and not self.running and not self.owner.busy else ['disabled'])
        self.buttons['stop'].state(['!disabled'] if meta and meta['status'] not in ('stopped','completed') and not self.stop_requested else ['disabled'])
        self.options_menu.entryconfigure(0,state='disabled' if self.owner.busy or self.running else 'normal')
        self.options_menu.entryconfigure(1,state='normal' if self.job is not None else 'disabled')
        if self._preview and self._preview.winfo_exists():self.fill_preview()

    def preview(self):
        if self.job is None:return
        if self._preview and self._preview.winfo_exists():self._preview.lift();return self._preview
        from app.ui.desktop import table
        win=tk.Toplevel(self.owner.root);win.title('Προεπισκόπηση ουράς · χωρίς ενέργεια στο EBS');win.geometry('1100x540')
        ttk.Label(win,text='Ακριβή δεδομένα ουράς. Η προσομοίωση δεν πατά Save και δεν αποθηκεύει στο EBS.',style='Subtitle.TLabel').pack(anchor='w',padx=16,pady=12)
        self.preview_tree=table(win,('invoice','name','vat','date','account','net','state','reason'),('Παραστατικό','Επωνυμία','ΑΦΜ','Ημερομηνία','Λογαριασμός','Καθαρή','Κατάσταση','Αιτία'),{'name':220,'reason':250})
        self._preview=win;self.fill_preview();return win

    def fill_preview(self):
        self.preview_tree.delete(*self.preview_tree.get_children())
        for item in self.rpa.items(self.owner.company,self.job)[1]:
            p=item['payload'];self.preview_tree.insert('','end',iid=str(item['id']),values=tuple(p[k] for k in ('invoice','name','vat','date','account','net'))+(LABELS.get(item['status'],item['status']),item['reason']))

    def accounts(self):
        if self.owner.busy or self.running:return
        if getattr(self,'_accounts',None) and self._accounts.winfo_exists():self._accounts.lift();return self._accounts
        chosen=self.owner.tree.selection()
        ids=[int(x) for x in chosen] if chosen else list(self.owner._documents)
        if not ids:messagebox.showinfo('Excel','Φόρτωσε πρώτα το Excel.',parent=self.owner.root);return
        rows=[self.owner._documents[x] for x in ids if self.owner._documents[x]['direction']=='incoming' and self.owner._documents[x]['kind']=='invoice' and (not self.owner._documents[x]['invoice_type'] or self.owner._documents[x]['rpa_allowed'])]
        if not rows:messagebox.showinfo('Έξοδα','Τα εκδοθέντα δεν καταχωρούνται στη ροή εξόδων EBS.',parent=self.owner.root);return
        ids=[r['id'] for r in rows]
        win=tk.Toplevel(self.owner.root);win.title('Έλεγχος λογαριασμών · '+str(len(ids))+' παραστατικά');win.geometry('900x630');win.minsize(780,520)
        win.transient(self.owner.root);win.grab_set()
        body=ttk.Frame(win,padding=18);body.pack(fill='both',expand=True)
        ttk.Label(body,text=f'{len(ids)} παραστατικά · Έλεγχος λογαριασμών',style='Section.TLabel').pack(anchor='w')
        ttk.Label(body,text='Μία γραμμή ανά προμηθευτή: επίλεξε Αγορές ή Έξοδα και γράψε τον λογαριασμό. Η έγκριση αφορά μόνο τα παραστατικά που επέλεξες στη λίστα.',style='Subtitle.TLabel',wraplength=820).pack(anchor='w',pady=(6,12))
        forms={}
        frame=ttk.Frame(body);frame.pack(fill='both',expand=True,pady=14)
        canvas=tk.Canvas(frame,highlightthickness=0,background='#f3f6fc');scroll=ttk.Scrollbar(frame,command=canvas.yview)
        inner=ttk.Frame(canvas);item=canvas.create_window((0,0),window=inner,anchor='nw')
        canvas.configure(yscrollcommand=scroll.set);canvas.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
        inner.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')));canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
        suppliers={}
        for row in rows:suppliers.setdefault(row['vat'],[]).append(row)
        for column,label in enumerate(('Προμηθευτής','Ομάδα','Λογαριασμός EBS')):ttk.Label(inner,text=label).grid(row=0,column=column,sticky='w',padx=8,pady=6)
        for index,(vat,documents) in enumerate(suppliers.items(),1):
            approved={r['account_code'] for r in documents if r.get('account_code')}
            if not approved:approved={r['suggested_account'] for r in documents if r.get('suggested_account')}
            account=next(iter(approved)) if len(approved)==1 else ''
            g=tk.StringVar(value=('2 · Αγορές' if account.startswith('2') else '6 · Έξοδα'));a=tk.StringVar(value=account);forms[vat]=(g,a)
            ttk.Label(inner,text=f"{documents[0]['name']}\nΑΦΜ {vat} · {len(documents)} εγγραφές",wraplength=330).grid(row=index,column=0,sticky='w',padx=8,pady=10)
            ttk.Combobox(inner,textvariable=g,values=('2 · Αγορές','6 · Έξοδα'),state='readonly',width=16).grid(row=index,column=1,padx=8)
            ttk.Entry(inner,textvariable=a,width=25).grid(row=index,column=2,padx=8)
        remember=tk.BooleanVar(value=False)
        ttk.Checkbutton(body,text='Να θυμάται τον λογαριασμό στην καρτέλα του προμηθευτή για τα επόμενα παραστατικά',variable=remember).pack(anchor='w')
        bottom=ttk.Frame(body);bottom.pack(fill='x',pady=(12,0))
        def approve():
            decisions=[dict(document=r['id'],group=forms[r['vat']][0].get()[0],account=forms[r['vat']][1].get()) for r in rows]
            if not messagebox.askyesno('Έγκριση λογαριασμών',f'Έλεγξες ομάδα και λογαριασμό για τα {len(rows)} παραστατικά; Θα εγκριθούν μαζί. Δεν γίνεται ακόμη καταχώριση.',parent=win):return
            try:self.workspace.approve_many(self.owner.company,decisions,confirmed=True,remember=remember.get())
            except (ValueError,RuntimeError) as exc:messagebox.showerror('Έλεγχος',str(exc),parent=win);return
            win.destroy();self.owner.refresh();self.state.set(f'Εγκρίθηκαν {len(rows)} παραστατικά. Συνέχισε με δοκιμή ή καταχώριση στο EBS.')
        ttk.Button(bottom,text='Έγκριση λογαριασμών',style='Primary.TButton',command=approve).pack(side='right')
        self._accounts=win
        return win

    def settings(self):
        if self.owner.busy or self.running:return
        existing=getattr(self,'_settings',None)
        if existing is not None and existing.winfo_exists():existing.deiconify();existing.lift();return existing
        win=tk.Toplevel(self.owner.root);self._settings=win
        win.title('Ρυθμίσεις EBS · Mapping οθόνης');win.geometry('820x700')
        body=ttk.Frame(win,padding=20);body.pack(fill='both',expand=True)
        saved=self.workspace.profile(self.owner.company);profile=saved['profile'] if saved else {'mapping':{},'save':None,'new':None}
        company=self.owner.company;capture_timer=None
        labels={'AFM_CREDITOR':'ΑΦΜ πιστωτή','INVOICE_REFERENCE':'Αριθμός παραστατικού','INVOICE_DATE':'Ημερομηνία · πρώτο ψηφίο','EXPENSE_ACCOUNT_GRID_CELL':'Κελί λογαριασμού εξόδων','NET_AMOUNT_GRID_CELL':'Κελί καθαρής αξίας','save':'Save','new':'Νέο ΤΕΔ'}
        positions={key:tk.StringVar() for key in labels}
        status=tk.StringVar()
        def describe():
            for key,var in positions.items():
                point=profile.get(key) if key in ('save','new') else profile['mapping'].get(key)
                var.set(f'{point[0]}, {point[1]}' if point is not None else 'Δεν ορίστηκε')
            status.set('Οι αλλαγές εφαρμόζονται με «Αποθήκευση ρυθμίσεων». Νέες θέσεις απαιτούν νέο πιλοτικό έλεγχο.')
        ttk.Label(body,text='Mapping πεδίων στην οθόνη σου',style='Section.TLabel').pack(anchor='w')
        ttk.Label(body,text='Άνοιξε κενό ΤΕΔ στην οθόνη όπου θα δουλεύεις. Πάτησε «Καταγραφή» και τοποθέτησε το ποντίκι στο αντίστοιχο πεδίο μέσα σε 3 δευτερόλεπτα. Δεν γίνεται κλικ ή πληκτρολόγηση. Μετά μην αλλάξεις θέση, μέγεθος ή κλιμάκωση του EBS.',wraplength=750,style='Subtitle.TLabel').pack(anchor='w',pady=10)
        def mapper():
            filename=filedialog.askopenfilename(parent=win,filetypes=[('CSV mapper','*.csv')])
            if not filename:return
            try:profile['mapping']=load_mapper(filename);describe()
            except (ValueError,OSError) as exc:messagebox.showerror('Mapper',str(exc),parent=win)
        ttk.Button(body,text='Φόρτωση υπάρχοντος CSV mapper',command=mapper).pack(anchor='w',pady=8)
        def capture(key):
            nonlocal capture_timer
            if capture_timer is not None:return
            if sys.platform!='win32':messagebox.showinfo('Windows','Η καταγραφή θέσεων γίνεται στον υπολογιστή με Entersoft.',parent=win);return
            from app.infrastructure.ebs_adapter.session import WindowsSession
            try:backend=WindowsSession()
            except RuntimeError as exc:messagebox.showerror('Adapter',str(exc),parent=win);return
            messagebox.showinfo('Καταγραφή θέσης','Μετά το ΟΚ βάλε το ποντίκι πάνω στο πεδίο «'+labels[key]+'» του Entersoft. Σε 3 δευτερόλεπτα καταγράφεται χωρίς κλικ.',parent=win)
            win.withdraw();self.owner.root.withdraw()
            def finish():
                nonlocal capture_timer
                capture_timer=None
                error=None
                try:
                    point=tuple(backend.pg.position())
                    if key in ('save','new'):backend.at_ebs(point);profile[key]=point
                    else:
                        backend.validate_target(key,point)
                        profile['mapping'][key]=point
                    describe()
                except Exception as exc:error=str(exc)
                finally:self.owner.root.deiconify();win.deiconify()
                if error:messagebox.showerror('Θέση EBS',error,parent=win)
            capture_timer=self.owner.root.after(3000,finish)
        grid=ttk.Frame(body);grid.pack(fill='x',pady=8);grid.columnconfigure(0,weight=1)
        for row,key in enumerate(labels):
            ttk.Label(grid,text=labels[key]).grid(row=row,column=0,sticky='w',pady=5)
            ttk.Label(grid,textvariable=positions[key],width=20).grid(row=row,column=1,sticky='w',padx=12)
            ttk.Button(grid,text='Καταγραφή '+labels[key],command=lambda key=key:capture(key)).grid(row=row,column=2,sticky='ew',pady=5)
        ttk.Label(body,textvariable=status,style='Subtitle.TLabel',justify='left').pack(anchor='w',pady=12);describe()
        def close():
            nonlocal capture_timer
            if capture_timer is not None:self.owner.root.after_cancel(capture_timer);capture_timer=None;self.owner.root.deiconify()
            win.destroy()
        win.protocol('WM_DELETE_WINDOW',close)
        def save():
            if self.owner.company!=company:messagebox.showerror('Ρυθμίσεις','Άλλαξε η ενεργή εταιρεία. Κλείσε και άνοιξε ξανά τις ρυθμίσεις EBS.',parent=win);return
            try:self.workspace.save_profile(company,profile)
            except ValueError as exc:messagebox.showerror('Ρυθμίσεις',str(exc),parent=win);return
            win.destroy();self.state.set('Οι θέσεις αποθηκεύτηκαν. Επόμενο: δοκιμή μίας εγγραφής και έλεγχος στο EBS.')
        ttk.Button(body,text='Εγκατάσταση RPA adapter · Ρυθμίσεις',command=self.owner.open_settings).pack(anchor='w',pady=8)
        ttk.Button(body,text='Αποθήκευση ρυθμίσεων',style='Primary.TButton',command=save).pack(side='bottom',anchor='e')
        return win

    def make(self,mode,pilot=False):
        if self.owner.busy or self.running:return
        self._notice=''
        try:
            ids=self.ids()
            if pilot:
                selected=self.owner.tree.selection()
                if not selected:raise ValueError('Επίλεξε ένα παραστατικό για πιλοτική καταχώριση')
                ids=[int(selected[0])]
            if not ids:raise ValueError('Δεν υπάρχουν εγγραφές. Φόρτωσε πρώτα Excel.')
            from app.application.ebs_reconciliation import EBSReconciliation
            matches=EBSReconciliation(self.owner.erp).results(self.owner.company)
            excluded_registered=sum(matches[d]['status']=='registered' for d in ids)
            excluded_review=sum(matches[d]['status'] not in ('registered','not_registered') for d in ids)
            ids=[d for d in ids if matches[d]['status']=='not_registered']
            if not ids:
                self.owner.notebook.select(self.owner.reconciliation_tab)
                raise ValueError('Δεν υπάρχουν επιβεβαιωμένα μη καταχωρισμένα στην επιλογή. Κάνε «Συμφωνία EBS» με πλήρη κατάλογο για τον μήνα. Καταχωρισμένα και αμφίβολα εξαιρούνται.')
            scope=self.rpa.expense_scope(self.owner.company,ids)
            excluded=len(scope['purchases']);issued=len(scope['outgoing'])
            if scope['needs_review'] and not scope['expenses']:
                self.owner.tree.selection_set([str(d) for d in scope['needs_review']])
                self.owner.tree.see(str(scope['needs_review'][0]))
                messagebox.showinfo('Χρειάζονται λογαριασμό',f"{len(scope['needs_review'])} παραστατικά της επιλογής δεν έχουν εγκεκριμένο λογαριασμό. Επιλέχθηκαν στη λίστα.\nΣτο επόμενο παράθυρο όρισε ομάδα και λογαριασμό ανά προμηθευτή και πάτησε «Έγκριση λογαριασμών».\nΟι {excluded} αγορές ομάδας 2 παραμένουν εκτός καταχώρισης.",parent=self.owner.root)
                self.accounts();return
            ids=scope['expenses']
            if not ids:raise ValueError('Δεν υπάρχουν εγκεκριμένα έξοδα ομάδας 6 σε αυτή την επιλογή. Οι αγορές ομάδας 2 παραμένουν στη βάση, εκτός EBS.')
            real=mode=='fill_only'
            if real and sys.platform!='win32':raise ValueError('Η πραγματική καταχώριση απαιτεί Windows με Entersoft. Η προσομοίωση λειτουργεί εδώ.')
            if not messagebox.askyesno('Έναρξη '+('EBS' if real else 'ελέγχου χωρίς καταχώριση'),f'{len(ids)} έξοδα ομάδας 6, με τους εγκεκριμένους λογαριασμούς τους.\n{excluded_registered} καταχωρισμένα και {excluded_review} χωρίς ασφαλή συμφωνία εξαιρέθηκαν.\n{len(scope["needs_review"])} χωρίς έγκριση λογαριασμού εξαιρέθηκαν· τα έτοιμα συνεχίζουν.\n{excluded} αγορές ομάδας 2 εξαιρέθηκαν και παραμένουν στη βάση. {issued} εκδοθέντα και {len(scope["excluded_types"])} μη υποστηριζόμενα είδη είναι εκτός ροής εξόδων.\n'+('Θα εκτελεστεί η ροή συμπλήρωση → Save → νέο ΤΕΔ. Επιβεβαιώνεις κενό ΤΕΔ και πραγματικές καταχωρίσεις;' if real else 'Δεν θα γίνει καμία ενέργεια στο EBS. Συνέχεια;'),parent=self.owner.root):return
            self.job=self.rpa.create(self.owner.company,ids,mode,confirmed=True,execution='save_new' if real else 'fill_only',pilot=pilot,reconciled_only=True)
        except ValueError as exc:messagebox.showwarning('Πριν την έναρξη',str(exc),parent=self.owner.root);return
        if mode=='simulation':self.preview()
        self.start()

    def post(self):self.posting('batch')
    def post_selected(self):self.posting('selected')
    def post_one(self):self.posting('one')
    def pilot(self):self.post_one()

    def posting(self,selection):
        if self.owner.busy or self.running:return
        visible=[int(key) for key in self.owner.tree.get_children()]
        chosen={int(key) for key in self.owner.tree.selection()}
        documents=visible if selection=='batch' else [key for key in visible if key in chosen]
        if not documents or (selection=='one' and len(documents)!=1):
            self.notify('Επίλεξε ακριβώς ένα παραστατικό.' if selection=='one' else 'Επίλεξε γραμμές στον πίνακα· το φίλτρο δεν αποτελεί επιλογή.');return
        if sys.platform!='win32':self.notify('Η πραγματική καταχώριση απαιτεί Windows με Entersoft.',error=True);return
        company=self.owner.company
        self.notify('Προετοιμασία παρτίδας · έλεγχος συμφωνίας και αποθηκευμένων λογαριασμών…')
        def prepare():
            service=ERP(self.owner.directory)
            try:
                try:return RPA(service).posting(company,documents,limit=40 if selection=='batch' else None)
                except (ValueError,RuntimeError) as exc:return dict(error=str(exc))
            finally:service.close()
        def ready(report):
            if self.owner._closing:return
            if report.get('error'):
                # Show the existing live queue that prevents a duplicate start;
                # do not reset/recover it or silently create a replacement.
                active=self.owner.erp.db.execute("SELECT id FROM rpa_jobs WHERE company_id=? AND mode='fill_only' AND status IN ('queued','paused','running') ORDER BY id DESC LIMIT 1",(company,)).fetchone()
                if active:self.job=active['id']
                self.notify(report['error'],error=True);return
            if report['job'] is None:
                self.notify(f"Καμία κατάλληλη εγγραφή · {len(report['skipped'])} παραλείψεις. "+(report['skipped'][0]['reason'] if report['skipped'] else ''),error=True);return
            self.job=report['job'];self.start()
        self.owner.run_worker(prepare,ready)

    def simulate(self):self.make('simulation')
    def queue_selected(self):
        self.scope.set('Μόνο επιλεγμένες')
        try:
            scope=self.rpa.expense_scope(self.owner.company,self.ids())
            if scope['needs_review']:raise ValueError('Υπάρχουν αταξινόμητες ή μη εγκεκριμένες εγγραφές')
            self.job=self.rpa.create(self.owner.company,scope['expenses'],confirmed=True,reconciled_only=True)
        except ValueError as exc:messagebox.showwarning('Έλεγχος',str(exc),parent=self.owner.root)
        self.refresh()

    def start(self):
        if self.owner.busy or self.running or self.job is None:return
        meta,items=self.rpa.items(self.owner.company,self.job)
        if meta['status'] in ('stopped','completed'):
            self.notify('Η συγκεκριμένη ουρά έχει κλείσει. Η καταχώριση της τρέχουσας λίστας γίνεται από τα κύρια κουμπιά.');return
        if any(i['status'] in ('started','save_pending','uncertain','filled_no_save') for i in items):
            self.notify('Χρειάζεται έλεγχος στο EBS προηγούμενης προσπάθειας από το Ιστορικό. Δεν επαναλαμβάνεται αυτόματα.',error=True);return
        self._notice=''
        self.pause_requested=False;self.stop_requested=False;self.running=True
        self.refresh();self.next_item(continuing=True)

    def next_item(self,continuing=False):
        self._next_after=None
        if self.owner._closing or not self.running:return
        if self.stop_requested:self.rpa.stop(self.owner.company,self.job);self.running=False;self.owner.root.deiconify();self.refresh();return
        if self.pause_requested:self.rpa.pause(self.owner.company,self.job);self.running=False;self.owner.root.deiconify();self.refresh();return
        if self.job is None:return
        if self.owner.busy:self._next_after=self.owner.root.after(150,self.next_item);return
        job=self.job;meta,_=self.rpa.items(self.owner.company,job)
        if meta['mode']=='fill_only':self.owner.root.withdraw()
        def execute():
            service=ERP(self.owner.directory)
            try:
                try:return RPA(service).advance(self.owner.company,job,live_confirmed=True,continue_after_pause=continuing)
                except Exception as exc:
                    expected=isinstance(exc,(ValueError,RuntimeError))
                    if not expected:
                        from app.infrastructure.crashlog import record
                        record(self.owner.directory,exc,'rpa_worker')
                        RPA(service).recover(self.owner.company)
                    reason=str(exc) if expected else 'Σφάλμα εκτέλεσης · η πρόοδος διατηρήθηκε. Έλεγξε το EBS και τα διαγνωστικά πριν συνέχεια.'
                    RPA(service).blocked(self.owner.company,job,reason)
                    return dict(status='blocked',reason=reason)
            finally:service.close()
        def done(result):
            if self.owner._closing:return
            self.owner.refresh();self.refresh()
            if result.get('reason'):self.state.set(result['reason'])
            if result['status']=='running' and not self.stop_requested and not self.pause_requested:self._next_after=self.owner.root.after(350,self.next_item)
            else:
                if self.stop_requested:self.rpa.stop(self.owner.company,job)
                elif self.pause_requested:self.rpa.pause(self.owner.company,job)
                self.running=False;self.owner.root.deiconify();self.refresh()
                if result['status']=='blocked' or result.get('item_status')=='uncertain':
                    self.notify(result.get('reason') or 'Έλεγξε το EBS και το ιστορικό πριν συνέχεια.',error=True)
        def dispatch():
            self._next_after=None
            if self.running and not self.owner._closing:self.owner.run_worker(execute,done)
        if meta['mode']=='fill_only':
            # Match the original Agent: let the window hide and EBS regain focus
            # before its worker inspects coordinates or native child windows.
            self._next_after=self.owner.root.after(850,dispatch)
        else:dispatch()

    def cancel_next(self):
        if self._next_after is not None:self.owner.root.after_cancel(self._next_after);self._next_after=None

    def pause(self):
        self._notice=''
        self.cancel_next();self.pause_requested=True
        if not self.owner.busy and self.job is not None:self.rpa.pause(self.owner.company,self.job);self.running=False;self.owner.root.deiconify()
        self.refresh()
        if self.running:self.state.set(self.state.get()+' · Παύση μετά την τρέχουσα εγγραφή')
    def stop(self):
        self._notice=''
        self.cancel_next();self.stop_requested=True
        if not self.owner.busy and self.job is not None:self.rpa.stop(self.owner.company,self.job);self.running=False;self.owner.root.deiconify()
        self.refresh()
        if self.running:self.state.set(self.state.get()+' · Διακοπή μετά την τρέχουσα εγγραφή')

    def history(self):
        win=tk.Toplevel(self.owner.root);win.title('Ιστορικό EBS · έλεγχος και συνέχεια');win.geometry('1000x600')
        frame=ttk.Frame(win,padding=16);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Save / νέο ΤΕΔ δεν αποτελούν αυτόματη επιβεβαίωση αποθήκευσης στη βάση EBS.',style='Subtitle.TLabel').pack(anchor='w',pady=8)
        from app.ui.desktop import table
        tree=table(frame,('job','invoice','vat','account','state','reason'),('Ουρά','Παραστατικό','ΑΦΜ','Λογαριασμός','Ενέργεια / αποτέλεσμα','Αιτία'),{'state':260,'reason':300})
        rows=self.owner.erp.db.execute('SELECT i.*,j.mode,j.status AS job_state FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? ORDER BY i.id DESC',(self.owner.company,)).fetchall()
        import json
        for row in rows:
            p=json.loads(row['payload']);tree.insert('','end',iid=str(row['id']),values=(row['job_id'],p['invoice'],p['vat'],p.get('account',''),'Μη εκτελεσμένο · παλιότερη ουρά' if row['status']=='queued' and row['job_state']=='stopped' else LABELS.get(row['status'],row['status']),row['reason']))
        bottom=ttk.Frame(frame);bottom.pack(fill='x',pady=10)
        def review(pilot=False):
            if self.owner.busy or self.running:
                messagebox.showwarning('Παύση πρώτα','Παύσε την εκτέλεση πριν επιβεβαιώσεις προηγούμενη προσπάθεια.',parent=win);return
            selected=tree.selection()
            if not selected:return
            item=int(selected[0]);row=next(r for r in rows if r['id']==item)
            stored=messagebox.askyesno('Οπτική επιβεβαίωση στο EBS','Επιβεβαιώνεις ότι το συγκεκριμένο παραστατικό υπάρχει αποθηκευμένο στο EBS με σωστό λογαριασμό και ποσά; Ναι = επιβεβαίωση αποθήκευσης, Όχι = μόνο σημείωση ελέγχου.',parent=win)
            if pilot and not stored:return
            note=simpledialog.askstring('Έλεγχος στο EBS','Σημείωση οπτικού ελέγχου (π.χ. αριθμός εγγραφής EBS):',parent=win)
            if not note:return
            try:
                if pilot:self.workspace.confirm_pilot(self.owner.company,item,note,confirmed=True)
                else:self.rpa.reviewed(self.owner.company,row['job_id'],item,note,confirmed=True,stored_in_ebs=stored)
            except ValueError as exc:messagebox.showerror('Έλεγχος',str(exc),parent=win);return
            win.destroy();self.owner.refresh();self.state.set('Ο χειροκίνητος έλεγχος καταγράφηκε. Η πιλοτική επιβεβαίωση επιτρέπει μαζική εκτέλεση.' if pilot else 'Καταγράφηκε ο έλεγχος στο EBS.')
        ttk.Button(bottom,text='Επιβεβαίωση πιλοτικού — ενεργοποίηση batch',command=lambda:review(True)).pack(side='left')
        ttk.Button(bottom,text='Χειροκίνητος έλεγχος προσπάθειας',command=review).pack(side='left',padx=8)
        def select():
            if self.owner.busy or self.running:
                messagebox.showwarning('Παύση πρώτα','Παύσε την εκτέλεση πριν επιλέξεις άλλη ουρά.',parent=win);return
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
