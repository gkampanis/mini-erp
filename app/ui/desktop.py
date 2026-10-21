"""Independent Greek desktop. Only the worker touches its own SQLite connection."""
import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from app.application.service import ERP
from app.infrastructure.importers.excel import preview, NAMES

LABELS = {'vat':'ΑΦΜ', 'name':'Επωνυμία', 'date':'Ημερομηνία', 'invoice':'Ενιαίος αριθμός',
          'series':'Σειρά', 'number':'Αριθμός', 'net':'Καθαρή', 'tax':'ΦΠΑ', 'gross':'Σύνολο',
          'mark':'MARK', 'kind':'Είδος', 'description':'Περιγραφή', 'currency':'Νόμισμα'}


def amount(value):
    from decimal import Decimal
    return f'{Decimal(value)/100:.2f}'


class Desktop:
    def __init__(self, root, directory):
        self.root, self.directory = root, Path(directory)
        self.erp = ERP(directory)
        rows = self.erp.db.execute('SELECT id FROM companies ORDER BY id').fetchall()
        if not rows:
            vat = simpledialog.askstring('Εταιρεία', 'ΑΦΜ εταιρείας (9 ψηφία):', parent=root)
            name = simpledialog.askstring('Εταιρεία', 'Επωνυμία εταιρείας:', parent=root) if vat else None
            if not vat or not name:
                self.erp.close()
                root.destroy()
                return
            try:
                self.company = self.erp.company(vat, name)
            except ValueError as exc:
                messagebox.showerror('Εταιρεία',str(exc),parent=root)
                self.erp.close()
                root.destroy()
                return
        else:
            self.company = rows[0][0]
        root.title('Mini ERP · Παραστατικά')
        root.geometry('1200x800')
        root.minsize(900, 600)
        try:
            root.state('zoomed')
        except tk.TclError:
            pass
        self.work = queue.Queue()
        self.busy = False
        self.status = tk.StringVar(value='Τοπική λειτουργία · Entersoft/myDATA ανενεργά · Χωρίς λογιστικές καταχωρίσεις')
        bar = ttk.Frame(root,padding=12)
        bar.pack(fill='x')
        self.import_button = ttk.Button(bar,text='Εισαγωγή Excel',command=self.choose_excel)
        self.import_button.pack(side='left')
        self.query = tk.StringVar()
        entry = ttk.Entry(bar,textvariable=self.query,width=45)
        entry.pack(side='left',padx=12)
        entry.bind('<Return>',lambda _:self.refresh())
        ttk.Button(bar,text='Αναζήτηση ΑΦΜ / παραστατικού / MARK',command=self.refresh).pack(side='left')
        ttk.Label(root,textvariable=self.status,padding=8).pack(fill='x')
        frame = ttk.Frame(root,padding=12)
        frame.pack(fill='both',expand=True)
        columns = ('issue_date','vat','name','series','number','mark','net_minor','tax_minor','gross_minor','status')
        self.tree = ttk.Treeview(frame,columns=columns,show='headings')
        titles = ('Ημερομηνία','ΑΦΜ','Επωνυμία','Σειρά','Αριθμός','MARK','Καθαρή €','ΦΠΑ €','Σύνολο €','Κατάσταση')
        for key,title in zip(columns,titles):
            self.tree.heading(key,text=title)
            self.tree.column(key,width=105,stretch=True)
        sy = ttk.Scrollbar(frame,orient='vertical',command=self.tree.yview)
        sx = ttk.Scrollbar(frame,orient='horizontal',command=self.tree.xview)
        self.tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        self.tree.grid(row=0,column=0,sticky='nsew')
        sy.grid(row=0,column=1,sticky='ns')
        sx.grid(row=1,column=0,sticky='ew')
        frame.rowconfigure(0,weight=1)
        frame.columnconfigure(0,weight=1)
        self.tree.bind('<Double-1>',lambda _:self.open_detail())
        ttk.Button(root,text='Προβολή επιλεγμένου / Προέλευση / Ιστορικό',command=self.open_detail).pack(pady=8)
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.refresh()
        root.after(80,self.poll)

    def close(self):
        if self.busy:
            messagebox.showinfo('Εργασία σε εξέλιξη','Περίμενε να ολοκληρωθεί η τρέχουσα εργασία.',parent=self.root)
            return
        self.erp.close()
        self.root.destroy()

    def run_worker(self, function, callback):
        if self.busy:
            return
        self.busy = True
        self.import_button.state(['disabled'])
        self.status.set('Επεξεργασία…')
        def work():
            try:
                result = function()
                self.work.put((callback,result,None))
            except Exception as exc:
                self.work.put((callback,None,str(exc)))
        threading.Thread(target=work,daemon=True).start()

    def poll(self):
        try:
            callback,result,error = self.work.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.import_button.state(['!disabled'])
            if error:
                self.status.set('Η εργασία απέτυχε · Καμία μερική εισαγωγή στη βάση')
                messagebox.showerror('Σφάλμα',error,parent=self.root)
            else:
                callback(result)
        self.root.after(80,self.poll)

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        rows = self.erp.search(self.company,self.query.get().strip())
        for row in rows:
            self.tree.insert('', 'end',iid=str(row['id']),values=[amount(row[k]) if k.endswith('_minor') else ('Προς έλεγχο' if k=='status' else row[k] or '') for k in self.tree['columns']])
        self.status.set(f'{len(rows)} παραστατικά · Entersoft/myDATA ανενεργά')

    def choose_excel(self):
        path = filedialog.askopenfilename(parent=self.root,filetypes=[('Excel','*.xlsx *.xlsm')])
        if path:
            self.run_worker(lambda:preview(path),lambda item:self.show_preview(path,item))

    def show_preview(self, path, item):
        self.status.set('Ελέγξτε την αντιστοίχιση και την προεπισκόπηση πριν την εισαγωγή')
        win = tk.Toplevel(self.root)
        win.title('Προεπισκόπηση εισαγωγής — απαιτείται επιβεβαίωση')
        win.geometry('1050x760')
        ttk.Label(win,text=f'{item.filename} · Φύλλο: {item.sheet} · SHA256: {item.sha256}',wraplength=1000,padding=8).pack(fill='x')
        mapping_frame = ttk.LabelFrame(win,text='Αντιστοίχιση στηλών (επιβεβαίωσε ειδικά Σειρά / Αριθμό)',padding=8)
        mapping_frame.pack(fill='x')
        options = ['—']+[f'{k+1}: {v}' for k,v in sorted(item.headers.items())]
        lookup = {f'{k+1}: {v}':k for k,v in item.headers.items()}
        variables = {}
        for i,key in enumerate(NAMES):
            ttk.Label(mapping_frame,text=LABELS.get(key,key)).grid(row=i//4*2,column=i%4,sticky='w')
            var = tk.StringVar(value=next((s for s,k in lookup.items() if k==item.mapping.get(key)),'—'))
            variables[key] = var
            ttk.Combobox(mapping_frame,textvariable=var,values=options,state='readonly',width=28).grid(row=i//4*2+1,column=i%4,padx=2,pady=2)
        text = tk.Text(win,wrap='none',height=16)
        text.pack(fill='both',expand=True,padx=8,pady=8)
        text.insert('end',f'Έγκυρες: {len(item.records)} · Εξαιρέσεις: {len(item.rejected)}\n\n')
        for row in item.records[:100]:
            d = row['document']
            text.insert('end',f"Γραμμή {row['row']}: {d['vat']} | {d['series']}/{d['number']} | {d['issue_date']} | {amount(d['gross_minor'])} EUR\n")
        for row in item.rejected:
            text.insert('end',f"ΕΞΑΙΡΕΣΗ γραμμής {row['row']}: {row['reason']}\n")
        text.configure(state='disabled')
        def remap():
            mapping = {k:lookup[v.get()] for k,v in variables.items() if v.get()!='—'}
            win.destroy()
            self.run_worker(lambda:preview(path,mapping),lambda new:self.show_preview(path,new))
        ttk.Button(win,text='Εφαρμογή νέας αντιστοίχισης και επανέλεγχος',command=remap).pack(pady=4)
        def commit():
            current = {k:lookup[v.get()] for k,v in variables.items() if v.get()!='—'}
            if current != item.mapping:
                messagebox.showwarning('Επανέλεγχος','Εφάρμοσε πρώτα τη νέα αντιστοίχιση.',parent=win)
                return
            if not messagebox.askyesno('Επιβεβαίωση',f'Εισαγωγή {len(item.records)} έγκυρων γραμμών; Οι {len(item.rejected)} εξαιρέσεις θα διατηρηθούν στην αναφορά. Δεν γίνεται λογιστική καταχώριση.',parent=win):
                return
            win.destroy()
            def execute():
                service = ERP(self.directory)
                try:
                    return service.commit_import(self.company,item,confirmed=True)
                finally:
                    service.close()
            def done(report):
                self.refresh()
                self.show_text('Αποτελέσματα εισαγωγής',json.dumps(report,ensure_ascii=False,indent=2))
            self.run_worker(execute,done)
        button = ttk.Button(win,text='Επιβεβαιώνω αντιστοίχιση και εισαγωγή στη βάση',command=commit)
        button.pack(pady=8)
        if not item.records:
            button.state(['disabled'])

    def show_text(self, title, body):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry('850x650')
        text = tk.Text(win,wrap='word')
        text.pack(fill='both',expand=True)
        text.insert('end',body)
        text.configure(state='disabled')

    def open_detail(self):
        selected = self.tree.selection()
        if selected:
            row,events = self.erp.detail(self.company,int(selected[0]))
            labels = {'net_minor':'Καθαρή EUR','tax_minor':'ΦΠΑ EUR','gross_minor':'Σύνολο EUR'}
            body = '\n'.join(f'{labels.get(k,LABELS.get(k,k))}: {amount(v) if k.endswith("_minor") else v}' for k,v in row.items())
            self.show_text('Παραστατικό · Προέλευση · Ιστορικό',body+'\n\nΙΣΤΟΡΙΚΟ\n'+json.dumps(events,ensure_ascii=False,indent=2))
