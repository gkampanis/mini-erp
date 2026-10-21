"""Small native ttk theme, no third-party UI runtime or copied theme code."""
import sys
from tkinter import ttk, font

BG = '#f3f6fb'
WHITE = '#ffffff'
INK = '#15263f'
MUTED = '#5e6f85'
BLUE = '#245bd6'
BORDER = '#dce4ef'


def apply(root):
    family = 'Segoe UI' if sys.platform == 'win32' else 'DejaVu Sans'
    for name in ('TkDefaultFont','TkTextFont','TkMenuFont'):
        font.nametofont(name).configure(family=family,size=10)
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.',background=BG,foreground=INK,font=(family,10))
    style.configure('TFrame',background=BG)
    style.configure('Card.TFrame',background=WHITE)
    style.configure('TLabel',background=BG,foreground=INK)
    style.configure('Card.TLabel',background=WHITE)
    style.configure('Title.TLabel',font=(family,22,'bold'))
    style.configure('Subtitle.TLabel',foreground=MUTED)
    style.configure('Metric.TLabel',background=WHITE,font=(family,23,'bold'))
    style.configure('Caption.TLabel',background=WHITE,foreground=MUTED)
    style.configure('Section.TLabel',font=(family,12,'bold'))
    style.configure('TButton',padding=(14,9),background=WHITE,bordercolor=BORDER,relief='flat')
    style.map('TButton',background=[('active','#eaf0fc')],foreground=[('disabled','#8491a5')])
    style.configure('Primary.TButton',background=BLUE,foreground=WHITE,bordercolor=BLUE)
    style.map('Primary.TButton',background=[('disabled','#dce4ef'),('active','#194ab5')],foreground=[('disabled','#8491a5')])
    style.configure('TEntry',padding=8,fieldbackground=WHITE,bordercolor=BORDER)
    style.configure('TCombobox',padding=6,fieldbackground=WHITE,bordercolor=BORDER)
    style.map('TCombobox',fieldbackground=[('readonly',WHITE)])
    style.configure('Treeview',background=WHITE,fieldbackground=WHITE,foreground=INK,rowheight=32,bordercolor=BORDER)
    style.configure('Treeview.Heading',background='#eaf0f8',foreground=INK,padding=(8,10),font=(family,9,'bold'),relief='flat')
    style.map('Treeview',background=[('selected','#dce8ff')],foreground=[('selected','#123476')])
    style.configure('TNotebook',background=BG,borderwidth=0)
    style.configure('TNotebook.Tab',padding=(20,12),background='#e7edf6',foreground=MUTED)
    style.map('TNotebook.Tab',background=[('selected',WHITE)],foreground=[('selected',BLUE)])
    style.configure('TLabelframe',background=BG,bordercolor=BORDER)
    style.configure('TLabelframe.Label',font=(family,10,'bold'),foreground=MUTED)
    style.configure('Horizontal.TProgressbar',background=BLUE,troughcolor='#e4ebf5',borderwidth=0)
    root.configure(background=BG)
    root.option_add('*Text.background',WHITE)
    root.option_add('*Text.foreground',INK)
    root.option_add('*Text.selectBackground','#dce8ff')
    return style
