"""Coordinated compact ttk appearance; presentation only, no external runtime."""
import sys
import tkinter as tk
from tkinter import ttk,font

PALETTES={
 'dark':dict(bg='#181d25',panel='#222a35',ink='#e4eaf3',muted='#acb8c8',blue='#88b0ff',button='#2b3749',border='#65758c',selected='#30476c',selected_ink='#ffffff',alternate='#272f3a',hover='#3b4d66',primary_ink='#14213a',warning='#f1c685',warning_bg='#4b3c22',success='#8cddbd'),
 'light':dict(bg='#f4f6f9',panel='#ffffff',ink='#243246',muted='#566478',blue='#245bd6',button='#edf1f7',border='#d7dee8',selected='#dce8ff',selected_ink='#123476',alternate='#f7f9fc',hover='#e1e9f5',primary_ink='#ffffff',warning='#88550e',warning_bg='#fff0cc',success='#176448')}
BG=PALETTES['dark']['bg'];WHITE=PALETTES['dark']['panel'];INK=PALETTES['dark']['ink'];MUTED=PALETTES['dark']['muted']

def palette(mode='dark'):return PALETTES.get(mode,PALETTES['dark'])

def colors(widget):
    while widget is not None:
        if hasattr(widget,'_desktop_owner'):return palette(widget._desktop_owner.ui_preferences.theme)
        widget=getattr(widget,'master',None)
    return palette()

