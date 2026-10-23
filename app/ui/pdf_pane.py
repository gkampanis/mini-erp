"""Inline, raster-only PDF preview beside document details."""
import tkinter as tk
from tkinter import ttk,messagebox
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
        messagebox.showinfo('Άνοιγμα παραστατικού',str(exc)+'\nΧρησιμοποίησε τη μαζική «Άντληση εξόδων & PDF».',parent=window)



class PDFPane:
    def __init__(self,owner,parent,document,window):
        self.owner,self.parent,self.document,self.window=owner,parent,document,window
        self.page=0;self.selected=None;self.image=None;self.records={}
        top=ttk.Frame(parent,padding=(12,8));top.pack(fill='x')
        ttk.Label(top,text='Έγγραφο παραστατικού',style='Section.TLabel').pack(anchor='w')
        from app.application.mydata import MyData
        document_type=MyData(owner.erp).document_type(owner.company,document)
        self.document_type=tk.StringVar(value=document_type['description'])
        ttk.Label(top,textvariable=self.document_type,style='Subtitle.TLabel',wraplength=420).pack(anchor='w',pady=8)
        ttk.Button(top,text='Άνοιγμα Παραστατικού',command=self.open_document).pack(anchor='w',pady=(0,6))
        self.files=ttk.Treeview(parent,columns=('kind','file'),show='headings',height=2,selectmode='browse')
        self.files.heading('kind',text='Είδος');self.files.heading('file',text='Συνδεδεμένο αρχείο')
        self.files.column('kind',width=120);self.files.column('file',width=200)
        self.files.pack(fill='x',padx=12,pady=(0,6));self.files.bind('<<TreeviewSelect>>',self.pick)
        self.state=tk.StringVar(value='Δεν υπάρχει συνδεδεμένο PDF.')
        ttk.Label(parent,textvariable=self.state,style='Subtitle.TLabel',wraplength=420).pack(anchor='w',padx=12,pady=4)
        controls=ttk.Frame(parent,padding=(12,4));controls.pack(fill='x');self.controls=controls
        self.previous=ttk.Button(controls,text='‹ Σελίδα',command=lambda:self.move(-1));self.previous.pack(side='left')
        self.next=ttk.Button(controls,text='Σελίδα ›',command=lambda:self.move(1));self.next.pack(side='left',padx=6)
        self.previous.state(['disabled']);self.next.state(['disabled'])
        self.setup=ttk.Button(controls,text='Ρύθμιση προβολής PDF',command=self.setup_renderer)
        if not renderer_available():self.setup.pack(side='left')
        canvas_frame=ttk.Frame(parent);canvas_frame.pack(fill='both',expand=True,padx=12,pady=(4,12));self.canvas_frame=canvas_frame
        self.canvas=tk.Canvas(canvas_frame,background='#e6ecf4',highlightthickness=0)
        vertical=ttk.Scrollbar(canvas_frame,orient='vertical',command=self.canvas.yview)
        horizontal=ttk.Scrollbar(canvas_frame,orient='horizontal',command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        self.canvas.grid(row=0,column=0,sticky='nsew');vertical.grid(row=0,column=1,sticky='ns');horizontal.grid(row=1,column=0,sticky='ew')
        canvas_frame.columnconfigure(0,weight=1);canvas_frame.rowconfigure(0,weight=1)
        self.refresh()

    def alive(self):return self.parent.winfo_exists() and not self.owner._closing

    def refresh(self):
        if not self.alive():return
        records=self.owner.erp.attachments(self.owner.company,self.document)
        self.records={r['id']:r for r in records}
        self.files.delete(*self.files.get_children())
        for r in records:self.files.insert('','end',iid=str(r['id']),values=(KINDS[r['kind']],r['original_filename']))
        if records:
            self.files.pack(fill='x',padx=12,pady=(0,6),after=self.parent.winfo_children()[0])
            self.controls.pack(fill='x');self.canvas_frame.pack(fill='both',expand=True,padx=12,pady=(4,12))
            selected=next((r for r in records if r['id']==self.selected),next((r for r in records if r['kind']=='invoice'),records[0]))
            self.files.selection_set(str(selected['id']))
        else:
            self.selected=None;self.image=None;self.canvas.delete('all')
            self.files.pack_forget();self.controls.pack_forget();self.canvas_frame.pack_forget()
            self.state.set(self.unavailable_reason())

    def unavailable_reason(self):
        from app.application.mydata import MyData
        from app.infrastructure.providers.pdf_downloads import state_label
        active=self.owner.erp.db.execute('SELECT environment FROM aade_settings WHERE company_id=?',(self.owner.company,)).fetchone()
        environment=active[0] if active else 'production'
        try:MyData(self.owner.erp).pdf_url(self.owner.company,self.document,environment)
        except ValueError as exc:return str(exc)+'\nΗ λήψη γίνεται από τη μαζική «Άντληση ΑΑΔΕ & PDF».'
        source=self.owner.erp.db.execute('SELECT mark FROM mydata_records WHERE company_id=? AND document_id=? AND environment=?',(self.owner.company,self.document,environment)).fetchone()
        attempt=self.owner.erp.db.execute('SELECT state FROM provider_attempts WHERE company_id=? AND environment=? AND mark=? ORDER BY id DESC LIMIT 1',(self.owner.company,environment,source['mark'])).fetchone()
        return ('Λήψη PDF: '+state_label(attempt['state'])+'. ' if attempt else 'Υπάρχει σύνδεσμος παρόχου, αλλά δεν έχει αποθηκευτεί PDF. ')+ 'Το «Άνοιγμα Παραστατικού» ανοίγει τον σύνδεσμο. Η μαζική άντληση αναλαμβάνει τη λήψη.'

    def open_document(self):
        if self.alive():return open_document(self.owner,self.document,self.window,self.selected)

    def refresh_if_changed(self):
        if not self.alive():return
        from app.application.mydata import MyData
        self.document_type.set(MyData(self.owner.erp).document_type(self.owner.company,self.document)['description'])
        current=self.owner.erp.attachments(self.owner.company,self.document)
        if set(self.records)!={r['id'] for r in current}:self.refresh()
        elif not current:self.state.set(self.unavailable_reason())

    def pick(self,event=None):
        chosen=self.files.selection()
        if not chosen:return
        self.selected=int(chosen[0]);self.page=0;self.show()

    def show(self):
        if not self.alive() or self.selected is None:return
        if not renderer_available():
            self.canvas_frame.pack_forget()
            self.state.set('Το PDF συνδέθηκε. Πάτησε «Άνοιγμα Παραστατικού» ή ρύθμισε την ενσωματωμένη προβολή από τις Ρυθμίσεις.');return
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
            self.previous.state(['disabled'] if page==0 else ['!disabled'])
            self.next.state(['disabled'] if page+1>=result['pages'] else ['!disabled'])
        self.owner.run_worker(execute,done)

    def move(self,offset):
        if self.selected is None:return
        target=self.page+offset
        if target<0 or target>=getattr(self,'total_pages',1):return
        self.page=target;self.show()

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
