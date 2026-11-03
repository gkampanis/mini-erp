"""Existing workspace tab: inspect real headers, reconcile, then explicitly run RPA."""
from collections import Counter
from datetime import date
import json
import re
from decimal import Decimal
import tkinter as tk
from tkinter import ttk,messagebox,simpledialog
from app.ui.theme import colors
from app.application.ebs_reconciliation import EBSReconciliation
from app.application.service import ERP
from app.application.periods import MONTHS,month_bounds
from app.ui.excel_mapping import ColumnMapping,EBS_COLUMNS,EBS_IGNORED,auto_mapping,best_layout,saved_ebs_layout

COLUMNS=EBS_COLUMNS

STATES={'Όλα':None,'Καταχωρισμένα':'registered','Μερική συμφωνία — Πιθανώς καταχωρισμένο':'partial','Μη καταχωρισμένα':'not_registered','Χρειάζονται έλεγχο':'review','Χρειάζεται έλεγχος στο EBS':'ebs_review','Δεν εντοπίστηκε στο Excel':'not_found','Χωρίς συμφωνία':'unreconciled'}
TITLES={v:k for k,v in STATES.items() if v}
SOURCES={'excel_ebs':'Excel EBS','normalization_operator':'Επιβεβαίωση μερικής αντιστοίχισης','rpa_operator':'RPA · οπτικός έλεγχος','rpa_attempt':'Προσπάθεια RPA · εκκρεμεί έλεγχος','manual_operator':'Χειροκίνητη επιβεβαίωση','ebs_duplicate_alert':'Μήνυμα υπάρχοντος παραστατικού EBS','':'—'}

def display_state(row):
    if row.get('submitted'):return 'registered'
    if row['status']=='review' and row.get('match_kind')=='attempt':return 'ebs_review'
    return 'partial' if row['status']=='review' and row.get('match_kind')=='normalized' else row['status']


def comparison_fields(row,entry):
    from app.ui.desktop import amount,reference
    item=entry['normalized'] if entry else {}
    values=[('Ημερομηνία',row['issue_date'],item.get('date','—'),row['issue_date']!=item.get('date')),
            ('ΑΦΜ',row['vat'],item.get('vat','—'),row['vat']!=item.get('vat')),
            ('Παραστατικό',reference(row),entry['original_reference'] if entry else '—',reference(row)!=(entry['original_reference'] if entry else None))]
    for label,key in (('Καθαρή €','net_minor'),('ΦΠΑ €','tax_minor'),('Σύνολο €','gross_minor')):
        exact=item.get(key.removesuffix('_minor')+'_exact')
        differs=row[key]!=item.get(key) or (exact is not None and Decimal(exact)!=Decimal(row[key])/100)
        text=exact.replace('.',',') if exact is not None and Decimal(exact)!=Decimal(item.get(key,0))/100 else amount(item[key]) if key in item else '—'
        values.append((label,amount(row[key]),text,differs))
    return values


def reference_note(left,right):
    if left.casefold()==right.casefold():return 'διαφορά μόνο σε πεζά / κεφαλαία'
    if re.sub(r'[\s/-]+','',left.casefold())==re.sub(r'[\s/-]+','',right.casefold()):return 'διαφορά μόνο σε κενά ή διαχωριστικά (/ και -)'
    from app.domain.ebs_matching import canonical_reference
    if canonical_reference(left)==canonical_reference(right):return 'διαφορά μορφοποίησης ή αρχικών μηδενικών του αριθμού'
    return 'διαφορά στην παρουσίαση σειράς / αριθμού — έλεγξε τα δύο αρχικά αναγνωριστικά'

def result_title(row):
    if row.get('submitted') and row['status']!='registered':return 'RPA ολοκληρώθηκε · αναμένει οπτικό έλεγχο'
    if row.get('match_kind')=='exact' and row['status']=='registered':return 'Καταχωρισμένο — Ακριβής συμφωνία'
    if row.get('match_kind')=='normalized_confirmed' and row['status']=='registered':return 'Καταχωρισμένο — Επιβεβαιωμένη μερική συμφωνία'
    return TITLES.get(display_state(row),row['status'])

