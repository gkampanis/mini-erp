"""Measure full-reload versus local column actions over 2,500 synthetic rows."""
import json
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.application.service import ERP
from app.ui.desktop import Desktop
from app.infrastructure.importers.excel import preview
from tests.fixtures import volume_workbook


def main():
    with tempfile.TemporaryDirectory() as temporary:
        folder=Path(temporary);volume_workbook(folder/'synthetic.xlsx')
        erp=ERP(folder/'data');company=erp.company('000000000','ΣΥΝΘΕΤΙΚΗ ΔΟΚΙΜΗ')
        erp.commit_import(company,preview(folder/'synthetic.xlsx'),confirmed=True);erp.close()
        root=tk.Tk();app=Desktop(root,folder/'data');root.update()
        try:
            app.month_filter.set('Όλοι οι μήνες');app.state_filter.set('Όλα τα παραστατικά');app.refresh();root.update()
            def measure(action):
                calls=[];app.erp.db.set_trace_callback(calls.append);started=time.perf_counter()
                try:action();root.update()
                finally:app.erp.db.set_trace_callback(None)
                return dict(seconds=round(time.perf_counter()-started,6),sql_statements=len(calls),visible_rows=len(app.tree.get_children()))
            report=dict(scope='Synthetic Linux UI/SQLite timings; no network, AADE or EBS',documents=2500)
            report['previous_sort_full_refresh']=measure(app.refresh)
            report['new_sort_move_only']=measure(lambda:app.sort_documents('gross_minor'))
            app.query.set('000000001')
            report['previous_search_full_refresh']=measure(app.refresh)
            report['new_search_cached']=measure(app.filter_documents)
            print(json.dumps(report,indent=2))
        finally:app.close()


if __name__=='__main__':main()
