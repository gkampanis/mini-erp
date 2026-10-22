"""Inline, raster-only PDF preview beside document details."""
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,simpledialog
from app.application.service import ERP
from app.infrastructure.pdf_archive import KINDS,render,renderer_available
from app.infrastructure.optional_packages import install


class PDFPane:
    def __init__(self,owner,parent,document,window):
        self.owner,self.parent,self.document,self.window=owner,parent,document,window
        self.page=0;self.selected=None;self.image=None;self.records={}
        top=ttk.Frame(parent,padding=(12,8));top.pack(fill='x')
        ttk.Label(top,text='PDF παραστατικού',style='Section.TLabel').pack(anchor='w')
        self.kind=tk.StringVar(value='Τιμολόγιο')
        ttk.Combobox(top,textvariable=self.kind,values=tuple(KINDS.values()),state='readonly',width=23).pack(anchor='w',pady=8)
        buttons=ttk.Frame(top);buttons.pack(fill='x')
        ttk.Button(buttons,text='Προσθήκη PDF',command=self.attach).pack(side='left',padx=(0,6))
        ttk.Button(buttons,text='Άντληση από σύνδεσμο',command=self.fetch).pack(side='left')
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
        else:self.state.set('Δεν έχει συνδεθεί PDF. Πρόσθεσε αρχείο ή άντλησέ το από έγκυρο σύνδεσμο HTTPS.')

    def pick(self,event=None):
        chosen=self.files.selection()
        if not chosen:return
        self.selected=int(chosen[0]);self.page=0;self.show()

    def show(self):
        if not self.alive() or self.selected is None:return
        if not renderer_available():
            self.state.set('Το PDF συνδέθηκε. Πάτησε «Ρύθμιση προβολής PDF» για να εμφανίζεται εδώ.');return
        if self.owner.busy:
            self.parent.after(150,self.show);return
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
            self.total_pages=result['pages'];self.state.set(f"Σελίδα {page+1} από {result['pages']} · Αρχικό PDF, χωρίς μεταβολή")
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

    def fetch(self):
        if self.owner.busy:return
        url=simpledialog.askstring('Άντληση PDF','Πλήρης σύνδεσμος HTTPS από τον εκδότη/πάροχο:',parent=self.window)
        if not url:return
        if not messagebox.askyesno('Λήψη PDF','Να ληφθεί το PDF και να συνδεθεί με αυτό το παραστατικό; Δεν θα σταλούν κωδικοί ΑΑΔΕ σε αυτόν τον σύνδεσμο.',parent=self.window):return
        kind=self.current_kind()
        def execute():
            service=ERP(self.owner.directory)
            try:return service.download_pdf(self.owner.company,self.document,url,kind,confirmed=True)
            finally:service.close()
        self.owner.run_worker(execute,lambda result:self.linked(result))

    def linked(self,result):
        if not self.alive():return
        self.selected=result['id'];self.owner.refresh();self.refresh()

    def setup_renderer(self):
        if self.owner.busy:return
        if not messagebox.askyesno('Προβολή PDF','Θα ληφθούν τα pypdfium2 και Pillow από το PyPI σε ξεχωριστό φάκελο MiniERP. Δεν θα αντικατασταθεί η Python ή το EBS. Συνέχεια;',parent=self.window):return
        def done(_):
            if self.alive():self.setup.pack_forget();self.show()
        self.owner.run_worker(lambda:install('pdf'),done)
