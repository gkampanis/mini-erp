"""Run explicitly with a display: DISPLAY=:99 python -m tests.gui_smoke.
Pillow is optional, used only to capture review screenshots, never by the app.
"""
from pathlib import Path
import tempfile
import time
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch
from app.application.service import ERP
from app.ui.desktop import Desktop
from tests.fixtures import demos


def wait(root, predicate):
    deadline = time.monotonic()+10
    while not predicate():
        root.update()
        if time.monotonic()>deadline:
            raise AssertionError('GUI worker timeout')
        time.sleep(.01)
    root.update()


def widgets(parent):
    for child in parent.winfo_children():
        yield child
        yield from widgets(child)


def screenshot(root, name):
    root.update()
    try:
        from PIL import ImageGrab
    except ImportError:
        ImageGrab = None
    import os
    import subprocess
    target = Path('docs/screenshots')
    target.mkdir(exist_ok=True)
    if ImageGrab is not None:
        ImageGrab.grab(xdisplay=os.environ.get('DISPLAY')).save(target/name)
    elif os.environ.get('MINIERP_SCREENSHOT_PYTHON'):
        subprocess.run([os.environ['MINIERP_SCREENSHOT_PYTHON'], '-c', 'import os,sys;from PIL import ImageGrab;ImageGrab.grab(xdisplay=os.environ.get("DISPLAY")).save(sys.argv[1])', str(target/name)], check=True)
    else:
        print('Screenshot skipped: optional Pillow absent')


def main():
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        demos(folder/'inputs')
        service = ERP(folder/'data')
        service.company('000000000','ΣΥΝΘΕΤΙΚΗ ΕΤΑΙΡΕΙΑ — GUI TEST')
        service.close()
        root = tk.Tk()
        app = Desktop(root,folder/'data')
        app.state_filter.set('Όλα τα παραστατικά');app.refresh()
        errors = []
        root.report_callback_exception = lambda *args:errors.append(str(args))
        try:
            for filename, count in [('separate.xlsx',2),('combined.xlsx',3),('separate.xlsx',3)]:
                with patch('app.ui.desktop.filedialog.askopenfilename',return_value=str(folder/'inputs'/filename)):
                    app.choose_excel()
                wait(root,lambda:not app.busy)
                top = [w for w in root.winfo_children() if isinstance(w,tk.Toplevel)][-1]
                if filename=='separate.xlsx' and count==2:
                    screenshot(root,'import-preview.png')
                commit = next(w for w in widgets(top) if isinstance(w,ttk.Button) and str(w.cget('text')).startswith('Επιβεβαιώνω'))
                with patch('app.ui.desktop.messagebox.askyesno',return_value=True):
                    commit.invoke()
                wait(root,lambda:not app.busy)
                assert len(app.tree.get_children())==count,(filename,count)
                for win in root.winfo_children():
                    if isinstance(win,tk.Toplevel):win.destroy()
            app.query.set('000000001')
            app.refresh()
            assert len(app.tree.get_children())==1
            app.tree.selection_set(app.tree.get_children()[0])
            app.open_detail()
            assert any(isinstance(w,tk.Toplevel) for w in root.winfo_children())
            screenshot(root,'document-detail.png')
            for win in root.winfo_children():
                if isinstance(win,tk.Toplevel):win.destroy()
            app.query.set('')
            app.refresh()
            screenshot(root,'documents.png')
            assert not errors,errors
            print('GUI PASS: preview → confirm → two layouts → 3 documents → duplicate retry → search → detail')
        finally:
            app.close()

if __name__=='__main__':main()
