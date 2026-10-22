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
from app.domain.validation import iso_date
from app.infrastructure.aade.credentials import OFFICIAL_DOCS,VaultUnavailable
from app.infrastructure.optional_packages import install


def open_settings(owner):
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
    from app.ui.registry import settings as registry_settings
    ttk.Button(panel,text='Ειδικοί κωδικοί Μητρώου · αναζήτηση επωνυμίας',command=lambda:registry_settings(owner,win)).pack(anchor='w',pady=(0,10))
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
    represented=tk.BooleanVar(value=False)
    ttk.Checkbutton(panel,text='Εξουσιοδοτημένος λογιστής / εκπρόσωπος (αποστολή ΑΦΜ εταιρείας ως entityVatNumber)',variable=represented).pack(anchor='w',pady=6)
    status=tk.StringVar(value='Δεν έγινε ακόμη έλεγχος σύνδεσης.')
    ttk.Label(panel,textvariable=status,style='Subtitle.TLabel',wraplength=850).pack(anchor='w',pady=10)
    def load(event=None):
        username.set('');key.set('')
        try:
            values=owner.erp.mydata_credentials(owner.company,choices[environment.get()]);username.set(values['username']);key.set(values['key'])
            status.set('Οι κωδικοί υπάρχουν στο Windows Credential Manager.' if values['key'] else 'Συμπλήρωσε και αποθήκευσε τους κωδικούς για αυτό το περιβάλλον.')
        except VaultUnavailable as exc:status.set(str(exc))
    box.bind('<<ComboboxSelected>>',load)
    def save():
        if owner.busy:return
        try:owner.erp.save_mydata_credentials(owner.company,choices[environment.get()],username.get(),key.get(),confirmed=True)
        except (ValueError,VaultUnavailable,sqlite3.Error) as exc:messagebox.showerror('Δεν αποθηκεύτηκαν κωδικοί',str(exc),parent=win);return
        status.set('Οι κωδικοί αποθηκεύτηκαν. Πάτησε «Έλεγχος σύνδεσης» ή «Εύρεση παραστατικών».');key.set('');reveal.set(False);secret.configure(show='●')
    actions=ttk.Frame(panel);actions.pack(side='bottom',fill='x',pady=10)
    ttk.Button(actions,text='Επίσημες οδηγίες ΑΑΔΕ',command=lambda:webbrowser.open(OFFICIAL_DOCS)).pack(side='left')
    ttk.Button(actions,text='Αποθήκευση κωδικών',style='Primary.TButton',command=save).pack(side='right')
    first=date.today().replace(day=1);last=first-timedelta(days=1)
    from_date=tk.StringVar(value=last.replace(day=1).isoformat());to_date=tk.StringVar(value=last.isoformat())
    header=ttk.Frame(data_panel);header.pack(fill='x')
    ttk.Label(header,text='Από').pack(side='left');ttk.Entry(header,textvariable=from_date,width=13).pack(side='left',padx=6)
    ttk.Label(header,text='Έως').pack(side='left');ttk.Entry(header,textvariable=to_date,width=13).pack(side='left',padx=6)
    kind=tk.StringVar(value='Ληφθέντα και εκδοθέντα')
    ttk.Combobox(header,textvariable=kind,values=('Ληφθέντα και εκδοθέντα','Ληφθέντα','Εκδοθέντα'),state='readonly',width=25).pack(side='left',padx=6)
    cancel=threading.Event();notifications=queue.Queue()
    output=tk.StringVar(value='1. Σύνδεση → 2. Εύρεση παραστατικών → 3. Λήψη PDF. Οι εγγραφές Excel συμφωνούνται με MARK, χωρίς δεύτερη φόρτωση.')
    ttk.Label(data_panel,textvariable=output,style='Subtitle.TLabel',wraplength=950).pack(anchor='w',pady=10)
    controls=ttk.Frame(data_panel);controls.pack(fill='x',pady=(0,10))
    from app.ui.desktop import table
    results=table(data_panel,('direction','mark','invoice','vat','status','pdf'),('Ροή','MARK','Παραστατικό','ΑΦΜ αντισυμβαλλομένου','Συμφωνία Excel','PDF'),{'status':200,'pdf':200})
    results.configure(selectmode='extended');records={}
    labels={'matched':'Συμφωνεί με Excel','different':'Διαφορά — έλεγχος','unmatched':'Δεν υπάρχει στο Excel','cancelled_at_aade':'Ακύρωση στην ΑΑΔΕ — έλεγχος'}
    def refresh():
        if not win.winfo_exists():return
        results.delete(*results.get_children());records.clear()
        from app.infrastructure.optional_packages import activate
        activate()
        from app.infrastructure.providers.pdf_downloads import state_label
        for row in MyData(owner.erp).records(owner.company,choices[environment.get()]):
            item=json.loads(row['record_json']);row['item']=item;records[str(row['id'])]=row
            attempt=owner.erp.db.execute('SELECT state FROM provider_attempts WHERE company_id=? AND environment=? AND mark=? ORDER BY id DESC LIMIT 1',(owner.company,choices[environment.get()],row['mark'])).fetchone()
            results.insert('','end',iid=str(row['id']),values=('Ληφθέν' if item.get('direction')=='incoming' else 'Εκδοθέν',row['mark'],'/'.join(x for x in [item['series'],item['number']] if x),item['vat'] if item.get('direction')=='incoming' else item['receiver'],labels.get(row['match_status'],row['match_status']),state_label(attempt['state']) if attempt else 'Διαθέσιμος σύνδεσμος' if item.get('pdf_url') else 'Χωρίς σύνδεσμο'))
    def fetch(test=False):
        if owner.busy:return
        vat=owner.erp.db.execute('SELECT vat FROM companies WHERE id=?',(owner.company,)).fetchone()[0]
        if vat=='000000000':messagebox.showwarning('Εταιρεία','Όρισε πρώτα το πραγματικό ΑΦΜ από την καρτέλα Σύνδεση. Οι κωδικοί δεν στέλνονται για τη συνθετική εταιρεία.',parent=win);notebook.select(panel);return
        try:start=iso_date(from_date.get());end=iso_date(to_date.get())
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
    ttk.Button(controls,text='1. Εύρεση παραστατικών',style='Primary.TButton',command=fetch).pack(side='left')
    def pdf(recovery=False):
        if owner.busy:return
        selected=results.selection();marks=[records[x]['mark'] for x in selected] if selected else [r['mark'] for r in records.values()]
        if not marks:messagebox.showinfo('Παραστατικά','Κάνε πρώτα εύρεση παραστατικών ΑΑΔΕ.',parent=win);return
        from app.infrastructure.providers.local_files import desktop_directory
        try:destination=desktop_directory()
        except Exception:
            path=filedialog.askdirectory(parent=win,title='Φάκελος αρχειοθέτησης PDF')
            if not path:return
            destination=Path(path)
        if not messagebox.askyesno('Ανάκτηση PDF',f'{len(marks)} εγγραφές. Αρχειοθέτηση: {destination} / ΑΦΜ εταιρείας / YYYY-MM / MARK.pdf.\n'+('Θα ανοίξει ξεχωριστός browser. Τυχόν CAPTCHA το ολοκληρώνεις εσύ.' if recovery else 'Άμεση λήψη ή φόρτωση παρόχου στο παρασκήνιο. Τα PDF από εκτύπωση επισημαίνονται χωριστά.')+' Συνέχεια;',parent=win):return
        cancel.clear();env=choices[environment.get()]
        def execute():
            from app.application.provider_pdf import run
            service=ERP(owner.directory)
            try:return run(service,owner.company,env,destination,cancel,marks,recovery,notice=lambda msg:notifications.put(msg),observer=lambda p:notifications.put(p.text()))
            finally:service.close()
        def done(result):
            if not win.winfo_exists():return
            output.set(f"PDF: {result['saved']} αποθηκευμένα ({result['printed']} από εκτύπωση), {result['pending']} εκκρεμή, {result['skipped']} υπήρχαν ήδη.");refresh();owner.refresh()
        owner.run_worker(execute,done)
    ttk.Button(controls,text='2. Λήψη PDF',command=pdf).pack(side='left',padx=6)
    ttk.Button(controls,text='Ανάκτηση εκκρεμών',command=lambda:pdf(True)).pack(side='left')
    ttk.Button(controls,text='Διακοπή',command=cancel.set).pack(side='right')
    bottom=ttk.Frame(data_panel);bottom.pack(side='bottom',fill='x',pady=8)
    def open_link():
        chosen=results.selection()
        if chosen:
            url=records[chosen[0]]['item'].get('pdf_url')
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
    ttk.Button(bottom,text='Άνοιγμα συνδέσμου',command=open_link).pack(side='left')
    ttk.Button(bottom,text='Εγκατάσταση browser PDF',command=lambda:owner.run_worker(lambda:install('browser'),lambda _:output.set('Ο browser εγκαταστάθηκε.')) if not owner.busy and messagebox.askyesno('Browser','Να εγκατασταθούν Playwright/Chromium σε χωριστό φάκελο MiniERP;',parent=win) else None).pack(side='right')
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
    load();refresh();notifications_poll()
    win.period_vars=(from_date,to_date);win.environment_var=environment;win.kind_var=kind;win.refresh_records=refresh;win.records_tree=results;win.fetch_aade=fetch
    return win
