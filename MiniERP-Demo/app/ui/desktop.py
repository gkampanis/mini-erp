"""Greek document preparation workspace. No EBS writes or accounting posting."""
import json
from datetime import date,timedelta
from decimal import Decimal
from pathlib import Path
import queue
import sqlite3
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from app.application.service import ERP
from app.infrastructure.importers.excel import preview, NAMES
from app.ui.theme import apply, colors
from app.ui.preferences import UIPreferences,display_column

LABELS = {'vat':'ΑΦΜ', 'name':'Επωνυμία', 'date':'Ημερομηνία', 'invoice':'Ενιαίος αριθμός',
          'series':'Σειρά', 'number':'Αριθμός', 'net':'Καθαρή', 'tax':'ΦΠΑ', 'gross':'Σύνολο',
          'mark':'MARK', 'kind':'Είδος', 'description':'Περιγραφή', 'currency':'Νόμισμα'}
GROUPS = {'Όλες οι ομάδες':None,'Ομάδα 2 · Αγορές':'2','Ομάδα 6 · Έξοδα':'6'}
STATES = ('Όλα τα παραστατικά','Χωρίς προετοιμασία','Με τοπική έγκριση','Μη καταχωρισμένα','Χρειάζονται έλεγχο','Δεν βρέθηκαν στο Excel','Χρειάζεται έλεγχος στο EBS')
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


