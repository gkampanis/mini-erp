"""Read-only myDATA ERP REST v2.0.2, official September 2026 documentation.

No send/cancel/classification endpoint is exposed. Credentials never follow redirects.
"""
from datetime import datetime
import time
import math
import hashlib
import threading
from email.utils import parsedate_to_datetime
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from app.infrastructure.aade.credentials import validate,USER_HEADER,KEY_HEADER

BASES={'test':'https://mydataapidev.aade.gr/','production':'https://mydatapi.aade.gr/myDATA/'}
NS={'m':'http://www.aade.gr/myDATA/invoice/v1.0'}
MAX_PAGE=16*1024*1024


class APIError(RuntimeError):pass


class RateLimitError(APIError):
    def __init__(self,retry_after):
        self.retry_after=max(1,math.ceil(retry_after))
        super().__init__(f'Η ΑΑΔΕ περιόρισε προσωρινά τα αιτήματα (HTTP 429). Νέα προσπάθεια σε {self.retry_after} δευτερόλεπτα. Η υπόλοιπη άντληση σταμάτησε.')


def retry_seconds(header):
    try:return max(1,math.ceil(float(header)))
    except (ValueError,TypeError,OverflowError):
        try:return max(1,math.ceil(parsedate_to_datetime(header).timestamp()-time.time()))
        except (ValueError,TypeError,OverflowError):return 60


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise APIError('Η ΑΑΔΕ επέστρεψε ανακατεύθυνση. Οι κωδικοί δεν προωθήθηκαν.')


def record_signature(item):
    from decimal import Decimal
    from app.infrastructure.aade.lines import financial_details
    identity=tuple(item.get(k) for k in ('vat','receiver','date','kind','series','number','is_delivery_note','correlated_marks','delivery_status','delivery_lifecycle'))
    amounts=tuple(Decimal(item[k]) if item.get(k) else None for k in ('net','tax','gross'))
    return identity,amounts,financial_details(item.get('detail_analysis'))


def unique_pages(pages):
    """Retain raw XML, deduplicate equivalent finances, reject conflicting MARKs."""
    from app.infrastructure.providers.xml_parser import positive_mark
    seen={};result=[]
    for data,page in pages:
        records=[]
        for item in page['records']:
            mark=str(positive_mark(str(item['mark'])))
            normalized=dict(item,mark=mark)
            if mark in seen:
                if record_signature(normalized)!=record_signature(seen[mark]):raise APIError('Αντικρουόμενα παραστατικά με ίδιο MARK στην άντληση ΑΑΔΕ. Δεν αποθηκεύτηκε μερική λήψη.')
                continue
            seen[mark]=normalized;records.append(normalized)
        result.append((data,dict(page,records=records)))
    return result


def parsed_page(data):
    from app.infrastructure.aade.lines import extract_lines,financial_details
    from app.infrastructure.providers.xml_parser import parse_response,read_envelope,child,text,positive_mark
    from app.infrastructure.providers.models import ParseError
    try:
        page=parse_response(data);root=read_envelope(data)
    except ParseError as exc:raise APIError(str(exc)) from None
    names={};metadata={};cancelled=[]
    for container in root:
        if container.tag.rsplit('}',1)[-1]=='invoicesDoc':
            for node in container:
                mark=str(positive_mark(text(node,'mark')))
                pair=(text(child(node,'issuer'),'name') or '',text(child(node,'counterpart'),'name') or '')
                header=child(node,'invoiceHeader')
                detail=dict(
                    detail_analysis=extract_lines(node),
                    correlated_marks=[e.text.strip() for e in header if e.tag.rsplit('}',1)[-1]=='correlatedInvoices' and e.text and e.text.strip()] if header is not None else [],
                    delivery_status=text(node,'invoiceDeliveryStatus') or '',
                    delivery_lifecycle=ET.tostring(child(node,'deliveryLifecycle'),encoding='unicode') if child(node,'deliveryLifecycle') is not None else '')
                if mark in metadata:
                    if (financial_details(metadata[mark]['detail_analysis'])!=financial_details(detail['detail_analysis'])
                            or any(metadata[mark][key]!=detail[key] for key in ('correlated_marks','delivery_status','delivery_lifecycle'))):raise APIError('Αντικρουόμενη ανάλυση για ίδιο MARK στην απάντηση ΑΑΔΕ.')
                else:names[mark]=pair;metadata[mark]=detail
                if text(node,'cancelledByMark'):cancelled.append(mark)
    records=[]
    for invoice in page.invoices:
        records.append(dict(mark=str(invoice.mark),vat=invoice.issuer_vat or '',name=names.get(str(invoice.mark),('',''))[0],receiver_name=names.get(str(invoice.mark),('',''))[1],receiver=invoice.recipient_vat or '',
                            series=invoice.series or '',number=invoice.number or '',date=invoice.issue_date,kind=invoice.invoice_type or '',
                            net=str(invoice.net) if invoice.net is not None else '',tax=str(invoice.vat) if invoice.vat is not None else '',gross=str(invoice.total) if invoice.total is not None else '',pdf_url=invoice.download_url or '',is_delivery_note=invoice.is_delivery_note,**metadata.get(str(invoice.mark),{})))
    result=dict(records=records,cancellations=cancelled+[str(c.invoice_mark) for c in page.changes if c.kind=='cancellation'],next=page.continuation)
    return unique_pages([(data,result)])[0][1]


