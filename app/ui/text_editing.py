"""Native text editing shortcuts and a Greek context menu, including new dialogs."""
import tkinter as tk

CLASSES=('Entry','TEntry','Text','TCombobox','Spinbox','TSpinbox')
ACTIONS={'a':'select','c':'copy','x':'cut','v':'paste','greek_alpha':'select','greek_psi':'copy','greek_chi':'cut','greek_omega':'paste'}

def editable(widget):
    if str(widget.cget('state')) in ('disabled','readonly'):return False
    return not hasattr(widget,'instate') or not (widget.instate(['disabled']) or widget.instate(['readonly']))

def perform(widget,action):
    if action in ('paste','cut') and not editable(widget):return 'break'
    if action=='select':
        if widget.winfo_class()=='Text':widget.tag_add('sel','1.0','end-1c')
        else:widget.selection_range(0,'end')
    else:widget.event_generate({'copy':'<<Copy>>','cut':'<<Cut>>','paste':'<<Paste>>'}[action])
    return 'break'

def shortcut(event):
    action=ACTIONS.get(event.keysym.casefold())
    if action:return perform(event.widget,action)

def install(root):
    # One binding set per Tcl interpreter; class bindings also cover later Toplevels.
    interpreter=root._root()
    if getattr(interpreter,'_minierp_text_editing',False):return
    interpreter._minierp_text_editing=True
    menu=tk.Menu(interpreter,tearoff=False)
    def popup(event):
        widget=event.widget;widget.focus_set();menu.delete(0,'end')
        for label,action in [('Αντιγραφή','copy'),('Επικόλληση','paste'),('Αποκοπή','cut'),('Επιλογή όλων','select')]:
            state='disabled' if action in ('paste','cut') and not editable(widget) else 'normal'
            menu.add_command(label=label,state=state,command=lambda a=action:perform(widget,a))
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()
        return 'break'
    for kind in CLASSES:
        interpreter.bind_class(kind,'<Button-3>',popup)
        interpreter.bind_class(kind,'<Control-KeyPress>',shortcut,add='+')
        for key in ('a','c','v','x','A','C','V','X'):
            interpreter.bind_class(kind,'<Control-'+key+'>',shortcut)
