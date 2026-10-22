"""Explicit synthetic demo, never touches an existing production data directory."""
import argparse
from pathlib import Path
from app.application.service import ERP
from app.infrastructure.importers.excel import preview
from tests.fixtures import demos


def main():
    parser = argparse.ArgumentParser(description='Συνθετικό demo Mini ERP')
    parser.add_argument('--data-dir',type=Path,default=Path('.local/demo'))
    parser.add_argument('--prepare-only',action='store_true')
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True,exist_ok=True)
    marker = args.data_dir/'SYNTHETIC_DEMO_ONLY'
    if (args.data_dir/'mini_erp.sqlite3').exists() and not marker.exists():
        raise SystemExit('Απαιτείται ξεχωριστός κενός φάκελος demo')
    marker.touch(exist_ok=True)
    demos(args.data_dir/'samples')
    service = ERP(args.data_dir)
    try:
        company = service.company('000000000','ΣΥΝΘΕΤΙΚΗ ΕΤΑΙΡΕΙΑ — DEMO')
        for path in sorted((args.data_dir/'samples').glob('*.xlsx')):
            print(path.name, service.commit_import(company,preview(path),confirmed=True))
        print('Παραστατικά:',len(service.search(company)))
    finally:
        service.close()
    if not args.prepare_only:
        import tkinter as tk
        from app.ui.desktop import Desktop
        from app.ui.dpi import enable
        enable()
        root = tk.Tk()
        Desktop(root,args.data_dir)
        root.mainloop()

if __name__=='__main__':main()
