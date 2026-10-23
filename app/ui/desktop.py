"""Greek document preparation workspace. No EBS writes or accounting posting."""
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
import queue
import sqlite3
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from app.application.service import ERP
from app.infrastructure.importers.excel import preview, NAMES
from app.ui.theme import apply, WHITE, MUTED

LABELS = {'vat':'ΑΦΜ', 'name':'Επωνυμία', 'date':'Ημερομηνία', 'invoice':'Ενιαίος αριθμός',
          'series':'Σειρά', 'number':'Αριθμός', 'net':'Καθαρή', 'tax':'ΦΠΑ', 'gross':'Σύνολο',
          'mark':'MARK', 'kind':'Είδος', 'description':'Περιγραφή', 'currency':'Νόμισμα'}
GROUPS = {'Όλες οι ομάδες':None,'Ομάδα 2 · Αγορές':'2','Ομάδα 6 · Έξοδα':'6'}
STATES = ('Όλα τα παραστατικά','Χωρίς προετοιμασία','Με τοπική έγκριση')
ACTIONS = {'document_imported':'Εισαγωγή παραστατικού','import_duplicate':'Παράλειψη διπλοτύπου',
           'import_conflict':'Σύγκρουση εισαγωγής','document_prepared':'Τοπική έγκριση προετοιμασίας',
           'import_warning':'Προειδοποίηση εισαγωγής','amounts_rounded':'Στρογγυλοποίηση ποσών', 'pdf_linked':'Σύνδεση PDF','counterparty_named':'Συμπλήρωση επωνυμίας'}


def amount(value):
    return f'{Decimal(value)/100:,.2f}'.replace(',','_').replace('.',',').replace('_','.')


def when(value):
    try:
        return date.fromisoformat(value).strftime('%d/%m/%Y')
    except (TypeError,ValueError):
        return str(value or '')


def reference(row):
    return '/'.join(str(row[k]) for k in ('series','number') if row.get(k))


def table(parent, columns, titles, widths=None, height=12):
    frame = ttk.Frame(parent,style='Card.TFrame')
    frame.pack(fill='both',expand=True)
    tree = ttk.Treeview(frame,columns=columns,show='headings',height=height,selectmode='browse')
    for key,title in zip(columns,titles):
        width = (widths or {}).get(key,120)
        tree.heading(key,text=title)
        tree.column(key,width=width,minwidth=65,stretch=True,anchor='e' if key in ('gross_minor','net','tax','gross','inserted','duplicates','rejected','warnings') else 'w')
    vertical = ttk.Scrollbar(frame,orient='vertical',command=tree.yview)
    horizontal = ttk.Scrollbar(frame,orient='horizontal',command=tree.xview)
    tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
    tree.grid(row=0,column=0,sticky='nsew')
    vertical.grid(row=0,column=1,sticky='ns')
    horizontal.grid(row=1,column=0,sticky='ew')
    frame.columnconfigure(0,weight=1)
    frame.rowconfigure(0,weight=1)
    tree.tag_configure('alternate',background='#f7f9fd')
    return tree


