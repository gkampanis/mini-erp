"""Synthetic before/after registry batch benchmark; never calls AADE.

Compare equivalent 200-card/2,500-document temporary databases. Network latency
is excluded: the injected transport returns valid synthetic JSON-like mappings.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.application.registry import Registry
from app.application.service import ERP
from app.infrastructure.importers.excel import preview
from tests.fixtures import HEADERS,workbook
from tests.test_supplier_purchases import synthetic_vat
from tests.test_workspace import MemoryVault


def measure(registry_type,folder,*,placeholders=False):
    erp=ERP(folder/'data',MemoryVault())
    try:
        company=erp.company('000000008','ΣΥΝΘΕΤΙΚΗ ΔΟΚΙΜΗ ΜΗΤΡΩΟΥ')
        source=folder/'synthetic-registry.xlsx'
        workbook(source,[HEADERS]+[[synthetic_vat(1+i%200),'ΣΥΝΘΕΤΙΚΗ ΕΠΩΝΥΜΙΑ','Δ',str(i+1),'2026-10-21','10','2.40','12.40',str(70000000+i)] for i in range(2500)])
        erp.commit_import(company,preview(source),confirmed=True)
        with erp.db:
            if placeholders:
                erp.db.execute("UPDATE counterparties SET name=CASE WHEN id%2=0 THEN vat ELSE 'Χωρίς επωνυμία' END WHERE company_id=?",(company,))
            else:erp.db.execute("UPDATE counterparties SET name='' WHERE company_id=?",(company,))
        registry=registry_type(erp);registry.save_credentials(company,'synthetic-user','synthetic-key',confirmed=True)
        requests=[];queries=[];notices=[]
        def transport(*args):
            requests.append(args[-1]);return dict(afm=args[-1],onomasia='ΣΥΝΘΕΤΙΚΗ ΕΠΩΝΥΜΙΑ')
        erp.db.set_trace_callback(queries.append);started=time.perf_counter()
        try:report=registry.fill_missing(company,transport=transport,notice=notices.append)
        finally:erp.db.set_trace_callback(None)
        elapsed=time.perf_counter()-started
        scans=sum(query.lstrip().casefold().startswith('select') and (' from documents ' in query.casefold() or ' join documents ' in query.casefold()) for query in queries)
        return dict(seconds=round(elapsed,6),sql_statements=len(queries),document_list_queries=scans,
                    transport_calls=len(requests),unique_requested_vats=len(set(requests)),request_phase_notices=sum(n.get('phase')=='request' for n in notices),
                    filled=report['filled'],skipped=report['skipped'],not_found=report['not_found'],failed=report['failed'],candidates=report['total'])
    finally:erp.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--baseline',type=Path);parser.add_argument('--output',type=Path);args=parser.parse_args()
    report=dict(scope='Synthetic CPU/SQLite comparison only; no network or production data',counterparties=200,documents=2500,transport='Injected immediate synthetic responses')
    with tempfile.TemporaryDirectory() as temporary:
        folder=Path(temporary)
        for label,placeholders in [('blank_names',False),('placeholder_names',True)]:
            case=folder/label;case.mkdir();new=case/'new';new.mkdir()
            report[label]=dict(new=measure(Registry,new,placeholders=placeholders))
            if args.baseline:
                spec=importlib.util.spec_from_file_location('previous_registry',args.baseline);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                old=case/'old';old.mkdir();report[label]['old']=measure(module.Registry,old,placeholders=placeholders)
    body=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(body,encoding='utf8')
    else:print(body)


if __name__=='__main__':main()
