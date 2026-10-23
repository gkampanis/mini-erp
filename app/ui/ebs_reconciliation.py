"""Existing workspace tab: inspect real headers, reconcile, then explicitly run RPA."""
from collections import Counter
from datetime import date
import json
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,simpledialog
from app.application.ebs_reconciliation import EBSReconciliation
from app.application.service import ERP
from app.application.periods import MONTHS,month_bounds

COLUMNS={'invoice':'Εναλ. παρ/κό','vat':'Α.Φ.Μ.','net':'Αξία','tax':'ΦΠΑ','gross':'Σύνολο'}

STATES={'Όλα':None,'Καταχωρισμένα':'registered','Μη καταχωρισμένα':'not_registered','Χρειάζονται έλεγχο':'review','Δεν εντοπίστηκε στο Excel':'not_found','Χωρίς συμφωνία':'unreconciled'}
TITLES={v:k for k,v in STATES.items() if v}
SOURCES={'excel_ebs':'Excel EBS','rpa_operator':'RPA · οπτικός έλεγχος','rpa_attempt':'Προσπάθεια RPA · εκκρεμεί έλεγχος','manual_operator':'Χειροκίνητη επιβεβαίωση','':'—'}

class ReconciliationTab:
    def __init__(self,owner,parent):
        from app.ui.desktop import table
        self.owner=owner;self.service=EBSReconciliation(owner.erp);self.rows={};self.sort=('issue_date',False)
        ttk.Label(parent,text='Συμφωνία με Excel / EBS',style='Section.TLabel').pack(anchor='w')
        ttk.Label(parent,text='Ίδιος μήνας με τη βασική λίστα. Η εισαγωγή δεν εκτελεί καταχώριση. Μόνο πλήρης, ελεγμένη εξαγωγή επιτρέπει χαρακτηρισμό «Μη καταχωρισμένα».',style='Subtitle.TLabel',wraplength=1000).pack(anchor='w',pady=6)
        controls=ttk.Frame(parent);controls.pack(fill='x',pady=8)
        ttk.Button(controls,text='Εισαγωγή Excel / ODS EBS',style='Primary.TButton',command=self.choose).pack(side='left')
        self.query=tk.StringVar();ttk.Entry(controls,textvariable=self.query,width=20).pack(side='left',fill='x',expand=True,padx=8)
        self.filter=tk.StringVar(value='Όλα');box=ttk.Combobox(controls,textvariable=self.filter,values=tuple(STATES),state='readonly',width=26);box.pack(side='left',padx=8);box.bind('<<ComboboxSelected>>',lambda _:self.refresh())
        ttk.Button(controls,text='Αναζήτηση',command=self.refresh).pack(side='left')
        self.counts=tk.StringVar();ttk.Label(parent,textvariable=self.counts,style='Subtitle.TLabel').pack(anchor='w',pady=6)
        bottom=ttk.Frame(parent);bottom.pack(side='bottom',fill='x',pady=8)
        ttk.Button(bottom,text='Άνοιγμα παραστατικού',command=self.open).pack(side='left')
        ttk.Button(bottom,text='Άνοιγμα PDF',command=self.pdf).pack(side='left',padx=6)
        ttk.Button(bottom,text='Σύγκριση στοιχείων',command=self.details).pack(side='left')
        checks=ttk.Frame(parent);checks.pack(side='bottom',fill='x',pady=4)
        ttk.Button(checks,text='Οπτική επιβεβαίωση στο EBS',command=self.confirm).pack(side='left')
        ttk.Button(checks,text='Ιστορικό συμφωνιών',command=self.history).pack(side='left',padx=6)
        ttk.Button(checks,text='Μη καταχωρισμένα → κύρια λίστα',command=self.pending).pack(side='right')
        self.tree=table(parent,('status','invoice','name','vat','issue_date','net_minor','tax_minor','gross_minor','reason','source','filename','when'),('Κατάσταση','Παραστατικό','Επωνυμία','ΑΦΜ','Ημερομηνία','Καθαρή €','ΦΠΑ €','Σύνολο €','Αιτιολόγηση','Πηγή','Αρχείο','Χρόνος'),{'reason':420,'status':200,'source':180,'name':240})
        self.tree.bind('<Double-1>',lambda _:self.open())
        self.tree.bind('<Return>',lambda _:self.open())
        for key in self.tree['columns']:self.tree.heading(key,command=lambda k=key:self.sort_by(k))
    def sort_by(self,key):self.sort=(key,not self.sort[1] if self.sort[0]==key else False);self.refresh()
    def refresh(self):
        from app.ui.desktop import amount,when,reference
        selected=self.tree.selection();self.rows=self.service.results(self.owner.company)
        month=self.owner._month_values.get(self.owner.month_filter.get());query=self.query.get().strip().casefold()
        rows=[r for r in self.rows.values() if r['direction']=='incoming' and (not month or r['issue_date'].startswith(month))]
        counts=Counter(r['status'] for r in rows)
        self.counts.set(' · '.join(f'{label}: {counts[state]}' for state,label in TITLES.items()))
        wanted=STATES[self.filter.get()]
        rows=[r for r in rows if (not wanted or r['status']==wanted) and (not query or any(query in str(r[k] or '').casefold() for k in ('name','vat','series','number','mark','reason')))]
        for r in rows:r['invoice']=reference(r)
        key,reverse=self.sort;rows.sort(key=lambda r:r.get(key) or (0 if key.endswith('_minor') else ''),reverse=reverse)
        self.tree.delete(*self.tree.get_children())
        for r in rows:self.tree.insert('','end',iid=str(r['id']),values=(TITLES[r['status']],reference(r),r['name'],r['vat'],when(r['issue_date']),amount(r['net_minor']),amount(r['tax_minor']),amount(r['gross_minor']),r['reason'],SOURCES[r['source']],r['filename'],r['when']))
        self.tree.selection_set([s for s in selected if self.tree.exists(s)])
    def chosen(self):return int(self.tree.selection()[0]) if self.tree.selection() else None
    def open(self):
        document=self.chosen()
        if document is not None:self.owner.open_detail(document)
    def pdf(self):
        document=self.chosen()
        if document is not None:self.owner.open_pdf(document)
    def details(self):
        document=self.chosen()
        if document is None:return
        from app.ui.desktop import table,amount,reference
        row,entries=self.service.evidence(self.owner.company,document)
        win=tk.Toplevel(self.owner.root);win.title('Σύγκριση ΑΑΔΕ / Mini ERP — Excel EBS');win.geometry('1000x550')
        ttk.Label(win,text=TITLES[row['status']]+' · '+row['reason'],wraplength=950,style='Subtitle.TLabel').pack(anchor='w',padx=16,pady=12)
        tree=table(win,('field','local','excel'),('Πεδίο','Mini ERP / ΑΑΔΕ','Excel EBS'),{'field':180,'local':320,'excel':380})
        for entry in entries or [None]:
            item=entry['normalized'] if entry else {}
            tree.insert('','end',values=('Γραμμή Excel','',entry['row_number'] if entry else 'Δεν υπάρχει αντιστοίχιση'))
            values=[('ΑΦΜ',row['vat'],item.get('vat','—')),('Παραστατικό',reference(row),entry['original_reference'] if entry else '—')]
            values.extend((label,amount(row[key]),amount(item[key]) if key in item else '—') for label,key in (('Καθαρή €','net_minor'),('ΦΠΑ €','tax_minor'),('Σύνολο €','gross_minor')))
            for values_row in values:tree.insert('','end',values=values_row)
        win.comparison_tree=tree;return win
    def pending(self):
        from app.ui.desktop import STATES
        self.owner.query.set('');self.owner.state_filter.set(STATES[3]);self.owner.group_filter.set('Όλες οι ομάδες');self.owner.refresh()
        self.owner.notebook.select(self.owner.documents_tab)
        self.owner.status.set('Επίλεξε εγγραφές και «Έλεγχος χωρίς καταχώριση» ή «Καταχώριση μη καταχωρισμένων». Καταχωρισμένα και αμφίβολα εξαιρούνται αυτόματα.')
    def confirm(self):
        document=self.chosen()
        if document is None or self.owner.busy or self.owner.rpa_panel.running:return
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
        if self.owner.busy or self.owner.rpa_panel.running:return
        path=filedialog.askopenfilename(parent=self.owner.root,filetypes=[('Εξαγωγή EBS','*.xlsx *.xlsm *.ods')])
        if path:self.owner.run_worker(lambda:self.service.layout(path),lambda book:self.import_dialog(book))
    def import_dialog(self,book):
        from app.ui.desktop import table,amount,reference
        from app.infrastructure.importers.excel import header_mapping
        win=tk.Toplevel(self.owner.root);win.title('Συμφωνία EBS · '+book['filename']);win.geometry('1120x760');win.minsize(920,650)
        self.owner.status.set('Το αρχείο διαβάστηκε. Έλεγξε τις στήλες και την περίοδο πριν την προεπισκόπηση.')
        win.transient(self.owner.root);win.grab_set();win.packet=None;win.generation=0
        body=ttk.Frame(win,padding=14);body.pack(fill='both',expand=True)
        owner=self.owner.erp.db.execute('SELECT vat,name FROM companies WHERE id=?',(self.owner.company,)).fetchone()
        ttk.Label(body,text=owner['name']+' · ΑΦΜ '+owner['vat'],style='Section.TLabel').pack(anchor='w')
        top=ttk.Frame(body);top.pack(fill='x',pady=8)
        sheet=tk.StringVar(value=book['sheets'][0]['name']);header=tk.StringVar(value='1')
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
        canvas=tk.Canvas(mapping_tab,highlightthickness=0,background='#f3f6fb')
        scroll=ttk.Scrollbar(mapping_tab,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');canvas.pack(fill='both',expand=True)
        mapping_content=ttk.Frame(canvas);mapping_window=canvas.create_window((0,0),window=mapping_content,anchor='nw')
        mapping_content.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda event:canvas.itemconfigure(mapping_window,width=event.width))
        vars={k:tk.StringVar(value='—') for k in COLUMNS};columns={};headers={}
        for index,key in enumerate(COLUMNS):
            ttk.Label(mapping_content,text=COLUMNS[key],wraplength=160).grid(row=index//2,column=(index%2)*2,sticky='w',pady=7,padx=8)
            box=ttk.Combobox(mapping_content,textvariable=vars[key],state='readonly',width=24);box.grid(row=index//2,column=(index%2)*2+1,sticky='ew',padx=8);columns[key]=box
        hint=tk.StringVar();ttk.Label(mapping_content,textvariable=hint,style='Subtitle.TLabel',wraplength=820).grid(row=3,column=0,columnspan=4,sticky='w',pady=12)
        problems_only=tk.BooleanVar(value=False)
        ttk.Checkbutton(sample_tab,text='Μόνο γραμμές με πρόβλημα',variable=problems_only).pack(anchor='w',pady=4)
        sample=table(sample_tab,('row',*COLUMNS,'issue'),('Γραμμή','Εναλ. παρ/κό','Α.Φ.Μ.','Αξία','ΦΠΑ','Σύνολο','Έλεγχος / κελί'),{'row':65,'invoice':170,'vat':120,'net':90,'tax':90,'gross':90,'issue':450})
        sample.tag_configure('issue',background='#fff1ed')
        result_tree=table(results_tab,('status','invoice','vat','net','tax','gross','reason'),('Κατάσταση','Παραστατικό Mini ERP','Α.Φ.Μ.','Αξία','ΦΠΑ','Σύνολο','Αιτιολόγηση'),{'status':180,'invoice':180,'vat':120,'net':90,'tax':90,'gross':90,'reason':450})
        company_ok=tk.BooleanVar(value=False);complete=tk.BooleanVar(value=False);remember=tk.BooleanVar(value=True)
        ttk.Checkbutton(footer,text=f'Επιβεβαιώνω ότι η εξαγωγή ανήκει στην εταιρεία ΑΦΜ {owner["vat"]} και στον επιλεγμένο μήνα',variable=company_ok).pack(anchor='w',pady=4)
        ttk.Checkbutton(footer,text='Πλήρης κατάλογος όλων των καταχωρισμένων για την εταιρεία και τον μήνα',variable=complete).pack(anchor='w',pady=4)
        ttk.Checkbutton(footer,text='Αποθήκευση αντιστοίχισης για ίδια διάταξη αρχείου',variable=remember).pack(anchor='w',pady=4)
        status=tk.StringVar(value='Έλεγξε τις πέντε στήλες και επίλεξε «Προεπισκόπηση συμφωνίας».')
        ttk.Label(footer,textvariable=status,style='Subtitle.TLabel',wraplength=870).pack(anchor='w',pady=8)
        bottom=ttk.Frame(footer);bottom.pack(fill='x')
        def invalid(*_):
            win.packet=None;win.generation+=1
            if hasattr(win,'apply_button'):win.apply_button.state(['disabled'])
        for var in (*vars.values(),year,month,company_ok,complete,sheet,header):var.trace_add('write',invalid)
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
        problems_only.trace_add('write',lambda *_:show_source())
        def load_headers(event=None):
            from app.infrastructure.importers.legacy_primitives import norm,NAMES
            invalid()
            try:line=int(header.get())
            except ValueError:status.set('Γράψε έγκυρο αριθμό γραμμής τίτλων.');return
            selected_sheet=next(s for s in book['sheets'] if s['name']==sheet.get());headers.clear();headers.update(next((raw for number,raw in selected_sheet['rows'] if number==line),{}))
            # These are explicitly unrelated to reconciliation. Retain their
            # raw cells, but do not offer them as mapping choices.
            labels={f'{index+1}: {title}':index for index,title in headers.items() if norm(title) not in NAMES['date'] and norm(title) not in ('παρ κο','κατ','συναλλασσομενος','τιτλος')};win.column_labels=labels
            proposed=self.service.saved_mapping(self.owner.company,headers)
            if not proposed:
                proposed={k:v for k,v in header_mapping(headers).items() if k in COLUMNS}
                # Actual EBS export labels; positions may change. Neither the
                # internal EBS reference nor its category is invoice identity.
                for key,label in COLUMNS.items():
                    matches=[i for i,title in headers.items() if norm(title)==norm(label)]
                    if len(matches)==1:proposed[key]=matches[0]
            for key,box in columns.items():
                box.configure(values=('—',*labels));vars[key].set(next((label for label,index in labels.items() if index==proposed.get(key)),'—'))
            result_tree.delete(*result_tree.get_children());show_source()
            hint.set('«Εναλ. παρ/κό» ↔ «Παραστατικό» Mini ERP, μαζί με ΑΦΜ, Αξία, ΦΠΑ και Σύνολο. Ο μήνας ορίζει την περίοδο εργασίας· η ημερομηνία δεν είναι κριτήριο συμφωνίας. «Παρ/κό» και «Κατ.» αγνοούνται.')
        sheet_box.bind('<<ComboboxSelected>>',load_headers);header_box.bind('<Return>',load_headers)
        header.trace_add('write',lambda *_:load_headers())
        ttk.Button(top,text='Εμφάνιση στηλών',command=load_headers).pack(side='right')
        def check():
            try:
                start,end=month_bounds(year.get(),MONTHS.index(month.get())+1);line=int(header.get())
                mapping={key:win.column_labels[value.get()] for key,value in vars.items() if value.get()!='—'}
            except (ValueError,KeyError):status.set('Έλεγξε μήνα, έτος, γραμμή τίτλων και στήλες.');return
            if len(mapping)!=len(COLUMNS):status.set('Επίλεξε και τις πέντε στήλες: Εναλ. παρ/κό, Α.Φ.Μ., Αξία, ΦΠΑ, Σύνολο.');return
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
                    result_tree.insert('','end',iid=str(document),values=(TITLES[result['status']],reference(row),row['vat'],amount(row['net_minor']),amount(row['tax_minor']),amount(row['gross_minor']),result['reason']))
                counts=Counter(r['status'] for r in packet['results'].values());summary=' · '.join(f'{TITLES[k]}: {v}' for k,v in counts.items())
                if not packet['can_commit']:
                    status.set(f'Δεν αποθηκεύεται ως πλήρης: {len({i["row"] for i in packet["blocking_issues"]})} γραμμές με πρόβλημα. Δες τα ακριβή κελιά στον «Έλεγχο αρχείου». Διόρθωσε την εξαγωγή ή κάνε νέα προεπισκόπηση χωρίς «Πλήρης κατάλογος».')
                else:status.set(f'Αρχείο: {len(packet["rows"])} γραμμές δεδομένων · {len(packet["ignored_rows"])} επικεφαλίδες / σημειώσεις. '+(summary or 'Δεν υπάρχουν παραστατικά Mini ERP στον επιλεγμένο μήνα.'))
                pages.select(sample_tab if any(r['error'] for r in packet['rows']) else results_tab)
            self.owner.run_worker(execute,done)
        def apply():
            if not win.packet or not win.packet['can_commit'] or self.owner.busy:return
            packet=win.packet
            if not messagebox.askyesno('Επιβεβαίωση συμφωνίας','Έλεγξες εταιρεία, περίοδο, mapping και αποτέλεσμα; Θα αποθηκευτεί μόνο η συμφωνία, χωρίς καταχώριση στο EBS.',parent=win):return
            save_mapping=remember.get()
            def execute():
                erp=ERP(self.owner.directory)
                try:return EBSReconciliation(erp).commit(packet,confirmed=True,remember=save_mapping)
                finally:erp.close()
            def done(result):
                if win.winfo_exists():win.destroy()
                self.owner.refresh();self.refresh()
            self.owner.run_worker(execute,done)
        ttk.Button(bottom,text='Προεπισκόπηση συμφωνίας',command=check).pack(side='left')
        win.apply_button=ttk.Button(bottom,text='Αποθήκευση συμφωνίας',style='Primary.TButton',command=apply,state='disabled');win.apply_button.pack(side='right')
        load_headers();win.mapping_vars=vars;win.complete_var=complete;win.company_ok_var=company_ok;win.check=check
        win.validation_tree=sample;win.results_tree=result_tree;win.problems_only_var=problems_only;win.status_var=status;return win
