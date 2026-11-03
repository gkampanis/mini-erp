"""Explicit review of Excel blockers before a fresh EBS posting decision."""
import sqlite3
import tkinter as tk
from tkinter import ttk,messagebox
from app.ui.copy_text import copy_text
from app.ui.theme import colors


def open_review(owner,requirements,on_authorized=None):
    """Show backend-approved review candidates; opening grants no permission."""
    from app.application.review_permissions import ReviewPermissions
    company=owner.company
    rows={row['document']:dict(row) for row in requirements
          if row.get('status') not in ('registered','submitted') and not row.get('submitted') and not row.get('posting_permitted')}
    if not rows:
        messagebox.showinfo('Έλεγχος πριν την καταχώριση','Δεν υπάρχουν εγγραφές που χρειάζονται αυτή την έγκριση.',parent=owner.root)
        return
    win=tk.Toplevel(owner.root);win.title('Έλεγχος πριν την καταχώριση στο EBS');win.geometry('1040x650');win.minsize(800,430)
    body=ttk.Frame(win,padding=16);body.pack(fill='both',expand=True)
    ttk.Label(body,text='Έλεγξε τις εκκρεμότητες της συμφωνίας Excel',style='Section.TLabel').pack(anchor='w')
    ttk.Label(body,text='Επίλεξε για ποιες εγγραφές θέλεις να επιχειρηθεί καταχώριση στο EBS, παρά την αμφιβολία του Excel. Το «Προχώρησε στο EBS» επιτρέπει αυτή την προσπάθεια χωρίς να δηλώνει ότι έχουν ήδη καταχωριστεί.',wraplength=980,style='Subtitle.TLabel').pack(fill='x',pady=(8,12))
    area=ttk.Frame(body);area.pack(fill='both',expand=True)
    canvas=tk.Canvas(area,background=colors(body)['bg'],highlightthickness=0)
    scroll=ttk.Scrollbar(area,orient='vertical',command=canvas.yview)
    scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True);canvas.configure(yscrollcommand=scroll.set)
    content=ttk.Frame(canvas);window=canvas.create_window((0,0),window=content,anchor='nw')
    content.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>',lambda event:canvas.itemconfigure(window,width=event.width))
    selected={}
    def compare(document):
        if owner.company!=company:
            messagebox.showerror('Σύγκριση στοιχείων','Άλλαξε η ενεργή εταιρεία· άνοιξε ξανά τον έλεγχο.',parent=win);return
        owner.reconciliation.show_document_comparison(document)
    for document,row in rows.items():
        frame=ttk.Frame(content,padding=(0,9));frame.pack(fill='x')
        selected[document]=tk.BooleanVar(master=win,value=True)
        ttk.Checkbutton(frame,text='Να προχωρήσει στο EBS',variable=selected[document]).grid(row=0,column=0,sticky='w')
        ttk.Button(frame,text='Σύγκριση στοιχείων',command=lambda doc=document:compare(doc)).grid(row=0,column=1,sticky='e',padx=(12,0))
        reference=row.get('reference') or '/'.join(str(row.get(key) or '') for key in ('series','number') if row.get(key)) or str(document)
        copy_text(frame,reference,style='Section.TLabel').grid(row=1,column=0,columnspan=2,sticky='ew',pady=(6,3))
        copy_text(frame,row.get('name','')).grid(row=2,column=0,columnspan=2,sticky='ew',pady=(0,5))
        reason=tk.Text(frame,height=3,wrap='word',borderwidth=0,highlightthickness=0,takefocus=True,
                       background=colors(body)['bg'],foreground=colors(body)['ink'],exportselection=False)
        reason.insert('1.0',row['reason']);reason.configure(state='disabled')
        reason.grid(row=3,column=0,columnspan=2,sticky='ew');frame.columnconfigure(0,weight=1)
        ttk.Separator(content).pack(fill='x')
    def authorize():
        documents=[doc for doc,value in selected.items() if value.get()]
        if not documents:
            messagebox.showinfo('Έλεγχος πριν την καταχώριση','Επίλεξε τουλάχιστον μία εγγραφή για προσπάθεια στο EBS.',parent=win);return
        try:
            if owner.company!=company:raise ValueError('Άλλαξε η ενεργή εταιρεία· άνοιξε ξανά τον έλεγχο.')
            if owner.busy or owner.rpa_panel.running:return
            ReviewPermissions(owner.erp).authorize(company,documents,expected_signatures={doc:rows[doc]['signature'] for doc in documents},confirmed=True)
        except (ValueError,RuntimeError,sqlite3.Error) as error:
            messagebox.showerror('Έλεγχος πριν την καταχώριση',str(error),parent=win);return
        win.destroy();owner.refresh()
        if on_authorized:on_authorized(documents)
    actions=ttk.Frame(body);actions.pack(fill='x',pady=(12,0))
    ttk.Button(actions,text='Άκυρο',command=win.destroy).pack(side='left')
    ttk.Button(actions,text='Προχώρησε στο EBS',style='Primary.TButton',command=authorize).pack(side='right')
    win.review_vars=selected;win.review_requirements=rows;win.authorize_review=authorize
    return win

