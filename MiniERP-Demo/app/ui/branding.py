"""Display identity only; legacy storage paths and connector identifiers stay."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk

NAME='Σύμβολον ERP'


def install(root,parent):
    path=Path(__file__).resolve().parents[2]/'docs/branding/symbolon-mark.png'
    try:
        icon=tk.PhotoImage(master=root,file=str(path));root._parastio_icon=icon
        root.iconphoto(True,icon)
        small=icon.subsample(max(1,icon.width()//28));root._parastio_small=small
        row=ttk.Frame(parent);row.pack(anchor='w')
        ttk.Label(row,image=small).pack(side='left',padx=(0,9))
        ttk.Label(row,text=NAME,style='Title.TLabel').pack(side='left')
    except (tk.TclError,OSError):ttk.Label(parent,text=NAME,style='Title.TLabel').pack(anchor='w')
