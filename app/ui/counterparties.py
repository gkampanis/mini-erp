"""Small supplier/creditor/customer cards using the existing document identities."""
import tkinter as tk
from tkinter import ttk,messagebox
import sqlite3
from app.application.counterparties import Counterparties

ROLES={'supplier':'Προμηθευτής','creditor':'Πιστωτής','customer':'Πελάτης'}


def open_register(owner):
    from app.ui.desktop import table
    service=Counterparties(owner.erp)
    win=tk.Toplevel(owner.root);win.title('Αντισυμβαλλόμενοι · Προμηθευτές / Πιστωτές / Πελάτες');win.geometry('1020x650');win.minsize(840,530)
    body=ttk.Frame(win,padding=18);body.pack(fill='both',expand=True)
    ttk.Label(body,text='Καρτέλες αντισυμβαλλομένων',style='Section.TLabel').pack(anchor='w')
    ttk.Label(body,text='Μία καρτέλα ανά ΑΦΜ στην εταιρεία. Ενημερώνεται από την ίδια εισαγωγή Excel.',style='Subtitle.TLabel').pack(anchor='w',pady=8)
    query=tk.StringVar();row=ttk.Frame(body);row.pack(fill='x',pady=8)
    entry=ttk.Entry(row,textvariable=query);entry.pack(side='left',fill='x',expand=True,padx=(0,8))
    tree=table(body,('code','name','vat','scope','roles','count'),('Κωδικός','Επωνυμία','ΑΦΜ','Διαχωρισμός','Ρόλοι','Παραστατικά'),{'name':300,'roles':220})
    def refresh():
        tree.delete(*tree.get_children())
        for card in service.list(owner.company,query.get()):tree.insert('','end',iid=str(card['id']),values=(card['code'],card['name'],card['vat'],card['transaction_scope'],', '.join(ROLES[r] for r in card['roles']),card['document_count']))
    ttk.Button(row,text='Αναζήτηση',command=refresh).pack(side='left');entry.bind('<Return>',lambda _:refresh())
    def open_card():
        selected=tree.selection()
        if selected:open_detail(owner,int(selected[0]),on_saved=refresh)
    tree.bind('<Double-1>',lambda _:open_card());tree.bind('<Return>',lambda _:open_card())
    ttk.Button(body,text='Άνοιγμα καρτέλας',command=open_card).pack(side='bottom',anchor='e',pady=8)
    refresh();win.card_tree=tree;return win


