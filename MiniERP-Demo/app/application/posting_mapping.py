"""Explain missing extra-row positions before native input; no posting actions."""
from decimal import Decimal


def require_mapping(payload,mapping):
    lines=payload.get('detail_lines',[])
    if not lines:return
    from app.infrastructure.ebs_adapter.adapter import detail_positions
    try:detail_positions(mapping,len(lines))
    except ValueError as exc:
        rows=[]
        for index,line in enumerate(lines,1):
            net=format(Decimal(line['net_minor'])/100,'.2f').replace('.',',')
            tax=format(Decimal(line['tax_minor'])/100,'.2f').replace('.',',')
            source=', '.join(map(str,line.get('source_line_numbers',[line.get('line_number',index)])))
            rows.append(f"Γραμμή EBS {index}: {line['account']} · καθαρή {net} € · ΦΠΑ ΑΑΔΕ {tax} € · γραμμές XML {source}")
        raise ValueError(f"{payload['invoice']} · {payload['name']} · {payload['date']}\n{exc}\nΑπαιτούνται {len(lines)} γραμμές EBS:\n"+'\n'.join(rows)) from None
