import argparse
from pathlib import Path
import os


def main():
    parser = argparse.ArgumentParser(description='Ανεξάρτητο Mini ERP')
    parser.add_argument('--data-dir',type=Path,default=Path(os.environ.get('MINIERP_DATA_DIR', str(Path.home()/'MiniERP-data'))))
    parser.add_argument('--check',action='store_true',help='Initialize/migrate database and report integrity')
    args = parser.parse_args()
    if args.check:
        from app.application.service import ERP
        service = ERP(args.data_dir)
        print('SQLite integrity:',service.db.execute('PRAGMA integrity_check').fetchone()[0])
        service.close()
    else:
        import tkinter as tk
        from app.ui.desktop import Desktop
        from app.ui.dpi import enable
        enable()
        root = tk.Tk()
        def callback_error(kind,error,tb):
            from app.infrastructure.crashlog import record
            from tkinter import messagebox
            record(args.data_dir,error.with_traceback(tb),'callback')
            messagebox.showerror('Σφάλμα εφαρμογής','Αποθηκεύτηκε διαγνωστικό. Ρυθμίσεις → Υποστήριξη → Αποθήκευση crashlog.',parent=root)
        root.report_callback_exception=callback_error
        Desktop(root,args.data_dir)
        try:
            root.mainloop()
        except tk.TclError:
            pass

if __name__ == '__main__':
    main()