def open_detail(owner,counterparty,on_saved=lambda:None):
    from app.ui.desktop import table,amount,reference,when
    service=Counterparties(owner.erp);card,documents=service.detail(owner.company,counterparty)
    win=tk.Toplevel(owner.root);win.title(card['code']+' · '+card['name']);win.geometry('1020x700');win.minsize(850,550)
    body=ttk.Frame(win,padding=18);body.pack(fill='both',expand=True)
    ttk.Label(body,text=f"{card['code']} · ΑΦΜ {card['vat']}",style='Section.TLabel').pack(anchor='w')
    from app.ui.registry import find as registry_find
    registry_buttons=ttk.Frame(body);registry_buttons.pack(fill='x',pady=5)
    name=tk.StringVar(value=card['name'])
    ttk.Button(registry_buttons,text='Άντληση στοιχείων από ΑΦΜ',command=lambda:registry_find(owner,counterparty,win,on_saved=lambda values:name.set(values['onomasia']))).pack(side='left')
    ttk.Entry(body,textvariable=name).pack(fill='x',pady=10)
    role_vars={role:tk.BooleanVar(value=role in card['roles']) for role in ROLES}
    line=ttk.Frame(body);line.pack(fill='x')
    for role,label in ROLES.items():ttk.Checkbutton(line,text=label,variable=role_vars[role]).pack(side='left',padx=(0,15))
    defaults=card['accounts']
    accounts=ttk.LabelFrame(body,text='Αποθηκευμένοι λογαριασμοί συναλλαγών',padding=10);accounts.pack(fill='x',pady=10)
    purchases=tk.StringVar(value=defaults['purchases_account']);expenses=tk.StringVar(value=defaults['expenses_account'])
    preferred=tk.StringVar(value={'2':'2 · Αγορές','6':'6 · Έξοδα'}.get(defaults['preferred_group'],'Επιλογή ανά παραστατικό'))
    ttk.Label(accounts,text='Αγορές · ομάδα 2').grid(row=0,column=0,sticky='w',padx=5,pady=5)
    ttk.Entry(accounts,textvariable=purchases,width=24).grid(row=0,column=1,padx=8)
    ttk.Label(accounts,text='Έξοδα · ομάδα 6').grid(row=0,column=2,sticky='w',padx=5)
    ttk.Entry(accounts,textvariable=expenses,width=24).grid(row=0,column=3,padx=8)
    ttk.Label(accounts,text='Συνήθης ομάδα').grid(row=1,column=0,sticky='w',padx=5,pady=5)
    ttk.Combobox(accounts,textvariable=preferred,values=('Επιλογή ανά παραστατικό','2 · Αγορές','6 · Έξοδα'),state='readonly',width=25).grid(row=1,column=1,columnspan=2,sticky='w',padx=8)
    ttk.Label(accounts,text='Συμπληρώνονται στα επόμενα παραστατικά για έγκριση. Δεν γίνονται αυτόματες καταχωρίσεις.',style='Subtitle.TLabel').grid(row=2,column=0,columnspan=4,sticky='w',padx=5,pady=5)
    notebook=ttk.Notebook(body);notebook.pack(fill='both',expand=True,pady=14)
    docs=ttk.Frame(notebook,padding=8);history=ttk.Frame(notebook,padding=8)
    notebook.add(docs,text='Συνδεδεμένα παραστατικά');notebook.add(history,text='Ιστορικό καρτέλας')
    tree=table(docs,('date','invoice','group','account','net','gross'),('Ημερομηνία','Παραστατικό','Ομάδα','Λογαριασμός','Καθαρή €','Σύνολο €'))
    for row in documents:tree.insert('','end',iid=str(row['id']),values=(when(row['issue_date']),reference(row),row.get('nature_group') or '—',row.get('account_code') or '—',amount(row['net_minor']),amount(row['gross_minor'])))
    def invoice():
        chosen=tree.selection()
        if not chosen:return
        owner.query.set(card['vat']);owner.refresh();owner.tree.selection_set(chosen[0]);owner.open_detail()
    tree.bind('<Double-1>',lambda _:invoice())
    import json
    events=[]
    for event in owner.erp.db.execute("SELECT * FROM audit_events WHERE company_id=? AND action IN ('counterparty_card_updated','counterparty_renamed','counterparty_named','account_rule_approved') ORDER BY id DESC",(owner.company,)):
        payload=json.loads(event['payload'])
        if payload.get('counterparty_id')==counterparty:events.append(event['created_at']+' · '+event['action']+'\n'+json.dumps(payload,ensure_ascii=False,indent=2))
    from app.ui.desktop import read_text
    read_text(history,'\n\n'.join(events) or 'Δεν υπάρχουν ακόμη αλλαγές καρτέλας.')
    bottom=ttk.Frame(body);bottom.pack(side='bottom',fill='x')
    notebook.pack_forget();notebook.pack(fill='both',expand=True,pady=14)
    ttk.Label(bottom,text=f'{len(documents)} παραστατικά · Η ομάδα/λογαριασμός ορίζονται ανά παραστατικό.',style='Subtitle.TLabel').pack(side='left')
    def save():
        if owner.busy:return
        if not messagebox.askyesno('Αποθήκευση καρτέλας','Να αποθηκευτούν επωνυμία και ρόλοι; Κωδικός και ΑΦΜ παραμένουν σταθερά.',parent=win):return
        try:service.save(owner.company,counterparty,name.get(),[r for r,v in role_vars.items() if v.get()],confirmed=True,accounts=dict(purchases_account=purchases.get(),expenses_account=expenses.get(),preferred_group=preferred.get()[0] if preferred.get()[0] in ('2','6') else None))
        except (ValueError,sqlite3.Error) as exc:messagebox.showerror('Καρτέλα',str(exc),parent=win);return
        owner.refresh();on_saved();win.destroy()
    ttk.Button(bottom,text='Αποθήκευση καρτέλας',style='Primary.TButton',command=save).pack(side='right')
    win.account_fields=(purchases,expenses,preferred);win.name_field=name;win.role_fields=role_vars;win.document_tree=tree;return win
