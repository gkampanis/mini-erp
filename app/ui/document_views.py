"""Filtered views over the existing monthly rows; never import or post records."""
import tkinter as tk
from tkinter import ttk

DELIVERY_STATUS={'1':'Εκδόθηκε','2':'Ακυρώθηκε','3':'Σε διακίνηση','4':'Απορρίφθηκε',
                 '5':'Παράδοση μεταφορέα · αναμονή λήπτη','7':'Αποτυχία παράδοσης',
                 '8':'Ολοκληρώθηκε','9':'Επιστροφή σε διακίνηση'}
MOVEMENT_FAMILIES={'delivery_note','quantity_receipt'}


def belongs(row,view):
    movement=row['family'] in MOVEMENT_FAMILIES
    if view=='movement':return movement or row['is_delivery_note']
    direction='incoming' if row['direction']=='outgoing' and row['self_recorded_expense'] else row['direction']
    if view=='income':return not movement and direction=='outgoing'
    return not movement and direction=='incoming' and bool(row.get('is_purchase'))==(view=='purchases')


class DocumentView:
    def __init__(self,owner,parent,view):
        from app.ui.desktop import table
        self.owner,self.parent,self.view=owner,parent,view
        self.rows={};self.sort=('issue_date',False)
        bar=ttk.Frame(parent);bar.pack(fill='x',pady=(0,8))
        self.query=tk.StringVar()
        entry=ttk.Entry(bar,textvariable=self.query);entry.pack(side='left',fill='x',expand=True)
        entry.bind('<Return>',lambda _:self.refresh())
        ttk.Button(bar,text='Αναζήτηση',command=self.refresh).pack(side='left',padx=6)
        ttk.Button(bar,text='Καθαρισμός',command=self.clear).pack(side='left')
        self.kind=tk.StringVar(value='Όλα')
        choices=('Όλα','Δελτία αποστολής','Ποσοτικές παραλαβές','Τιμολόγια με διακίνηση') if view=='movement' else ('Όλα','Τιμολόγια','Πιστωτικά','Λοιπά / για έλεγχο')
        box=ttk.Combobox(bar,textvariable=self.kind,values=choices,state='readonly',width=25)
        box.pack(side='left',padx=6);box.bind('<<ComboboxSelected>>',lambda _:self.refresh())
        self.count=tk.StringVar();ttk.Label(parent,textvariable=self.count,style='Subtitle.TLabel').pack(anchor='w',pady=(0,6))
        ttk.Label(parent,text='Τίτλοι στηλών: κλικ για ταξινόμηση ↑↓ · δεξί κλικ για φίλτρο',style='Subtitle.TLabel').pack(anchor='w',pady=(0,4))
        actions=ttk.Frame(parent);actions.pack(side='bottom',fill='x',pady=(8,0))
        ttk.Button(actions,text='Άνοιγμα παραστατικού',command=self.pdf).pack(side='right')
        ttk.Button(actions,text='Στοιχεία',command=self.detail).pack(side='right',padx=6)
        common=('reference','description','name','vat','issue_date','mark')
        columns=common+('flow','issuer','receiver','correlated','delivery','display_account_code') if view=='movement' else common+('net_minor','tax_minor','gross_minor')+('display_account_code',)+(() if view=='income' else ('reconciliation',))+('pdf_state',)
        titles=('Παραστατικό','Είδος ΑΑΔΕ','Συναλλασσόμενος','ΑΦΜ','Ημερομηνία','MARK')
        titles+=('Ροή','Εκδότης / ΑΦΜ','Λήπτης / ΑΦΜ','Συσχετιζόμενα MARK','Κατάσταση διακίνησης','Λογαριασμός καρτέλας') if view=='movement' else ('Καθαρή €','ΦΠΑ €','Σύνολο €')+('Λογαριασμός καρτέλας',)+(() if view=='income' else ('Συμφωνία EBS',))+('PDF',)
        self.tree=table(parent,columns,titles,{'reference':120,'name':210,'description':230,'issuer':220,'receiver':220,'delivery':240})
        for key in columns:self.tree.heading(key,command=lambda k=key:self.sort_by(k))
        self.tree.bind('<Double-1>',self.double_click);self.tree.bind('<Return>',lambda _:self.detail())
        self.tree.bind('<ButtonRelease-1>',self.click_pdf)
        from app.ui.column_filters import ColumnFilters
        self.column_filters=ColumnFilters(self.tree,self.refresh,rows=lambda:self.rows,extra_menu=owner.purchase_menu if view in ('expenses','purchases') else None,show_summary=True)

    def clear(self):self.query.set('');self.refresh()
    def sort_by(self,key):
        from app.ui.table_actions import sort_tree
        self.sort=(key,not self.sort[1] if self.sort[0]==key else False)
        sort_tree(self.tree,self.rows,*self.sort)
        self.column_filters.sync_headings()
    def chosen(self):return int(self.tree.selection()[0]) if self.tree.selection() else None
    def detail(self):
        document=self.chosen()
        if document is not None:self.owner.open_detail(document)
    def double_click(self,event):
        if self.tree.identify_region(event.x,event.y)!='cell':return
        if 'pdf_state' in self.tree['columns'] and self.tree.identify_column(event.x)=='#'+str(list(self.tree['columns']).index('pdf_state')+1):return 'break'
        row=self.tree.identify_row(event.y)
        if row:self.tree.selection_set(row);return self.detail()
    def pdf(self):
        document=self.chosen()
        if document is not None:self.owner.open_pdf(document)
    def click_pdf(self,event):
        if 'pdf_state' not in self.tree['columns']:return
        if self.tree.identify_region(event.x,event.y)=='cell' and self.tree.identify_column(event.x)=='#'+str(list(self.tree['columns']).index('pdf_state')+1):
            row=self.tree.identify_row(event.y)
            if row:self.tree.selection_set(row);self.pdf()

    def refresh(self,*,render=True):
        from app.ui.desktop import amount,when,reference
        from app.ui.ebs_reconciliation import result_title
        query=self.query.get().strip().casefold();wanted=self.kind.get();rows=[]
        for source in getattr(self.owner,'_month_rows',[]):
            if not belongs(source,self.view):continue
            if query and query not in reference(source).casefold() and not any(query in str(source.get(k) or '').casefold() for k in ('vat','name','series','number','mark','issuer_vat','receiver_vat')):continue
            family=source['family']
            if wanted=='Δελτία αποστολής' and family!='delivery_note':continue
            if wanted=='Ποσοτικές παραλαβές' and family!='quantity_receipt':continue
            if wanted=='Τιμολόγια με διακίνηση' and not (family=='invoice' and source['is_delivery_note']):continue
            if wanted=='Τιμολόγια' and family!='invoice':continue
            if wanted=='Πιστωτικά' and family!='credit_note':continue
            if wanted=='Λοιπά / για έλεγχο' and family in ('invoice','credit_note'):continue
            row=dict(source,reference=reference(source),flow='Εισερχόμενο' if source['direction']=='incoming' else 'Εξερχόμενο',
                     issuer=' · '.join(x for x in (source['issuer_name'],source['issuer_vat']) if x) or 'Δεν δόθηκε',
                     receiver=' · '.join(x for x in (source['receiver_name'],source['receiver_vat']) if x) or 'Δεν δόθηκε',
                     correlated=', '.join(source['correlated_marks']) or '—',
                     delivery=DELIVERY_STATUS.get(source['delivery_status'],'Δεν δόθηκε' if not source['delivery_status'] else 'Κωδικός ΑΑΔΕ '+source['delivery_status']),
                     reconciliation=result_title(self.owner._evidence[source['id']]) if source['id'] in getattr(self.owner,'_evidence',{}) else '—')
            rows.append(row)
        rows=self.column_filters.apply(rows)
        key,reverse=self.sort;rows.sort(key=lambda r:(r.get(key) or 0) if key.endswith('_minor') else str(r.get(key) or '').casefold(),reverse=reverse)
        self.rows={r['id']:r for r in rows}
        self.count.set(f'{len(rows)} παραστατικά · {self.owner.month_filter.get()}')
        if not render:return
        selected=self.tree.selection();focused=self.tree.focus();x=self.tree.xview();y=self.tree.yview()
        self.tree.delete(*self.tree.get_children())
        for index,row in enumerate(rows):
            self.tree.insert('','end',iid=str(row['id']),values=[amount(row[k]) if k.endswith('_minor') else when(row[k]) if k=='issue_date' else row.get(k) or '—' for k in self.tree['columns']],tags=('alternate',) if index%2 else ())
        self.tree.selection_set([s for s in selected if self.tree.exists(s)])
        if focused and self.tree.exists(focused):self.tree.focus(focused)
        if x:self.tree.xview_moveto(x[0])
        if y:self.tree.yview_moveto(y[0])
        self.column_filters.sync_headings()
