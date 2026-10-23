"""AADE connection, incoming/outgoing reads and the user's provider PDF workflow."""
from datetime import date,timedelta
import json
from pathlib import Path
import queue
import sqlite3
import threading
import tkinter as tk
from tkinter import ttk,messagebox,filedialog,simpledialog
import webbrowser
from app.application.service import ERP
from app.application.mydata import MyData
from app.application.periods import MONTHS,month_bounds
from app.infrastructure.aade.credentials import OFFICIAL_DOCS,VaultUnavailable


def open_settings(owner,document=None,acquire=False,period=None):
    win=tk.Toplevel(owner.root);win.title('ΑΑΔΕ / myDATA · Σύνδεση και παραστατικά');win.geometry('1060x740');win.minsize(900,630)
    notebook=ttk.Notebook(win);notebook.pack(fill='both',expand=True,padx=16,pady=16)
    panel=ttk.Frame(notebook,padding=18);data_panel=ttk.Frame(notebook,padding=14)
    notebook.add(panel,text='Σύνδεση & κωδικοί');notebook.add(data_panel,text='Ληφθέντα / Εκδοθέντα / PDF')
    company=owner.erp.db.execute('SELECT vat,name FROM companies WHERE id=?',(owner.company,)).fetchone()
    ttk.Label(panel,text='Στοιχεία εταιρείας και κωδικοί API',style='Section.TLabel').pack(anchor='w')
    company_label=tk.StringVar(value=company['name']+' · ΑΦΜ '+company['vat'])
    ttk.Label(panel,textvariable=company_label,style='Subtitle.TLabel').pack(anchor='w',pady=10)
    def identify():
        current=owner.erp.db.execute('SELECT vat,name FROM companies WHERE id=?',(owner.company,)).fetchone()
        if current['vat']!='000000000':messagebox.showinfo('Εταιρεία','Το ΑΦΜ της εταιρείας είναι ήδη ορισμένο. Δεν αλλάζει για να μη συνδεθούν ξένα παραστατικά.',parent=win);return
        vat=simpledialog.askstring('ΑΦΜ εταιρείας','Πραγματικό ΑΦΜ εταιρείας των εισαγμένων παραστατικών:',parent=win)
        if not vat:return
        name=simpledialog.askstring('Επωνυμία εταιρείας','Επωνυμία εταιρείας:',parent=win)
        if not name:return
        if len(vat)!=9 or not vat.isascii() or not vat.isdigit() or vat=='000000000':messagebox.showerror('ΑΦΜ','Χρειάζεται πραγματικό ΑΦΜ 9 ψηφίων.',parent=win);return
        count=owner.erp.db.execute('SELECT count(*) FROM documents WHERE company_id=?',(owner.company,)).fetchone()[0]
        if not messagebox.askyesno('Ταυτοποίηση εταιρείας',f'Τα {count} παραστατικά της υπάρχουσας λίστας θα παραμείνουν και θα ανήκουν στην εταιρεία {name}, ΑΦΜ {vat}. Επιβεβαιώνεις ότι είναι της εταιρείας αυτής;',parent=win):return
        try:
            with owner.erp.db:
                owner.erp.db.execute('UPDATE companies SET vat=?,name=? WHERE id=?',(vat,name,owner.company))
                owner.erp.repository.audit(owner.company,'company_identified',None,dict(before=dict(current),after=dict(vat=vat,name=name)))
        except sqlite3.Error:messagebox.showerror('Εταιρεία','Δεν αποθηκεύτηκε η εταιρεία. Έλεγξε αν υπάρχει ήδη το ΑΦΜ.',parent=win);return
        company_label.set(name+' · ΑΦΜ '+vat);username.set('');key.set('');owner.refresh()
    ttk.Button(panel,text='Ορισμός πραγματικής εταιρείας αντί DEMO',command=identify).pack(anchor='w',pady=(0,10))
    ttk.Label(panel,text='API username και subscription key myDATA. Δεν χρειάζονται οι προσωπικοί κωδικοί TAXISnet.',style='Subtitle.TLabel',wraplength=850).pack(anchor='w',pady=(0,12))
    environment=tk.StringVar(value='Παραγωγικό');username=tk.StringVar();key=tk.StringVar()
    choices={'Δοκιμαστικό':'test','Παραγωγικό':'production'}
    form=ttk.Frame(panel);form.pack(fill='x');form.columnconfigure(1,weight=1)
    ttk.Label(form,text='Περιβάλλον').grid(row=0,column=0,sticky='w',pady=8)
    box=ttk.Combobox(form,textvariable=environment,values=tuple(choices),state='readonly');box.grid(row=0,column=1,sticky='ew',padx=(16,0))
    ttk.Label(form,text='Όνομα χρήστη API').grid(row=1,column=0,sticky='w',pady=8)
    win.api_username_entry=ttk.Entry(form,textvariable=username);win.api_username_entry.grid(row=1,column=1,sticky='ew',padx=(16,0))
    ttk.Label(form,text='Subscription key').grid(row=2,column=0,sticky='w',pady=8)
    secret=ttk.Entry(form,textvariable=key,show='●');win.api_key_entry=secret;secret.grid(row=2,column=1,sticky='ew',padx=(16,0))
    reveal=tk.BooleanVar(value=False)
    ttk.Checkbutton(panel,text='Εμφάνιση κλειδιού',variable=reveal,command=lambda:secret.configure(show='' if reveal.get() else '●')).pack(anchor='w',pady=8)
    from app.application.sync import Sync
    represented=tk.BooleanVar(value=False)
    auto_pdf=tk.BooleanVar(value=True)
    ttk.Checkbutton(panel,text='Εξουσιοδοτημένος λογιστής / εκπρόσωπος (αποστολή ΑΦΜ εταιρείας ως entityVatNumber)',variable=represented).pack(anchor='w',pady=6)
    status=tk.StringVar(value='Δεν έγινε ακόμη έλεγχος σύνδεσης.')
    ttk.Label(panel,textvariable=status,style='Subtitle.TLabel',wraplength=850).pack(anchor='w',pady=10)
    def load(event=None):
        username.set('');key.set('')
        try:
            values=owner.erp.mydata_credentials(owner.company,choices[environment.get()]);username.set(values['username']);key.set(values['key'])
            status.set('Οι κωδικοί υπάρχουν στο Windows Credential Manager.' if values['key'] else 'Συμπλήρωσε και αποθήκευσε τους κωδικούς για αυτό το περιβάλλον.')
        except VaultUnavailable as exc:status.set(str(exc))
    def load_options(event=None):
        load();options=Sync(owner.erp).preferences(owner.company,choices[environment.get()]);represented.set(bool(options['represented']));auto_pdf.set(bool(options['auto_pdf']) if owner.erp.db.execute('SELECT 1 FROM sync_preferences WHERE company_id=? AND environment=?',(owner.company,choices[environment.get()])).fetchone() else True)
    box.bind('<<ComboboxSelected>>',lambda event:(load_options(event),refresh()))
    ttk.Checkbutton(panel,text='Λήψη PDF μαζί με τη μαζική άντληση',variable=auto_pdf).pack(anchor='w',pady=6)
    def save():
        if owner.busy or owner.rpa_panel.running:return False
        try:owner.erp.save_mydata_credentials(owner.company,choices[environment.get()],username.get(),key.get(),confirmed=True)
        except (ValueError,VaultUnavailable,sqlite3.Error) as exc:messagebox.showerror('Δεν αποθηκεύτηκαν κωδικοί',str(exc),parent=win);return False
        Sync(owner.erp).save_preferences(owner.company,choices[environment.get()],represented.get(),auto_pdf.get())
        status.set('Οι κωδικοί αποθηκεύτηκαν. Πάτησε «Έλεγχος σύνδεσης» ή «Εύρεση παραστατικών».');key.set('');reveal.set(False);secret.configure(show='●')
        return True
    actions=ttk.Frame(panel);actions.pack(side='bottom',fill='x',pady=10)
    ttk.Button(actions,text='Επίσημες οδηγίες ΑΑΔΕ',command=lambda:webbrowser.open(OFFICIAL_DOCS)).pack(side='left')
    ttk.Button(actions,text='Αποθήκευση κωδικών',style='Primary.TButton',command=save).pack(side='right')
    first=date.today().replace(day=1);last=first-timedelta(days=1)
    year=tk.StringVar(value=str(last.year));month=tk.StringVar(value=MONTHS[last.month-1])
    if period:
        selected=date.fromisoformat(period+'-01');year.set(str(selected.year));month.set(MONTHS[selected.month-1])
    def selected_period():return month_bounds(year.get(),MONTHS.index(month.get())+1)
    header=ttk.Frame(data_panel);header.pack(fill='x')
    ttk.Label(header,text='Έτος').pack(side='left');year_box=ttk.Combobox(header,textvariable=year,values=tuple(str(y) for y in range(2000,date.today().year+2)),state='readonly',width=7);year_box.pack(side='left',padx=6)
    ttk.Label(header,text='Μήνας').pack(side='left');month_box=ttk.Combobox(header,textvariable=month,values=MONTHS,state='readonly',width=16);month_box.pack(side='left',padx=6)
    kind=tk.StringVar(value='Ληφθέντα και εκδοθέντα')
    kind_box=ttk.Combobox(header,textvariable=kind,values=('Ληφθέντα και εκδοθέντα','Ληφθέντα','Εκδοθέντα'),state='readonly',width=25);kind_box.pack(side='left',padx=6)
    cancel=threading.Event();notifications=queue.Queue()
    output=tk.StringVar(value='Άντληση εξόδων μήνα → εγγραφές στη βασική λίστα → λήψη και σύνδεση PDF. Υπάρχουσες εγγραφές Excel αντιστοιχίζονται με MARK και έλεγχο στοιχείων.')
    ttk.Label(data_panel,textvariable=output,style='Subtitle.TLabel',wraplength=950).pack(anchor='w',pady=10)
    controls=ttk.Frame(data_panel);controls.pack(fill='x',pady=(0,10))
    from app.ui.desktop import table
    results=table(data_panel,('direction','mark','invoice','kind','vat','status','pdf'),('Ροή','MARK','Παραστατικό','Είδος ΑΑΔΕ','ΑΦΜ αντισυμβαλλομένου','Συμφωνία εγγραφής','PDF'),{'kind':260,'status':200,'pdf':200})
    results.configure(selectmode='extended');records={}
    labels={'matched':'Συμφωνεί με εγγραφή','different':'Διαφορά — έλεγχος','unmatched':'Δεν υπάρχει στη βασική λίστα','cancelled_at_aade':'Ακύρωση στην ΑΑΔΕ — έλεγχος'}
    def refresh():
        if not win.winfo_exists():return
        results.delete(*results.get_children());records.clear()
        from app.infrastructure.optional_packages import activate
        activate()
        from app.infrastructure.providers.pdf_downloads import state_label
        start,end=selected_period()
        attempts={r['mark']:r['state'] for r in owner.erp.db.execute('SELECT mark,state FROM provider_attempts WHERE company_id=? AND environment=? ORDER BY id',(owner.company,choices[environment.get()]))}
        for row in MyData(owner.erp).records(owner.company,choices[environment.get()]):
            item=json.loads(row['record_json'])
            if not start<=item['date']<=end:continue
            if kind.get()=='Ληφθέντα' and item.get('direction')!='incoming':continue
            if kind.get()=='Εκδοθέντα' and item.get('direction')!='outgoing':continue
            row['item']=item;records[str(row['id'])]=row
            attempt=attempts.get(row['mark'])
            from app.domain.invoice_types import classify
            kind_label=classify(row['invoice_type'],row['is_delivery_note'])['description']
            results.insert('','end',iid=str(row['id']),values=('Ληφθέν' if item.get('direction')=='incoming' else 'Εκδοθέν',row['mark'],'/'.join(x for x in [item['series'],item['number']] if x),kind_label,item['vat'] if item.get('direction')=='incoming' else item['receiver'],labels.get(row['match_status'],row['match_status']),state_label(attempt) if attempt else 'Διαθέσιμος σύνδεσμος' if item.get('pdf_url') else 'Χωρίς σύνδεσμο'))
    def fetch(test=False):
        if owner.busy or owner.rpa_panel.running:return
        vat=owner.erp.db.execute('SELECT vat FROM companies WHERE id=?',(owner.company,)).fetchone()[0]
        if vat=='000000000':messagebox.showwarning('Εταιρεία','Όρισε πρώτα το πραγματικό ΑΦΜ από την καρτέλα Σύνδεση. Οι κωδικοί δεν στέλνονται για τη συνθετική εταιρεία.',parent=win);notebook.select(panel);return
        try:start,end=selected_period()
        except ValueError as exc:messagebox.showerror('Ημερομηνίες',str(exc),parent=win);return
        env=choices[environment.get()];rep=represented.get();vault=owner.erp.credential_store
        methods=['RequestDocs','RequestTransmittedDocs'] if kind.get()=='Ληφθέντα και εκδοθέντα' else ['RequestDocs' if kind.get()=='Ληφθέντα' else 'RequestTransmittedDocs']
        cancel.clear();output.set('Επικοινωνία με ΑΑΔΕ…');status.set('Έλεγχος / λήψη σε εξέλιξη…')
        def execute():
            service=ERP(owner.directory,credential_store=vault)
            try:
                values=[]
                for method in methods:
                    try:values.append(dict(method=method,result=MyData(service).fetch(owner.company,start,end,env,represented=rep,test=test,cancel=cancel,method=method)))
                    except (ValueError,RuntimeError,sqlite3.Error) as exc:values.append(dict(method=method,error=str(exc)))
                return values
            finally:service.close()
        def done(value):
            if not win.winfo_exists():return
            successful=[v for v in value if 'result' in v];failed=[v for v in value if 'error' in v]
            status.set('Επιτυχής επικοινωνία: '+', '.join(v['method'] for v in successful) if successful else 'Δεν ολοκληρώθηκε επικοινωνία με ΑΑΔΕ.')
            if failed:
                output.set('Ολοκληρώθηκαν '+str(len(successful))+'/'+str(len(methods))+' κλήσεις. Τα επιτυχή δεδομένα διατηρούνται. '+ ' · '.join(v['method']+': '+v['error'] for v in failed))
            else:
                output.set('Έλεγχος σύνδεσης επιτυχής. Δεν αποθηκεύτηκαν παραστατικά.' if test else 'Ολοκληρώθηκε η λήψη: '+str(sum(v['result'].get('matched',0) for v in successful))+' συμφωνούν, '+str(sum(v['result'].get('different',0) for v in successful))+' διαφέρουν, '+str(sum(v['result'].get('unmatched',0) for v in successful))+' δεν υπάρχουν στο Excel.')
            owner.refresh();refresh()
        owner.run_worker(execute,done)
    ttk.Button(actions,text='Έλεγχος σύνδεσης',command=lambda:fetch(True)).pack(side='right',padx=8)
    def full_sync():
        if owner.busy or owner.rpa_panel.running:return
        if key.get().strip() and not save():return
        try:
            start,end=selected_period()
            env=choices[environment.get()]
            Sync(owner.erp).save_preferences(owner.company,env,represented.get(),auto_pdf.get())
        except ValueError as exc:messagebox.showerror('Περίοδος',str(exc),parent=win);return
        methods=['RequestDocs','RequestTransmittedDocs'] if kind.get()=='Ληφθέντα και εκδοθέντα' else ['RequestDocs' if kind.get()=='Ληφθέντα' else 'RequestTransmittedDocs']
        cancel.clear();vault=owner.erp.credential_store;rep=represented.get()
        output.set('Άντληση βιβλίου, αναλυτικών παραστατικών και PDF…');notebook.select(data_panel)
        def execute():
            service=ERP(owner.directory,credential_store=vault)
            try:return Sync(service).run(owner.company,env,start,end,represented=rep,cancel=cancel,notice=lambda msg:notifications.put(msg),methods=methods,download=auto_pdf_value)
            finally:service.close()
        def done(result):
            if not win.winfo_exists():return
            while not notifications.empty():notifications.get_nowait()
            imported=result.get('import',{});pdf=result.get('pdf',{})
            output.set(f"Νέα στη λίστα: {imported.get('inserted',0)} · Υπήρχαν: {imported.get('duplicates',0)} · Για έλεγχο: {len(imported.get('rejected',[]))} · PDF: {pdf.get('saved',0)} · Εκκρεμή PDF: {pdf.get('pending',0)}"+(' · Βιβλίο: '+result['book_error'] if result.get('book_error') else '')+(' · PDF: '+result['pdf_error'] if result.get('pdf_error') else ''))
            if result.get('errors'):output.set(output.get()+' · Δεν ολοκληρώθηκαν: '+' · '.join(v['method']+': '+v['error'] for v in result['errors']))
            if result.get('cancelled'):output.set('Η άντληση διακόπηκε. Οι ολοκληρωμένες λήψεις διατηρούνται. '+output.get())
            if acquire:
                label=MONTHS[int(start[5:7])-1]+' '+start[:4]
                owner.month_filter.set(label);owner._month_values[label]=start[:7];owner._period_initialized=True
            owner.refresh();refresh()
        auto_pdf_value=auto_pdf.get()
        owner.run_worker(execute,done)
    ttk.Button(panel,text='Αποθήκευση & άντληση παραστατικών + PDF',style='Primary.TButton',command=full_sync).pack(fill='x',before=actions,pady=8)
    ttk.Button(data_panel,text='Άντληση Παραστατικών μήνα + PDF',style='Primary.TButton',command=full_sync).pack(fill='x',before=controls,pady=(0,8))
    ttk.Button(controls,text='1. Εύρεση παραστατικών',command=fetch).pack(side='left')
    def pdf(recovery=False,camoufox=False):
        if owner.busy or owner.rpa_panel.running:return
        selected=results.selection()
        if camoufox and not selected:
            messagebox.showinfo('Ανάκτηση PDF','Επίλεξε τα εκκρεμή παραστατικά που θέλεις να ανακτήσεις.',parent=win);return
        marks=[records[x]['mark'] for x in selected] if selected else [r['mark'] for r in records.values()]
        if camoufox:
            from app.application.provider_pdf import ProviderDatabase
            pending={str(r['mark']) for r in ProviderDatabase(owner.erp,owner.company,choices[environment.get()]).failed_download_candidates(str(owner.company))}
            marks=[mark for mark in marks if str(mark) in pending]
        if not marks:messagebox.showinfo('Παραστατικά','Κάνε πρώτα εύρεση παραστατικών ΑΑΔΕ.',parent=win);return
        from app.infrastructure.providers.local_files import desktop_directory
        try:destination=owner.directory/'pdf-archive' if camoufox else desktop_directory()
        except Exception:
            path=filedialog.askdirectory(parent=win,title='Φάκελος αρχειοθέτησης PDF')
            if not path:return
            destination=Path(path)
        if not messagebox.askyesno('Ανάκτηση PDF',f'{len(marks)} εγγραφές. Αρχειοθέτηση: {destination} / ΑΦΜ εταιρείας / YYYY-MM / MARK.pdf.\n'+('Θα ανοίξει ξεχωριστός browser. Τυχόν CAPTCHA το ολοκληρώνεις εσύ.' if recovery else 'Άμεση λήψη ή φόρτωση παρόχου στο παρασκήνιο. Τα PDF από εκτύπωση επισημαίνονται χωριστά.')+' Συνέχεια;',parent=win):return
        cancel.clear();env=choices[environment.get()]
        def execute():
            from app.application.provider_pdf import run
            service=ERP(owner.directory)
            try:
                if camoufox:
                    from app.application.camoufox_pdf import run as recover_camoufox
                    return recover_camoufox(service,owner.company,env,marks,cancel)
                return run(service,owner.company,env,destination,cancel,marks,recovery,notice=lambda msg:notifications.put(msg),observer=lambda p:notifications.put(p.text()))
            finally:service.close()
        def done(result):
            if not win.winfo_exists():return
            if result.get('incomplete_summary'):
                output.set('Η ανάκτηση διακόπηκε. Τα PDF που είχαν ήδη αποθηκευτεί διατηρούνται.');refresh();owner.refresh();return
            output.set(f"PDF: {result['saved']} αποθηκευμένα ({result['printed']} από εκτύπωση), {result['pending']} εκκρεμή, {result['skipped']} υπήρχαν ήδη.");refresh();owner.refresh()
        owner.run_worker(execute,done)
    ttk.Button(controls,text='2. Λήψη PDF',command=pdf).pack(side='left',padx=6)
    ttk.Button(controls,text='Ανάκτηση εκκρεμών',command=lambda:pdf(True)).pack(side='left')
    ttk.Button(data_panel,text='Ανάκτηση εκκρεμών με Camoufox (προαιρετικό)',command=lambda:pdf(True,True)).pack(fill='x',before=results.master,pady=(0,6))
    ttk.Button(controls,text='Διακοπή',command=cancel.set).pack(side='right')
    bottom=ttk.Frame(data_panel);bottom.pack(side='bottom',fill='x',pady=8)
    def open_link():
        chosen=results.selection()
        if not chosen:messagebox.showinfo('Παραστατικό','Επίλεξε εγγραφή από τη λίστα.',parent=win);return
        if chosen:
            url=records[chosen[0]]['item'].get('pdf_url')
            if not url:return view_pdf()
            if url:
                from urllib.parse import urlsplit
                try:
                    parsed=urlsplit(url)
                    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:raise ValueError()
                except ValueError:return
                webbrowser.open(url)
    def view_pdf():
        chosen=results.selection()
        if not chosen or owner.busy:return
        row=records[chosen[0]]
        artifact=owner.erp.db.execute("SELECT path,sha256 FROM provider_attempts WHERE company_id=? AND environment=? AND mark=? AND state IN ('saved_unverified','printed_unverified','imported_unverified') ORDER BY id DESC LIMIT 1",(owner.company,choices[environment.get()],row['mark'])).fetchone()
        if not artifact:messagebox.showinfo('PDF','Δεν έχει ακόμη αποθηκευτεί PDF. Πάτησε Λήψη PDF ή Ανάκτηση εκκρεμών.',parent=win);return
        from app.ui.pdf_pane import open_saved_pdf
        open_saved_pdf(owner,artifact['path'],artifact['sha256'])
    results.bind('<Double-1>',lambda _:view_pdf());results.bind('<Return>',lambda _:view_pdf())
    ttk.Button(bottom,text='Προβολή αποθηκευμένου PDF',command=view_pdf).pack(side='left',padx=(0,8))
    ttk.Button(bottom,text='Άνοιγμα Παραστατικού',command=open_link).pack(side='left')
    ttk.Button(bottom,text='Ρυθμίσεις λήψης PDF',command=lambda:owner.open_settings('pdf')).pack(side='right')
    results.master.pack_forget();results.master.pack(fill='both',expand=True)
    def notifications_poll():
        if not win.winfo_exists() or owner._closing:return
        try:
            while True:output.set(notifications.get_nowait())
        except queue.Empty:pass
        owner.root.after(180,notifications_poll)
    def close():cancel.set();win.destroy()
    win.protocol('WM_DELETE_WINDOW',close)
    stored=owner.erp.db.execute('SELECT environment FROM aade_settings WHERE company_id=?',(owner.company,)).fetchone()
    if stored:environment.set('Παραγωγικό' if stored[0]=='production' else 'Δοκιμαστικό')
    if document is not None:
        row,_=owner.erp.detail(owner.company,document);chosen=date.fromisoformat(row['issue_date']);year.set(str(chosen.year));month.set(MONTHS[chosen.month-1])
    load_options();refresh();notifications_poll()
    if acquire:notebook.select(data_panel)
    kind_box.bind('<<ComboboxSelected>>',lambda _:refresh())
    year_box.bind('<<ComboboxSelected>>',lambda _:refresh());month_box.bind('<<ComboboxSelected>>',lambda _:refresh())
    win.year_var=year;win.month_var=month;win.selected_period=selected_period;win.environment_var=environment;win.kind_var=kind;win.refresh_records=refresh;win.records_tree=results;win.fetch_aade=fetch;win.sync_expenses=full_sync
    return win
