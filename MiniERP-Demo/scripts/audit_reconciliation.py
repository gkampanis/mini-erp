"""Read-only, redacted cross-check of the bounded importer against calamine.

Developer tool, not an alternative production importer. Install requirements-quality.txt.
No VAT, name, invoice reference or financial value is emitted in the report.
"""
import argparse
from datetime import date,datetime
import hashlib
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.infrastructure.importers.excel import read_workbook,header_mapping
from app.domain.ebs_matching import normalize


def audit_readers(path):
    from python_calamine import CalamineWorkbook
    source=Path(path);original=source.read_bytes();started=time.perf_counter()
    # Run the existing size/XML/formula checks before the independent reader.
    book=read_workbook(source,data=original);import_seconds=time.perf_counter()-started
    started=time.perf_counter();other=CalamineWorkbook.from_path(str(source))
    independent={name:other.get_sheet_by_name(name).to_python(skip_empty_area=False) for name in other.sheet_names}
    calamine_seconds=time.perf_counter()-started
    fields={'date','invoice','vat','net','tax','gross'};compared=0;mismatches=[];valid=0;invalid=0;rows_count=0
    for sheet in book['sheets']:
        if not sheet['rows']:continue
        header_line,headers=sheet['rows'][0];mapping={k:v for k,v in header_mapping(headers).items() if k in fields}
        from app.infrastructure.importers.legacy_primitives import norm
        for index,title in headers.items():
            if norm(title)==norm('Εναλ. παρ/κό'):mapping['invoice']=index
            if norm(title)==norm('Α.Φ.Μ.'):mapping['vat']=index
            if norm(title)==norm('Αξία'):mapping['net']=index
        for line,raw in sheet['rows']:
            if line<=header_line:continue
            rows_count+=1;item,error=normalize(raw,mapping,book['epoch1904'],numeric_columns=sheet['numeric_cells'].get(line,()))
            invalid+=bool(error);valid+=not bool(error)
            alternative=independent.get(sheet['name'],[])
            values=alternative[line-1] if line<=len(alternative) else []
            alt={};numerics=[]
            for column in mapping.values():
                value=values[column] if column<len(values) else ''
                if isinstance(value,(date,datetime)):value=value.date().isoformat() if isinstance(value,datetime) else value.isoformat()
                elif isinstance(value,(int,float)) and not isinstance(value,bool):numerics.append(column)
                alt[column]=str(value)
            converted,_=normalize(alt,mapping,book['epoch1904'],numeric_columns=numerics)
            for field in mapping:
                compared+=1;key=field+'_minor' if field in ('net','tax','gross') else field
                if item.get(key)!=converted.get(key):mismatches.append(dict(row=line,column=mapping[field]+1,field=field))
    assert hashlib.sha256(source.read_bytes()).digest()==hashlib.sha256(original).digest()
    return dict(source_sha256=hashlib.sha256(original).hexdigest(),rows=rows_count,valid_rows=valid,rows_with_issues=invalid,
                compared_fields=compared,mismatches=mismatches,existing_reader_seconds=round(import_seconds,6),calamine_reader_seconds=round(calamine_seconds,6),
                formula_cells=sum(len(columns) for sheet in book['sheets'] for columns in sheet['formula_cells'].values()),output='Readability cross-check only; no document values or identifiers logged',production_database='NOT_ACCESSED')


def reference_suggestions(document,indexed_rows,limit=5):
    """QA-only ranking inside an already indexed strict identity/financial block.

    Never changes stored matching status. Results contain row numbers/scores,
    never reference text or financial values. Large ambiguous blocks are not ranked.
    """
    from rapidfuzz import process,fuzz
    from app.domain.ebs_matching import strict_key,financial_differences,full_reference
    key=strict_key(document,True)
    rows=[r for r in indexed_rows.get(key,[]) if strict_key(r['normalized'])==key
          and not r['error'] and not financial_differences(r['normalized'],document)]
    if not key or len(rows)>25:return []
    return [(rows[index]['row'],score) for _,score,index in process.extract(full_reference(document),[full_reference(r['normalized']) for r in rows],scorer=fuzz.ratio,limit=limit,score_cutoff=85)]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    report=audit_readers(args.source);body=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    if args.output:args.output.write_text(body,encoding='utf8')
    else:print(body)
    return 1 if report['mismatches'] else 0

if __name__=='__main__':raise SystemExit(main())