class ReconciliationTab:
    def __init__(self,owner,parent):
        from app.ui.desktop import table
        self.owner=owner;self.service=EBSReconciliation(owner.erp);self.rows={};self.sort=('issue_date',False)
        ttk.Label(parent,text='Συμφωνία με Excel / EBS',style='Section.TLabel').pack(anchor='w')
        ttk.Label(parent,text='Ίδιος μήνας με τη βασική λίστα. Η εισαγωγή δεν εκτελεί καταχώριση. Μόνο πλήρης, ελεγμένη εξαγωγή επιτρέπει χαρακτηρισμό «Μη καταχωρισμένα».',style='Subtitle.TLabel',wraplength=1000).pack(anchor='w',pady=6)
        ttk.Button(parent,text='Αντιστοίχιση στηλών EBS',command=lambda:owner.choose_excel(purpose='ebs',manual_mapping=True)).pack(anchor='w',pady=(0,6))
        controls=ttk.Frame(parent);controls.pack(fill='x',pady=8)
        self.query=tk.StringVar();entry=ttk.Entry(controls,textvariable=self.query,width=20);entry.pack(side='left',fill='x',expand=True,padx=8)
        entry.bind('<Return>',lambda _:self.refresh(self.rows))
        self.filter=tk.StringVar(value='Όλα');box=ttk.Combobox(controls,textvariable=self.filter,values=tuple(STATES),state='readonly',width=26);box.pack(side='left',padx=8);box.bind('<<ComboboxSelected>>',lambda _:self.refresh(self.rows))
        ttk.Button(controls,text='Αναζήτηση',command=lambda:self.refresh(self.rows)).pack(side='left')
        ttk.Button(controls,text='Καθαρισμός',command=self.clear).pack(side='left',padx=(6,0))
        self.counts=tk.StringVar();ttk.Label(parent,textvariable=self.counts,style='Subtitle.TLabel').pack(anchor='w',pady=6)
        ttk.Label(parent,text='Τίτλοι στηλών: κλικ για ταξινόμηση ↑↓ · δεξί κλικ για φίλτρο',style='Subtitle.TLabel').pack(anchor='w',pady=(0,4))
        bottom=ttk.Frame(parent);bottom.pack(side='bottom',fill='x',pady=8)
        ttk.Button(bottom,text='Άνοιγμα παραστατικού',command=self.open).pack(side='left')
        ttk.Button(bottom,text='Άνοιγμα PDF',command=self.pdf).pack(side='left',padx=6)
        ttk.Button(bottom,text='Σύγκριση στοιχείων',command=self.details).pack(side='left')
        checks=ttk.Frame(parent);checks.pack(side='bottom',fill='x',pady=4)
        self.confirm_button=ttk.Button(checks,text='Οπτική επιβεβαίωση στο EBS',command=self.confirm);self.confirm_button.pack_forget()
        options=ttk.Menubutton(checks,text='Επιλογές συμφωνίας ▾');options.pack(side='left')
        menu=tk.Menu(options,tearoff=False);options.configure(menu=menu)
        menu.add_command(label='Ιστορικό συμφωνιών',command=self.history)
        menu.add_command(label='Επιβεβαίωση επιλεγμένου',command=self.confirm)
        ttk.Button(checks,text='Μη καταχωρισμένα → κύρια λίστα',command=self.pending).pack(side='right')
        self.tree=table(parent,('status','invoice','name','vat','issue_date','net_minor','tax_minor','gross_minor','reason','source','filename','when'),('Κατάσταση','Παραστατικό','Επωνυμία','ΑΦΜ','Ημερομηνία','Καθαρή €','ΦΠΑ €','Σύνολο €','Αιτιολόγηση','Πηγή','Αρχείο','Χρόνος'),{'reason':420,'status':200,'source':180,'name':240},table_key='reconciliation')
        self.sort=self.tree.presentation.saved_sort(self.sort)
        self.tree.bind('<Double-1>',self.double_click)
        self.tree.bind('<Return>',lambda _:self.open())
        self.tree.bind('<<TreeviewSelect>>',self.selection_changed)
        for key in self.tree['columns']:self.tree.heading(key,command=lambda k=key:self.sort_by(k))
        from app.ui.column_filters import ColumnFilters
        self.column_filters=ColumnFilters(self.tree,lambda:self.refresh(self.rows),rows=lambda:self.rows,value=lambda row,key:result_title(row) if key=='status' else SOURCES[row['source']] if key=='source' else row.get(key),show_summary=True)
    def clear(self):
        self.query.set('');self.refresh(self.rows)
    def sort_by(self,key):
        from app.ui.table_actions import sort_tree
        self.sort=(key,not self.sort[1] if self.sort[0]==key else False)
        translated={'status':result_title,'source':lambda row:SOURCES[row['source']]}
        sort_tree(self.tree,self.rows,*self.sort,value=translated.get(key))
        self.column_filters.sync_headings()
        self.tree.presentation.rows_changed(self.rows)
    def refresh(self,results=None,*,render=True):
        from app.ui.desktop import amount,when,reference
        selected=self.tree.selection();focused=self.tree.focus();x=self.tree.xview();y=self.tree.yview()
        self.rows=self.service.results(self.owner.company) if results is None else results
        month=self.owner._month_values.get(self.owner.month_filter.get());query=self.query.get().strip().casefold()
        rows=[r for r in self.rows.values() if r['direction']=='incoming' and (not month or r['issue_date'].startswith(month))]
        counts=Counter(display_state(r) for r in rows)
        self.counts.set(' · '.join(f'{label}: {counts[state]}' for state,label in TITLES.items()))
        wanted=STATES[self.filter.get()]
        rows=[r for r in rows if (not wanted or display_state(r)==wanted) and (not query or query in reference(r).casefold() or any(query in str(r[k] or '').casefold() for k in ('name','vat','series','number','mark','reason')))]
        for r in rows:r['invoice']=reference(r)
        rows=self.column_filters.apply(rows)
        key,reverse=self.sort
        rows.sort(key=lambda r:(r.get(key) or 0) if key.endswith('_minor') else str(result_title(r) if key=='status' else SOURCES[r['source']] if key=='source' else r.get(key) or '').casefold(),reverse=reverse)
        if not render:return
        self.tree.delete(*self.tree.get_children())
        for r in rows:self.tree.insert('','end',iid=str(r['id']),values=(result_title(r),reference(r),r['name'],r['vat'],when(r['issue_date']),amount(r['net_minor']),amount(r['tax_minor']),amount(r['gross_minor']),r['reason'],SOURCES[r['source']],r['filename'],r['when']))
        self.tree.selection_set([s for s in selected if self.tree.exists(s)])
        if focused and self.tree.exists(focused):self.tree.focus(focused)
        if x:self.tree.xview_moveto(x[0])
        if y:self.tree.yview_moveto(y[0])
        self.column_filters.sync_headings()
        self.tree.presentation.rows_changed(self.rows)
    def chosen(self):return int(self.tree.selection()[0]) if self.tree.selection() else None
    def selection_changed(self,event=None):
        row=self.rows.get(self.chosen(),{})
        self.confirm_button.configure(text='Επιβεβαίωση αντιστοίχισης' if row.get('match_kind')=='normalized' and row.get('status')=='review' else 'Οπτική επιβεβαίωση στο EBS')
    def open(self):
        document=self.chosen()
        if document is not None:self.owner.open_detail(document)
    def double_click(self,event):
        if self.tree.identify_region(event.x,event.y)!='cell':return
        row=self.tree.identify_row(event.y)
        if row:self.tree.selection_set(row);return self.open()
    def pdf(self):
        document=self.chosen()
        if document is not None:self.owner.open_pdf(document)
    def details(self):
        document=self.chosen()
        if document is None:return
        return self.show_document_comparison(document)

    def show_document_comparison(self,document):
        from app.ui.desktop import table,amount,reference
        row,entries=self.service.evidence(self.owner.company,document)
        win=tk.Toplevel(self.owner.root);win.title('Σύγκριση ΑΑΔΕ / Σύμβολον ERP — Excel EBS');win.geometry('1000x550')
        ttk.Label(win,text=result_title(row)+' · '+row['reason'],wraplength=950,style='Subtitle.TLabel').pack(anchor='w',padx=16,pady=12)
        tree=table(win,('field','local','excel'),('Πεδίο','Σύμβολον ERP / ΑΑΔΕ','Excel EBS'),{'field':180,'local':320,'excel':380})
        from tkinter import font
        bold=font.nametofont('TkDefaultFont').copy();bold.configure(weight='bold');win.difference_font=bold
        tree.tag_configure('difference',background=colors(win)['warning_bg'],foreground=colors(win)['ink'],font=bold)
        for entry in entries or [None]:
            tree.insert('','end',values=('Γραμμή Excel','',entry['row_number'] if entry else 'Δεν υπάρχει αντιστοίχιση'))
            if entry and entry.get('error'):
                tree.insert('','end',values=('Πρόβλημα / κελί Excel','',entry['error']),tags=('difference',))
            values=comparison_fields(row,entry)
            for *cells,differs in values:tree.insert('','end',values=cells,tags=('difference',) if differs and entry else ())
            if entry and not any(v[3] for v in values if v[0]!='Παραστατικό') and values[2][3]:
                ttk.Label(win,text='Ημερομηνία, ΑΦΜ και ποσά συμφωνούν — '+reference_note(values[2][1],values[2][2])+'.',style='Subtitle.TLabel',wraplength=950).pack(anchor='w',padx=16,pady=8,before=tree.master)
        if row.get('match_kind')=='normalized' and row.get('status')=='review':
            def accept():
                if self.owner.busy or self.owner.rpa_panel.running:return
                self.service.confirm_partial(self.owner.company,document);win.destroy();self.owner.refresh()
            ttk.Button(win,text='Επιβεβαίωση αντιστοίχισης',style='Primary.TButton',command=accept).pack(anchor='e',padx=16,pady=10)
        from app.application.review_permissions import ReviewPermissions
        reviewed=ReviewPermissions(self.owner.erp).inspect(self.owner.company,[document])
        requirements=[r for r in reviewed if not r.get('posting_permitted')]
        if requirements:
            def attempt():
                if self.owner.busy or self.owner.rpa_panel.running:return
                from app.ui.posting_review import open_review
                open_review(self.owner,requirements,on_authorized=lambda documents:self.owner.rpa_panel.posting('selected',documents_override=documents))
            ttk.Button(win,text='Προχώρησε στο EBS…',command=attempt).pack(anchor='e',padx=16,pady=8)
        elif reviewed:
            ttk.Button(win,text='Καταχώριση στο EBS',command=lambda:self.owner.rpa_panel.posting('selected',documents_override=[document])).pack(anchor='e',padx=16,pady=8)
        win.comparison_tree=tree;return win
    def pending(self):
        from app.ui.desktop import STATES
        self.owner.query.set('');self.owner.state_filter.set(STATES[3]);self.owner.group_filter.set('Όλες οι ομάδες');self.owner.refresh()
        self.owner.notebook.select(self.owner.documents_tab)
        self.owner.status.set('Έλεγξε λογαριασμούς και επίλεξε «Καταχώριση έως 40», «Καταχώριση επιλεγμένων» ή «Μεμονωμένη καταχώριση». Καταχωρισμένα και αμφίβολα εξαιρούνται αυτόματα.')
    def confirm(self):
        document=self.chosen()
        if document is None or self.owner.busy or self.owner.rpa_panel.running:return
        row=self.service.results(self.owner.company).get(document,{})
        if row.get('match_kind')=='normalized' and row.get('status')=='review':
            self.service.confirm_partial(self.owner.company,document);self.owner.refresh();return
        if row.get('match_kind')=='attempt':return self.owner.rpa_panel.confirm_document(document)
        if not messagebox.askyesno('Οπτική επιβεβαίωση','Έλεγξες στο EBS ότι αυτό το συγκεκριμένο παραστατικό έχει αποθηκευτεί σωστά;',parent=self.owner.root):return
        note=simpledialog.askstring('Σημείωση ελέγχου','Αριθμός εγγραφής EBS ή σημείωση οπτικού ελέγχου:',parent=self.owner.root)
        if not note:return
        self.service.confirm_manual(self.owner.company,document,note,confirmed=True);self.owner.refresh()
    def history(self):
        from app.ui.desktop import table
        win=tk.Toplevel(self.owner.root);win.title('Ιστορικό συμφωνιών EBS');win.geometry('1000x500')
        tree=table(win,('id','date','file','period','complete','report'),('Α/Α','Χρόνος','Αρχείο','Περίοδος','Πλήρης κατάλογος','Αποτέλεσμα'),{'file':240,'report':300})
        for row in self.owner.erp.db.execute('SELECT * FROM ebs_reconciliation_runs WHERE company_id=? ORDER BY id DESC',(self.owner.company,)):
            report=json.loads(row['report_json']);labels={**TITLES,'excel_rows':'Γραμμές αρχείου','invalid_rows':'Γραμμές με προβλήματα','ignored_rows':'Επικεφαλίδες / σημειώσεις'};text=' · '.join(f'{labels.get(k,k)}: {v}' for k,v in report.items())
            tree.insert('','end',values=(row['id'],row['created_at'],row['filename'],row['date_from']+' — '+row['date_to'],'Ναι' if row['complete'] else 'Όχι',text))
        return win
    def choose(self):
        return self.owner.choose_excel(purpose='ebs')

    def applied(self,report):
        month=report.get('month')
        label=next((k for k,v in self.owner._month_values.items() if v==month),None)
        if label:self.owner.month_filter.set(label)
        self.owner.refresh();self.owner.notebook.select(self.owner.documents_tab)
        self.owner.status.set(f"Ο έλεγχος EBS εφαρμόστηκε. Ακριβείς: {report.get('exact_matches',0)} · Μερικές: {report.get('normalized_matches',0)} · Για έλεγχο: {report.get('review',0)-report.get('normalized_matches',0)}. Οι αντιστοιχισμένες εγγραφές αφαιρέθηκαν από τα μη καταχωρισμένα.")

    def apply_book(self,book):
        layout=saved_ebs_layout(self.owner.erp,self.owner.company,book) or best_layout(book,'ebs',saved_mapping=lambda headers:self.service.saved_mapping(self.owner.company,headers))
        mapping=layout['mapping']
        if any(k not in mapping for k in COLUMNS) or len(set(mapping.values()))!=len(mapping):return self.import_dialog(book)
        company=self.owner.company;month=self.owner._month_values.get(self.owner.month_filter.get()) or date.today().isoformat()[:7]
        def execute():
            erp=ERP(self.owner.directory)
            try:return EBSReconciliation(erp).apply_matches(company,book,layout,month=month)
            finally:erp.close()
        self.owner.run_worker(execute,self.applied)
    def import_dialog(self,book,window=None,*,edit_mapping=False):
        from app.ui.desktop import table,amount,reference
        if window is None and self.owner._has_preview():
            self.owner.preview_window.lift();return self.owner.preview_window
        win=window if window is not None else tk.Toplevel(self.owner.root)
        win._import_generation=None
        for child in win.winfo_children():child.destroy()
        self.owner.preview_window=win
        win.protocol('WM_DELETE_WINDOW',self.owner._dismiss_preview)
        win.bind('<Escape>',lambda _:self.owner._dismiss_preview())
        owned_traces=[]
        def trace(var,callback):owned_traces.append((var,var.trace_add('write',callback)))
        def destroyed(event):
            if event.widget!=win:return
            for var,callback in owned_traces:var.trace_remove('write',callback)
            owned_traces.clear()
            if self.owner.preview_window is win:
                self.owner.preview_window=None;self.owner._sync_import_button()
        win.bind('<Destroy>',destroyed,add='+')
        win.title('Συμφωνία EBS · '+book['filename']);win.geometry('1120x760');win.minsize(920,650)
        self.owner.status.set('Χρειάζεται αντιστοίχιση στηλών. Συμπλήρωσε τις στήλες και πάτησε «Εφαρμογή».')
        win.transient(self.owner.root);win.grab_set();win.packet=None;win.generation=0
        body=ttk.Frame(win,padding=14);body.pack(fill='both',expand=True)
        owner=self.owner.erp.db.execute('SELECT vat,name FROM companies WHERE id=?',(self.owner.company,)).fetchone()
        ttk.Label(body,text=owner['name']+' · ΑΦΜ '+owner['vat'],style='Section.TLabel').pack(anchor='w')
        top=ttk.Frame(body);top.pack(fill='x',pady=8)
        layout=saved_ebs_layout(self.owner.erp,self.owner.company,book) or best_layout(book,'ebs',saved_mapping=lambda headers:self.service.saved_mapping(self.owner.company,headers))
        sheet=tk.StringVar(value=layout['sheet']);header=tk.StringVar(value=str(layout['header_row']))
        ttk.Label(top,text='Φύλλο').pack(side='left');sheet_box=ttk.Combobox(top,textvariable=sheet,values=[s['name'] for s in book['sheets']],state='readonly',width=15);sheet_box.pack(side='left',padx=6)
        ttk.Label(top,text='Γραμμή τίτλων').pack(side='left');header_box=ttk.Spinbox(top,from_=1,to=20000,textvariable=header,width=6);header_box.pack(side='left',padx=6)
        selected=self.owner._month_values.get(self.owner.month_filter.get()) or date.today().isoformat()[:7]
        year=tk.StringVar(value=selected[:4]);month=tk.StringVar(value=MONTHS[int(selected[5:])-1])
        ttk.Combobox(top,textvariable=month,values=MONTHS,state='readonly',width=16).pack(side='left',padx=6)
        ttk.Combobox(top,textvariable=year,values=[str(y) for y in range(2000,date.today().year+2)],state='readonly',width=7).pack(side='left')
        footer=ttk.Frame(body);footer.pack(side='bottom',fill='x')
        pages=ttk.Notebook(body);pages.pack(fill='both',expand=True)
        mapping_tab=ttk.Frame(pages,padding=10);sample_tab=ttk.Frame(pages,padding=10);results_tab=ttk.Frame(pages,padding=10)
        pages.add(mapping_tab,text='Αντιστοίχιση στηλών');pages.add(sample_tab,text='Έλεγχος αρχείου');pages.add(results_tab,text='Αποτέλεσμα συμφωνίας')
        canvas=tk.Canvas(mapping_tab,highlightthickness=0,background=colors(mapping_tab)['bg'])
        scroll=ttk.Scrollbar(mapping_tab,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');canvas.pack(fill='both',expand=True)
        mapping_content=ttk.Frame(canvas);mapping_window=canvas.create_window((0,0),window=mapping_content,anchor='nw')
        mapping_content.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda event:canvas.itemconfigure(mapping_window,width=event.width))
        mapper=ColumnMapping(mapping_content,COLUMNS,unique=True);mapper.pack(fill='x')
        vars=mapper.variables;headers={}
        hint=tk.StringVar();ttk.Label(mapping_content,textvariable=hint,style='Subtitle.TLabel',wraplength=820).pack(fill='x',pady=12)
        problems_only=tk.BooleanVar(value=False)
        ttk.Checkbutton(sample_tab,text='Μόνο γραμμές με πρόβλημα',variable=problems_only).pack(anchor='w',pady=4)
        sample=table(sample_tab,('row',*COLUMNS,'issue'),('Γραμμή','Ημερομηνία','Εναλ. παρ/κό','Α.Φ.Μ.','Αξία','ΦΠΑ','Σύνολο','Έλεγχος / κελί'),{'row':65,'invoice':170,'vat':120,'net':90,'tax':90,'gross':90,'issue':450})
        sample.tag_configure('issue',background=colors(mapping_tab)['warning_bg'],foreground=colors(mapping_tab)['ink'])
        result_tree=table(results_tab,('status','invoice','vat','net','tax','gross','reason'),('Κατάσταση','Παραστατικό Σύμβολον ERP','Α.Φ.Μ.','Αξία','ΦΠΑ','Σύνολο','Αιτιολόγηση'),{'status':180,'invoice':180,'vat':120,'net':90,'tax':90,'gross':90,'reason':450})
        company_ok=tk.BooleanVar(value=True);complete=tk.BooleanVar(value=False);remember=tk.BooleanVar(value=True)
        status=tk.StringVar(value='Συμπλήρωσε τις έξι στήλες και πάτησε «Εφαρμογή».')
        ttk.Label(footer,textvariable=status,style='Subtitle.TLabel',wraplength=870).pack(anchor='w',pady=8)
        bottom=ttk.Frame(footer);bottom.pack(fill='x')
        def invalid(*_):
            win.packet=None;win.generation+=1
            if hasattr(win,'apply_button'):
                try:ready=not mapper.missing(COLUMNS)
                except ValueError:ready=False
                win.apply_button.state(['!disabled'] if ready else ['disabled'])
        for var in (*vars.values(),year,month,company_ok,complete,sheet,header):trace(var,invalid)
        def show_source():
            sample.delete(*sample.get_children())
            if win.packet:
                rows=sorted(win.packet['rows']+[dict(r,error='',note=r['reason']) for r in win.packet['ignored_rows']],key=lambda r:r['row']);mapping=win.packet['mapping']
            else:
                mapping={key:win.column_labels[value.get()] for key,value in vars.items() if value.get() in win.column_labels}
                rows=[dict(row=number,raw=raw,error='Δεν ελέγχθηκε ακόμη') for number,raw in next(s for s in book['sheets'] if s['name']==sheet.get())['rows'] if number>int(header.get())][:8]
            for row in rows:
                if problems_only.get() and not row['error']:continue
                sample.insert('','end',values=(row['row'],*(row['raw'].get(mapping.get(k),'—') for k in COLUMNS),row['error'] or row.get('note') or 'Έγκυρη γραμμή'),tags=('issue',) if win.packet and row['error'] else ())
        trace(problems_only,lambda *_:show_source())
        def load_headers(event=None):
            invalid()
            try:line=int(header.get())
            except ValueError:status.set('Γράψε έγκυρο αριθμό γραμμής τίτλων.');return
            selected_sheet=next(s for s in book['sheets'] if s['name']==sheet.get());headers.clear();headers.update(next((raw for number,raw in selected_sheet['rows'] if number==line),{}))
            periods=self.service.source_months(selected_sheet,line,book['epoch1904'])
            if len(periods)==1:
                period=next(iter(periods));year.set(period[:4]);month.set(MONTHS[int(period[5:])-1])
                status.set(f'Το αρχείο αφορά {month.get()} {year.get()}. Η περίοδος επιλέχθηκε από τις ημερομηνίες· η ημερομηνία έκδοσης είναι υποχρεωτικό κριτήριο συμφωνίας.')
            # These are explicitly unrelated to reconciliation. Retain their
            # raw cells, but do not offer them as mapping choices.
            proposed=self.service.saved_mapping(self.owner.company,headers)
            if not proposed:proposed=auto_mapping(headers,'ebs')
            mapper.set_headers(headers,proposed,excluded_labels=EBS_IGNORED)
            win.column_labels=mapper.lookup
            result_tree.delete(*result_tree.get_children());show_source()
            hint.set('«Εναλ. παρ/κό» ↔ «Παραστατικό» Σύμβολον ERP, μαζί με ΑΦΜ, Αξία, ΦΠΑ και Σύνολο. Η ημερομηνία έκδοσης πρέπει να ταυτίζεται. Ο μήνας περιορίζει την περίοδο εργασίας. «Παρ/κό» και «Κατ.» αγνοούνται.')
        sheet_box.bind('<<ComboboxSelected>>',load_headers);header_box.bind('<Return>',load_headers)
        trace(header,lambda *_:load_headers())
        def check(auto_commit=False):
            try:
                start,end=month_bounds(year.get(),MONTHS.index(month.get())+1);line=int(header.get())
                mapping=mapper.mapping()
            except (ValueError,KeyError):status.set('Έλεγξε μήνα, έτος, γραμμή τίτλων και στήλες.');return
            if len(mapping)!=len(COLUMNS):status.set('Επίλεξε ημερομηνία και τις πέντε στήλες: Εναλ. παρ/κό, Α.Φ.Μ., Αξία, ΦΠΑ, Σύνολο.');return
            if len(set(mapping.values()))!=len(mapping):status.set('Η ίδια στήλη χρησιμοποιείται δύο φορές. Διόρθωσε την αντιστοίχιση.');return
            if not company_ok.get():status.set('Επιβεβαίωσε πρώτα ότι η εξαγωγή αφορά την εταιρεία και τον επιλεγμένο μήνα.');return
            selected_sheet=sheet.get();attested=company_ok.get();full=complete.get()
            generation=win.generation
            def execute():
                erp=ERP(self.owner.directory)
                try:return EBSReconciliation(erp).preview(self.owner.company,book['filename'],selected_sheet,line,mapping,start,end,owner['vat'],complete=full,company_confirmed=attested,data=book['data'])
                finally:erp.close()
            def done(packet):
                if not win.winfo_exists():return
                if win.generation!=generation:status.set('Οι επιλογές άλλαξαν· χρειάζεται νέα προεπισκόπηση.');return
                win.packet=packet;win.apply_button.state(['!disabled'] if packet['can_commit'] else ['disabled'])
                problems_only.set(any(r['error'] for r in packet['rows']));show_source()
                self.owner.status.set('Η προεπισκόπηση συμφωνίας είναι έτοιμη. Δεν έχει γίνει καταχώριση στο EBS.')
                documents={r['id']:r for r in self.service.documents(self.owner.company)}
                result_tree.delete(*result_tree.get_children())
                for document,result in packet['results'].items():
                    row=documents[document]
                    result_tree.insert('','end',iid=str(document),values=(result_title(result),reference(row),row['vat'],amount(row['net_minor']),amount(row['tax_minor']),amount(row['gross_minor']),result['reason']))
                counts=Counter(display_state(r) for r in packet['results'].values());summary=' · '.join(f'{TITLES[k]}: {v}' for k,v in counts.items())
                if not packet['can_commit']:
                    status.set(f'Δεν αποθηκεύεται ως πλήρης: {len({i["row"] for i in packet["blocking_issues"]})} γραμμές με πρόβλημα. Δες τα ακριβή κελιά στον «Έλεγχο αρχείου». Έλεγξε τις εξαιρέσεις ή κάνε νέα προεπισκόπηση χωρίς «Πλήρης κατάλογος».')
                else:status.set(('Μερική συμφωνία· δεν τεκμηριώνει απουσία από EBS και δεν επιτρέπει νέα RPA. ' if not packet['complete'] else '')+f'Αρχείο: {len(packet["rows"])} γραμμές δεδομένων · {sum(bool(r["error"]) for r in packet["rows"])} με ελλείψεις. '+(summary or 'Δεν υπάρχουν παραστατικά Σύμβολον ERP στον επιλεγμένο μήνα.'))
                pages.select(sample_tab if any(r['error'] for r in packet['rows']) else results_tab)
                if auto_commit and packet['can_commit']:apply()
            self.owner.run_worker(execute,done)
        def apply():
            if not win.packet or not win.packet['can_commit'] or self.owner.busy:return
            packet=win.packet
            save_mapping=remember.get()
            def execute():
                erp=ERP(self.owner.directory)
                try:return EBSReconciliation(erp).commit(packet,confirmed=True,remember=save_mapping)
                finally:erp.close()
            def done(result):
                if win.winfo_exists():win.destroy()
                self.applied(dict(result,month=packet['start'][:7]))
            self.owner.run_worker(execute,done)
        win.apply_button=ttk.Button(bottom,text='Εφαρμογή',style='Primary.TButton',command=lambda:apply() if win.packet else check(True));win.apply_button.pack(side='right')
        load_headers()
        if not edit_mapping and not mapper.missing(COLUMNS):pages.select(sample_tab)
        win.pages=pages;win.mapping_page=mapping_tab;win.mapping_control=mapper
        self.owner._sync_import_button()
        win.mapping_vars=vars;win.complete_var=complete;win.company_ok_var=company_ok;win.check=check
        win.validation_tree=sample;win.results_tree=result_tree;win.problems_only_var=problems_only;win.status_var=status;win.period_vars=(year,month);return win
