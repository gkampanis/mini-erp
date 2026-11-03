"""One-time operator preview and approval, using the existing card update flow."""
import sqlite3
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from app.application.history_accounts import HistoryAccounts


class HistoryImport:
    def __init__(self,owner):
        self.owner=owner;self.company=owner.company;self.service=HistoryAccounts(owner.erp);self.packet=None;self.rows={}
        self.win=tk.Toplevel(owner.root);self.win.title('Εισαγωγή λογαριασμών από ιστορικό EBS');self.win.geometry('1250x720');self.win.minsize(950,550)
        body=ttk.Frame(self.win,padding=16);body.pack(fill='both',expand=True)
        ttk.Label(body,text='Συχνότερος λογαριασμός ανά πιστωτή',style='Section.TLabel').pack(anchor='w')
        ttk.Label(body,text='Ενημερώνονται οι εγκεκριμένες καρτέλες και τα επιλέξιμα εκκρεμή. Η ομάδα 2 και οι προηγούμενες καταχωρίσεις προστατεύονται. Διπλό κλικ για επιλογή καρτέλας ή ισοπαλία.',wraplength=1150,style='Subtitle.TLabel').pack(anchor='w',pady=8)
        actions=ttk.Frame(body);actions.pack(fill='x',pady=6)
        ttk.Button(actions,text='Άνοιγμα Excel ιστορικού',command=self.choose_file).pack(side='left')
        ttk.Button(actions,text='Επιλογή βέβαιων αντιστοιχίσεων',command=self.select_ready).pack(side='left',padx=8)
        ttk.Button(actions,text='Αντιστοίχιση επιλεγμένης γραμμής',command=self.edit).pack(side='left')
        footer=ttk.Frame(body);footer.pack(side='bottom',fill='x',pady=10)
        self.status=tk.StringVar(value='Επίλεξε το αρχείο με Συν/νος, Παρ/κό και Δαπάνη.')
        ttk.Label(footer,textvariable=self.status,wraplength=900).pack(side='left',fill='x',expand=True)
        ttk.Button(footer,text='Έγκριση & ενημέρωση επιλεγμένων',style='Primary.TButton',command=self.apply_selected).pack(side='right')
        from app.ui.desktop import table
        self.tree=table(body,('source','card','vat','current','proposed','frequency','state'),('Επωνυμία Excel','Καρτέλα εφαρμογής','ΑΦΜ','Υπάρχων','Προτεινόμενος','Χρήσεις','Κατάσταση'),{'source':250,'card':250,'state':170})
        self.tree.configure(selectmode='extended');self.tree.bind('<Double-1>',lambda _:self.edit())

    def choose_file(self):
        path=filedialog.askopenfilename(parent=self.win,title='Ιστορικό λογαριασμών EBS',filetypes=[('Excel / ODS','*.xlsx *.xlsm *.ods')])
        if path:
            try:self.load(path)
            except (ValueError,OSError,sqlite3.Error) as exc:messagebox.showerror('Ιστορικό EBS',str(exc),parent=self.win)

    def load(self,path,*,data=None):
        if self.company!=self.owner.company:raise ValueError('Άλλαξε η ενεργή εταιρεία· άνοιξε ξανά την εισαγωγή')
        self.packet=self.service.preview(self.company,path,data=data);self.rows={r['key']:dict(r) for r in self.packet['rows']};self.render()

    def ready(self,row):return bool(row['card_id'] and row['account'] and not row['excluded'] and not row['applied'])

    def render(self):
        self.tree.delete(*self.tree.get_children())
        cards={c['id']:c for c in self.packet['cards']}
        for key,row in self.rows.items():
            card=cards.get(row['card_id'],{});state='Ήδη εφαρμόστηκε' if row['applied'] else 'Ομάδα 2 · εκτός' if row['excluded'] else 'Έτοιμη για έγκριση' if self.ready(row) else 'Επίλεξε καρτέλα / λογαριασμό'
            self.tree.insert('','end',iid=key,values=(row['source_name'],card.get('name','—'),card.get('vat','—'),card.get('expenses_account') or '—',row['account'] or 'Ισοπαλία',f"{row['frequency']} / {row['total']}",state))
        self.status.set(f"{len(self.rows)} επωνυμίες · {sum(self.ready(r) for r in self.rows.values())} έτοιμες για έγκριση. Ctrl / Shift για επιλογή.")

    def select_ready(self):
        self.tree.selection_set([key for key,row in self.rows.items() if self.ready(row)])

    def edit(self):
        selected=self.tree.selection()
        if not selected:return
        row=self.rows[selected[0]];win=tk.Toplevel(self.win);win.title('Αντιστοίχιση πιστωτή');win.geometry('850x300')
        body=ttk.Frame(win,padding=16);body.pack(fill='both',expand=True)
        ttk.Label(body,text=row['source_name'],wraplength=800).pack(anchor='w',pady=8)
        candidates=row['candidates'];ids={c['id'] for c in candidates};cards=candidates+[c for c in self.packet['cards'] if c['id'] not in ids]
        labels={f"{c['name']} · ΑΦΜ {c['vat']} · #{c['id']}":c['id'] for c in cards}
        chosen=tk.StringVar(value=next((s for s,i in labels.items() if i==row['card_id']),''));account=tk.StringVar(value=row['account'] or '')
        ttk.Label(body,text='Καρτέλα εφαρμογής · οι πιθανές επωνυμίες εμφανίζονται πρώτες').pack(anchor='w')
        ttk.Combobox(body,textvariable=chosen,values=list(labels),state='readonly',width=110).pack(fill='x',pady=5)
        ttk.Label(body,text='Συχνότερος λογαριασμός · σε ισοπαλία επιλέγεις έναν από τους ισόβαθμους').pack(anchor='w')
        ttk.Combobox(body,textvariable=account,values=row['winners'],state='readonly').pack(fill='x',pady=5)
        ttk.Label(body,text=' · '.join(f'{a}: {n} χρήσεις' for a,n in row['counts'].items()),wraplength=800).pack(anchor='w')
        def save():
            if chosen.get() not in labels or account.get() not in row['winners']:return
            cp=labels[chosen.get()];card=next(c for c in cards if c['id']==cp)
            row.update(card_id=cp,account=account.get(),excluded=account.get().startswith('2') or card['vat'] in self.service.excluded_vats(self.company),applied=cp in self.service.applied(self.company,self.packet['sha256']))
            self.render();win.destroy()
        ttk.Button(body,text='Χρήση αντιστοίχισης',command=save).pack(side='bottom',anchor='e')

    def apply_selected(self):
        try:
            if self.owner.company!=self.company:raise ValueError('Άλλαξε η ενεργή εταιρεία· άνοιξε ξανά την εισαγωγή')
            selected=[self.rows[k] for k in self.tree.selection()]
            if not selected or any(not self.ready(r) for r in selected):raise ValueError('Επίλεξε μόνο έτοιμες αντιστοιχίσεις')
            if not messagebox.askyesno('Ενημέρωση λογαριασμών',f'Ενημέρωση {len(selected)} καρτελών και των επιλέξιμων εκκρεμών παραστατικών τους;',parent=self.win):return
            report=self.service.apply(self.packet,[dict(key=r['key'],card_id=r['card_id'],account=r['account']) for r in selected],confirmed=True)
            self.owner.refresh();self.load(self.packet['filename'],data=self.packet['data'])
            self.status.set(f"Ενημερώθηκαν {report['updated']} καρτέλες και {report['documents']} παραστατικά · {len(report['protected'])} προστατευμένα · {len(report['needs_review'])} για έλεγχο.")
        except (ValueError,OSError,sqlite3.Error) as exc:messagebox.showerror('Ενημέρωση λογαριασμών',str(exc),parent=self.win)