def apply(root,mode='dark'):
    c=palette(mode);family='Segoe UI' if sys.platform=='win32' else 'DejaVu Sans'
    for name in ('TkDefaultFont','TkTextFont','TkMenuFont'):font.nametofont(name).configure(family=family,size=10)
    style=ttk.Style(root);style.theme_use('clam')
    style.configure('.',background=c['bg'],foreground=c['ink'],font=(family,10))
    for name in ('TFrame','TLabel','TLabelframe','TNotebook'):style.configure(name,background=c['bg'])
    style.configure('TLabel',foreground=c['ink']);style.configure('Card.TFrame',background=c['panel']);style.configure('Card.TLabel',background=c['panel'],foreground=c['ink'])
    style.configure('Title.TLabel',font=(family,18,'bold'));style.configure('Subtitle.TLabel',foreground=c['muted'])
    style.configure('Metric.TLabel',background=c['panel'],font=(family,23,'bold'));style.configure('Caption.TLabel',background=c['panel'],foreground=c['muted'])
    style.configure('Section.TLabel',font=(family,12,'bold'))
    for name in ('TButton','TMenubutton'):
        style.configure(name,padding=(11,7),background=c['button'],foreground=c['ink'],arrowcolor=c['ink'],bordercolor=c['border'],lightcolor=c['border'],darkcolor=c['border'],focuscolor=c['blue'],relief='flat')
        style.map(name,background=[('disabled',c['button']),('pressed',c['hover']),('active',c['hover'])],foreground=[('disabled',c['muted'])],arrowcolor=[('disabled',c['muted'])],bordercolor=[('focus',c['blue'])],lightcolor=[('pressed',c['border'])],darkcolor=[('pressed',c['border'])])
    style.configure('Primary.TButton',background=c['blue'],foreground=c['primary_ink'],bordercolor=c['blue'])
    style.map('Primary.TButton',background=[('disabled',c['button']),('active',c['blue'])],foreground=[('disabled',c['muted']),('active',c['primary_ink'])])
    for name in ('TEntry','TCombobox','TSpinbox'):
        style.configure(name,padding=6,background=c['button'],fieldbackground=c['panel'],foreground=c['ink'],arrowcolor=c['ink'],bordercolor=c['border'],lightcolor=c['border'],darkcolor=c['border'],insertcolor=c['ink'],selectbackground=c['selected'],selectforeground=c['selected_ink'])
        style.map(name,background=[('disabled',c['button']),('pressed',c['hover']),('active',c['hover'])],fieldbackground=[('disabled',c['bg']),('readonly',c['panel'])],foreground=[('disabled',c['muted'])],arrowcolor=[('disabled',c['muted'])],bordercolor=[('focus',c['blue'])],lightcolor=[('focus',c['blue'])],darkcolor=[('focus',c['blue'])])
    for name in ('TCheckbutton','TRadiobutton'):
        style.configure(name,background=c['bg'],foreground=c['ink'],indicatorbackground=c['panel'],bordercolor=c['border'],lightcolor=c['border'],darkcolor=c['border'],focuscolor=c['blue'],padding=(0,3))
        style.map(name,background=[('active',c['bg'])],foreground=[('disabled',c['muted'])],indicatorbackground=[('disabled',c['bg']),('pressed',c['panel']),('alternate',c['panel']),('selected',c['panel'])],bordercolor=[('focus',c['blue'])])
    style.configure('Treeview',background=c['panel'],fieldbackground=c['panel'],foreground=c['ink'],rowheight=font.nametofont('TkDefaultFont').metrics('linespace')+10,bordercolor=c['border'])
    style.configure('Treeview.Heading',background=c['bg'],foreground=c['ink'],padding=(8,8),font=(family,9,'bold'),relief='flat')
    style.map('Treeview.Heading',background=[('active',c['hover'])])
    style.map('Treeview',background=[('selected',c['selected'])],foreground=[('selected',c['selected_ink'])])
    style.configure('TNotebook',borderwidth=0);style.configure('TNotebook.Tab',padding=(10,7),font=(family,9),background=c['bg'],foreground=c['muted'])
    style.map('TNotebook.Tab',background=[('selected',c['panel'])],foreground=[('selected',c['blue'])])
    style.configure('TLabelframe',bordercolor=c['border']);style.configure('TLabelframe.Label',font=(family,10,'bold'),foreground=c['muted'])
    style.configure('Horizontal.TProgressbar',background=c['blue'],troughcolor=c['button'],borderwidth=0)
    for orient in ('Vertical','Horizontal'):style.configure(orient+'.TScrollbar',background=c['button'],troughcolor=c['bg'],bordercolor=c['border'],arrowcolor=c['muted'])
    for pattern,value in {'*Text.background':c['panel'],'*Text.foreground':c['ink'],'*Text.insertBackground':c['ink'],'*Text.selectBackground':c['selected'],'*Text.selectForeground':c['selected_ink'],'*Listbox.background':c['panel'],'*Listbox.foreground':c['ink'],'*Listbox.selectBackground':c['selected'],'*Listbox.selectForeground':c['selected_ink'],'*Menu.background':c['panel'],'*Menu.foreground':c['ink'],'*Menu.activeBackground':c['selected'],'*Menu.activeForeground':c['selected_ink']}.items():root.option_add(pattern,value)
    def update(widget):
        try:
            if isinstance(widget,(tk.Tk,tk.Toplevel,tk.Frame)):widget.configure(background=c['bg'])
            elif isinstance(widget,tk.Text):
                widget.configure(background=c['panel'],foreground=c['ink'],insertbackground=c['ink'],selectbackground=c['selected'],selectforeground=c['selected_ink'])
                if 'issue' in widget.tag_names():widget.tag_configure('issue',background=c['warning_bg'],foreground=c['ink'])
            elif isinstance(widget,tk.Canvas):widget.configure(background=c['bg'])
            elif isinstance(widget,tk.Menu):widget.configure(background=c['panel'],foreground=c['ink'],activebackground=c['selected'],activeforeground=c['selected_ink'])
            elif isinstance(widget,ttk.Treeview):
                widget.tag_configure('alternate',background=c['alternate']);widget.tag_configure('difference',background=c['warning_bg'],foreground=c['ink'])
                widget.tag_configure('status_review',foreground=c['warning']);widget.tag_configure('status_approved',foreground=c['success'])
            for child in widget.winfo_children():update(child)
        except tk.TclError:pass
    update(root);return style
