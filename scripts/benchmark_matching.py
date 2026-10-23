"""Repeatable synthetic before/after matching; never reads a customer database."""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.domain.ebs_matching import compare
from tests.test_ebs_matching_rules import document,excel


def cases():
    docs=[];rows=[]
    def add(number,source=None,series='INV',**changes):
        doc=document(len(docs)+1,series,str(number));docs.append(doc)
        if source is not None:
            row=excel(source,**changes);row['row']=len(rows)+2;rows.append(row)
        return doc
    add('125','INV/125')
    add('126','INV-126')
    add('00127','Α-127','Α')
    add('128','ΤΠ 128','ΤΠ')
    add('129',None);rows.append(dict(row=6,normalized=dict(vat='000000001',series='inv',series_original='INV',number='129',number_original='129',date='2026-09-15',net_minor=10000,tax_minor=2400,gross_minor=12400),error=''))
    add('999')
    add('131','INV/131',net_minor=10001)
    add('132','INV/132',date='2026-09-16')
    add('133','INV/133');duplicate=dict(rows[-1],row=len(rows)+2);rows.append(duplicate)
    add('00134',None,'Α');add('134','Α/134','Α')
    add('135','INV/135');rows[-1]['normalized'].pop('date')
    add('136','Α136','Α*')
    return docs,rows


def summarize(result,seconds):
    counts=Counter(r['status'] for r in result.values());kinds=Counter(r.get('match_kind','legacy') for r in result.values())
    return dict(documents=len(result),registered=counts['registered'],exact=kinds['exact'],normalized=kinds['normalized'],
                needs_review=counts['review']-kinds['normalized'],pending=counts['not_registered'],seconds=round(seconds,6))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--baseline',type=Path);parser.add_argument('--output',type=Path);args=parser.parse_args()
    docs,rows=cases();start=time.perf_counter();new=compare(docs,rows,True);report=dict(scope='Synthetic decision matrix; not production AADE reconciliation',new=summarize(new,time.perf_counter()-start))
    if args.baseline:
        spec=importlib.util.spec_from_file_location('previous_matching',args.baseline);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        start=time.perf_counter();old=module.compare(docs,rows,True);report['old']=summarize(old,time.perf_counter()-start)
        report['previous_auto_matches_now_protected']=sum(old[k]['status']=='registered' and new[k]['status']=='review' for k in new)
        report['strict_failures_previously_auto_matched']=sum(old[k]['status']=='registered' and new[k]['match_kind'] in ('conflict','ambiguous') for k in new)
    docs=[document(i+1,number=str(i+1)) for i in range(10000)]
    rows=[dict(excel('INV'+('/' if i%4==0 else '-')+('00' if i%4==2 else '')+str(i+1)),row=i+2) for i in range(10000) if i%4!=3]
    start=time.perf_counter();volume=compare(docs,rows,True);report['volume_new']=summarize(volume,time.perf_counter()-start)
    if args.baseline:
        start=time.perf_counter();oldvolume=module.compare(docs,rows,True);report['volume_old']=summarize(oldvolume,time.perf_counter()-start)
    body=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    if args.output:args.output.write_text(body,encoding='utf8')
    else:print(body)

if __name__=='__main__':main()
