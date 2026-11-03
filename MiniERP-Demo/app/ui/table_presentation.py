"""Reusable table presentation over existing widgets and stable row identities."""
from collections.abc import Mapping
import tkinter as tk
from tkinter import ttk,font
from app.ui.preferences import clean_layout,display_column,visible_totals


def proposed_widths(columns,headings,samples,measure,available):
    widths={};minimum={};flex=[]
    for key in columns:
        strings=[str(row.get(key) or '') for row in samples]
        title=str(headings.get(key,key)).removeprefix('● ').removesuffix(' ↑').removesuffix(' ↓')
        required=max([measure(title)]+[measure(v) for v in strings])+24
        exact=key.endswith('_minor') or key in ('vat','issue_date','account','display_account_code')
        minimum[key]=max(75,measure(title)+22,required if exact else 120 if key in ('name','description','reason') else 85)
        widths[key]=max(minimum[key],required if exact else min(required,360 if key in ('name','description','reason') else 260))
        if not exact:flex.append(key)
    overflow=sum(widths.values())-max(0,available)
    for key in sorted(flex,key=lambda k:widths[k]-minimum[k],reverse=True):
        reduction=min(max(0,overflow),widths[key]-minimum[key]);widths[key]-=reduction;overflow-=reduction
    remaining=max(0,available-sum(widths.values()))
    for key in ('name','description','reason'):
        if key in widths:
            extra=min(remaining,max(0,520-widths[key]));widths[key]+=extra;remaining-=extra
    return {key:int(value) for key,value in widths.items()}


def find_owner(widget):
    while widget is not None:
        if hasattr(widget,'_desktop_owner'):return widget._desktop_owner
        widget=getattr(widget,'master',None)
    return None


