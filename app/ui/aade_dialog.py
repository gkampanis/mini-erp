"""Company-scoped myDATA API credentials, separate from TAXISnet passwords."""
import tkinter as tk
from tkinter import ttk,messagebox
import webbrowser
import sqlite3
from app.infrastructure.aade.credentials import OFFICIAL_DOCS,VaultUnavailable


def open_settings(owner):
    win=tk.Toplevel(owner.root);win.title('ΑΑΔΕ · Κωδικοί myDATA API');win.geometry('780x520');win.minsize(690,480)
    panel=ttk.Frame(win,padding=24);panel.pack(fill='both',expand=True)
    ttk.Label(panel,text='ΑΑΔΕ / myDATA REST API',style='Section.TLabel').pack(anchor='w')
    ttk.Label(panel,text='Χρησιμοποίησε κωδικούς API myDATA (όνομα χρήστη API και subscription key). Οι προσωπικοί κωδικοί TAXISnet δεν χρειάζονται και δεν αποθηκεύονται εδώ.',style='Subtitle.TLabel',wraplength=680).pack(anchor='w',pady=(8,20))
    environment=tk.StringVar(value='Δοκιμαστικό');username=tk.StringVar();key=tk.StringVar()
    choices={'Δοκιμαστικό':'test','Παραγωγικό':'production'}
    form=ttk.Frame(panel);form.pack(fill='x');form.columnconfigure(1,weight=1)
    ttk.Label(form,text='Περιβάλλον').grid(row=0,column=0,sticky='w',pady=8)
    box=ttk.Combobox(form,textvariable=environment,values=tuple(choices),state='readonly')
    box.grid(row=0,column=1,sticky='ew',padx=(16,0))
    ttk.Label(form,text='Όνομα χρήστη API').grid(row=1,column=0,sticky='w',pady=8)
    ttk.Entry(form,textvariable=username).grid(row=1,column=1,sticky='ew',padx=(16,0))
    ttk.Label(form,text='Subscription key').grid(row=2,column=0,sticky='w',pady=8)
    secret=ttk.Entry(form,textvariable=key,show='●');secret.grid(row=2,column=1,sticky='ew',padx=(16,0))
    reveal=tk.BooleanVar(value=False)
    ttk.Checkbutton(panel,text='Εμφάνιση κλειδιού',variable=reveal,command=lambda:secret.configure(show='' if reveal.get() else '●')).pack(anchor='w',pady=12)
    status=tk.StringVar(value='Δεν έγινε δοκιμή σύνδεσης ή αποστολή παραστατικών.')
    ttk.Label(panel,textvariable=status,style='Subtitle.TLabel',wraplength=680).pack(anchor='w',pady=12)
    def load(event=None):
        username.set('');key.set('')
        try:
            values=owner.erp.mydata_credentials(owner.company,choices[environment.get()])
            username.set(values['username']);key.set(values['key'])
            status.set('Κωδικοί αποθηκευμένοι στο Windows Credential Manager.' if values['key'] else 'Δεν υπάρχουν αποθηκευμένοι κωδικοί για αυτό το περιβάλλον.')
        except VaultUnavailable as exc:status.set(str(exc))
    box.bind('<<ComboboxSelected>>',load)
    def save():
        try:
            owner.erp.save_mydata_credentials(owner.company,choices[environment.get()],username.get(),key.get(),confirmed=True)
        except (ValueError,VaultUnavailable,sqlite3.Error) as exc:
            messagebox.showerror('Δεν αποθηκεύτηκαν κωδικοί',str(exc),parent=win);return
        status.set('Αποθηκεύτηκαν με ασφάλεια. Δεν έγινε ακόμη έλεγχος API ή αποστολή.')
        key.set('');reveal.set(False);secret.configure(show='●')
    actions=ttk.Frame(panel);actions.pack(side='bottom',fill='x',pady=(12,0))
    ttk.Button(actions,text='Επίσημες οδηγίες ΑΑΔΕ',command=lambda:webbrowser.open(OFFICIAL_DOCS)).pack(side='left')
    ttk.Button(actions,text='Αποθήκευση κωδικών',style='Primary.TButton',command=save).pack(side='right')
    stored=owner.erp.db.execute('SELECT environment FROM aade_settings WHERE company_id=?',(owner.company,)).fetchone()
    if stored:environment.set('Παραγωγικό' if stored[0]=='production' else 'Δοκιμαστικό')
    load()
    return win
