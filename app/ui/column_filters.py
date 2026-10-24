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
    def __init__(self,tree,on_change,*,value=None,rows=None,extra_menu=None,show_summary=False):
        self.tree,self.on_change,self.value=tree,on_change,value
        self.filters={};self.cell_filters={};self.window=None;self.rows=rows;self.extra_menu=extra_menu;self.menu=None
        self.summary=None;self.reset_button=None
        if show_summary:
            self.summary=tk.StringVar(master=tree)
            footer=ttk.Frame(tree.master);footer.grid(row=2,column=0,columnspan=2,sticky="ew")
            ttk.Label(footer,textvariable=self.summary,style="Subtitle.TLabel",wraplength=900).pack(side="left",fill="x",expand=True)
            self.reset_button=ttk.Button(footer,text="Επαναφορά φίλτρων",command=lambda:self.clear(notify=True))
        tree.bind('<Button-3>',self.popup,add='+')

    def clear(self,notify=False):
        self.filters.clear();self.cell_filters.clear();self.sync_headings()
        if notify:self.on_change()

    def set(self,column,text):
        text=text.strip()
        if not text:self.remove(column);return
        if column.endswith('_minor') and re.match(r'^[<>=]',text):
            match=re.fullmatch(r'(<=|>=|=|<|>)\s*(.+)',text)
            if not match or not money(match[2]).is_finite():raise ValueError('Γράψε ποσό, π.χ. >=100,00')
        self.cell_filters.pop(column,None)
        if text:self.filters[column]=text
        else:self.filters.pop(column,None)
        self.sync_headings();self.on_change()

    def raw(self,row,column):return self.value(row,column) if self.value else row.get(column)

    def canonical(self,column,value):
        if value is None or value=='':return value
        if column.endswith('_minor'):return Decimal(value)
        if column=='issue_date':
            from datetime import date,datetime
            if isinstance(value,datetime):return value.date()
            if isinstance(value,date):return value
            return date.fromisoformat(str(value))
        return str(value)  # VAT/account identifiers retain leading zeros.

    def cell(self,column,value,exclude=False):
        rule=(exclude,self.canonical(column,value))
        # A new operation replaces the previous mode in this column. Other
        # columns remain AND-combined; repeated exclusions still accumulate.
        self.filters.pop(column,None)
        rules=[r for r in self.cell_filters.get(column,[]) if r[0]] if exclude else []
        if rule not in rules:rules.append(rule)
        self.cell_filters[column]=rules
        self.sync_headings();self.on_change()

    def remove(self,column):
        self.filters.pop(column,None);self.cell_filters.pop(column,None)
        self.sync_headings();self.on_change()

    def remove_rule(self,column,rule):
        if rule is None:self.filters.pop(column,None)
        else:
            rules=self.cell_filters.get(column,[])
            if rule in rules:rules.remove(rule)
            if not rules:self.cell_filters.pop(column,None)
        self.sync_headings();self.on_change()

    def rule_label(self,column,value):
        from app.ui.desktop import amount,when
        return amount(value) if column.endswith('_minor') and value is not None else when(str(value)) if column=='issue_date' and value else str(value if value is not None else 'κενό')

    def apply(self,rows):
        def matches(row,column,query):
            raw=self.raw(row,column)
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
        result=[row for row in rows if all(matches(row,col,text) for col,text in self.filters.items()) and all(
            all((self.canonical(col,self.raw(row,col))!=value) if exclude else (self.canonical(col,self.raw(row,col))==value) for exclude,value in rules)
            for col,rules in self.cell_filters.items())]
        active=set(self.filters)|set(self.cell_filters)
        if self.summary is not None:
            parts=[]
            from app.ui.desktop import amount,when
            for column in sorted(active):
                title=self.tree.heading(column,'text').removeprefix('● ').removesuffix(' ↑').removesuffix(' ↓')
                rules=[self.filters[column]] if column in self.filters else []
                for exclude,value in self.cell_filters.get(column,[]):
                    label=amount(value) if column.endswith('_minor') and value is not None else when(str(value)) if column=='issue_date' and value else str(value or 'κενό')
                    rules.append(('≠ ' if exclude else '= ')+label)
                parts.append(title+': '+' ΚΑΙ '.join(rules))
            self.summary.set(f'{len(result)} / {len(rows)} εγγραφές · '+(' · '.join(parts) if parts else 'Χωρίς φίλτρα στηλών'))
        return result

    def sync_headings(self):
        if self.reset_button is not None:
            if self.filters or self.cell_filters:self.reset_button.pack(side='right',padx=6,pady=2)
            else:self.reset_button.pack_forget()
        for column in self.tree['columns']:
            title=self.tree.heading(column,'text').removeprefix('● ')
            self.tree.heading(column,text=('● ' if column in self.filters or column in self.cell_filters else '')+title)

    def removal_actions(self,menu):
        if not (self.filters or self.cell_filters):return
        menu.add_command(label='Καθαρισμός όλων των φίλτρων',command=lambda:self.clear(notify=True))
        submenu=tk.Menu(menu,tearoff=False)
        for active in sorted(set(self.filters)|set(self.cell_filters)):
            title=self.tree.heading(active,'text').removeprefix('● ')
            if active in self.filters:submenu.add_command(label=title+': '+self.filters[active],command=lambda c=active:self.remove_rule(c,None))
            for rule in self.cell_filters.get(active,[]):
                exclude,value=rule
                submenu.add_command(label=title+(' ≠ ' if exclude else ' = ')+self.rule_label(active,value),command=lambda c=active,r=rule:self.remove_rule(c,r))
        menu.add_cascade(label='Αφαίρεση συγκεκριμένου φίλτρου',menu=submenu)

    def popup(self,event):
        region=self.tree.identify_region(event.x,event.y)
        if region not in ('heading','cell'):
            if not (self.filters or self.cell_filters):return
            if self.menu is not None:self.menu.destroy()
            menu=tk.Menu(self.tree,tearoff=False);self.menu=menu;self.removal_actions(menu)
            try:menu.tk_popup(event.x_root,event.y_root)
            finally:menu.grab_release()
            return 'break'
        display=list(self.tree['displaycolumns'])
        if display==['#all']:display=list(self.tree['columns'])
        index=int(self.tree.identify_column(event.x)[1:])-1
        if index<0 or index>=len(display):return
        column=display[index]
        if region=='cell':
            key=self.tree.identify_row(event.y)
            if not key or self.rows is None:return
            row=self.rows().get(int(key))
            if row is None:return
            raw=self.raw(row,column)
            if self.menu is not None:self.menu.destroy()
            menu=tk.Menu(self.tree,tearoff=False);self.menu=menu
            if self.extra_menu:self.extra_menu(event,self.tree,menu)
            menu.add_command(label='Φίλτρο με αυτή την τιμή',command=lambda:self.cell(column,raw))
            menu.add_command(label='Εξαίρεση αυτής της τιμής',command=lambda:self.cell(column,raw,True))
            if column in self.filters or column in self.cell_filters:
                menu.add_command(label='Αφαίρεση φίλτρου αυτής της στήλης',command=lambda:self.remove(column))
            self.removal_actions(menu)
            try:menu.tk_popup(event.x_root,event.y_root)
            finally:menu.grab_release()
            return 'break'
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
        ttk.Button(actions,text='Καθαρισμός όλων',command=lambda:(self.clear(notify=True),win.destroy())).pack(side='left',padx=4)
        ttk.Button(actions,text='Εφαρμογή',command=apply).pack(side='right')
        ttk.Button(actions,text='Καθαρισμός',command=lambda:(self.remove(column),win.destroy())).pack(side='left')
        entry.bind('<Return>',lambda _:apply());win.bind('<Escape>',lambda _:win.destroy());entry.focus_set();entry.selection_range(0,'end')
        return 'break'