class TablePresentation:
    def __init__(self,tree,owner,key,toolbar):
        self.tree,self.owner,self.key=tree,owner,key;self.preferences=owner.ui_preferences;self.toolbar=toolbar
        self.initialized=False;self.automatic=True;self._resize=None;self._tip_after=None;self.tip=None;self._hover=None;self._dragging=False;self._capture_after=None
        self.default_columns=[];self.default_widths={};self.models=None;self.totals=(0,0,0);self.preference_error=False
        self.summary=tk.StringVar(master=tree)
        footer=ttk.Label(tree.master,textvariable=self.summary,style='Subtitle.TLabel',wraplength=1050)
        footer.grid(row=3,column=0,columnspan=2,sticky='ew',pady=(4,0))
        footer.bind('<Configure>',lambda e:footer.configure(wraplength=max(150,e.width-4)),add='+')
        ttk.Button(toolbar,text='Αυτόματο πλάτος',command=self.fit).pack(side='right',padx=(6,0))
        self.columns_button=ttk.Menubutton(toolbar,text='Στήλες ▾');self.columns_button.pack(side='right')
        self.menu=tk.Menu(self.columns_button,tearoff=False,postcommand=self.fill_menu);self.columns_button.configure(menu=self.menu)
        self._tag='ParastioPresentation_'+str(id(tree));tree.bindtags((self._tag,*tree.bindtags()))
        self._bind_root=tree._root();self._bindings=[]
        for event,callback in (('<ButtonPress-1>',self.press),('<ButtonRelease-1>',self.release),('<Double-1>',self.double),('<Motion>',self.motion),('<Leave>',lambda e:self.hide_tip()),('<MouseWheel>',lambda e:self.hide_tip())):
            self._bindings.append(tree.bind_class(self._tag,event,callback))
        tree.bind('<<TreeviewSelect>>',lambda e:self.update_summary(),add='+')
        tree.bind('<Configure>',self.resized,add='+');tree.bind('<Destroy>',self.destroy,add='+')
        self._init_after=tree.after_idle(self.initialize)
    def shown(self):
        value=list(self.tree['displaycolumns'])
        return list(self.tree['columns']) if value==['#all'] else value
    def initialize(self):
        self._init_after=None
        if not self.tree.winfo_exists():return
        self.default_columns=self.shown();self.default_widths={c:self.tree.column(c,'width') for c in self.tree['columns']}
        layout=clean_layout(self.preferences.layout(self.key),self.tree['columns'])
        if 'visible' in layout:self.tree.configure(displaycolumns=layout['visible'])
        for c in self.tree['columns']:self.tree.column(c,stretch=False)
        for c,width in layout.get('widths',{}).items():self.tree.column(c,width=width)
        if 'sort' in layout:
            key,reverse=layout['sort']
            title=self.tree.heading(key,'text').removesuffix(' ↑').removesuffix(' ↓')
            self.tree.heading(key,text=title+(' ↓' if reverse else ' ↑'))
        self.automatic=not bool(layout.get('widths'));self.initialized=True
        if self.automatic:self.schedule_fit()
        self.update_summary()
    def fill_menu(self):
        self.menu.delete(0,'end');self._vars=[];shown=self.shown()
        for key in self.tree['columns']:
            var=tk.BooleanVar(master=self.tree,value=key in shown);self._vars.append(var)
            title=self.tree.heading(key,'text').removeprefix('● ').removesuffix(' ↑').removesuffix(' ↓')
            self.menu.add_checkbutton(label=title,variable=var,command=lambda c=key,v=var:self.show_column(c,v.get()))
        self.menu.add_separator();self.menu.add_command(label='Επαναφορά διάταξης',command=self.reset)
    def show_column(self,key,show):
        if key not in self.tree['columns']:return
        shown=self.shown()
        if show and key not in shown:
            shown.append(key);shown.sort(key=lambda c:list(self.tree['columns']).index(c))
        elif not show and key in shown and len(shown)>1:shown.remove(key)
        self.tree.configure(displaycolumns=shown);self.hide_tip();self.capture()
    def capture(self):
        if not self.initialized:return
        self.automatic=False
        if self._resize:
            try:self.tree.after_cancel(self._resize)
            except tk.TclError:pass
            self._resize=None
        layout=self.preferences.layout(self.key)
        layout.update(visible=self.shown(),widths={c:int(self.tree.column(c,'width')) for c in self.tree['columns']})
        self.preference_error=not self.preferences.set_layout(self.key,layout);self.update_summary()
    def save_sort(self,key,reverse):
        if not self.initialized:return
        layout=self.preferences.layout(self.key)
        if layout.get('sort')==[key,bool(reverse)]:return
        layout['sort']=[key,bool(reverse)]
        self.preference_error=not self.preferences.set_layout(self.key,layout)
    def saved_sort(self,default):return self.preferences.sort(self.key,default,self.tree['columns'])
    def reset(self):
        self.tree.configure(displaycolumns=self.default_columns)
        for key,width in self.default_widths.items():self.tree.column(key,width=width,stretch=False)
        # Reset only presentation; filters, selection, order and posting scope stay.
        layout=self.preferences.layout(self.key);layout.pop('widths',None);layout['visible']=self.default_columns
        self.preference_error=not self.preferences.set_layout(self.key,layout)
        self.automatic=True;self.schedule_fit();self.update_summary()
    def press(self,event):
        self.hide_tip();self._dragging=self.tree.identify_region(event.x,event.y)=='separator'
        if self._dragging:self.automatic=False
    def release(self,event):
        if self._dragging:
            self._dragging=False
            def save():self._capture_after=None;self.capture()
            self._capture_after=self.tree.after_idle(save)
    def double(self,event):
        if self.tree.identify_region(event.x,event.y)=='separator':
            key=display_column(self.tree,event.x)
            if key:self.fit_column(key)
            return 'break'
    def samples(self):
        keys=list(self.tree['columns']);result=[]
        for item in self.tree.get_children():
            values=self.tree.item(item,'values');result.append(dict(zip(keys,values)))
        return result
    def fit_column(self,key):
        widths=proposed_widths([key],{key:self.tree.heading(key,'text')},self.samples(),font.nametofont('TkDefaultFont').measure,0)
        self.tree.column(key,width=widths[key],stretch=False);self.capture()
    def fit(self,persist=True):
        self._resize=None
        if not self.initialized or not self.tree.winfo_exists() or self.tree.winfo_width()<100:return
        shown=self.shown();headings={c:self.tree.heading(c,'text') for c in shown}
        widths=proposed_widths(shown,headings,self.samples(),font.nametofont('TkDefaultFont').measure,self.tree.winfo_width()-4)
        for key,width in widths.items():self.tree.column(key,width=width,stretch=False)
        if persist:self.capture()
    def schedule_fit(self):
        if self._resize:
            try:self.tree.after_cancel(self._resize)
            except tk.TclError:pass
        self._resize=self.tree.after(160,lambda:self.fit(persist=False) if self.automatic else None)
    def resized(self,event):
        if self.initialized and self.automatic:self.schedule_fit()
        self.hide_tip()
    def rows_changed(self,models=None):
        if models is not None:self.models=models if isinstance(models,Mapping) else {}
        self.update_summary()
        if self.initialized and self.automatic:self.schedule_fit()
    def update_summary(self):
        from app.ui.desktop import amount
        count=len(self.tree.get_children());selected=len(self.tree.selection())
        if count==0:
            text='Κανένα αποτέλεσμα · δοκίμασε διαφορετικά φίλτρα ή καθάρισε την αναζήτηση'
            if self.preference_error:text+=' · Η διάταξη δεν αποθηκεύτηκε'
            self.summary.set(text)
            self.totals=(0,0,0)
            return
        text=f'Ορατά: {count} · Επιλεγμένα: {selected}'
        if self.models is not None and any(c in self.tree['columns'] for c in ('net_minor','gross_minor','net','gross')):
            visible=[]
            for item in self.tree.get_children():
                try:row_id=int(item)
                except (TypeError,ValueError):continue
                row=self.models.get(row_id)
                if isinstance(row,Mapping):visible.append(row)
            self.totals=visible_totals(visible)
            if visible:text+=' · Σύνολα ορατών: Καθαρή '+amount(self.totals[0])+' € · ΦΠΑ '+amount(self.totals[1])+' € · Σύνολο '+amount(self.totals[2])+' €'
        if self.preference_error:text+=' · Η διάταξη δεν αποθηκεύτηκε'
        self.summary.set(text)
    def motion(self,event):
        if self.tree.identify_region(event.x,event.y)!='cell':self.hide_tip();return
        item=self.tree.identify_row(event.y);column=display_column(self.tree,event.x);hover=(item,column)
        if hover==self._hover:return
        self.hide_tip();self._hover=hover
        if not item or not column:return
        text=str(self.tree.set(item,column));box=self.tree.bbox(item,column)
        if not box or font.nametofont('TkDefaultFont').measure(text)<=box[2]-18:return
        def show():
            self._tip_after=None
            if not self.tree.winfo_exists() or self._hover!=hover:return
            self.tip=tk.Toplevel(self.tree);self.tip.overrideredirect(True)
            from app.ui.theme import palette
            colors=palette(self.owner.ui_preferences.theme)
            label=tk.Label(self.tip,text=text,background=colors['panel'],foreground=colors['ink'],padx=9,pady=6,wraplength=520,justify='left',relief='solid',borderwidth=1)
            label.pack();self.tip.update_idletasks()
            x=min(event.x_root+12,self.tree.winfo_screenwidth()-self.tip.winfo_reqwidth()-10)
            y=min(event.y_root+20,self.tree.winfo_screenheight()-self.tip.winfo_reqheight()-10)
            self.tip.geometry(f'+{max(0,x)}+{max(0,y)}')
        self._tip_after=self.tree.after(650,show)
    def hide_tip(self):
        self._hover=None
        if self._tip_after:
            try:self.tree.after_cancel(self._tip_after)
            except tk.TclError:pass
            self._tip_after=None
        if self.tip:
            try:self.tip.destroy()
            except tk.TclError:pass
            self.tip=None
    def destroy(self,event):
        if event.widget is not self.tree:return
        self.hide_tip()
        for pending in (self._resize,self._init_after,self._capture_after):
            if pending:
                try:self.tree.after_cancel(pending)
                except tk.TclError:pass
        for sequence in ('<ButtonPress-1>','<ButtonRelease-1>','<Double-1>','<Motion>','<Leave>','<MouseWheel>'):
            self.tree.unbind_class(self._tag,sequence)

        for binding in self._bindings:
            if binding:
                try:self._bind_root.deletecommand(binding)
                except tk.TclError:pass
        self._bindings.clear()
