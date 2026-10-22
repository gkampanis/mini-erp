"""Special registry credentials and explicit company-name lookup preview."""
import tkinter as tk
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
