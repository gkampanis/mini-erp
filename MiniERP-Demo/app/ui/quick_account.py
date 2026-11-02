"""Fast card account edit from a pending document; uses existing propagation."""
import sqlite3
import tkinter as tk
from tkinter import ttk,messagebox
from app.application.counterparties import Counterparties
from app.application.supplier_accounts import SupplierAccounts
from app.application.ebs_reconciliation import EBSReconciliation
from app.ui.copy_text import copy_text


def extend_menu(owner,event,tree,menu):
    if owner.busy or owner.rpa_panel.running or tree is not owner.tree:return
    if owner.state_filter.get()!='Μη καταχωρισμένα' or tree.identify_region(event.x,event.y)!='cell':return
    key=tree.identify_row(event.y)
    if not key:return
    row=owner._documents.get(int(key))
    if not row or row.get('environment')!='production' or row.get('direction')!='incoming' or row.get('is_purchase'):return
    menu.add_command(label='Ορισμός λογαριασμού καρτέλας',command=lambda:open_account(owner,int(key)))
    menu.add_separator()


def open_account(owner,document):
    company=owner.company;row,_=owner.erp.detail(company,document);cp=row['counterparty_id']
    if row['vat'] in EBSReconciliation(owner.erp).excluded_vats(company):return
    service=Counterparties(owner.erp);card,_=service.detail(company,cp);before=dict(card['accounts'])
    win=tk.Toplevel(owner.root);win.title('Λογαριασμός καρτέλας');win.geometry('650x280')
    body=ttk.Frame(win,padding=18);body.pack(fill='both',expand=True)
    copy_text(body,card['name'],style='Section.TLabel').pack(fill='x')
    copy_text(body,'ΑΦΜ '+card['vat'],style='Subtitle.TLabel').pack(fill='x',pady=6)
    copy_text(body,'Τρέχων λογαριασμός: '+(before['expenses_account'] or '—'),style='Subtitle.TLabel').pack(fill='x')
    account=tk.StringVar(value=before['expenses_account'] or row.get('account_code') or '')
    values=sorted({r[0] for r in owner.erp.db.execute("SELECT expenses_account FROM counterparty_accounts WHERE company_id=? AND expenses_account<>''",(company,))})
    box=ttk.Combobox(body,textvariable=account,values=values);box.pack(fill='x',pady=8);box.focus_set()
    ttk.Label(body,text='Αποθηκεύεται στην καρτέλα και ενημερώνει τα επιλέξιμα εκκρεμή έξοδα του πιστωτή σε όλους τους μήνες.',wraplength=610,style='Subtitle.TLabel').pack(anchor='w',pady=8)
    def save():
        try:
            if owner.company!=company:raise ValueError('Άλλαξε η ενεργή εταιρεία· άνοιξε ξανά την καρτέλα')
            if owner.busy or owner.rpa_panel.running:return
            fresh,_=service.detail(company,cp)
            if fresh['accounts']!=before:raise ValueError('Ο λογαριασμός άλλαξε από άλλη οθόνη· άνοιξε ξανά την καρτέλα')
            if row['vat'] in EBSReconciliation(owner.erp).excluded_vats(company):raise ValueError('Η καρτέλα είναι στην ομάδα 2')
            report=SupplierAccounts(owner.erp).save(company,[cp],'6',account.get(),confirmed=True,classify_supplier=False)
        except (ValueError,sqlite3.Error) as exc:messagebox.showerror('Λογαριασμός καρτέλας',str(exc),parent=win);return
        win.destroy();owner.refresh();owner.status.set(f"Ο λογαριασμός καρτέλας αποθηκεύτηκε · {report['updated']} εκκρεμή ενημερώθηκαν.")
    ttk.Button(body,text='Αποθήκευση & ενημέρωση εκκρεμών',style='Primary.TButton',command=save).pack(side='bottom',anchor='e')
    win.account_var=account;win.save_account=save;return win
