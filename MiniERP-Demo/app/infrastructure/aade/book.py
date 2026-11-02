"""RequestMyExpenses is aggregated book information, never an individual invoice."""
from datetime import date
from decimal import Decimal,InvalidOperation
from app.infrastructure.providers.xml_parser import unwrap_xml,local_name,child,text
from app.infrastructure.providers.models import ParseError


def parse_book(data):
    try:
        root=unwrap_xml(data)
        if local_name(root.tag)!='RequestedBookInfo':raise ValueError()
        rows=[];continuation=None
        for node in root:
            kind=local_name(node.tag)
            if kind=='continuationToken':
                if continuation is not None:raise ValueError()
                continuation=(text(node,'nextPartitionKey'),text(node,'nextRowKey'))
                if not all(continuation):raise ValueError()
            elif kind=='bookInfo':
                row={k:text(node,k) or '' for k in ('counterVatNumber','issueDate','invType','selfpricing','invoiceDetailType','netValue','vatAmount','withheldAmount','otherTaxesAmount','stampDutyAmount','feesAmount','deductionsAmount','thirdPartyAmount','grossValue','count','minMark','maxMark')}
                date.fromisoformat(row['issueDate'])
                if not row['invType'] or not row['count'].isascii() or not row['count'].isdigit() or int(row['count'])<1:raise ValueError()
                for key in ('netValue','vatAmount','withheldAmount','otherTaxesAmount','stampDutyAmount','feesAmount','deductionsAmount','thirdPartyAmount','grossValue'):
                    if row[key] and not Decimal(row[key]).is_finite():raise ValueError()
                rows.append(row)
            else:raise ValueError()
        return dict(rows=rows,next=continuation)
    except (ParseError,ValueError,InvalidOperation):
        from app.infrastructure.aade.client import APIError
        raise APIError('Μη έγκυρη απόκριση συνοπτικού βιβλίου εξόδων. Δεν δημιουργήθηκαν τιμολόγια από συγκεντρωτικές γραμμές.') from None
