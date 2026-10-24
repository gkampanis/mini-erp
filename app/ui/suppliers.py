"""Supplier overview and explicit bulk account propagation using existing cards."""
import sqlite3
import tkinter as tk
from tkinter import ttk,messagebox
from app.application.supplier_accounts import SupplierAccounts

class Suppliers:
    def __init__(self,owner,parent):
        from app.ui.desktop import table
        self.owner=owner;self.service=SupplierAccounts(owner.erp)
        header=ttk.Frame(parent);header.pack(fill='x',pady=(0,12))
        ttk.Label(header,text='Προμηθευτές και λογαριασμοί EBS',style='Section.TLabel').pack(anchor='w')
        ttk.Label(header,text='Αποθήκευσε λογαριασμό ανά προμηθευτή για τα εκκρεμή και επόμενα παραστατικά του. Οι αγορές ομάδας 2 δεν καταχωρούνται στο EBS.',style='Subtitle.TLabel',wraplength=1000).pack(anchor='w',pady=6)
        filters=ttk.Frame(header);filters.pack(fill='x')
        self.query=tk.StringVar();entry=ttk.Entry(filters,textvariable=self.query);entry.pack(side='left',fill='x',expand=True)
        entry.bind('<Return>',lambda _:self.refresh());self.filter=tk.StringVar(value='Όλοι')
        box=ttk.Combobox(filters,textvariable=self.filter,values=('Όλοι','Χωρίς λογαριασμό','Με λογαριασμό','Χωρίς επωνυμία'),state='readonly',width=24);box.pack(side='left',padx=8);box.bind('<<ComboboxSelected>>',lambda _:self.refresh())
        ttk.Button(filters,text='Αναζήτηση',command=self.refresh).pack(side='left')
        self.names_button=ttk.Button(header,text='Συμπλήρωση κενών επωνυμιών από ΑΦΜ',command=self.fill_missing_names)
        self.names_button.pack(anchor='w',pady=(8,0))
        actions=ttk.Frame(parent);actions.pack(side='bottom',fill='x',pady=10)
        ttk.Button(actions,text='Μαζική αντιστοίχιση & ενημέρωση εκκρεμών',style='Primary.TButton',command=self.bulk).pack(side='left')
        ttk.Button(actions,text='Όλες οι καρτέλες αντισυμβαλλομένων',command=owner.open_counterparties).pack(side='right',padx=8)
        ttk.Button(actions,text='Άνοιγμα καρτέλας',command=self.open_card).pack(side='right')
        self.status=tk.StringVar(value='Επίλεξε έναν ή περισσότερους προμηθευτές (Ctrl / Shift).')
        ttk.Label(parent,textvariable=self.status,style='Subtitle.TLabel',wraplength=1050).pack(side='bottom',anchor='w',pady=6)
        self.tree=table(parent,('name','vat','group','account','state','count'),('Επωνυμία','ΑΦΜ','Ομάδα','Λογαριασμός EBS','Κατάσταση','Παραστατικά'),{'name':260,'state':260,'account':170})
        from app.ui.column_filters import ColumnFilters
        self.column_filters=ColumnFilters(self.tree,self.filter_rows,rows=lambda:self.rows,value=lambda r,k:r.get({'state':'account_state','count':'document_count'}.get(k,k)),show_summary=True)
        self.sort=('name',False)
        for key in self.tree['columns']:self.tree.heading(key,command=lambda k=key:self.sort_by(k))
        self.tree.configure(selectmode='extended');self.tree.bind('<Double-1>',lambda _:self.open_card())
    def refresh(self):
        self.names_button.state(['disabled'] if self.owner.busy or self.owner.rpa_panel.running else ['!disabled'])
        self.source_rows=self.service.rows(self.owner.company,self.query.get().strip())
        self.filter_rows()
    def filter_rows(self):
        selected=self.tree.selection();self.tree.delete(*self.tree.get_children());self.rows={}
        rows=[]
        for row in getattr(self,'source_rows',[]):
            if self.filter.get()=='Χωρίς λογαριασμό' and row['account']:continue
            if self.filter.get()=='Με λογαριασμό' and not row['account']:continue
            from app.domain.counterparty_names import missing_name
            if self.filter.get()=='Χωρίς επωνυμία' and not missing_name(row['name'],row['vat']):continue
            rows.append(row)
        for row in self.column_filters.apply(rows):
            self.rows[row['id']]=row;self.tree.insert('','end',iid=str(row['id']),values=(row['name'],row['vat'],row['group'] or '—',row['account'] or '—',row['account_state'],row['document_count']))
        self.tree.selection_set([key for key in selected if self.tree.exists(key)])
        from app.ui.table_actions import sort_tree
        key,reverse=self.sort
        sort_tree(self.tree,self.rows,key,reverse,value=lambda r:self.column_filters.raw(r,key))
        self.column_filters.sync_headings()
    def sort_by(self,key):
        from app.ui.table_actions import sort_tree
        self.sort=(key,not self.sort[1] if self.sort[0]==key else False)
        sort_tree(self.tree,self.rows,*self.sort,value=lambda r:self.column_filters.raw(r,key))
        self.column_filters.sync_headings()
    def fill_missing_names(self):
        from app.ui.registry import fill_missing
        return fill_missing(self.owner)
    def open_card(self):
        from app.ui.counterparties import open_detail
        selected=self.tree.selection()
        if selected:return open_detail(self.owner,int(selected[0]),on_saved=self.refresh)
    def bulk(self):
        if self.owner.busy or self.owner.rpa_panel.running:return
        ids=[int(key) for key in self.tree.selection()]
        if not ids:messagebox.showinfo('Προμηθευτές','Επίλεξε προμηθευτές από τη λίστα.',parent=self.owner.root);return
        win=tk.Toplevel(self.owner.root);win.title('Μαζική αντιστοίχιση λογαριασμού');win.geometry('700x350')
        body=ttk.Frame(win,padding=20);body.pack(fill='both',expand=True)
        ttk.Label(body,text=f'{len(ids)} προμηθευτές · έγκριση λογαριασμού',style='Section.TLabel').pack(anchor='w',pady=10)
        group=tk.StringVar(value='6 · Έξοδα');account=tk.StringVar()
        ttk.Combobox(body,textvariable=group,values=('6 · Έξοδα','2 · Αγορές'),state='readonly').pack(fill='x',pady=6)
        ttk.Label(body,text='Λογιστικός λογαριασμός EBS').pack(anchor='w');ttk.Entry(body,textvariable=account).pack(fill='x',pady=6)
        ttk.Label(body,text='Ενημερώνονται οι εκκρεμείς εγγραφές της ίδιας ομάδας και οι μη εκτελεσμένες ουρές. Ήδη επιχειρημένες καταχωρίσεις εξαιρούνται. Δεν αλλάζει αυτόματα τίποτα μέσα στο EBS.',wraplength=640,style='Subtitle.TLabel').pack(anchor='w',pady=8)
        def save():
            try:report=self.service.save(self.owner.company,ids,group.get()[0],account.get(),confirmed=True)
            except (ValueError,sqlite3.Error) as exc:messagebox.showerror('Αντιστοίχιση',str(exc),parent=win);return
            win.destroy();self.owner.refresh()
            self.status.set(f"Ενημερώθηκαν {report['updated']} παραστατικά / {report['queues']} εγγραφές ουρών. {len(report['purchases'])} ταξινομημένες αγορές διατηρήθηκαν. {len(report['protected'])} προσπάθειες EBS εξαιρέθηκαν. {len(report['needs_review'])} απαιτούν έλεγχο.")
        ttk.Button(body,text='OK',style='Primary.TButton',command=save).pack(side='bottom',anchor='e')
        win.account_var=account;win.group_var=group;return win