def table(parent, columns, titles, widths=None, height=12, table_key=None):
    from app.ui.table_presentation import find_owner,TablePresentation
    owner=find_owner(parent);toolbar=None
    if owner is not None and table_key:
        toolbar=ttk.Frame(parent);toolbar.pack(fill='x',pady=(0,6))
    frame = ttk.Frame(parent,style='Card.TFrame')
    frame.pack(fill='both',expand=True)
    tree = ttk.Treeview(frame,columns=columns,show='headings',height=height,selectmode='browse')
    for key,title in zip(columns,titles):
        width = (widths or {}).get(key,120)
        tree.heading(key,text=title)
        tree.column(key,width=width,minwidth=65,stretch=True,anchor='e' if key.endswith('_minor') or key in ('net','tax','gross','inserted','duplicates','rejected','warnings','count') else 'w')
    vertical = ttk.Scrollbar(frame,orient='vertical',command=tree.yview)
    horizontal = ttk.Scrollbar(frame,orient='horizontal',command=tree.xview)
    tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
    tree.grid(row=0,column=0,sticky='nsew')
    vertical.grid(row=0,column=1,sticky='ns')
    horizontal.grid(row=1,column=0,sticky='ew')
    frame.columnconfigure(0,weight=1)
    frame.rowconfigure(0,weight=1)
    c=colors(parent)
    tree.tag_configure('alternate',background=c['alternate'])
    tree.tag_configure('difference',background=c['warning_bg'],foreground=c['ink'])
    tree.tag_configure('status_review',foreground=c['warning']);tree.tag_configure('status_approved',foreground=c['success'])
    if toolbar is not None:tree.presentation=TablePresentation(tree,owner,table_key,toolbar)
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
        self.ui_preferences=UIPreferences(directory)
        root._desktop_owner=self
        self.style = apply(root,self.ui_preferences.theme)
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
        from app import __version__
        root.title('Σύμβολον ERP · Προετοιμασία παραστατικών για EBS · '+__version__)
        root.geometry(f'{min(1320,root.winfo_screenwidth()-40)}x{min(880,root.winfo_screenheight()-40)}')
        root.minsize(960,650)
        try:
            root.state('zoomed')
        except tk.TclError:
            pass
        header = ttk.Frame(root,padding=(16,6,16,4))
        header.pack(fill='x')
        self.acquire_button=ttk.Button(header,text='Άντληση ΑΑΔΕ — εγγραφές',style='Primary.TButton',command=self.open_acquisition)
        self.acquire_button.pack(side='right',padx=(8,0))
        ttk.Button(header,text='Ρυθμίσεις',command=self.open_settings).pack(side='right',padx=6)
        ttk.Button(header,text='ΑΑΔΕ / myDATA',command=self.open_aade).pack(side='right')
        from app.ui.branding import install as install_branding
        install_branding(root,header)
        self.company_caption=tk.StringVar(value=f"{company['name']}  ·  Προετοιμασία παραστατικών για EBS")
        period_bar=ttk.Frame(root,padding=(16,0,16,6));period_bar.pack(fill='x')
        import_bar=period_bar
        self.import_button=ttk.Button(import_bar,text='Εισαγωγή βιβλίου ΑΑΔΕ',command=self.choose_excel)
        self.import_button.pack(side='right')
        self.ebs_import_button=ttk.Button(import_bar,text='Έλεγχος καταχωρημένων EBS',command=lambda:self.choose_excel(purpose='ebs'))
        self.ebs_import_button.pack(side='right',padx=8)
        self.company_choices={f"{r['name']} · {r['vat']}":r['id'] for r in self.erp.db.execute('SELECT id,vat,name FROM companies ORDER BY name')}
        self.company_filter=tk.StringVar(value=next(k for k,v in self.company_choices.items() if v==self.company))
        ttk.Label(period_bar,text='Επιχείρηση:').pack(side='left',padx=(0,6))
        self.company_box=ttk.Combobox(period_bar,textvariable=self.company_filter,values=tuple(self.company_choices),state='readonly',width=22)
        self.company_box.pack(side='left',padx=(0,14));self.company_box.bind('<<ComboboxSelected>>',self.company_changed)
        metrics=ttk.Frame(root,padding=(24,0,24,10))
        self.metrics={}
        for key,label in [('total','Παραστατικά συνολικά'),('pending','Χωρίς έγκριση (περίοδος)'),('issues','Προειδοποιήσεις εισαγωγών')]:
            var=tk.StringVar(value='0');self.metrics[key]=var
            ttk.Label(metrics,text=label+':',style='Subtitle.TLabel').pack(side='left',padx=(0,5))
            ttk.Label(metrics,textvariable=var).pack(side='left',padx=(0,24))
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill='both',expand=True,padx=16)
        self.documents_tab = ttk.Frame(self.notebook,padding=8)
        self.reviews_tab = ttk.Frame(self.notebook,padding=14)
        self.notebook.add(self.documents_tab,text='Μη καταχωρισμένα στο EBS')
        from app.ui.document_views import DocumentView
        self.document_views={}
        for view,title in (('expenses','Έξοδα'),('purchases','Αγορές'),('income','Έσοδα'),('movement','Δελτία Αποστολής')):
            parent=ttk.Frame(self.notebook,padding=14);self.notebook.add(parent,text=title)
            self.document_views[view]=DocumentView(self,parent,view)
        self.notebook.add(self.reviews_tab,text='Έλεγχοι εισαγωγής')
        self.suppliers_tab=ttk.Frame(self.notebook,padding=14)
        self.notebook.add(self.suppliers_tab,text='Προμηθευτές')
        self.creditors_tab=ttk.Frame(self.notebook,padding=14)
        self.notebook.add(self.creditors_tab,text='Πιστωτές')
        self.reconciliation_tab=ttk.Frame(self.notebook,padding=14)
        self.notebook.add(self.reconciliation_tab,text='Συμφωνία')
        filters = ttk.Frame(self.documents_tab)
        filters.pack(fill='x',pady=(0,4))
        search_bar = ttk.Frame(filters)
        search_bar.pack(fill='x')
        self.query = tk.StringVar()
        entry = ttk.Entry(search_bar,textvariable=self.query)
        entry.pack(side='left',fill='x',expand=True,padx=(0,8))
        entry.bind('<Return>',lambda _:self.filter_documents())
        ttk.Button(search_bar,text='Αναζήτηση',command=self.filter_documents).pack(side='left',padx=(0,6))
        ttk.Button(search_bar,text='Καθαρισμός',command=self.reset_filters).pack(side='left')
        filter_bar = ttk.Frame(filters)
        filter_bar.pack(fill='x',pady=(6,0))
        ttk.Label(period_bar,text='Μήνας:').pack(side='left',padx=(0,6))
        from app.application.periods import MONTHS
        previous=date.today().replace(day=1)-timedelta(days=1)
        self.month_filter=tk.StringVar(value=MONTHS[previous.month-1]+' '+str(previous.year))
        self._month_values={}
        self._period_initialized=False
        self.month_box=ttk.Combobox(period_bar,textvariable=self.month_filter,state='readonly',width=18)
        self.month_box.pack(side='left',padx=(0,12))
        self.month_box.bind('<<ComboboxSelected>>',self.month_changed)
        self.state_filter = tk.StringVar(value=STATES[3])
        self.group_filter = tk.StringVar(value='Όλες οι ομάδες')
        for var,options in ((self.state_filter,STATES),(self.group_filter,tuple(GROUPS))):
            box = ttk.Combobox(filter_bar,textvariable=var,values=options,state='readonly',width=25)
            box.pack(side='left',padx=(0,8))
            box.bind('<<ComboboxSelected>>',lambda _:self.filter_documents())
        self.result_count = tk.StringVar()
        from app.ui.pending_reasons import expose_pending_column
        expose_pending_column(self.ui_preferences)
        columns = ('reference','description','name','vat','issue_date','net_minor','tax_minor','gross_minor','display_account_code','preparation_state','pending_reason','aade_state','pdf_state')
        titles = ('Παραστατικό','Είδος ΑΑΔΕ','Συναλλασσόμενος','ΑΦΜ','Ημερομηνία','Καθαρή €','ΦΠΑ €','Σύνολο €','Λογαριασμός καρτέλας','Έλεγχος','Αιτία εκκρεμότητας','ΑΑΔΕ','PDF · κλικ για άνοιγμα')
        self.tree = table(self.documents_tab,columns,titles,{'name':190,'reference':100,'vat':95,'issue_date':90,'gross_minor':85,'display_account_code':170,'preparation_state':120,'aade_state':90,'pdf_state':200},table_key='documents')
        self._sort=self.tree.presentation.saved_sort(self._sort)
        self.tree.configure(selectmode='extended')
        self.tree.presentation.toolbar.pack_forget()
        self.tree.presentation.toolbar.pack(in_=filter_bar,side='right')
        from app.ui.column_filters import ColumnFilters
        from app.ui.quick_account import extend_menu
        self.column_filters=ColumnFilters(self.tree,self.filter_documents,rows=lambda:self._documents,extra_menu=lambda event,tree,menu:(extend_menu(self,event,tree,menu),self.rpa_panel.document_menu(event,tree,menu),self.pending_reason_menu(event,tree,menu)),show_summary=True,reset_parent=search_bar)
        self.tree.configure(displaycolumns=('reference','name','vat','issue_date','net_minor','tax_minor','gross_minor','display_account_code','preparation_state','pending_reason','pdf_state'))
        self.tree.column('pending_reason',width=280)
        for key,width in {'reference':95,'name':180,'vat':90,'issue_date':85,'net_minor':80,'tax_minor':80,'gross_minor':80,'display_account_code':170,'preparation_state':125,'pdf_state':135}.items():self.tree.column(key,width=width)
        for col in columns:
            self.tree.heading(col,command=lambda key=col:self.sort_documents(key))
        self.tree.bind('<ButtonRelease-1>',self.pdf_click)
        self.tree.bind('<Double-1>',self.document_double_click)
        self.tree.bind('<Return>',lambda _:self.open_detail())
        actions = ttk.Frame(self.documents_tab)
        actions.pack(side='bottom',fill='x',pady=(6,0))
        self.tree.master.pack_forget()
        self.tree.master.pack(fill='both',expand=True)
        ttk.Button(actions,text='Στοιχεία & προετοιμασία',command=self.open_detail).pack(side='right')
        ttk.Button(actions,text='Άνοιγμα PDF',command=self.open_pdf).pack(side='right',padx=8)
        ttk.Label(self.reviews_tab,text='Ιστορικό εισαγωγών και εξαιρέσεις',style='Section.TLabel').pack(anchor='w')
        ttk.Label(self.reviews_tab,text='Οι αναφορές διατηρούνται μετά το κλείσιμο της εφαρμογής. Διπλό κλικ για αναλυτικό έλεγχο.',style='Subtitle.TLabel').pack(anchor='w',pady=(4,12))
        self.review_tree = table(self.reviews_tab,('created_at','filename','inserted','duplicates','rejected','warnings'),
                                 ('Χρόνος εισαγωγής','Αρχείο','Νέα','Διπλότυπα','Εξαιρέσεις','Προειδοποιήσεις'),{'filename':300},table_key='imports')
        self.review_filters=ColumnFilters(self.review_tree,self.filter_reviews,rows=lambda:getattr(self,'_review_rows',{}),show_summary=True)
        self.review_tree.bind('<Double-1>',lambda _:self.open_review())
        ttk.Button(self.reviews_tab,text='Προβολή αναφοράς',command=self.open_review).pack(side='bottom',anchor='e',pady=(12,0))
        self.review_tree.master.pack_forget()
        self.review_tree.master.pack(fill='both',expand=True)
        self.rpa_tab=ttk.Frame(self.documents_tab)
        self.rpa_tab.pack(side='bottom',fill='x',pady=(4,0))
        self.tree.master.pack_forget()
        self.tree.master.pack(fill='both',expand=True)
        from app.ui.rpa_panel import RPAPanel
        self.rpa_panel=RPAPanel(self,self.rpa_tab,table)
        from app.ui.suppliers import Suppliers
        self.suppliers=Suppliers(self,self.suppliers_tab,group='2')
        self.creditors=Suppliers(self,self.creditors_tab,group=('2','6'))
        from app.ui.ebs_reconciliation import ReconciliationTab
        self.reconciliation=ReconciliationTab(self,self.reconciliation_tab)
        self.notebook.bind('<<NotebookTabChanged>>',self.tab_changed)
        footer = ttk.Frame(root,padding=(16,5,16,5))
        footer.pack(side='bottom',fill='x')
        self.notebook.pack_forget()
        self.notebook.pack(fill='both',expand=True,padx=16)
        self.progress = ttk.Progressbar(footer,mode='indeterminate',length=110)
        self.purchase_undo_button=ttk.Button(footer,text='Αναίρεση χαρακτηρισμού',command=self.undo_purchase)
        self.purchase_exceptions_button=ttk.Button(footer,text='Εξαιρέσεις χαρακτηρισμού',command=self.show_purchase_exceptions)
        status_label=ttk.Label(footer,textvariable=self.status,style='Subtitle.TLabel',wraplength=1100);status_label.pack(anchor='w')
        footer.bind('<Configure>',lambda event:status_label.configure(wraplength=max(200,event.width-48)))
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.bind('<Control-f>',lambda _:(entry.focus_set(),entry.select_range(0,'end')))
        self.refresh()
        self._poll_after = root.after(80,self.poll)
        from app.application.names import NameRecovery
        if NameRecovery(self.erp).needed(self.company):root.after(120,self.recover_names)

    def change_theme(self,mode):
        if self.busy or self.rpa_panel.running:
            self.status.set('Η εμφάνιση αλλάζει μετά την ολοκλήρωση της τρέχουσας εργασίας.');return False
        saved=self.ui_preferences.set_theme(mode)
        self.style=apply(self.root,mode)
        for tree in (self.tree,self.review_tree,*[v.tree for v in self.document_views.values()],self.suppliers.tree,self.creditors.tree,self.reconciliation.tree):
            if hasattr(tree,'presentation'):tree.presentation.hide_tip()
        if not saved:self.status.set('Η εμφάνιση άλλαξε, αλλά δεν αποθηκεύτηκε η προτίμηση.');return True
        self.status.set('Εμφάνιση: '+('Σκούρα' if mode=='dark' else 'Φωτεινή'));return True

    def _has_preview(self):
        return self.preview_window is not None and self.preview_window.winfo_exists()

    def _sync_import_button(self):
        if self._closing:
            return
        self.import_button.state(['disabled'] if self.busy or self.rpa_panel.running or self._has_preview() else ['!disabled'])
        self.ebs_import_button.state(['disabled'] if self.busy or self.rpa_panel.running or self._has_preview() else ['!disabled'])
        self.acquire_button.state(['disabled'] if self.busy or self.rpa_panel.running else ['!disabled'])
        self.month_box.configure(state='disabled' if self.busy or self.rpa_panel.running else 'readonly')
        self.company_box.configure(state='disabled' if self.busy or self.rpa_panel.running else 'readonly')
        self.rpa_panel.refresh()

    def close(self):
        if self._closing:
            return
        if self.busy or self.rpa_panel.running:
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
            except BaseException as exc:
                from app.infrastructure.crashlog import record
                record(self.directory,exc,'worker')
                self.work.put((callback,None,str(exc) or type(exc).__name__))
        from app.ui import worker_collection
        worker_collection.begin()
        try:
            self._worker_thread=threading.Thread(target=work,daemon=True)
            self._worker_thread.start()
        except BaseException:
            worker_collection.end();self.busy=False
            raise
        return True

    def poll(self):
        if self._closing:
            return
        try:
            callback,result,error = self.work.get_nowait()
        except queue.Empty:
            pass
        else:
            from app.ui import worker_collection
            worker=getattr(self,'_worker_thread',None)
            if worker is not None:worker.join()
            worker_collection.end()
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
        # Search clear preserves the independently selected filters/exclusions.
        self.query.set('')
        self.filter_documents()

    def sort_documents(self, key):
        self._sort = (key,not self._sort[1] if key==self._sort[0] else False)
        from app.ui.table_actions import sort_tree
        sort_tree(self.tree,self._documents,*self._sort)
        self.column_filters.sync_headings()

    def tab_changed(self,event=None):
        if self.notebook.select()==str(self.suppliers_tab):self.suppliers.refresh()
        elif self.notebook.select()==str(self.creditors_tab):self.creditors.refresh()
        elif self.notebook.select()==str(self.reconciliation_tab):self.reconciliation.refresh()
        else:
            for view in self.document_views.values():
                if self.notebook.select()==str(view.parent):view.refresh()

    def month_changed(self,event=None):
        self._period_initialized=True
        self.refresh()

    def company_changed(self,event=None):
        chosen=self.company_choices.get(self.company_filter.get())
        if chosen is None or chosen==self.company:return
        if self.busy or self.rpa_panel.running or any(isinstance(w,tk.Toplevel) for w in self.root.winfo_children()):
            self.company_filter.set(next(k for k,v in self.company_choices.items() if v==self.company))
            self.status.set('Κλείσε πρώτα τις ανοικτές καρτέλες ή ολοκλήρωσε την εργασία πριν αλλάξεις επιχείρηση.')
            return
        self.company=chosen;self.rpa_panel.job=None;self.rpa_panel.mapping=None
        self.column_filters.clear()
        for view in self.document_views.values():view.column_filters.clear()
        self.reconciliation.column_filters.clear()
        self._purchase_undo=None;self._purchase_exceptions=[];self.purchase_undo_button.pack_forget();self.purchase_exceptions_button.pack_forget()
        self.rpa_panel.scope.set('Εκκρεμή προς EBS')
        self.rpa_panel.state.set('Έλεγχος χωρίς καταχώριση: ελέγχει την επιλογή χωρίς ενέργεια στο EBS.')
        self.rpa_panel.restore_job();self.query.set('');self.state_filter.set(STATES[3])
        self.reconciliation.query.set('');self._period_initialized=True;self.refresh()

    def open_pdf(self,document=None):
        selected=self.tree.selection()
        if document is None and not selected:return
        from app.ui.pdf_pane import open_document
        return open_document(self,document if document is not None else int(selected[0]),self.root)

    def purchase_menu(self,event,tree,menu=None):
        if self.busy or self.rpa_panel.running or tree.identify_region(event.x,event.y)!='cell':return
        columns=list(tree['displaycolumns'])
        if columns==['#all']:columns=list(tree['columns'])
        if display_column(tree,event.x)!='name':return
        selected=tree.identify_row(event.y)
        if not selected:return
        if menu is None:tree.selection_set(selected)
        row=next((r for r in self._month_rows if r['id']==int(selected)),None)
        if row is None or row.get('environment','production')!='production':return
        from app.application.supplier_purchases import SupplierPurchases
        from app.ui.document_views import belongs
        if not (belongs(row,'expenses') or belongs(row,'purchases')):return
        try:scope=SupplierPurchases(self.erp).inspect(self.company,row['vat'])
        except ValueError as exc:self.status.set(str(exc));return
        enabled=not scope['enabled'];count=sum((d not in scope['tagged']) if enabled else (d in scope['tagged']) for d in scope['eligible'])
        previous=getattr(self,'_purchase_menu',None)
        if previous is not None:previous.destroy()
        supplied=menu is not None
        menu=menu if supplied else tk.Menu(tree,tearoff=False);self._purchase_menu=menu
        label='Ορισμός ως προμηθευτής αγορών' if enabled else 'Άρση χαρακτηρισμού προμηθευτή αγορών'
        menu.add_command(label=f'{label} — αφορά {count} εκκρεμή παραστατικά',command=lambda:self.set_purchase(row['vat'],enabled))
        if scope['enabled'] and scope['previous_group'] is not None:
            menu.add_command(label='Επαναφορά προηγούμενης ομάδας',command=lambda:self.restore_purchase_group(row['vat']))
        if supplied:menu.add_separator();return
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()

    def restore_purchase_group(self,supplier):
        if self.busy or self.rpa_panel.running:return
        from app.application.supplier_purchases import SupplierPurchases
        try:SupplierPurchases(self.erp).restore(self.company,supplier)
        except (ValueError,sqlite3.Error) as exc:self.status.set(str(exc));return
        self._purchase_undo=None;self.purchase_undo_button.pack_forget();self.refresh()
        self.status.set('Επαναφέρθηκε η προηγούμενη ομάδα. Οι λογαριασμοί διατηρήθηκαν.')

    def set_purchase(self,supplier,enabled,expected_version=None):
        if self.busy or self.rpa_panel.running:return False
        from app.application.supplier_purchases import SupplierPurchases
        if enabled:
            card=self.erp.db.execute('SELECT name FROM counterparties WHERE company_id=? AND vat=?',(self.company,supplier)).fetchone()
            if card is None:return False
            if not messagebox.askyesno('Μεταφορά στην Ομάδα 2',f"Θέλετε να μεταφέρετε τον προμηθευτή {card['name']} (ΑΦΜ: {supplier}) στην Ομάδα 2;",parent=self.root):return False
        try:report=SupplierPurchases(self.erp).set(self.company,supplier,enabled,expected_version=expected_version)
        except (ValueError,sqlite3.Error) as exc:self.status.set(str(exc));return False
        self._purchase_undo=(self.company,supplier,report['previous'],report['version'])
        self._purchase_exceptions=report['exceptions'];self.purchase_undo_button.pack(side='right')
        self.purchase_exceptions_button.pack_forget()
        if report['exceptions']:self.purchase_exceptions_button.pack(side='right',padx=6)
        self.refresh()
        self.status.set(f"{'Χαρακτηρίστηκαν ως αγορές' if enabled else 'Αφαιρέθηκε ο χαρακτηρισμός από'}: {report['changed']} παραστατικά σε όλους τους μήνες. {report['queues']} αναμονές ουρών αποκλείστηκαν. {len(report['exceptions'])} προστατευμένες εξαιρέσεις.")
        return True

    def undo_purchase(self):
        previous=getattr(self,'_purchase_undo',None)
        if previous and previous[0]==self.company and self.set_purchase(previous[1],previous[2],previous[3]):
            self.purchase_undo_button.pack_forget()
            self._purchase_undo=None

    def pending_reason_menu(self,event,tree,menu):
        key=tree.identify_row(event.y)
        row=getattr(self,'_documents',{}).get(int(key)) if key else None
        if row and row.get('pending_reason'):
            def copy():
                self.root.clipboard_clear();self.root.clipboard_append(row['pending_reason'])
            menu.add_command(label='Αντιγραφή αιτίας εκκρεμότητας',command=copy)

    def show_purchase_exceptions(self):
        win=tk.Toplevel(self.root);win.title('Προστατευμένες εγγραφές · χωρίς μεταβολή')
        entries=[]
        for exception in getattr(self,'_purchase_exceptions',[]):
            row,_=self.erp.detail(self.company,exception['document'])
            entries.append(f"{reference(row)} · {row['name']} · ΑΦΜ {row['vat']}\n{exception['reason']}")
        read_text(win,'\n\n'.join(entries))

    def pdf_click(self,event):
        if self.tree.identify_region(event.x,event.y)!='cell':return
        if display_column(self.tree,event.x)!='pdf_state':return
        row=self.tree.identify_row(event.y)
        if row:self.tree.selection_set(row);self.open_pdf(int(row))

    def document_double_click(self,event):
        if self.tree.identify_region(event.x,event.y)!='cell' or not self.tree.identify_row(event.y):return 'break'
        if display_column(self.tree,event.x)=='pdf_state':return 'break'
        self.open_detail()

    def refresh(self):
        identity=self.erp.db.execute('SELECT vat,name FROM companies WHERE id=?',(self.company,)).fetchone()
        self.company_choices={f"{r['name']} · {r['vat']}":r['id'] for r in self.erp.db.execute('SELECT id,vat,name FROM companies ORDER BY name')}
        self.company_box.configure(values=tuple(self.company_choices))
        self.company_filter.set(next(k for k,v in self.company_choices.items() if v==self.company))
        active=self.erp.db.execute('SELECT environment FROM aade_settings WHERE company_id=?',(self.company,)).fetchone()
        self.company_caption.set(identity['name']+' · ΑΦΜ '+identity['vat']+' · '+('Δοκιμαστική ΑΑΔΕ' if active and active[0]=='test' else 'Παραγωγική ΑΑΔΕ'))
        from app.application.supplier_accounts import SupplierAccounts
        environment=active[0] if active else 'production'
        display_accounts=SupplierAccounts(self.erp).display_accounts(self.company,environment=environment)
        accounts_changed=self.company!=getattr(self,'_display_company',None) or environment!=getattr(self,'_display_environment',None) or display_accounts!=getattr(self,'_display_accounts',None)
        self._display_environment=environment
        self._display_company=self.company
        self._display_accounts=display_accounts
        for window in list(self._details.values()):
            if window.winfo_exists() and hasattr(window,'refresh_identity'):window.refresh_identity()
            if window.winfo_exists() and hasattr(window,'pdf_pane'):window.pdf_pane.refresh_if_changed()
        months=[r[0] for r in self.erp.db.execute('SELECT DISTINCT substr(issue_date,1,7) FROM documents WHERE company_id=? AND environment=? ORDER BY 1 DESC',(self.company,environment))]
        from app.application.periods import MONTHS
        available=set(months)|set(self._month_values.values())|{f'{year}-{month:02d}' for year in (date.today().year-1,date.today().year) for month in range(1,13)}
        periods={MONTHS[int(m[5:])-1]+' '+m[:4]:m for m in sorted(available,reverse=True)}
        self._month_values=periods
        self.month_box.configure(values=('Όλοι οι μήνες',*periods))
        if months and not self._period_initialized:self.month_filter.set(MONTHS[int(months[0][5:])-1]+' '+months[0][:4]);self._period_initialized=True
        month=periods.get(self.month_filter.get()) if self.month_filter.get()!='Όλοι οι μήνες' else None
        total=self.erp.db.execute('SELECT count(*) FROM documents WHERE company_id=? AND environment=?',(self.company,environment)).fetchone()[0]
        revision=(self.company,total)
        for window in self.root.winfo_children():
            if window.winfo_exists() and hasattr(window,'refresh_accounts'):window.refresh_accounts(display_accounts)
        self._account_document_revision=revision
        jobs = self.erp.import_reviews(self.company,environment=environment)
        from app.application.workspace import Workspace
        month_rows=Workspace(self.erp).rows(self.company,month=month)
        from app.application.ebs_reconciliation import EBSReconciliation
        evidence=EBSReconciliation(self.erp).results(self.company)
        for row in month_rows:
            if row['environment']=='test':evidence[row['id']]=dict(row,status='unreconciled',match_kind='',reason='Δοκιμαστικό παραστατικό · εκτός παραγωγικής συμφωνίας EBS',run=None,source='',filename='',when='')
        from app.ui.pending_reasons import pending_reasons
        reasons=pending_reasons(self.erp,self.company,month_rows,evidence)
        for row in month_rows:
            row['display_account_code']=display_accounts.get(row['vat'],'')
            row['pending_reason']=reasons[row['id']]
        self._month_rows=month_rows;self._evidence=evidence
        self.filter_documents(fit_columns=True)
        self.metrics['total'].set(str(total))
        self.metrics['pending'].set(str(sum(r['direction']=='incoming' and not r['is_purchase'] and not r.get('prepared_at') for r in month_rows)))
        self.metrics['issues'].set(str(sum(len(j['report'].get('rejected',[]))+len(j['report'].get('warnings',[])) for j in jobs)))
        self._jobs = {j['id']:j for j in jobs}
        self._review_rows={j['id']:dict(id=j['id'],created_at=j['created_at'],filename=j['filename'],inserted=j['report'].get('inserted',0),duplicates=j['report'].get('duplicates',0),rejected=len(j['report'].get('rejected',[])),warnings=len(j['report'].get('warnings',[]))) for j in jobs}
        self.filter_reviews()
        for view in self.document_views.values():view.refresh(render=accounts_changed or self.notebook.select()==str(view.parent))
        self.reconciliation.refresh(evidence,render=self.notebook.select()==str(self.reconciliation_tab))
        if accounts_changed or self.notebook.select()==str(self.suppliers_tab):self.suppliers.refresh()
        if accounts_changed or self.notebook.select()==str(self.creditors_tab):self.creditors.refresh()
        self.rpa_panel.refresh()
        if not self.busy:
            self.status.set('Τα παραστατικά και οι αναφορές έχουν φορτωθεί από τη βάση.')


    def filter_reviews(self):
        self.review_tree.delete(*self.review_tree.get_children())
        for row in self.review_filters.apply(list(getattr(self,'_review_rows',{}).values())):
            self.review_tree.insert('','end',iid=str(row['id']),values=[row[k] for k in self.review_tree['columns']])
        self.review_tree.presentation.rows_changed()

    def filter_documents(self,*,fit_columns=False):
        if not hasattr(self,'_month_rows'):return
        from app.ui.rpa_panel import LABELS as EBS_LABELS
        month_rows=self._month_rows;evidence=self._evidence
        selected=self.tree.selection();focused=self.tree.focus();x=self.tree.xview();y=self.tree.yview()
        from app.domain.invoice_types import financial_document
        # Immutable scope of this view, before every search/dropdown/column filter.
        base=[r for r in month_rows if r['direction']=='incoming' and financial_document(r) is not False
              and not r['is_purchase'] and evidence[r['id']]['status']!='registered' and not evidence[r['id']].get('submitted')
              and (evidence[r['id']].get('posting_permitted') or
                   (not evidence[r['id']].get('file_matched') and
                    not (evidence[r['id']]['status']=='review' and evidence[r['id']].get('match_kind')=='normalized')))]
        query=self.query.get().strip().casefold()
        rows=[dict(r) for r in base if not query or query in reference(r).casefold() or any(query in str(r[k] or '').casefold() for k in ('vat','name','number','series','mark','issue_date'))]
        wanted_group = GROUPS.get(self.group_filter.get())
        rows = [r for r in rows if (wanted_group is None or (r.get('nature_group') or r.get('suggested_group'))==wanted_group)
                and (self.state_filter.get()!=STATES[1] or not r.get('prepared_at'))
                and (self.state_filter.get()!=STATES[2] or r.get('prepared_at'))]
        if self.state_filter.get()=='Χρειάζεται έλεγχος στο EBS':
            rows=[r for r in rows if evidence[r['id']]['status']=='review' and evidence[r['id']].get('match_kind')=='attempt' and not evidence[r['id']].get('submitted')]
        elif self.state_filter.get() in ('Χρειάζονται έλεγχο','Δεν βρέθηκαν στο Excel'):
            wanted='review' if self.state_filter.get()=='Χρειάζονται έλεγχο' else 'not_found'
            rows=[r for r in rows if evidence[r['id']]['status']==wanted]
        for row in rows:
            row['reference'] = reference(row)
            row['ebs_state'] = EBS_LABELS.get(row['ebs_state'],row['ebs_state'])
            row['aade_state'] = {'not_checked':'Δεν ελέγχθηκε','matched':'Συμφωνεί','different':'Διαφορά','cancelled_at_aade':'Αναφορά ακύρωσης'}.get(row['aade_state'],row['aade_state'])
            row['preparation_state'] = 'Εκδοθέν · εκτός εξόδων' if row['direction']=='outgoing' else 'Εκτός ΤΕΔ αξίας' if row['kind']!='invoice' or (row['invoice_type'] and not row['rpa_allowed']) else 'Εγκεκριμένο' if row.get('prepared_at') else 'Πρόταση καρτέλας' if row.get('suggested_account') else 'Χρειάζεται λογαριασμό'
            review_label={'unreconciled':'Χωρίς συμφωνία EBS','not_found':'Δεν βρέθηκε σε μερικό Excel','review':'Έλεγχος συμφωνίας EBS'}.get(evidence[row['id']]['status'])
            if review_label:row['preparation_state']+=' · '+review_label
            if not evidence[row['id']].get('submitted') and evidence[row['id']]['status']=='review' and evidence[row['id']].get('match_kind')=='attempt':row['preparation_state']='Χρειάζεται έλεγχος στο EBS'
            if not row.get('prepared_at') and row.get('suggested_account'):
                row['nature_group']=row['suggested_group'];row['account_code']=row['suggested_account']
        rows=self.column_filters.apply(rows)
        key,reverse = self._sort
        rows.sort(key=lambda r:(r.get(key) is None,r.get(key) or 0) if key.endswith('_minor') or key=='source_record_id' else str(r.get(key) or '').casefold(),reverse=reverse)
        self._documents = {r['id']:r for r in rows}
        self.tree.delete(*self.tree.get_children())
        for i,row in enumerate(rows):
            self.tree.insert('','end',iid=str(row['id']),values=[amount(row[k]) if k.endswith('_minor') else when(row[k]) if k=='issue_date' else row.get(k) or '—' for k in self.tree['columns']],tags=(('alternate',) if i%2 else ())+ (('status_approved',) if row['preparation_state'].startswith('Εγκεκριμένο') else ('status_review',) if 'Χρειάζεται' in row['preparation_state'] else ()))
        self.tree.selection_set([key for key in selected if self.tree.exists(key)])
        if focused and self.tree.exists(focused):self.tree.focus(focused)
        if x:self.tree.xview_moveto(x[0])
        if y:self.tree.yview_moveto(y[0])
        self.column_filters.sync_headings()
        self.tree.presentation.rows_changed(self._documents)
        caption=f'{len(rows)} παραστατικά · {self.month_filter.get()}'
        partials=sum(evidence[r['id']]['status']=='review' and evidence[r['id']].get('match_kind')=='normalized' for r in month_rows if r['direction']=='incoming')
        if partials:caption+=f' · {partials} πιθανώς καταχωρισμένα στην καρτέλα «Συμφωνία»'
        if self.state_filter.get()==STATES[3] and not rows:
            statuses={evidence[r['id']]['status'] for r in month_rows if r['direction']=='incoming' and not evidence[r['id']].get('submitted')}
            if statuses & {'unreconciled','not_found','review'}:caption+=' · Χρειάζεται πλήρης συμφωνία Excel EBS ή έλεγχος εκκρεμοτήτων.'
            elif any(evidence[r['id']].get('submitted') for r in month_rows):caption+=' · Τα ολοκληρωμένα RPA βρίσκονται στη «Συμφωνία».'
            elif not month_rows:caption+=' · Ξεκίνα με «Άντληση ΑΑΔΕ — εγγραφές».'
        if self.column_filters.filters:caption+=f' · Φίλτρα στηλών: {len(self.column_filters.filters)}'
        self.result_count.set(caption)
        self.rpa_panel.update_selection_actions()

    def choose_excel(self,*,purpose='documents',manual_mapping=False):
        if purpose not in ('documents','ebs'):raise ValueError('Μη έγκυρος σκοπός εισαγωγής')
        if self._has_preview():
            self.preview_window.lift()
            return
        if self.busy or self.rpa_panel.running:
            return
        path = filedialog.askopenfilename(parent=self.root,title='Έλεγχος καταχωρημένων EBS' if purpose=='ebs' else 'Εισαγωγή συνοπτικού βιβλίου ΑΑΔΕ',filetypes=[('Υπολογιστικά φύλλα','*.xlsx *.xlsm *.ods')])
        if path:
            from app.infrastructure.importers.excel import read_workbook
            from app.ui.excel_mapping import classify_workbook,raw_preview
            company=self.company
            def execute():
                book=read_workbook(path)
                if purpose=='ebs':return book,None
                service=ERP(self.directory)
                try:
                    if classify_workbook(book,service,company)=='ebs':return book,None
                    return book,raw_preview(service,company,path,book)
                finally:service.close()
            def done(result):
                book,item=result
                if purpose=='ebs':
                    if manual_mapping:self.reconciliation.import_dialog(book,edit_mapping=True)
                    else:self.reconciliation.apply_book(book)
                elif item is None:self.status.set('Το αρχείο αναγνωρίστηκε ως εξαγωγή EBS. Χρησιμοποίησε «Έλεγχος καταχωρημένων EBS». Δεν εισήχθησαν παραστατικά.')
                else:self.show_preview(path,item,book=book)
            self.run_worker(execute,done)

    def _dismiss_preview(self):
        if self._has_preview():
            self.preview_window.destroy()
        self.preview_window = None
        self._sync_import_button()

    def show_preview(self, path, item, *, book=None, window=None):
        if window is None and self._has_preview():
            self.preview_window.lift()
            return
        win = window if window is not None else tk.Toplevel(self.root)
        for child in win.winfo_children():child.destroy()
        generation=object();win._import_generation=generation
        self.preview_window = win
        win.title('Εισαγωγή βιβλίου ΑΑΔΕ · Έλεγχος πριν την αποθήκευση')
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
        from app.ui.excel_mapping import ColumnMapping
        mapping_frame = ColumnMapping(mapping_tab,{key:LABELS.get(key,key)+(' *' if key in ('vat','date','net','tax') else '') for key in NAMES})
        mapping_frame.pack(fill='x')
        mapping_frame.set_headers(item.headers,item.mapping)
        win.column_mapping=mapping_frame
        error_tree = table(errors_tab,('row','reason'),('Γραμμή Excel','Αιτία εξαίρεσης'),{'row':100,'reason':780})
        for row in item.rejected:
            error_tree.insert('','end',values=(row['row'],row['reason']))
        bottom = ttk.Frame(win,padding=18)
        bottom.pack(side='bottom',fill='x')
        pages.pack_forget()
        pages.pack(fill='both',expand=True,padx=18)
        ttk.Label(bottom,text='Η επιβεβαίωση αποθηκεύει μόνο στο Σύμβολον ERP.',style='Subtitle.TLabel').pack(anchor='w',pady=(0,10))
        ttk.Button(bottom,text='Ακύρωση',command=self._dismiss_preview).pack(side='left')
        def remap():
            if self.busy:
                return
            mapping = mapping_frame.mapping()
            def done(new):
                if self._closing or not win.winfo_exists() or win._import_generation is not generation:return
                self.show_preview(path,new,book=book,window=win)
            self.run_worker(lambda:preview(path,mapping,book=book,sheet=item.sheet,header_row=item.header_row),done)
        ttk.Button(bottom,text='Επανέλεγχος αντιστοίχισης',command=remap).pack(side='left',padx=8)
        def commit():
            if self.busy:
                return
            current = mapping_frame.mapping()
            if current!=item.mapping:
                messagebox.showwarning('Χρειάζεται επανέλεγχος','Άλλαξες την αντιστοίχιση. Πάτησε πρώτα «Επανέλεγχος αντιστοίχισης».',parent=win)
                return
            if not item.records:
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
        if not item.records:
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

    def open_detail(self,document_id=None):
        identity=self.erp.db.execute('SELECT vat,name FROM companies WHERE id=?',(self.company,)).fetchone()
        self.company_caption.set(identity['name']+' · ΑΦΜ '+identity['vat']+' · Προετοιμασία για EBS')
        selected = self.tree.selection()
        if document_id is None and not selected:
            return
        document_id = int(selected[0]) if document_id is None else document_id
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
        display_company=self.company
        current_account=tk.StringVar()
        def refresh_accounts(mapping=None):
            if display_company!=self.company:return
            if mapping is None or row['environment']!=getattr(self,'_display_environment','production'):
                from app.application.supplier_accounts import SupplierAccounts
                mapping=SupplierAccounts(self.erp).display_accounts(display_company,environment=row['environment'])
            current_account.set('Τρέχων λογαριασμός καρτέλας: '+(mapping.get(row['vat']) or 'Δεν έχει οριστεί'))
        win.refresh_accounts=refresh_accounts;win.current_account_var=current_account
        refresh_accounts()
        ttk.Label(header,textvariable=current_account,style='Subtitle.TLabel').pack(anchor='w',pady=4)
        ttk.Label(header,textvariable=identity_caption,style='Subtitle.TLabel').pack(anchor='w',pady=4)
        ttk.Label(header,text=f"Καθαρή {amount(row['net_minor'])} €    +    ΦΠΑ {amount(row['tax_minor'])} €    +    Στρογγ. {amount(row['rounding_minor'])} €    =    Σύνολο {amount(row['gross_minor'])} €",style='Section.TLabel').pack(anchor='w',pady=(8,0))
        split=ttk.Panedwindow(win,orient='horizontal')
        split.pack(fill='both',expand=True,padx=18,pady=(0,18))
        left=ttk.Frame(split,width=640);right=ttk.Frame(split,width=480)
        split.add(left,weight=1);split.add(right,weight=1)
        win.after_idle(lambda:split.sashpos(0,int(split.winfo_width()*.52)) if split.winfo_exists() else None)
        from app.domain.invoice_types import classify
        from app.ui.document_views import belongs
        kind=self.erp.db.execute("SELECT invoice_type,is_delivery_note FROM mydata_records WHERE company_id=? AND document_id=? AND environment=coalesce((SELECT environment FROM aade_settings WHERE company_id=?),'production') ORDER BY id DESC LIMIT 1",(self.company,document_id,self.company)).fetchone()
        category=classify(kind['invoice_type'],kind['is_delivery_note']) if kind else classify('')
        if belongs(dict(row,**category),'income'):
            for label,value in [('ΑΦΜ',row['vat']),('Παραστατικό',reference(row)),('Ημερομηνία',when(row['issue_date'])),('MARK',row['mark'] or '—')]:
                ttk.Label(left,text=label+'  ·  '+value,padding=12).pack(anchor='w')
            from app.ui.pdf_pane import PDFPane
            win.pdf_pane=PDFPane(self,right,document_id,win);return win
        pages = ttk.Notebook(left)
        pages.pack(fill='both',expand=True)
        summary,prepare_tab,source,history = [ttk.Frame(pages,padding=12) for _ in range(4)]
        for page,title in ((summary,'Στοιχεία'),(prepare_tab,'Προετοιμασία EBS'),(source,'Προέλευση'),(history,'Ιστορικό')):
            pages.add(page,text=title)
        details = [('Επωνυμία',row['name']),('ΑΦΜ',row['vat']),('Αριθμός',row['number']),('Σειρά',row['series'] or '—'),('MARK',row['mark'] or '—'),('Νόμισμα',row['currency']),('Κατάσταση','Τοπικά εγκεκριμένη προετοιμασία' if preparation else 'Χρειάζεται έλεγχο')]
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
        ttk.Label(fields,text='Λογαριασμός προετοιμασίας').grid(row=1,column=0,sticky='w',pady=8)
        ttk.Entry(fields,textvariable=account,width=30).grid(row=1,column=1,sticky='ew',padx=16)
        ttk.Label(fields,text='Σημείωση ελέγχου').grid(row=2,column=0,sticky='w',pady=8)
        ttk.Entry(fields,textvariable=note,width=28).grid(row=2,column=1,sticky='ew',padx=16)
        fields.columnconfigure(1,weight=1)
        remember_account=tk.BooleanVar(value=True)
        ttk.Checkbutton(prepare_tab,text='Καρτέλα και εκκρεμή ίδιας ομάδας, όλων των μηνών (αλλιώς μόνο αυτό)',variable=remember_account).pack(anchor='w',pady=8)
        approved = tk.BooleanVar(value=False)
        ttk.Checkbutton(prepare_tab,text='Έλεγξα το παραστατικό, την ομάδα και τον λογαριασμό.',variable=approved).pack(anchor='w',pady=18)
        ttk.Label(prepare_tab,text='Η έγκριση αφορά μόνο την τοπική προετοιμασία. Δεν επαληθεύει τον λογαριασμό στο EBS και δεν δημιουργεί λογιστική εγγραφή.',style='Subtitle.TLabel',wraplength=520).pack(anchor='w')
        def save():
            if self.busy:
                messagebox.showinfo('Εργασία σε εξέλιξη','Περίμενε να ολοκληρωθεί η εισαγωγή.',parent=win)
                return
            if self.erp.preparation(display_company,document_id)!=preparation_snapshot[0]:
                baseline_fields[0]=(group.get(),account.get(),note.get());refresh_preparation()
                messagebox.showinfo('Ενημερωμένο παραστατικό','Ο λογαριασμός άλλαξε από άλλο σημείο. Φορτώθηκαν οι τρέχουσες τιμές· έλεγξέ τες πριν αποθηκεύσεις.',parent=win);return
            if not approved.get():
                messagebox.showwarning('Απαιτείται έλεγχος','Επιβεβαίωσε πρώτα ότι έλεγξες τα στοιχεία.',parent=win)
                return
            if not messagebox.askyesno('Τοπική έγκριση',f'Αποθήκευση προετοιμασίας για {reference(row)};\nΟμάδα: {group.get()}\nΛογαριασμός: {account.get().strip()}\nΕνημέρωση καρτέλας και εκκρεμών ίδιας ομάδας: {'Ναι' if remember_account.get() else 'Όχι, μόνο αυτό το παραστατικό'}\nΔεν θα σταλεί τίποτα στο EBS.',parent=win):
                return
            try:
                from app.application.workspace import Workspace
                Workspace(self.erp).approve_many(self.company,[dict(document=document_id,group=choices.get(group.get(),''),account=account.get().strip(),note=note.get())],confirmed=True,remember=remember_account.get())
            except (ValueError,sqlite3.Error) as exc:
                messagebox.showerror('Η προετοιμασία δεν αποθηκεύτηκε',str(exc),parent=win)
                return
            win.destroy()
            self.refresh()
            if self.tree.exists(str(document_id)):
                self.tree.selection_set(str(document_id))
            self.status.set('Η προετοιμασία εγκρίθηκε τοπικά και καταγράφηκε στο ιστορικό. Δεν έγινε αποστολή στο EBS.')
        preparation_snapshot=[self.erp.preparation(display_company,document_id)]
        def preparation_values(value):
            if value:return (next((label for label,key in choices.items() if key==value['nature_group']),''),value['account_code'],value['note'])
            return (group.get(),account.get(),note.get())
        baseline_fields=[(group.get(),account.get(),note.get())]
        def refresh_preparation(mapping=None):
            refresh_accounts(mapping)
            if display_company!=self.company:return
            latest_card,_=Counterparties(self.erp).detail(display_company,row['counterparty_id'])
            cp_defaults.clear();cp_defaults.update(latest_card['accounts'])
            fresh=self.erp.preparation(display_company,document_id)
            if (group.get(),account.get(),note.get())==baseline_fields[0] and fresh!=preparation_snapshot[0]:
                values=preparation_values(fresh)
                group.set(values[0]);account.set(values[1]);note.set(values[2]);approved.set(False)
                baseline_fields[0]=values;preparation_snapshot[0]=fresh
        win.refresh_accounts=refresh_preparation
        win.preparation_fields=(group,account,note);win.remember_account=remember_account
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

    def open_acquisition(self):
        if self.busy or self.rpa_panel.running:return
        from app.ui.aade_dialog import open_settings
        return open_settings(self,acquire=True,period=self._month_values.get(self.month_filter.get()))

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
