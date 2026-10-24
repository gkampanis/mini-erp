"""Small local column filters; never reload the database or change source records."""
import re
import unicodedata
import tkinter as tk
from tkinter import ttk
from decimal import Decimal
from app.domain.validation import money


def fold_text(value):
    return ''.join(c for c in unicodedata.normalize('NFD',str(value or '').casefold()) if not unicodedata.combining(c))


class ColumnFilters:
    def __init__(self,tree,on_change,*,value=None):
        self.tree,self.on_change,self.value=tree,on_change,value
        self.filters={};self.window=None
        tree.bind('<Button-3>',self.popup,add='+')

    def clear(self,notify=False):
        self.filters.clear();self.sync_headings()
        if notify:self.on_change()

    def set(self,column,text):
        text=text.strip()
        if column.endswith('_minor') and re.match(r'^[<>=]',text):
            match=re.fullmatch(r'(<=|>=|=|<|>)\s*(.+)',text)
            if not match or not money(match[2]).is_finite():raise ValueError('Γράψε ποσό, π.χ. >=100,00')
        if text:self.filters[column]=text
        else:self.filters.pop(column,None)
        self.sync_headings();self.on_change()

    def apply(self,rows):
        def matches(row,column,query):
            raw=self.value(row,column) if self.value else row.get(column)
            if column.endswith('_minor'):
                if raw is None:return False
                match=re.fullmatch(r'(<=|>=|=|<|>)\s*(.+)',query)
                if match:
                    left=Decimal(raw);right=money(match[2])*100
                    return {'<':left<right,'>':left>right,'<=':left<=right,'>=':left>=right,'=':left==right}[match[1]]
                from app.ui.desktop import amount
                display=amount(raw)
            elif column=='issue_date':
                from app.ui.desktop import when
                display=when(raw)+' '+str(raw or '')
            else:display=str(raw or '')
            if query.startswith('='):return fold_text(display)==fold_text(query[1:].strip())
            return fold_text(query) in fold_text(display)
        return [row for row in rows if all(matches(row,col,text) for col,text in self.filters.items())]

    def sync_headings(self):
        for column in self.tree['columns']:
            title=self.tree.heading(column,'text').removeprefix('● ')
            self.tree.heading(column,text=('● ' if column in self.filters else '')+title)

    def popup(self,event):
        if self.tree.identify_region(event.x,event.y)!='heading':return
        display=list(self.tree['displaycolumns'])
        if display==['#all']:display=list(self.tree['columns'])
        index=int(self.tree.identify_column(event.x)[1:])-1
        if index<0 or index>=len(display):return
        column=display[index]
        if self.window is not None and self.window.winfo_exists():self.window.destroy()
        win=tk.Toplevel(self.tree);self.window=win
        title=self.tree.heading(column,'text').removeprefix('● ').removesuffix(' ↑').removesuffix(' ↓')
        win.title('Φίλτρο · '+title);win.transient(self.tree.winfo_toplevel());win.geometry('430x220')
        body=ttk.Frame(win,padding=16);body.pack(fill='both',expand=True)
        ttk.Label(body,text='Φίλτρο στη στήλη '+title,style='Section.TLabel').pack(anchor='w')
        text=tk.StringVar(value=self.filters.get(column,''));entry=ttk.Entry(body,textvariable=text);entry.pack(fill='x',pady=12)
        state=tk.StringVar(value='Περιέχει κείμενο. Για ποσά: π.χ. >=100,00. = για ακριβή τιμή.')
        ttk.Label(body,textvariable=state,wraplength=390).pack(anchor='w')
        actions=ttk.Frame(body);actions.pack(fill='x',pady=12)
        def apply():
            try:self.set(column,text.get())
            except (ValueError,ArithmeticError):state.set('Έλεγξε την τιμή του φίλτρου. Ποσό: π.χ. >=100,00.');return
            win.destroy()
        ttk.Button(actions,text='Εφαρμογή',command=apply).pack(side='right')
        ttk.Button(actions,text='Καθαρισμός',command=lambda:(text.set(''),apply())).pack(side='left')
        entry.bind('<Return>',lambda _:apply());win.bind('<Escape>',lambda _:win.destroy());entry.focus_set();entry.selection_range(0,'end')
        return 'break'
