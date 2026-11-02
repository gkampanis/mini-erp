"""Document-specific corrective navigation for every skipped posting row."""
import sqlite3
import tkinter as tk
from tkinter import ttk,messagebox
from app.ui.copy_text import copy_text


def issue_actions(reason,reviewable=False):
    text=reason.casefold()
    def contains(*values):return any(value.casefold() in text for value in values)
    excluded=text.startswith(tuple(value.casefold() for value in ('καταχωρισμένο','υπάρχει ήδη στο ebs','υπάρχει επιβεβαιωμένη καταχώριση'))) or contains('αγορές, έσοδα','ομάδας 2','εκδοθέν','μη υποστηριζόμενο είδος')
    excel=contains('excel','συμφωνία','κατάλογ','εξαγωγ','μερική','πολλαπλές','αντιστοιχίσεις','διαφορετικά/ελλιπή')
    return dict(compare=excel,account=not excluded and contains('λογαριασ','προετοιμασ','ομάδας 6','φπα'),
                settings=not excluded and contains('mapper','mapping','θέσεις','σημείο ebs','γραμμές ebs'),
                import_excel=excel and not excluded,review=reviewable)


def open_issues(owner,skipped,on_retry=None):
    from app.application.review_permissions import ReviewPermissions
    from app.ui.desktop import read_text
    company=owner.company
    rows=[]
    for item in skipped:
        document=item.get('document')
        try:detail,_=owner.erp.detail(company,document) if document is not None else ({},[])
        except (ValueError,sqlite3.Error):detail={}
        reference=item.get('reference') or '/'.join(str(detail.get(key) or '') for key in ('series','number')).strip('/') or str(document or '—')
        rows.append(dict(item,reference=reference,name=item.get('name') or detail.get('name',''),vat=detail.get('vat','')))
    win=tk.Toplevel(owner.root);win.title('Εκκρεμότητες καταχώρισης EBS');win.geometry('1120x720');win.minsize(850,500)
    body=ttk.Frame(win,padding=16);body.pack(fill='both',expand=True)
    ttk.Label(body,text=f'{len(rows)} εγγραφές χρειάζονται ενέργεια',style='Section.TLabel').pack(anchor='w')
    area=ttk.Frame(body);area.pack(fill='both',expand=True,pady=10)
    tree=ttk.Treeview(area,columns=('reference','name','reason'),show='headings',selectmode='browse',height=9)
    for key,label,width in [('reference','Παραστατικό',170),('name','Πιστωτής',260),('reason','Αιτία',570)]:tree.heading(key,text=label);tree.column(key,width=width)
    scroll=ttk.Scrollbar(area,orient='vertical',command=tree.yview);tree.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right',fill='y');tree.pack(fill='both',expand=True)
    for index,row in enumerate(rows):tree.insert('','end',iid=str(index),values=(row['reference'],row['name'],row.get('reason','')))
    header=copy_text(body,'',style='Section.TLabel');header.pack(fill='x',pady=(3,6))
    reason=read_text(body,'');reason.configure(height=5);reason.pack(fill='x')
    actions=ttk.Frame(body);actions.pack(fill='x',pady=(12,0));buttons={}
    def valid():
        if owner.company!=company:
            messagebox.showerror('Εκκρεμότητες EBS','Άλλαξε η ενεργή εταιρεία· άνοιξε ξανά τις εκκρεμότητες.',parent=win);return False
        return not owner.busy and not owner.rpa_panel.running
    def inspect(document):
        return [row for row in ReviewPermissions(owner.erp).inspect(company,[document]) if not row.get('posting_permitted')]
    def selected():
        keys=tree.selection();return rows[int(keys[0])] if keys else None
    def run(action):
        row=selected()
        if not valid() or row is None:return
        document=row.get('document')
        if action=='compare':owner.reconciliation.show_document_comparison(document)
        elif action=='account':
            from app.ui.quick_account import open_account
            open_account(owner,document)
        elif action=='detail':owner.open_detail(document)
        elif action=='settings':owner.rpa_panel.settings()
        elif action=='import':owner.choose_excel(purpose='ebs')
        elif action=='review':
            from app.ui.posting_review import open_review
            try:requirements=inspect(document)
            except (ValueError,RuntimeError,sqlite3.Error) as error:messagebox.showerror('Έλεγχος EBS',str(error),parent=win);return
            if requirements:open_review(owner,requirements,on_authorized=lambda accepted:retry())
    def retry():
        if not valid():return
        win.destroy()
        if on_retry:on_retry()
    for key,label in [('compare','Σύγκριση με Excel'),('account','Λογαριασμός καρτέλας'),('detail','Στοιχεία παραστατικού'),('settings','Ρυθμίσεις EBS'),('import','Εισαγωγή νέου Excel'),('review','Προχώρησε στο EBS')]:
        button=ttk.Button(actions,text=label,command=lambda action=key:run(action));button.grid(row=0 if len(buttons)<3 else 1,column=len(buttons)%3,sticky='ew',padx=3,pady=3);buttons[key]=button
    for col in range(3):actions.columnconfigure(col,weight=1)
    footer=ttk.Frame(body);footer.pack(fill='x',pady=(12,0))
    ttk.Button(footer,text='Κλείσιμο',command=win.destroy).pack(side='left')
    buttons['retry']=ttk.Button(footer,text='Επανάληψη επιλογής',command=retry);buttons['retry'].pack(side='right')
    def update(event=None):
        row=selected()
        header.configure(state='normal');header.delete(0,'end');header.insert(0,(f"{row['reference']} · {row['name']} · ΑΦΜ {row['vat']} · #{row.get('document','—')}" if row else 'Επίλεξε εγγραφή'));header.configure(state='readonly')
        reason.configure(state='normal');reason.delete('1.0','end');reason.insert('1.0',row.get('reason','') if row else '');reason.configure(state='disabled')
        reviewable=False
        if row and row.get('document') is not None and owner.company==company:
            try:reviewable=bool(inspect(row['document']))
            except (ValueError,RuntimeError,sqlite3.Error):pass
        available=issue_actions(row.get('reason',''),reviewable) if row else {}
        for key,button in buttons.items():
            enabled=bool(on_retry) if key=='retry' else bool(row and row.get('document') is not None and (key=='detail' or available.get('import_excel' if key=='import' else key)))
            button.state(['!disabled'] if enabled and not owner.busy and not owner.rpa_panel.running else ['disabled'])
    tree.bind('<<TreeviewSelect>>',update)
    win.issue_tree=tree;win.issue_reason=reason;win.issue_buttons=buttons;win.issue_rows=rows
    if rows:tree.selection_set('0')
    update();return win