class Client:
    _cooldowns={}
    _cooldown_lock=threading.Lock()
    def __init__(self,environment,username,key,opener=None,sleep=time.sleep):
        self.credentials=validate(environment,username,key);self.base=BASES[environment]
        self._limit_key=hashlib.sha256((self.base+'\0'+self.credentials['username']).encode()).hexdigest()
        self.opener=opener or urllib.request.build_opener(NoRedirect());self.sleep=sleep

    def _check_cooldown(self):
        with self._cooldown_lock:remaining=self._cooldowns.get(self._limit_key,0)-time.monotonic()
        if remaining>0:raise RateLimitError(remaining)

    def fetch(self,date_from,date_to,mark='0',entity_vat=None,method='RequestDocs',single_page=False,cancel=None):
        self._check_cooldown()
        if method not in ('RequestDocs','RequestTransmittedDocs','RequestMyExpenses'):raise ValueError('Επιτρέπεται μόνο λήψη παραστατικών')
        start=datetime.strptime(date_from,'%Y-%m-%d');end=datetime.strptime(date_to,'%Y-%m-%d')
        if start>end:raise ValueError('Η ημερομηνία από πρέπει να προηγείται της έως')
        if not isinstance(mark,str) or not mark.isascii() or not mark.isdigit():raise ValueError('Μη έγκυρο MARK εκκίνησης')
        params=dict(dateFrom=start.strftime('%d/%m/%Y'),dateTo=end.strftime('%d/%m/%Y'))
        if method!='RequestMyExpenses':params['mark']=mark
        if entity_vat:
            if len(entity_vat)!=9 or not entity_vat.isascii() or not entity_vat.isdigit():raise ValueError('Μη έγκυρο ΑΦΜ εκπροσωπούμενης εταιρείας')
            params['entityVatNumber']=entity_vat
        seen=set();pages=[];total=0
        for page in range(100):
            if cancel is not None and cancel.is_set():raise APIError('Η λήψη ακυρώθηκε χωρίς αποθήκευση μερικών δεδομένων')
            request=urllib.request.Request(self.base+method+'?'+urllib.parse.urlencode(params),headers={USER_HEADER:self.credentials['username'],KEY_HEADER:self.credentials['key'],'Accept':'application/xml'},method='GET')
            for attempt in range(3):
                try:
                    self._check_cooldown()
                    with self.opener.open(request,timeout=30) as response:data=response.read(MAX_PAGE+1)
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code==429:
                        wait=retry_seconds(exc.headers.get('Retry-After') if exc.headers else None)
                        with self._cooldown_lock:
                            now=time.monotonic()
                            deadline=max(self._cooldowns.get(self._limit_key,0),now+wait)
                            self._cooldowns[self._limit_key]=deadline
                        raise RateLimitError(deadline-now) from None
                    if exc.code in (401,403):raise APIError('Η ΑΑΔΕ αρνήθηκε πρόσβαση. Έλεγξε API username/key, περιβάλλον και εξουσιοδότηση εταιρείας.') from None
                    if exc.code in (500,502,503,504) and attempt<2:self.sleep(min(2**attempt,4));continue
                    raise APIError('Σφάλμα ΑΑΔΕ HTTP '+str(exc.code)+'. Δεν αποθηκεύτηκε μερική λήψη.') from None
                except (urllib.error.URLError,TimeoutError,OSError):raise APIError('Δεν επιτεύχθηκε σύνδεση με ΑΑΔΕ. Έλεγξε δίκτυο και περιβάλλον.') from None
            if method=='RequestMyExpenses':
                from app.infrastructure.aade.book import parse_book
                parsed=parse_book(data)
            else:parsed=parsed_page(data)
            pages.append((data,parsed));total+=len(data)
            if total>64*1024*1024:raise APIError('Η λήψη υπερβαίνει το όριο. Επίλεξε μικρότερο χρονικό διάστημα.')
            token=parsed['next']
            if single_page or token is None:return pages if method=='RequestMyExpenses' else unique_pages(pages)
            if token in seen:raise APIError('Επαναλαμβανόμενη σελιδοποίηση ΑΑΔΕ. Δεν αποθηκεύτηκε μερική λήψη.')
            seen.add(token);params.update(nextPartitionKey=token[0],nextRowKey=token[1])
        raise APIError('Πάνω από 100 σελίδες. Επίλεξε μικρότερο διάστημα.')