def read_text(parent, body):
    frame = ttk.Frame(parent,padding=12)
    frame.pack(fill='both',expand=True)
    text = tk.Text(frame,wrap='word',relief='flat',padx=12,pady=12,font='TkTextFont')
    scroll = ttk.Scrollbar(frame,command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right',fill='y')
    text.pack(fill='both',expand=True)
    text.insert('end',body)
    text.configure(state='disabled')
    return text


class Desktop:
    def __init__(self, root, directory):
        self.root, self.directory = root, Path(directory)
        self.style = apply(root)
        from app.ui.text_editing import install
        install(root)
        self.erp = ERP(directory)
        company = self.erp.db.execute('SELECT id,name FROM companies ORDER BY id').fetchone()
        if company is None:
            vat = simpledialog.askstring('Εταιρεία','ΑΦΜ εταιρείας (9 ψηφία):',parent=root)
            name = simpledialog.askstring('Εταιρεία','Επωνυμία εταιρείας:',parent=root) if vat else None
            if not vat or not name:
                self.erp.close(); root.destroy(); return
            try:
                company_id = self.erp.company(vat,name)
            except ValueError as exc:
                messagebox.showerror('Εταιρεία',str(exc),parent=root)
                self.erp.close(); root.destroy(); return
            company = {'id':company_id,'name':name}
        self.company = company['id']
        self.work = queue.Queue()
        self.busy = False
        self._closing = False
        self.preview_window = None
        self._documents = {}
        self._jobs = {}
        self._details = {}
        self._sort = ('source_record_id',False)
        self.status = tk.StringVar(value='')
        root.title('Mini ERP · Προετοιμασία παραστατικών για EBS')
        root.geometry(f'{min(1320,root.winfo_screenwidth()-40)}x{min(880,root.winfo_screenheight()-40)}')
        root.minsize(960,650)
        try:
            root.state('zoomed')
        except tk.TclError:
            pass
        header = ttk.Frame(root,padding=(24,20,24,12))
        header.pack(fill='x')
        self.import_button = ttk.Button(header,text='+  Εισαγωγή Excel',style='Primary.TButton',command=self.choose_excel)
        self.import_button.pack(side='right',padx=(8,0))
        ttk.Button(header,text='Ρυθμίσεις',command=self.open_settings).pack(side='right',padx=6)
        ttk.Button(header,text='ΑΑΔΕ / myDATA',command=self.open_aade).pack(side='right')
        ttk.Button(header,text='Αντισυμβαλλόμενοι',command=self.open_counterparties).pack(side='right',padx=8)
        ttk.Label(header,text='Mini ERP',style='Title.TLabel').pack(anchor='w')
        self.company_caption=tk.StringVar(value=f"{company['name']}  ·  Προετοιμασία παραστατικών για EBS")
        ttk.Label(header,textvariable=self.company_caption,style='Subtitle.TLabel').pack(anchor='w',pady=(3,0))
        metrics=ttk.Frame(root,padding=(24,0,24,10));metrics.pack(fill='x')
        self.metrics={}
        for key,label in [('total','Παραστατικά'),('pending','Έξοδα / διαχωρισμός για έλεγχο'),('issues','Έλεγχοι εισαγωγής')]:
            var=tk.StringVar(value='0');self.metrics[key]=var
            ttk.Label(metrics,text=label+':',style='Subtitle.TLabel').pack(side='left',padx=(0,5))
            ttk.Label(metrics,textvariable=var).pack(side='left',padx=(0,24))
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill='both',expand=True,padx=24)
        self.documents_tab = ttk.Frame(self.notebook,padding=14)
        self.reviews_tab = ttk.Frame(self.notebook,padding=14)
        self.notebook.add(self.documents_tab,text='Παραστατικά → EBS')
        self.notebook.add(self.reviews_tab,text='Έλεγχοι εισαγωγής')
        filters = ttk.Frame(self.documents_tab)
        filters.pack(fill='x',pady=(0,12))
        ttk.Label(filters,text='Αναζήτηση ΑΦΜ, επωνυμίας, παραστατικού ή MARK',style='Subtitle.TLabel').pack(anchor='w',pady=(0,5))
        search_bar = ttk.Frame(filters)
        search_bar.pack(fill='x')
        self.query = tk.StringVar()
        entry = ttk.Entry(search_bar,textvariable=self.query)
        entry.pack(side='left',fill='x',expand=True,padx=(0,8))
        entry.bind('<Return>',lambda _:self.refresh())
        ttk.Button(search_bar,text='Αναζήτηση',command=self.refresh).pack(side='left',padx=(0,6))
        ttk.Button(search_bar,text='Καθαρισμός',command=self.reset_filters).pack(side='left')
        filter_bar = ttk.Frame(filters)
        filter_bar.pack(fill='x',pady=(8,0))
        self.state_filter = tk.StringVar(value=STATES[0])
        self.group_filter = tk.StringVar(value='Όλες οι ομάδες')
        for var,options in ((self.state_filter,STATES),(self.group_filter,tuple(GROUPS))):
            box = ttk.Combobox(filter_bar,textvariable=var,values=options,state='readonly',width=25)
            box.pack(side='left',padx=(0,8))
            box.bind('<<ComboboxSelected>>',lambda _:self.refresh())
        self.result_count = tk.StringVar()
        ttk.Label(self.documents_tab,textvariable=self.result_count,style='Subtitle.TLabel').pack(anchor='w',pady=(0,8))
        columns = ('reference','name','vat','issue_date','gross_minor','account_code','preparation_state','aade_state','pdf_state','ebs_state')
        titles = ('Παραστατικό','Επωνυμία','ΑΦΜ','Ημερομηνία','Σύνολο €','Λογαριασμός','Έλεγχος','ΑΑΔΕ','PDF','EBS')
        self.tree = table(self.documents_tab,columns,titles,{'name':190,'reference':100,'vat':95,'issue_date':90,'gross_minor':85,'account_code':120,'preparation_state':120,'aade_state':90,'pdf_state':70,'ebs_state':170})
        self.tree.configure(selectmode='extended')
        for col in columns:
            self.tree.heading(col,command=lambda key=col:self.sort_documents(key))
        self.tree.bind('<Double-1>',lambda _:self.open_detail())
        self.tree.bind('<Return>',lambda _:self.open_detail())
        actions = ttk.Frame(self.documents_tab)
        actions.pack(side='bottom',fill='x',pady=(12,0))
        self.tree.master.pack_forget()
        self.tree.master.pack(fill='both',expand=True)
        ttk.Label(actions,text='Διπλό κλικ ή Enter για στοιχεία και έλεγχο.',style='Subtitle.TLabel').pack(side='left')
        ttk.Button(actions,text='Στοιχεία & προετοιμασία',command=self.open_detail).pack(side='right')
        ttk.Label(self.reviews_tab,text='Ιστορικό εισαγωγών και εξαιρέσεις',style='Section.TLabel').pack(anchor='w')
        ttk.Label(self.reviews_tab,text='Οι αναφορές διατηρούνται μετά το κλείσιμο της εφαρμογής. Διπλό κλικ για αναλυτικό έλεγχο.',style='Subtitle.TLabel').pack(anchor='w',pady=(4,12))
        self.review_tree = table(self.reviews_tab,('created_at','filename','inserted','duplicates','rejected','warnings'),
                                 ('Χρόνος εισαγωγής','Αρχείο','Νέα','Διπλότυπα','Εξαιρέσεις','Προειδοποιήσεις'),{'filename':300})
        self.review_tree.bind('<Double-1>',lambda _:self.open_review())
        ttk.Button(self.reviews_tab,text='Προβολή αναφοράς',command=self.open_review).pack(side='bottom',anchor='e',pady=(12,0))
        self.review_tree.master.pack_forget()
        self.review_tree.master.pack(fill='both',expand=True)
        self.rpa_tab=ttk.Frame(self.documents_tab)
        self.rpa_tab.pack(side='bottom',fill='x',pady=(8,0))
        self.tree.master.pack_forget()
        self.tree.master.pack(fill='both',expand=True)
        from app.ui.rpa_panel import RPAPanel
        self.rpa_panel=RPAPanel(self,self.rpa_tab,table)
        footer = ttk.Frame(root,padding=(24,12,24,12))
        footer.pack(side='bottom',fill='x')
        self.notebook.pack_forget()
        self.notebook.pack(fill='both',expand=True,padx=24)
        self.progress = ttk.Progressbar(footer,mode='indeterminate',length=110)
        ttk.Label(footer,textvariable=self.status,style='Subtitle.TLabel').pack(anchor='w')
        ttk.Label(footer,text='Μία εισαγωγή Excel · Έλεγχος λογαριασμών · Καταχώριση EBS · Ctrl+Shift+F9 παύση / F10 συνέχεια / F12 διακοπή',style='Subtitle.TLabel').pack(anchor='w',pady=(3,0))
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.bind('<Control-f>',lambda _:(entry.focus_set(),entry.select_range(0,'end')))
        self.refresh()
        self._poll_after = root.after(80,self.poll)
        from app.application.names import NameRecovery
        if NameRecovery(self.erp).needed(self.company):root.after(120,self.recover_names)

    def _has_preview(self):
        return self.preview_window is not None and self.preview_window.winfo_exists()

    def _sync_import_button(self):
        if self._closing:
            return
        self.import_button.state(['disabled'] if self.busy or self._has_preview() else ['!disabled'])

    def close(self):
        if self._closing:
            return
        if self.busy:
            messagebox.showinfo('Εργασία σε εξέλιξη','Περίμενε να ολοκληρωθεί η τρέχουσα εργασία.',parent=self.root)
            return
        self._dismiss_preview()
        self._closing = True
        self.root.after_cancel(self._poll_after)
        self.erp.close()
        self.root.destroy()

    def run_worker(self, function, callback):
        if self.busy:
            return False
        self.busy = True
        self._sync_import_button()
        self.progress.pack(side='right',padx=(12,0))
        self.progress.start(12)
        self.status.set('Επεξεργασία… Περίμενε να ολοκληρωθεί η εργασία.')
        def work():
            try:
                self.work.put((callback,function(),None))
            except Exception as exc:
                from app.infrastructure.crashlog import record
                record(self.directory,exc,'worker')
                self.work.put((callback,None,str(exc)))
        threading.Thread(target=work,daemon=True).start()
        return True

    def poll(self):
        if self._closing:
            return
        try:
            callback,result,error = self.work.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.progress.stop()
            self.progress.pack_forget()
            if error:
                self.status.set('Η εργασία δεν ολοκληρώθηκε. Δες την αιτία στο μήνυμα· μην επαναλάβεις καταχώριση EBS χωρίς έλεγχο ιστορικού.')
                self.root.deiconify()
                messagebox.showerror('Η εργασία δεν ολοκληρώθηκε',error,parent=self.root)
            else:
                try:callback(result)
                except Exception as exc:
                    from app.infrastructure.crashlog import record
                    record(self.directory,exc,'callback')
                    messagebox.showerror('Η εργασία δεν ολοκληρώθηκε','Αποθηκεύτηκε διαγνωστικό στις Ρυθμίσεις → Υποστήριξη.',parent=self.root)
            self._sync_import_button()
        self._poll_after = self.root.after(80,self.poll)

    def reset_filters(self):
        self.query.set('')
        self.state_filter.set(STATES[0])
        self.group_filter.set('Όλες οι ομάδες')
        self.refresh()

    def sort_documents(self, key):
        self._sort = (key,not self._sort[1] if key==self._sort[0] else False)
        self.refresh()

    def refresh(self):
        identity=self.erp.db.execute('SELECT vat,name FROM companies WHERE id=?',(self.company,)).fetchone()
        self.company_caption.set(identity['name']+' · ΑΦΜ '+identity['vat']+' · Προετοιμασία για EBS')
        for window in list(self._details.values()):
            if window.winfo_exists() and hasattr(window,'refresh_identity'):window.refresh_identity()
            if window.winfo_exists() and hasattr(window,'pdf_pane'):window.pdf_pane.refresh_if_changed()
        selected = self.tree.selection()
        all_rows = self.erp.search(self.company)
        jobs = self.erp.import_reviews(self.company)
        from app.application.workspace import Workspace
        from app.ui.rpa_panel import LABELS as EBS_LABELS
        rows = Workspace(self.erp).rows(self.company,self.query.get().strip())
        wanted_group = GROUPS.get(self.group_filter.get())
        rows = [r for r in rows if (wanted_group is None or (r.get('nature_group') or r.get('suggested_group'))==wanted_group)
                and (self.state_filter.get()!=STATES[1] or not r.get('prepared_at'))
                and (self.state_filter.get()!=STATES[2] or r.get('prepared_at'))]
        for row in rows:
            row['reference'] = reference(row)
            row['ebs_state'] = EBS_LABELS.get(row['ebs_state'],row['ebs_state'])
            row['aade_state'] = {'not_checked':'Δεν ελέγχθηκε','matched':'Συμφωνεί','different':'Διαφορά','cancelled_at_aade':'Αναφορά ακύρωσης'}.get(row['aade_state'],row['aade_state'])
            row['preparation_state'] = 'Εγκεκριμένο' if row.get('prepared_at') else 'Πρόταση καρτέλας' if row.get('suggested_account') else 'Χρειάζεται λογαριασμό'
            if not row.get('prepared_at') and row.get('suggested_account'):
                row['nature_group']=row['suggested_group'];row['account_code']=row['suggested_account']
        key,reverse = self._sort
        rows.sort(key=lambda r:r.get(key) or (0 if key.endswith('_minor') else ''),reverse=reverse)
        self._documents = {r['id']:r for r in rows}
        self.tree.delete(*self.tree.get_children())
        for i,row in enumerate(rows):
            self.tree.insert('','end',iid=str(row['id']),values=[amount(row[k]) if k.endswith('_minor') else when(row[k]) if k=='issue_date' else row.get(k) or '—' for k in self.tree['columns']],tags=('alternate',) if i%2 else ())
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
        self.result_count.set(f'{len(rows)} από {len(all_rows)} παραστατικά')
        self.metrics['total'].set(str(len(all_rows)))
        scope=self.rpa_panel.rpa.expense_scope(self.company,[r['id'] for r in all_rows])
        self.metrics['pending'].set(str(len(scope['needs_review'])))
        self.metrics['issues'].set(str(sum(len(j['report'].get('rejected',[]))+len(j['report'].get('warnings',[])) for j in jobs)))
        self._jobs = {j['id']:j for j in jobs}
        self.review_tree.delete(*self.review_tree.get_children())
        for job in jobs:
            report = job['report']
            self.review_tree.insert('','end',iid=str(job['id']),values=(job['created_at'],job['filename'],report.get('inserted',0),report.get('duplicates',0),len(report.get('rejected',[])),len(report.get('warnings',[]))))
        if not self.busy:
            self.status.set('Τα παραστατικά και οι αναφορές έχουν φορτωθεί από τη βάση.')

    def choose_excel(self):
        if self._has_preview():
            self.preview_window.lift()
            return
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self.root,filetypes=[('Excel','*.xlsx *.xlsm')])
        if path:
            self.run_worker(lambda:preview(path),lambda item:self.show_preview(path,item))

    def _dismiss_preview(self):
        if self._has_preview():
            self.preview_window.destroy()
        self.preview_window = None
        self._sync_import_button()

    def show_preview(self, path, item):
        if self._has_preview():
            self.preview_window.lift()
            return
        win = tk.Toplevel(self.root)
        self.preview_window = win
        win.title('Εισαγωγή Excel · Έλεγχος πριν την αποθήκευση')
        win.geometry('1120x780')
        win.minsize(900,620)
        win.transient(self.root)
        win.grab_set()
        win.protocol('WM_DELETE_WINDOW',self._dismiss_preview)
        win.bind('<Escape>',lambda _:self._dismiss_preview())
        def destroyed(event):
            if event.widget==win:
                self.preview_window = None
                self._sync_import_button()
        win.bind('<Destroy>',destroyed)
        self._sync_import_button()
        header = ttk.Frame(win,padding=18)
        header.pack(fill='x')
        ttk.Label(header,text='Έλεγχος εισαγωγής',style='Section.TLabel').pack(anchor='w')
        ttk.Label(header,text=f'{item.filename}  ·  Φύλλο: {item.sheet}',style='Subtitle.TLabel').pack(anchor='w',pady=4)
        ttk.Label(header,text=f'{len(item.records)} έγκυρες εγγραφές    |    {len(item.rejected)} εξαιρέσεις    |    {sum(bool(r.get("rounding_changes")) for r in item.records)} με στρογγυλοποίηση',style='Section.TLabel').pack(anchor='w')
        pages = ttk.Notebook(win)
        pages.pack(fill='both',expand=True,padx=18)
        valid_tab, mapping_tab, errors_tab = [ttk.Frame(pages,padding=12) for _ in range(3)]
        pages.add(valid_tab,text='Εγγραφές')
        pages.add(mapping_tab,text='Αντιστοίχιση στηλών')
        pages.add(errors_tab,text=f'Εξαιρέσεις ({len(item.rejected)})')
        ttk.Label(valid_tab,text='Έλεγξε ΑΦΜ, σειρά / αριθμό, ημερομηνία και ποσά πριν επιβεβαιώσεις.',style='Subtitle.TLabel').pack(anchor='w',pady=(0,10))
        valid_tree = table(valid_tab,('row','name','vat','reference','date','net','tax','rounding','gross'),('Γραμμή','Επωνυμία','ΑΦΜ','Παραστατικό','Ημερομηνία','Καθαρή €','ΦΠΑ €','Στρογγ. €','Σύνολο €'),{'row':70,'name':220,'reference':160})
        for row in item.records:
            d = row['document']
            valid_tree.insert('','end',values=(row['row'],d['name'],d['vat'],reference(d),when(d['issue_date']),amount(d['net_minor']),amount(d['tax_minor']),amount(d['rounding_minor']),amount(d['gross_minor'])))
        ttk.Label(mapping_tab,text='Άλλαξε μόνο ό,τι χρειάζεται και πάτησε «Επανέλεγχος». Τα πεδία με * είναι απαραίτητα.',style='Subtitle.TLabel',wraplength=850).pack(anchor='w',pady=(0,14))
        mapping_frame = ttk.Frame(mapping_tab)
        mapping_frame.pack(fill='x')
        options = ['—']+[f'{k+1}: {v}' for k,v in sorted(item.headers.items())]
        lookup = {f'{k+1}: {v}':k for k,v in item.headers.items()}
        variables = {}
        for col in range(3):
            mapping_frame.columnconfigure(col,weight=1,uniform='mapping')
        for i,key in enumerate(NAMES):
            col,row = i%3,i//3*2
            label = LABELS.get(key,key)+(' *' if key in ('vat','date','net','tax') else '')
            ttk.Label(mapping_frame,text=label).grid(row=row,column=col,sticky='w',pady=(8,4))
            var = tk.StringVar(value=next((s for s,k in lookup.items() if k==item.mapping.get(key)),'—'))
            variables[key] = var
            ttk.Combobox(mapping_frame,textvariable=var,values=options,state='readonly',width=28).grid(row=row+1,column=col,sticky='ew',padx=(0,10))
        error_tree = table(errors_tab,('row','reason'),('Γραμμή Excel','Αιτία εξαίρεσης'),{'row':100,'reason':780})
        for row in item.rejected:
            error_tree.insert('','end',values=(row['row'],row['reason']))
        bottom = ttk.Frame(win,padding=18)
        bottom.pack(side='bottom',fill='x')
        pages.pack_forget()
        pages.pack(fill='both',expand=True,padx=18)
        ttk.Label(bottom,text='Η επιβεβαίωση αποθηκεύει μόνο στο Mini ERP.',style='Subtitle.TLabel').pack(anchor='w',pady=(0,10))
        ttk.Button(bottom,text='Ακύρωση',command=self._dismiss_preview).pack(side='left')
        def remap():
            if self.busy:
                return
            mapping = {k:lookup[v.get()] for k,v in variables.items() if v.get()!='—'}
            self._dismiss_preview()
            self.run_worker(lambda:preview(path,mapping),lambda new:self.show_preview(path,new))
        ttk.Button(bottom,text='Επανέλεγχος αντιστοίχισης',command=remap).pack(side='left',padx=8)
        def commit():
            if self.busy:
                return
            current = {k:lookup[v.get()] for k,v in variables.items() if v.get()!='—'}
            if current!=item.mapping:
                messagebox.showwarning('Χρειάζεται επανέλεγχος','Άλλαξες την αντιστοίχιση. Πάτησε πρώτα «Επανέλεγχος αντιστοίχισης».',parent=win)
                return
            if not item.records:
                return
            if not messagebox.askyesno('Επιβεβαίωση εισαγωγής',f'Αποθήκευση {len(item.records)} έγκυρων γραμμών στη βάση;\nΟι {len(item.rejected)} εξαιρέσεις θα διατηρηθούν στην αναφορά.\nΔεν γίνεται καταχώριση στο EBS.',parent=win):
                return
            self._dismiss_preview()
            def execute():
                service = ERP(self.directory)
                try:
                    return service.commit_import(self.company,item,confirmed=True)
                finally:
                    service.close()
            def done(report):
                self.refresh()
                self.show_report(item.filename,report)
            self.run_worker(execute,done)
        button = ttk.Button(bottom,text='Επιβεβαιώνω εισαγωγή',style='Primary.TButton',command=commit)
        button.pack(side='right')
        if not item.records:
            button.state(['disabled'])
            pages.select(mapping_tab)

    def show_report(self, filename, report):
        win = tk.Toplevel(self.root)
        win.title('Αναφορά εισαγωγής · '+filename)
        win.geometry('1050x680')
        header = ttk.Frame(win,padding=18)
        header.pack(fill='x')
        ttk.Label(header,text=filename,style='Section.TLabel').pack(anchor='w')
        ttk.Label(header,text=f"Νέα: {report.get('inserted',0)}   ·   Διπλότυπα: {report.get('duplicates',0)}   ·   Εξαιρέσεις: {len(report.get('rejected',[]))}   ·   Προειδοποιήσεις: {len(report.get('warnings',[]))}",style='Subtitle.TLabel').pack(anchor='w',pady=8)
        report_pages = ttk.Notebook(win)
        report_pages.pack(fill='both',expand=True,padx=18,pady=(0,18))
        body = ttk.Frame(report_pages,padding=12)
        raw_page = ttk.Frame(report_pages)
        report_pages.add(body,text='Έλεγχοι')
        report_pages.add(raw_page,text='Αναλυτικά στοιχεία')
        read_text(raw_page,json.dumps(report,ensure_ascii=False,indent=2))
        tree = table(body,('type','row','reason'),('Έλεγχος','Γραμμή','Αιτία / επόμενη ενέργεια'),{'type':130,'row':80,'reason':750})
        for key,label in (('rejected','Εξαίρεση'),('warnings','Προειδοποίηση')):
            for item in report.get(key,[]):
                tree.insert('','end',values=(label,item.get('row',''),item.get('reason','')))
        if not report.get('rejected') and not report.get('warnings'):
            ttk.Label(body,text='Δεν καταγράφηκαν εξαιρέσεις ή προειδοποιήσεις.',style='Subtitle.TLabel').pack(anchor='w',pady=8)

    def open_review(self):
        selection = self.review_tree.selection()
        if selection:
            job = self._jobs[int(selection[0])]
            self.show_report(job['filename'],job['report'])

    def open_detail(self):
        identity=self.erp.db.execute('SELECT vat,name FROM companies WHERE id=?',(self.company,)).fetchone()
        self.company_caption.set(identity['name']+' · ΑΦΜ '+identity['vat']+' · Προετοιμασία για EBS')
        selected = self.tree.selection()
        if not selected:
            return
        document_id = int(selected[0])
        if document_id in self._details and self._details[document_id].winfo_exists():
            self._details[document_id].lift()
            return
        row,events = self.erp.detail(self.company,document_id)
        preparation = self.erp.preparation(self.company,document_id)
        win = tk.Toplevel(self.root)
        self._details[document_id] = win
        def clear_detail(event):
            if event.widget==win:
                self._details.pop(document_id,None)
        win.bind('<Destroy>',clear_detail)
        win.title('Παραστατικό · '+reference(row))
        win.geometry(f'{min(1480,self.root.winfo_screenwidth()-40)}x{min(880,self.root.winfo_screenheight()-40)}')
        win.minsize(960,650)
        header = ttk.Frame(win,padding=18)
        header.pack(fill='x')
        ttk.Label(header,text=reference(row),style='Title.TLabel').pack(anchor='w')
        identity_caption=tk.StringVar(value=f"{row['name']}  ·  ΑΦΜ {row['vat']}  ·  {when(row['issue_date'])}")
        name_caption=tk.StringVar(value=row['name'])
        def refresh_identity():
            current,_=self.erp.detail(self.company,document_id);name_caption.set(current['name']);identity_caption.set(f"{current['name']}  ·  ΑΦΜ {current['vat']}  ·  {when(current['issue_date'])}")
        win.refresh_identity=refresh_identity
        ttk.Label(header,textvariable=identity_caption,style='Subtitle.TLabel').pack(anchor='w',pady=4)
        ttk.Label(header,text=f"Καθαρή {amount(row['net_minor'])} €    +    ΦΠΑ {amount(row['tax_minor'])} €    +    Στρογγ. {amount(row['rounding_minor'])} €    =    Σύνολο {amount(row['gross_minor'])} €",style='Section.TLabel').pack(anchor='w',pady=(8,0))
        split=ttk.Panedwindow(win,orient='horizontal')
        split.pack(fill='both',expand=True,padx=18,pady=(0,18))
        left=ttk.Frame(split,width=640);right=ttk.Frame(split,width=480)
        split.add(left,weight=1);split.add(right,weight=1)
        win.after_idle(lambda:split.sashpos(0,int(split.winfo_width()*.52)) if split.winfo_exists() else None)
        pages = ttk.Notebook(left)
        pages.pack(fill='both',expand=True)
        summary,prepare_tab,source,history = [ttk.Frame(pages,padding=12) for _ in range(4)]
        for page,title in ((summary,'Στοιχεία'),(prepare_tab,'Προετοιμασία EBS'),(source,'Προέλευση'),(history,'Ιστορικό')):
            pages.add(page,text=title)
        from app.application.workspace import Workspace
        from app.ui.rpa_panel import LABELS as EBS_LABELS
        state=next((r['ebs_state'] for r in Workspace(self.erp).rows(self.company) if r['id']==document_id),'not_sent')
        details = [('Επωνυμία',row['name']),('ΑΦΜ',row['vat']),('Αριθμός',row['number']),('Σειρά',row['series'] or '—'),('MARK',row['mark'] or '—'),('Νόμισμα',row['currency']),('Κατάσταση','Τοπικά εγκεκριμένη προετοιμασία' if preparation else 'Χρειάζεται έλεγχο'),('EBS',EBS_LABELS.get(state,state))]
        for i,(label,value) in enumerate(details):
            ttk.Label(summary,text=label,style='Subtitle.TLabel').grid(row=i,column=0,sticky='w',padx=12,pady=12)
            ttk.Label(summary,textvariable=name_caption if label=='Επωνυμία' else None,text='' if label=='Επωνυμία' else value,wraplength=300).grid(row=i,column=1,sticky='w',padx=18,pady=12)
        def card():
            from app.ui.counterparties import open_detail
            return open_detail(self,row['counterparty_id'])
        ttk.Button(summary,text='Καρτέλα αντισυμβαλλομένου',command=card).grid(row=len(details)+1,column=0,columnspan=2,sticky='w',padx=12,pady=8)
        def rename():
            value=simpledialog.askstring('Επωνυμία αντισυμβαλλομένου','Επωνυμία (το ΑΦΜ παραμένει αμετάβλητο):',initialvalue=row['name'],parent=win)
            if not value:return
            if not messagebox.askyesno('Επιβεβαίωση','Η επωνυμία θα ενημερωθεί για αυτόν τον αντισυμβαλλόμενο, με ιστορικό. Συνέχεια;',parent=win):return
            try:self.erp.rename_counterparty(self.company,row['counterparty_id'],value,confirmed=True)
            except ValueError as exc:messagebox.showerror('Επωνυμία',str(exc),parent=win);return
            win.destroy();self.refresh()
        ttk.Button(summary,text='Διόρθωση επωνυμίας',command=rename).grid(row=len(details),column=0,columnspan=2,sticky='w',padx=12,pady=8)
        ttk.Label(prepare_tab,text='Ομάδα και λογαριασμός ανά παραστατικό',style='Section.TLabel').pack(anchor='w')
        ttk.Label(prepare_tab,text='Ο ίδιος αντισυμβαλλόμενος μπορεί να έχει αγορές και έξοδα. Επιβεβαίωσε τη φύση της συγκεκριμένης συναλλαγής και τον λογαριασμό του δικού σου σχεδίου.',style='Subtitle.TLabel',wraplength=520).pack(anchor='w',pady=(6,14))
        from app.application.counterparties import Counterparties
        cp_card,_=Counterparties(self.erp).detail(self.company,row['counterparty_id'])
        cp_defaults=cp_card['accounts']
        choices = {'2 · Αγορές':'2','6 · Έξοδα':'6'}
        group = tk.StringVar(value=next((label for label,value in choices.items() if value==(preparation['nature_group'] if preparation else cp_defaults['preferred_group'])),''))
        account = tk.StringVar(value=preparation['account_code'] if preparation else cp_defaults['purchases_account'] if cp_defaults['preferred_group']=='2' else cp_defaults['expenses_account'] if cp_defaults['preferred_group']=='6' else '')
        note = tk.StringVar(value=preparation['note'] if preparation else '')
        fields = ttk.Frame(prepare_tab)
        fields.pack(fill='x')
        ttk.Label(fields,text='Ομάδα συναλλαγής').grid(row=0,column=0,sticky='w',pady=8)
        group_box=ttk.Combobox(fields,textvariable=group,values=tuple(choices),state='readonly',width=28)
        group_box.grid(row=0,column=1,sticky='ew',padx=16)
        group_box.bind('<<ComboboxSelected>>',lambda _:account.set(cp_defaults['purchases_account'] if choices.get(group.get())=='2' else cp_defaults['expenses_account']))
        ttk.Label(fields,text='Λογαριασμός').grid(row=1,column=0,sticky='w',pady=8)
        ttk.Entry(fields,textvariable=account,width=30).grid(row=1,column=1,sticky='ew',padx=16)
        ttk.Label(fields,text='Σημείωση ελέγχου').grid(row=2,column=0,sticky='w',pady=8)
        ttk.Entry(fields,textvariable=note,width=28).grid(row=2,column=1,sticky='ew',padx=16)
        fields.columnconfigure(1,weight=1)
        approved = tk.BooleanVar(value=False)
        ttk.Checkbutton(prepare_tab,text='Έλεγξα το παραστατικό, την ομάδα και τον λογαριασμό.',variable=approved).pack(anchor='w',pady=18)
        ttk.Label(prepare_tab,text='Η έγκριση αφορά μόνο την τοπική προετοιμασία. Δεν επαληθεύει τον λογαριασμό στο EBS και δεν δημιουργεί λογιστική εγγραφή.',style='Subtitle.TLabel',wraplength=520).pack(anchor='w')
        def save():
            if self.busy:
                messagebox.showinfo('Εργασία σε εξέλιξη','Περίμενε να ολοκληρωθεί η εισαγωγή.',parent=win)
                return
            if not approved.get():
                messagebox.showwarning('Απαιτείται έλεγχος','Επιβεβαίωσε πρώτα ότι έλεγξες τα στοιχεία.',parent=win)
                return
            if not messagebox.askyesno('Τοπική έγκριση',f'Αποθήκευση προετοιμασίας για {reference(row)};\nΟμάδα: {group.get()}\nΛογαριασμός: {account.get().strip()}\nΔεν θα σταλεί τίποτα στο EBS.',parent=win):
                return
            try:
                self.erp.prepare_document(self.company,document_id,choices.get(group.get(),''),account.get().strip(),note=note.get(),confirmed=True)
            except (ValueError,sqlite3.Error) as exc:
                messagebox.showerror('Η προετοιμασία δεν αποθηκεύτηκε',str(exc),parent=win)
                return
            win.destroy()
            self.refresh()
            if self.tree.exists(str(document_id)):
                self.tree.selection_set(str(document_id))
            self.status.set('Η προετοιμασία εγκρίθηκε τοπικά και καταγράφηκε στο ιστορικό. Δεν έγινε αποστολή στο EBS.')
        ttk.Button(prepare_tab,text='Έγκριση τοπικής προετοιμασίας',style='Primary.TButton',command=save).pack(anchor='e',pady=18)
        source_kind='Αρχικά στοιχεία ΑΑΔΕ (αμετάβλητα)' if json.loads(row['raw_json']).get('_source') else 'Αρχική γραμμή Excel (αμετάβλητη)'
        read_text(source,f"Αρχείο: {row['filename']}\nSHA-256: {row['sha256']}\n\n{source_kind}:\n"+json.dumps(json.loads(row['raw_json']),ensure_ascii=False,indent=2))
        timeline = '\n\n'.join(f"{event['created_at']}  ·  {ACTIONS.get(event['action'],event['action'])}\nΧειριστής: {event['actor']}\n{json.dumps(json.loads(event['payload']),ensure_ascii=False,indent=2)}" for event in events)
        read_text(history,timeline or 'Δεν υπάρχουν ενέργειες.')
        from app.ui.pdf_pane import PDFPane
        win.pdf_pane=PDFPane(self,right,document_id,win)

    def open_settings(self,section=None):
        from app.ui.settings import open_settings
        return open_settings(self,section)

    def open_aade(self,document=None):
        from app.ui.aade_dialog import open_settings
        return open_settings(self,document)

    def open_counterparties(self):
        from app.ui.counterparties import open_register
        return open_register(self)

    def recover_names(self):
        if self._closing or self.busy:return
        def execute():
            from app.application.names import NameRecovery
            service=ERP(self.directory)
            try:return NameRecovery(service).run(self.company)
            finally:service.close()
        def done(result):
            self.refresh()
            if result['updated']:self.status.set(f"Συμπληρώθηκαν {result['updated']} επωνυμίες από τα ήδη αποθηκευμένα Excel, χωρίς νέα εισαγωγή.")
        self.run_worker(execute,done)
