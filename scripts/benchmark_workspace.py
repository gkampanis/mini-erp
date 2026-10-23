"""Measure list refresh with temporary synthetic data, never the user's database.

DISPLAY=:99 /usr/bin/python3 scripts/benchmark_workspace.py --gui
Times are observations on the current machine, not guaranteed Windows timings.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.application.service import ERP
from app.application.workspace import Workspace
from app.application.supplier_accounts import SupplierAccounts
from app.infrastructure.importers.excel import preview
from tests.fixtures import volume_workbook


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gui',action='store_true')
    options=parser.parse_args()
    with tempfile.TemporaryDirectory() as temporary:
        folder=Path(temporary);erp=ERP(folder/'data');company=erp.company('000000000','ΣΥΝΘΕΤΙΚΗ ΔΟΚΙΜΗ ΟΓΚΟΥ')
        volume_workbook(folder/'volume.xlsx');erp.commit_import(company,preview(folder/'volume.xlsx'),confirmed=True)
        results=dict(documents=2500,suppliers=300)
        for label,fn in [('workspace',lambda:Workspace(erp).rows(company)),('suppliers_list',lambda:SupplierAccounts(erp).rows(company))]:
            calls=[];erp.db.set_trace_callback(calls.append);start=time.perf_counter()
            try:rows=fn()
            finally:erp.db.set_trace_callback(None)
            results[label]=dict(seconds=round(time.perf_counter()-start,4),queries=len(calls),rows=len(rows))
        erp.close()
        if options.gui:
            import tkinter as tk
            from app.ui.desktop import Desktop
            root=tk.Tk();start=time.perf_counter();app=Desktop(root,folder/'data');root.update()
            results['desktop_initial_seconds']=round(time.perf_counter()-start,4)
            app.month_filter.set('Όλοι οι μήνες');app.refresh();root.update()
            start=time.perf_counter();app.refresh();root.update()
            results['desktop_all_2500_refresh_seconds']=round(time.perf_counter()-start,4)
            app.close()
        print(json.dumps(results,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
