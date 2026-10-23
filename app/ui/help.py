"""Small explanatory hover text for the stateful RPA controls."""
import tkinter as tk
from tkinter import ttk

def tooltip(widget,text):
    state={'timer':None,'window':None};root=widget._root()
    def close(event=None):
        if state['timer'] is not None:root.after_cancel(state['timer']);state['timer']=None
        if state['window'] is not None:state['window'].destroy();state['window']=None
    def show():
        state['timer']=None
        if not widget.winfo_exists():return
        win=tk.Toplevel(widget);win.overrideredirect(True);win.geometry(f'+{widget.winfo_rootx()}+{widget.winfo_rooty()+widget.winfo_height()+4}')
        ttk.Label(win,text=text,padding=8,wraplength=360).pack();state['window']=win
    def enter(_):close();state['timer']=root.after(500,show)
    widget.bind('<Enter>',enter,add='+');widget.bind('<Leave>',close,add='+');widget.bind('<Destroy>',close,add='+')
