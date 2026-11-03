"""One explicit account decision per creditor/VAT signature, reused thereafter."""
import tkinter as tk
import sqlite3
from tkinter import ttk,messagebox
from app.application.vat_lines import VATLines,signature,vat_label
from app.domain.preparation import preparation_values
from app.ui.copy_text import copy_text
from app.infrastructure.aade.lines import posting_source_lines


def open_rules(owner,requirements=None,*,counterparty=None,on_saved=lambda:None):
    if owner.busy or owner.rpa_panel.running:return
    company=owner.company;service=VATLines(owner.erp);items={}
    for requirement in requirements or []:
        cp=requirement['counterparty_id']
        for line in posting_source_lines(requirement['analysis']):
            key=(cp,*signature(line))
            item=items.setdefault(key,dict(counterparty=cp,name=requirement['name'],vat_category=key[1],vat_exemption=key[2] or None,net_minor=0,tax_minor=0,document=requirement['document']))
            item['net_minor']+=line['net_minor'];item['tax_minor']+=line['tax_minor']
    if counterparty is not None:
        card=owner.erp.db.execute('SELECT name FROM counterparties WHERE company_id=? AND id=?',(company,counterparty)).fetchone()
        if card is None:raise ValueError('Δεν βρέθηκε πιστωτής')
        for rule in service.rules(company,counterparty):items[(counterparty,*signature(rule))]=dict(rule,counterparty=counterparty,name=card['name'],net_minor=None,tax_minor=None)
    if not items:
        messagebox.showinfo('Λογαριασμοί ανά ΦΠΑ','Οι επιπλέον λογαριασμοί ορίζονται όταν διαβαστεί το πρώτο παραστατικό με διαφορετικό ΦΠΑ.',parent=owner.root);return
    win=tk.Toplevel(owner.root);win.title('Λογαριασμοί ανά ΦΠΑ');win.geometry('980x530');win.minsize(800,380)
    body=ttk.Frame(win,padding=18);body.pack(fill='both',expand=True)
    ttk.Label(body,text='Λογαριασμοί πιστωτή ανά ΦΠΑ',style='Section.TLabel').pack(anchor='w')
    ttk.Label(body,text='Ο βασικός λογαριασμός συμπληρώνεται από την καρτέλα. Όρισε τον επιπλέον λογαριασμό· η επιλογή αποθηκεύεται για τα επόμενα παραστατικά.',style='Subtitle.TLabel',wraplength=900).pack(anchor='w',pady=(7,14))
    frame=ttk.Frame(body);frame.pack(fill='both',expand=True)
    from app.ui.theme import colors
    canvas=tk.Canvas(frame,highlightthickness=0,background=colors(body)['bg']);scroll=ttk.Scrollbar(frame,command=canvas.yview)
    scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True);canvas.configure(yscrollcommand=scroll.set)
    grid=ttk.Frame(canvas);window=canvas.create_window((0,0),window=grid,anchor='nw')
    grid.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
    for column,title in enumerate(('Πιστωτής','ΦΠΑ','Καθαρή €','ΦΠΑ €','Βασικός','Λογαριασμός')):ttk.Label(grid,text=title).grid(row=0,column=column,sticky='w',padx=6,pady=7)
    grid.columnconfigure(0,weight=1);forms={};primary_by_cp={}
    used_primary={item['counterparty'] for item in items.values() if any(r['use_primary'] for r in service.rules(company,item['counterparty']))}
    from app.ui.desktop import amount
    for index,(key,item) in enumerate(items.items(),1):
        cp=item['counterparty'];known={signature(r):r for r in service.rules(company,cp)};rule=known.get(key[1:])
        values=owner.erp.db.execute('SELECT expenses_account FROM counterparty_accounts WHERE company_id=? AND counterparty_id=?',(company,cp)).fetchone()
        primary=''
        if item.get('document'):
            approval=owner.erp.preparation(company,item['document']);primary=approval['account_code'] if approval and approval['nature_group']=='6' else ''
        if not primary:primary=values[0] if values and values[0] else ''
        primary_by_cp[cp]=primary
        selected=bool(rule['use_primary']) if rule else bool(primary and cp not in used_primary and item['vat_category'] not in (7,8))
        if selected:used_primary.add(cp)
        primary_var=tk.BooleanVar(value=selected);account=tk.StringVar(value=primary if selected else rule['account'] if rule else '')
        copy_text(grid,item['name'],width=26).grid(row=index,column=0,sticky='ew',padx=6,pady=9)
        label=vat_label(item)+(f" · εξαίρ. {item['vat_exemption']}" if item['vat_exemption'] else '')
        copy_text(grid,label,width=len(label)).grid(row=index,column=1,sticky='ew',padx=6)
        for column,field in ((2,'net_minor'),(3,'tax_minor')):
            summary=amount(item[field]) if item[field] is not None else '—'
            copy_text(grid,summary,width=max(8,len(summary))).grid(row=index,column=column,sticky='ew',padx=6)
        entry=ttk.Entry(grid,textvariable=account,width=23);entry.grid(row=index,column=5,sticky='ew',padx=6)
        def toggle(var=primary_var,value=account,widget=entry,code=primary):
            if var.get():value.set(code);widget.configure(state='readonly')
            else:widget.configure(state='normal')
        ttk.Checkbutton(grid,variable=primary_var,command=toggle,state='normal' if primary else 'disabled').grid(row=index,column=4)
        toggle();forms[key]=dict(primary=primary_var,account=account,item=item)
    def save():
        if owner.company!=company or owner.busy or owner.rpa_panel.running:return
        grouped={}
        try:
            for (cp,category,exempt),form in forms.items():
                primary=form['primary'].get();account=form['account'].get().strip()
                preparation_values('6',primary_by_cp[cp] if primary else account,'','local_operator',True)
                grouped.setdefault(cp,[]).append(dict(vat_category=category,vat_exemption=exempt or None,use_primary=primary,account=None if primary else account))
            with owner.erp.db:
                if not owner.erp.db.in_transaction:owner.erp.db.execute('BEGIN IMMEDIATE')
                for cp,rules in grouped.items():service.save_rules(company,cp,rules,confirmed=True)
        except (ValueError,RuntimeError,sqlite3.Error) as exc:messagebox.showerror('Λογαριασμοί ανά ΦΠΑ',str(exc),parent=win);return
        win.destroy();owner.refresh();on_saved()
    actions=ttk.Frame(body);actions.pack(fill='x',pady=(12,0))
    ttk.Button(actions,text='Άκυρο',command=win.destroy).pack(side='left')
    ttk.Button(actions,text='Αποθήκευση λογαριασμών και συνέχεια' if requirements else 'Αποθήκευση λογαριασμών',style='Primary.TButton',command=save).pack(side='right')
    win.vat_forms=forms;win.vat_save=save;return win
