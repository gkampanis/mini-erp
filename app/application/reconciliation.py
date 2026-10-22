"""Associate by MARK and verified identity; differences remain visible for review."""
from app.domain.validation import cents


def reference(series,number):
    return '/'.join(part.strip() for part in '/'.join(p for p in (series,number) if p).split('/')).casefold()


def associate(db,company,item):
    document=db.execute('SELECT d.*,c.vat FROM documents d JOIN counterparties c ON c.id=d.counterparty_id WHERE d.company_id=? AND d.mark=?',(company,item['mark'])).fetchone()
    if document is None or document['direction']!=item['direction']:return None,'unmatched',False
    identity=(document['vat']==item['vat'] and document['issue_date']==item['date'] and reference(document['series'],document['number'])==reference(item['series'],item['number']))
    try:amounts=all(document[column]==cents(item[field]) for column,field in [('net_minor','net'),('tax_minor','tax'),('gross_minor','gross')])
    except ValueError:amounts=False
    return document,'matched' if identity and amounts else 'different',identity
