"""One settings entry point for optional components and shareable diagnostics."""
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from app.infrastructure.optional_packages import install
from app.infrastructure import camoufox_install
from app.infrastructure.crashlog import export

def open_settings(owner,section=None):
    win=tk.Toplevel(owner.root);win.title('Ρυθμίσεις Mini ERP');win.geometry('820x630');win.minsize(740,580)
    tabs=ttk.Notebook(win);tabs.pack(fill='both',expand=True,padx=16,pady=16)
    connections,pdf,support=[ttk.Frame(tabs,padding=18) for _ in range(3)]
    for frame,label in ((connections,'Συνδέσεις'),(pdf,'PDF και λήψεις'),(support,'Υποστήριξη')):tabs.add(frame,text=label)
    ttk.Label(connections,text='Συνδέσεις εταιρείας',style='Section.TLabel').pack(anchor='w',pady=(0,12))
    ttk.Button(connections,text='ΑΑΔΕ / myDATA · εταιρεία και κωδικοί',command=owner.open_aade).pack(fill='x',pady=6)
    from app.ui.registry import settings as registry_settings
    ttk.Button(connections,text='Μητρώο ΑΑΔΕ · ειδικοί κωδικοί',command=lambda:registry_settings(owner,win)).pack(fill='x',pady=6)
    ttk.Button(connections,text='EBS / RPA · αντιστοίχιση και ελεγχόμενη εκτέλεση',command=owner.rpa_panel.settings).pack(fill='x',pady=6)
    state=tk.StringVar(value='Camoufox: εγκατεστημένο' if camoufox_install.ready() else 'Camoufox: δεν έχει εγκατασταθεί (προαιρετικό)')
    def install_feature(feature):
        if owner.busy:return
        text='Η εγκατάσταση γίνεται σε χωριστό φάκελο MiniERP.'
        if feature=='camoufox':text='Ο Camoufox θα εγκατασταθεί στον φάκελο της εφαρμογής: Optional/Camoufox. Λήψη περίπου 1,31 GB και τουλάχιστον 7 GB ελεύθερα. Απαιτούνται Windows x64 και δικαίωμα εγγραφής στον φάκελο. Θα ελεγχθεί ο browser πριν ενεργοποιηθεί.'
        if not messagebox.askyesno('Εγκατάσταση',text+'\nΝα ξεκινήσει;',parent=win):return
        state.set('Εγκατάσταση σε εξέλιξη… μπορεί να χρειαστούν αρκετά λεπτά.')
        def done(_):
            if win.winfo_exists():state.set('Η εγκατάσταση ολοκληρώθηκε.')
            if feature in ('pdf','browser'):
                for detail in list(owner._details.values()):
                    if detail.winfo_exists() and hasattr(detail,'pdf_pane'):
                        pane=detail.pdf_pane;pane.setup.pack_forget();pane.show()
        owner.run_worker(camoufox_install.install if feature=='camoufox' else lambda:install(feature),done)
    ttk.Label(pdf,text='Προβολή και ανάκτηση παραστατικών',style='Section.TLabel').pack(anchor='w',pady=(0,10))
    ttk.Label(pdf,text='Η κανονική λήψη και η εκτύπωση PDF συνεχίζουν με Chromium.\nΟ Camoufox είναι πρόσθετη επιλογή για εκκρεμή PDF· CAPTCHA ολοκληρώνεται από εσένα.',wraplength=710).pack(anchor='w',pady=8)
    for label,feature in [('Εγκατάσταση προβολής PDF','pdf'),('Εγκατάσταση browser PDF (Chromium)','browser'),('Εγκατάσταση Camoufox (προαιρετικό)','camoufox')]:
        ttk.Button(pdf,text=label,command=lambda f=feature:install_feature(f)).pack(fill='x',pady=6)
    ttk.Button(connections,text='Εγκατάσταση RPA adapter',command=lambda:install_feature('rpa')).pack(fill='x',pady=6)
    ttk.Label(pdf,textvariable=state,wraplength=710).pack(anchor='w',pady=12)
    ttk.Label(support,text='Μικρό διαγνωστικό για υποστήριξη',style='Section.TLabel').pack(anchor='w',pady=10)
    ttk.Label(support,text='Καταγράφει τύπο σφάλματος, έκδοση Python και θέσεις κώδικα.\nΔεν καταγράφει κωδικούς, μηνύματα σφαλμάτων, URL ή στοιχεία παραστατικών.\nΔεν αποστέλλεται αυτόματα. Το εξάγεις και το στέλνεις εσύ όταν χρειαστεί.',wraplength=710).pack(anchor='w',pady=8)
    def save_log():
        destination=filedialog.asksaveasfilename(parent=win,defaultextension='.txt',initialfile='MiniERP-crashlog.txt',filetypes=[('Διαγνωστικό','*.txt')])
        if destination:
            try:export(owner.directory,destination)
            except OSError:messagebox.showerror('Διαγνωστικό','Δεν αποθηκεύτηκε. Διάλεξε φάκελο με δικαίωμα εγγραφής.',parent=win);return
            messagebox.showinfo('Διαγνωστικό','Το αρχείο αποθηκεύτηκε. Μπορείς να το στείλεις για έλεγχο.',parent=win)
    ttk.Button(support,text='Αποθήκευση crashlog για αποστολή',command=save_log).pack(anchor='w',pady=14)
    if section=='pdf':tabs.select(pdf)
    elif section=='support':tabs.select(support)
    win.settings_tabs=tabs;return win
