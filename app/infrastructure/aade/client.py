"""Read-only myDATA ERP REST v2.0.2, official September 2026 documentation.

No send/cancel/classification endpoint is exposed. Credentials never follow redirects.
"""
from datetime import datetime
import time
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from app.infrastructure.aade.credentials import validate,USER_HEADER,KEY_HEADER

BASES={'test':'https://mydataapidev.aade.gr/','production':'https://mydatapi.aade.gr/myDATA/'}
NS={'m':'http://www.aade.gr/myDATA/invoice/v1.0'}
MAX_PAGE=16*1024*1024


class APIError(RuntimeError):pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise APIError('Η ΑΑΔΕ επέστρεψε ανακατεύθυνση. Οι κωδικοί δεν προωθήθηκαν.')


def parsed_page(data):
    from app.infrastructure.providers.xml_parser import parse_response,read_envelope,child,text
    from app.infrastructure.providers.models import ParseError
    try:
        page=parse_response(data);root=read_envelope(data)
    except ParseError as exc:raise APIError(str(exc)) from None
    names={};cancelled=[]
    for container in root:
        if container.tag.rsplit('}',1)[-1]=='invoicesDoc':
            for node in container:
                names[text(node,'mark')]=(text(child(node,'issuer'),'name') or '',text(child(node,'counterpart'),'name') or '')
                if text(node,'cancelledByMark'):cancelled.append(str(text(node,'mark')))
    records=[]
    for invoice in page.invoices:
        records.append(dict(mark=str(invoice.mark),vat=invoice.issuer_vat or '',name=names.get(str(invoice.mark),('',''))[0],receiver_name=names.get(str(invoice.mark),('',''))[1],receiver=invoice.recipient_vat or '',
                            series=invoice.series or '',number=invoice.number or '',date=invoice.issue_date,kind=invoice.invoice_type or '',
                            net=str(invoice.net) if invoice.net is not None else '',tax=str(invoice.vat) if invoice.vat is not None else '',gross=str(invoice.total) if invoice.total is not None else '',pdf_url=invoice.download_url or ''))
    return dict(records=records,cancellations=cancelled+[str(c.invoice_mark) for c in page.changes if c.kind=='cancellation'],next=page.continuation)


class Client:
    def __init__(self,environment,username,key,opener=None,sleep=time.sleep):
        self.credentials=validate(environment,username,key);self.base=BASES[environment]
        self.opener=opener or urllib.request.build_opener(NoRedirect());self.sleep=sleep

    def fetch(self,date_from,date_to,mark='0',entity_vat=None,method='RequestDocs',single_page=False,cancel=None):
        if method not in ('RequestDocs','RequestTransmittedDocs'):raise ValueError('Επιτρέπεται μόνο λήψη παραστατικών')
        start=datetime.strptime(date_from,'%Y-%m-%d');end=datetime.strptime(date_to,'%Y-%m-%d')
        if start>end:raise ValueError('Η ημερομηνία από πρέπει να προηγείται της έως')
        if not isinstance(mark,str) or not mark.isascii() or not mark.isdigit():raise ValueError('Μη έγκυρο MARK εκκίνησης')
        params=dict(mark=mark,dateFrom=start.strftime('%d/%m/%Y'),dateTo=end.strftime('%d/%m/%Y'))
        if entity_vat:
            if len(entity_vat)!=9 or not entity_vat.isascii() or not entity_vat.isdigit():raise ValueError('Μη έγκυρο ΑΦΜ εκπροσωπούμενης εταιρείας')
            params['entityVatNumber']=entity_vat
        seen=set();pages=[];total=0
        for page in range(100):
            if cancel is not None and cancel.is_set():raise APIError('Η λήψη ακυρώθηκε χωρίς αποθήκευση μερικών δεδομένων')
            request=urllib.request.Request(self.base+method+'?'+urllib.parse.urlencode(params),headers={USER_HEADER:self.credentials['username'],KEY_HEADER:self.credentials['key'],'Accept':'application/xml'},method='GET')
            for attempt in range(3):
                try:
                    with self.opener.open(request,timeout=30) as response:data=response.read(MAX_PAGE+1)
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code in (401,403):raise APIError('Η ΑΑΔΕ αρνήθηκε πρόσβαση. Έλεγξε API username/key, περιβάλλον και εξουσιοδότηση εταιρείας.') from None
                    if exc.code in (429,500,502,503,504) and attempt<2:self.sleep(min(2**attempt,4));continue
                    raise APIError('Σφάλμα ΑΑΔΕ HTTP '+str(exc.code)+'. Δεν αποθηκεύτηκε μερική λήψη.') from None
                except (urllib.error.URLError,TimeoutError,OSError):raise APIError('Δεν επιτεύχθηκε σύνδεση με ΑΑΔΕ. Έλεγξε δίκτυο και περιβάλλον.') from None
            parsed=parsed_page(data);pages.append((data,parsed));total+=len(data)
            if total>64*1024*1024:raise APIError('Η λήψη υπερβαίνει το όριο. Επίλεξε μικρότερο χρονικό διάστημα.')
            token=parsed['next']
            if single_page or token is None:return pages
            if token in seen:raise APIError('Επαναλαμβανόμενη σελιδοποίηση ΑΑΔΕ. Δεν αποθηκεύτηκε μερική λήψη.')
            seen.add(token);params.update(nextPartitionKey=token[0],nextRowKey=token[1])
        raise APIError('Πάνω από 100 σελίδες. Επίλεξε μικρότερο διάστημα.')
