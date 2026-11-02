"""Synthetic bulk-history GUI stress.

Run: python -X utf8 -X faulthandler scripts/stress_bulk_history.py --cards 240 --cycles 8

Never opens EBS or production data. Every database/workbook lives in TemporaryDirectory.
"""
import argparse
import faulthandler
import gc
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from app.application.service import ERP
from app.infrastructure.importers.excel import preview
from app.ui.desktop import Desktop
from app.ui.history_accounts import HistoryImport
from tests.fixtures import volume_workbook,workbook


def pump(root,milliseconds=230):
    deadline=time.monotonic()+milliseconds/1000
    while time.monotonic()<deadline:
        root.update();time.sleep(.005)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cards',type=int,default=240)
    parser.add_argument('--cycles',type=int,default=8)
    parser.add_argument('--mode',choices=('full','pending-destroy','no-fit'),default='full')
    args=parser.parse_args();faulthandler.enable(all_threads=True)
    print('RUNTIME',sys.version,flush=True)
    with tempfile.TemporaryDirectory(prefix='minierp-synthetic-bulk-') as folder:
        folder=Path(folder);book=folder/'source.xlsx';volume_workbook(book,args.cards,args.cards)
        erp=ERP(folder/'data');company=erp.company('000000000','SYNTHETIC BULK STRESS')
        erp.commit_import(company,preview(book),confirmed=True)
        with erp.db:erp.db.execute("UPDATE counterparties SET environment='production' WHERE company_id=?",(company,))
        erp.close();root=tk.Tk();errors=[]
        root.report_callback_exception=lambda *exc:errors.append(repr(exc))
        print('TK',root.tk.call('info','patchlevel'),'MODE',args.mode,flush=True)
        app=Desktop(root,folder/'data');app.state_filter.set('Όλα τα παραστατικά');app.refresh();pump(root)
        cards=app.erp.db.execute('SELECT id,name FROM counterparties WHERE company_id=? ORDER BY id',(company,)).fetchall()
        assert len(cards)==args.cards,(len(cards),args.cards)
        if args.mode=='no-fit':app.tree.presentation.automatic=False
        ui=None
        try:
            for cycle in range(args.cycles):
                history=folder/f'history-{cycle}.xlsx'
                workbook(history,[['Συν/νος','Ημ/νία','Παρ/κό','Δαπάνη','Περιγραφή'],
                    *[[card['name'],'2026-09-01',f'S{cycle}-{card["id"]}','64.03.0000','synthetic'] for card in cards]])
                ui=HistoryImport(app);ui.load(history);root.update();ui.select_ready()
                assert len(ui.tree.selection())==args.cards
                print('APPLY',cycle,'selected',len(ui.tree.selection()),flush=True)
                with patch('app.ui.history_accounts.messagebox.askyesno',return_value=True),patch('app.ui.history_accounts.messagebox.showerror',side_effect=AssertionError):
                    ui.apply_selected()
                if args.mode=='pending-destroy':ui.win.destroy();ui=None
                root.geometry(f'{1100+cycle%3*30}x{760+cycle%2*20}')
                app.refresh();pump(root)
                if ui is not None:
                    assert all(row['applied'] for row in ui.rows.values())
                    ui.win.destroy();ui=None
                gc.collect();pump(root,180)
                print('CYCLE_OK',cycle,flush=True)
            assert not errors,errors
            print('PASS',args.cards,'cards',args.cycles,'cycles',flush=True)
        finally:
            if ui is not None and ui.win.winfo_exists():ui.win.destroy()
            app.close();gc.collect()
            print('WINDOWS_CLOSED',flush=True)


if __name__=='__main__':main()
