"""Inline, raster-only PDF preview beside document details."""
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from app.application.service import ERP
from app.infrastructure.pdf_archive import KINDS,render,renderer_available


def open_document(owner,document,window,selected_attachment=None):
    import os
    import sys
    import webbrowser
    from urllib.parse import urlsplit
    try:
        attachments=owner.erp.attachments(owner.company,document)
        if attachments:
            selected=next((a for a in attachments if a['id']==selected_attachment),next((a for a in attachments if a['kind']=='invoice'),attachments[0]))
            path=owner.erp.attachment_path(owner.company,document,selected['id'])
            if sys.platform=='win32':os.startfile(str(path))
            elif not webbrowser.open(path.resolve().as_uri()):raise ValueError('Δεν άνοιξε το τοπικό PDF. Όρισε εφαρμογή προβολής PDF στο λειτουργικό.')
            return
        from app.application.mydata import MyData
        active=owner.erp.db.execute('SELECT environment FROM aade_settings WHERE company_id=?',(owner.company,)).fetchone()
        url=MyData(owner.erp).pdf_url(owner.company,document,active[0] if active else 'production')
        parsed=urlsplit(url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or any(ord(c)<33 for c in url):raise ValueError('Δεν υπάρχει έγκυρος HTTPS σύνδεσμος παρόχου.')
        if not webbrowser.open(url):raise ValueError('Δεν άνοιξε ο browser. Έλεγξε την προεπιλεγμένη εφαρμογή του λειτουργικού.')
    except (ValueError,OSError,RuntimeError) as exc:
        messagebox.showinfo('Άνοιγμα παραστατικού',str(exc)+'\nΜπορείς να δοκιμάσεις «ΑΑΔΕ → Λήψη PDF».',parent=window)



class PDFPane:
    def __init__(self,owner,parent,document,window):
        self.owner,self.parent,self.document,self.window=owner,parent,document,window
        self.page=0;self.selected=None;self.image=None;self.records={}
        top=ttk.Frame(parent,padding=(12,8));top.pack(fill='x')
        ttk.Label(top,text='PDF παραστατικού',style='Section.TLabel').pack(anchor='w')
        self.kind=tk.StringVar(value='Τιμολόγιο')
        ttk.Combobox(top,textvariable=self.kind,values=tuple(KINDS.values()),state='readonly',width=23).pack(anchor='w',pady=8)
        buttons=ttk.Frame(top);buttons.pack(fill='x')
        ttk.Button(top,text='Άνοιγμα Παραστατικού',command=self.open_document).pack(anchor='w',pady=(0,6))
        ttk.Button(top,text='ΑΑΔΕ → Λήψη PDF',command=self.fetch_aade).pack(anchor='w',pady=(0,6))
        ttk.Button(buttons,text='Προσθήκη PDF',command=self.attach).pack(side='left',padx=(0,6))
        self.files=ttk.Treeview(parent,columns=('kind','file'),show='headings',height=2,selectmode='browse')
        self.files.heading('kind',text='Είδος');self.files.heading('file',text='Συνδεδεμένο αρχείο')
        self.files.column('kind',width=120);self.files.column('file',width=200)
        self.files.pack(fill='x',padx=12,pady=(0,6));self.files.bind('<<TreeviewSelect>>',self.pick)
        self.state=tk.StringVar(value='Δεν υπάρχει συνδεδεμένο PDF.')
        ttk.Label(parent,textvariable=self.state,style='Subtitle.TLabel',wraplength=420).pack(anchor='w',padx=12,pady=4)
        controls=ttk.Frame(parent,padding=(12,4));controls.pack(fill='x')
        ttk.Button(controls,text='‹ Σελίδα',command=lambda:self.move(-1)).pack(side='left')
        ttk.Button(controls,text='Σελίδα ›',command=lambda:self.move(1)).pack(side='left',padx=6)
        self.setup=ttk.Button(controls,text='Ρύθμιση προβολής PDF',command=self.setup_renderer)
        if not renderer_available():self.setup.pack(side='left')
        canvas_frame=ttk.Frame(parent);canvas_frame.pack(fill='both',expand=True,padx=12,pady=(4,12))
        self.canvas=tk.Canvas(canvas_frame,background='#e6ecf4',highlightthickness=0)
        vertical=ttk.Scrollbar(canvas_frame,orient='vertical',command=self.canvas.yview)
        horizontal=ttk.Scrollbar(canvas_frame,orient='horizontal',command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        self.canvas.grid(row=0,column=0,sticky='nsew');vertical.grid(row=0,column=1,sticky='ns');horizontal.grid(row=1,column=0,sticky='ew')
        canvas_frame.columnconfigure(0,weight=1);canvas_frame.rowconfigure(0,weight=1)
        self.refresh()
        self.owner.root.after(350,self.auto_fetch)

    def alive(self):return self.parent.winfo_exists() and not self.owner._closing
    def current_kind(self):return next(k for k,v in KINDS.items() if v==self.kind.get())

    def refresh(self):
        if not self.alive():return
        records=self.owner.erp.attachments(self.owner.company,self.document)
        self.records={r['id']:r for r in records}
        self.files.delete(*self.files.get_children())
        for r in records:self.files.insert('','end',iid=str(r['id']),values=(KINDS[r['kind']],r['original_filename']))
        if records:
            selected=next((r for r in records if r['id']==self.selected),next((r for r in records if r['kind']=='invoice'),records[0]))
            self.files.selection_set(str(selected['id']))
        else:self.state.set('Δεν έχει συνδεθεί PDF. Πάτησε «ΑΑΔΕ → Λήψη PDF» για αυτόματη εύρεση ή πρόσθεσε τοπικό PDF.')

    def open_document(self):
        if self.alive():return open_document(self.owner,self.document,self.window,self.selected)

    def auto_fetch(self):
        if not self.alive() or self.records or self.owner.busy:return
        from app.application.sync import Sync
        active=self.owner.erp.db.execute('SELECT environment FROM aade_settings WHERE company_id=?',(self.owner.company,)).fetchone()
        if active and Sync(self.owner.erp).preferences(self.owner.company,active[0])['auto_pdf']:
            self.fetch_aade()

    def fetch_aade(self):
        if not self.alive() or self.owner.busy:return
        active=self.owner.erp.db.execute('SELECT environment FROM aade_settings WHERE company_id=?',(self.owner.company,)).fetchone()
        if active is None:
            self.owner.open_aade(document=self.document);return
        self.state.set('Άντληση ΑΑΔΕ και σύνδεση PDF με το MARK…')
        def execute():
            from app.application.sync import Sync
            service=ERP(self.owner.directory,credential_store=self.owner.erp.credential_store)
            try:
                Sync(service).document_pdf(self.owner.company,self.document)
                return None
            except (ValueError,RuntimeError,OSError) as exc:return str(exc)
            finally:service.close()
        def done(error):
            if not self.alive():return
            self.owner.refresh();self.refresh()
            if error:self.state.set(error)
        self.owner.run_worker(execute,done)

    def refresh_if_changed(self):
        if not self.alive():return
        current=self.owner.erp.attachments(self.owner.company,self.document)
        if set(self.records)!={r['id'] for r in current}:self.refresh()

    def pick(self,event=None):
        chosen=self.files.selection()
        if not chosen:return
        self.selected=int(chosen[0]);self.page=0;self.show()

    def show(self):
        if not self.alive() or self.selected is None:return
        if not renderer_available():
            self.state.set('Το PDF συνδέθηκε. Πάτησε «Ρύθμιση προβολής PDF» για να εμφανίζεται εδώ.');return
        if self.owner.busy:
            self.owner.root.after(150,self.show);return
        attachment=self.selected;page=self.page
        width=max(100,self.canvas.winfo_width()-20);height=max(100,self.canvas.winfo_height()-20)
        self.state.set('Φόρτωση PDF…')
        def execute():
            service=ERP(self.owner.directory)
            try:return render(service.attachment_path(self.owner.company,self.document,attachment),page,width,height)
            finally:service.close()
        def done(result):
            if not self.alive() or self.selected!=attachment:return
            self.image=tk.PhotoImage(master=self.canvas,data=result['ppm'],format='PPM')
            self.canvas.delete('all');self.canvas.create_image(8,8,image=self.image,anchor='nw')
            self.canvas.configure(scrollregion=self.canvas.bbox('all'))
            self.total_pages=result['pages'];self.state.set(f"Σελίδα {page+1} από {result['pages']} · Αρχειοθετημένο PDF · απαιτείται έλεγχος περιεχομένου")
        self.owner.run_worker(execute,done)

    def move(self,offset):
        if self.selected is None:return
        target=self.page+offset
        if target<0 or target>=getattr(self,'total_pages',1):return
        self.page=target;self.show()

    def attach(self):
        if self.owner.busy:return
        path=filedialog.askopenfilename(parent=self.window,filetypes=[('PDF','*.pdf')])
        if not path:return
        if not messagebox.askyesno('Σύνδεση PDF','Να αντιγραφεί το αρχικό PDF στην αρχειοθήκη αυτού του παραστατικού; Η πηγή δεν θα μεταβληθεί.',parent=self.window):return
        kind=self.current_kind()
        def execute():
            service=ERP(self.owner.directory)
            try:return service.attach_pdf(self.owner.company,self.document,path,kind,confirmed=True)
            finally:service.close()
        self.owner.run_worker(execute,lambda result:self.linked(result))

    def linked(self,result):
        if not self.alive():return
        self.selected=result['id'];self.owner.refresh();self.refresh()

    def setup_renderer(self):
        return self.owner.open_settings('pdf')


def open_saved_pdf(owner,path,digest):
    """View a provider artifact, including AADE documents absent from the Excel."""
    import hashlib
    from pathlib import Path
    win=tk.Toplevel(owner.root);win.title('PDF παρόχου · '+Path(path).name);win.geometry('800x820')
    frame=ttk.Frame(win,padding=12);frame.pack(fill='both',expand=True)
    state=tk.StringVar(value='Φόρτωση PDF…');ttk.Label(frame,textvariable=state).pack(anchor='w')
    controls=ttk.Frame(frame);controls.pack(fill='x',pady=8)
    canvas=tk.Canvas(frame,background='#e6ecf4');canvas.pack(fill='both',expand=True)
    current={'page':0,'total':1,'image':None}
    def show(offset=0):
        if owner.busy:return
        page=current['page']+offset
        if page<0 or page>=current['total']:return
        def execute():
            file=Path(path)
            if not file.is_file() or file.is_symlink() or hashlib.sha256(file.read_bytes()).hexdigest()!=digest:raise ValueError('Το PDF λείπει ή έχει αλλάξει. Δεν προβλήθηκε ως το αρχειοθετημένο αρχείο.')
            return render(file,page,max(200,canvas.winfo_width()-20),max(200,canvas.winfo_height()-20))
        def done(result):
            if not win.winfo_exists():return
            current['page']=page;current['total']=result['pages'];current['image']=tk.PhotoImage(master=canvas,data=result['ppm'],format='PPM')
            canvas.delete('all');canvas.create_image(8,8,image=current['image'],anchor='nw');state.set(f"Σελίδα {page+1}/{result['pages']} · Αρχειοθετημένο PDF, χωρίς ανεξάρτητη λογιστική επαλήθευση")
        owner.run_worker(execute,done)
    ttk.Button(controls,text='‹ Σελίδα',command=lambda:show(-1)).pack(side='left')
    ttk.Button(controls,text='Σελίδα ›',command=lambda:show(1)).pack(side='left',padx=6)
    win.update_idletasks();show();return win
