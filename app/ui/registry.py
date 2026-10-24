"""Special registry credentials and explicit company-name lookup preview."""
import tkinter as tk
import queue
import threading
from tkinter import ttk,messagebox
from app.application.service import ERP
from app.application.registry import Registry
from app.infrastructure.aade.credentials import VaultUnavailable


def settings(owner,parent=None):
    win=tk.Toplevel(parent or owner.root);win.title('ΑΑΔΕ · Ειδικοί κωδικοί Μητρώου');win.geometry('760x380')
    panel=ttk.Frame(win,padding=20);panel.pack(fill='both',expand=True)
    ttk.Label(panel,text='Αναζήτηση επωνυμίας από ΑΦΜ',style='Section.TLabel').pack(anchor='w')
    ttk.Label(panel,text='Ειδικοί κωδικοί «Βασικών Στοιχείων Μητρώου Επιχειρήσεων». Είναι διαφορετικοί από TAXISnet και myDATA API.',wraplength=680,style='Subtitle.TLabel').pack(anchor='w',pady=12)
    user=tk.StringVar();password=tk.StringVar();ttk.Label(panel,text='Όνομα χρήστη υπηρεσίας').pack(anchor='w');ttk.Entry(panel,textvariable=user).pack(fill='x',pady=6)
    ttk.Label(panel,text='Κωδικός υπηρεσίας').pack(anchor='w');ttk.Entry(panel,textvariable=password,show='●').pack(fill='x',pady=6)
    status=tk.StringVar();ttk.Label(panel,textvariable=status,wraplength=680).pack(anchor='w',pady=8)
    try:
        existing=Registry(owner.erp).read_credentials(owner.company)
        if existing:user.set(existing['username']);status.set('Υπάρχουν αποθηκευμένοι κωδικοί στο Windows Credential Manager.')
    except VaultUnavailable as exc:status.set(str(exc))
    def save():
        if owner.busy:return
        try:Registry(owner.erp).save_credentials(owner.company,user.get(),password.get(),confirmed=True)
        except (ValueError,VaultUnavailable) as exc:messagebox.showerror('Κωδικοί Μητρώου',str(exc),parent=win);return
        password.set('');status.set('Αποθηκεύτηκαν με ασφάλεια. Η αναζήτηση γίνεται από την καρτέλα αντισυμβαλλομένου.')
    ttk.Button(panel,text='Αποθήκευση ειδικών κωδικών',style='Primary.TButton',command=save).pack(side='bottom',anchor='e')
    return win


def find(owner,counterparty,parent,on_saved=lambda:None):
    if owner.busy:return
    vault=owner.erp.credential_store
    def execute():
        erp=ERP(owner.directory,credential_store=vault)
        try:return Registry(erp).preview(owner.company,counterparty)
        finally:erp.close()
    def done(values):
        if not parent.winfo_exists():return
        address=' '.join(values.get(k,'') for k in ('postal_address','postal_address_no','postal_zip_code','postal_area_description'))
        if not messagebox.askyesno('Στοιχεία Μητρώου',f"ΑΦΜ: {values['afm']}\nΕπωνυμία: {values['onomasia']}\nΔιεύθυνση: {address}\nΔΟΥ: {values.get('doy_descr','')}\n\nΝα ενημερωθεί η ίδια καρτέλα; Ο κωδικός, το ΑΦΜ και οι λογαριασμοί διατηρούνται.",parent=parent):return
        try:Registry(owner.erp).apply(owner.company,counterparty,values,confirmed=True)
        except ValueError as exc:messagebox.showerror('Μητρώο',str(exc),parent=parent);return
        owner.refresh();on_saved(values)
    owner.run_worker(execute,done)


def fill_missing(owner):
    if owner.busy or owner.rpa_panel.running:return
    win=tk.Toplevel(owner.root);win.title('Συμπλήρωση κενών επωνυμιών από ΑΦΜ');win.geometry('690x250')
    panel=ttk.Frame(win,padding=20);panel.pack(fill='both',expand=True)
    ttk.Label(panel,text='Μητρώο ΑΑΔΕ · όλοι οι μήνες της ενεργής εταιρείας',style='Section.TLabel').pack(anchor='w')
    status=tk.StringVar(value='Προετοιμασία αναζήτησης κενών επωνυμιών…')
    ttk.Label(panel,textvariable=status,wraplength=640).pack(anchor='w',pady=14)
    progress=ttk.Progressbar(panel,mode='determinate');progress.pack(fill='x')
    cancel=threading.Event();updates=queue.Queue();company=owner.company;vault=owner.erp.credential_store
    stop=ttk.Button(panel,text='Διακοπή μετά το τρέχον αίτημα',command=cancel.set);stop.pack(anchor='e',pady=12)
    finished={'value':False}
    def execute():
        erp=ERP(owner.directory,credential_store=vault)
        try:return Registry(erp).fill_missing(company,cancel=cancel,notice=updates.put)
        finally:erp.close()
    def done(report):
        finished['value']=True;owner.refresh()
        if not win.winfo_exists():return
        text=f"Συμπληρώθηκαν: {report['filled']} · Παραλείφθηκαν: {report['skipped']} · Δεν βρέθηκαν: {report['not_found']} · Απέτυχαν: {report['failed']}"
        if report['cancelled']:text+='\nΗ διακοπή ολοκληρώθηκε. Οι επιτυχείς αλλαγές διατηρήθηκαν.'
        if report['stopped']:text+='\n'+report['stopped']
        status.set(text);owner.status.set(text);stop.configure(text='Κλείσιμο',command=win.destroy)
        progress.configure(value=report['total'],maximum=max(1,report['total']))
    def poll():
        if not win.winfo_exists():return
        if finished['value']:return
        try:
            while True:
                item=updates.get_nowait();progress.configure(maximum=max(1,item['total']),value=item['done'])
                status.set(f"Ελέγχθηκαν {item['done']} από {item['total']} κενές επωνυμίες. Οι επιτυχείς συμπληρώσεις αποθηκεύονται.")
        except queue.Empty:pass
        if not finished['value'] and owner.busy:win.after(100,poll)
        elif not finished['value']:stop.configure(text='Κλείσιμο',command=win.destroy)
    win.protocol('WM_DELETE_WINDOW',lambda:win.destroy() if finished['value'] or not owner.busy else cancel.set())
    owner.run_worker(execute,done);win.after(100,poll)
    win.cancel_event=cancel;win.status_var=status;return win
