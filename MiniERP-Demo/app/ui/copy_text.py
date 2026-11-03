"""Selectable, read-only dialog values using the shared text shortcuts/menu."""
from tkinter import ttk
from app.ui.text_editing import install


def copy_text(parent,text,*,style='TLabel',width=1):
    """Present a value like a label while retaining native selection and copy."""
    install(parent)
    theme=ttk.Style(parent)
    name=style.replace('.TLabel','.Copy.TEntry') if style!='TLabel' else 'Copy.TEntry'
    background=theme.lookup(style,'background') or theme.lookup('TFrame','background')
    foreground=theme.lookup(style,'foreground')
    theme.configure(name,padding=0,borderwidth=0,relief='flat',font=theme.lookup(style,'font'))
    theme.map(name,fieldbackground=[('readonly',background)],foreground=[('readonly',foreground)])
    value=ttk.Entry(parent,style=name,width=width,state='normal',exportselection=False)
    value.insert(0,str(text));value.configure(state='readonly')
    return value
