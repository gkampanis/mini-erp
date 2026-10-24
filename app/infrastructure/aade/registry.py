"""Official RgWsPublic2 SOAP 1.2 contract, AADE developer bundle v1.1 (2023-07)."""
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from app.infrastructure.aade.client import NoRedirect,APIError

ENDPOINT='https://www1.gsis.gr/wsaade/RgWsPublic2/RgWsPublic2'
ACTION='http://rgwspublic2/RgWsPublic2Service:rgWsPublic2AfmMethod'
SOAP='http://www.w3.org/2003/05/soap-envelope'
WSSE='http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd'
SERVICE='http://rgwspublic2/RgWsPublic2Service'
TYPES='http://rgwspublic2/RgWsPublic2'
REQUEST_TIMEOUT=15

class RegistryAccessError(APIError):pass
class RegistryLimited(APIError):pass
class RegistryNotFound(APIError):pass


def credentials(username,password):
    if any(not isinstance(s,str) or not s.strip() or len(s)>1000 or any(ord(c)<32 for c in s) for s in (username,password)):raise ValueError('Συμπλήρωσε έγκυρους ειδικούς κωδικούς Μητρώου')
    return dict(username=username.strip(),key=password)


def vat(value):
    if not isinstance(value,str) or len(value)!=9 or not value.isascii() or not value.isdigit():raise ValueError('Χρειάζεται ΑΦΜ 9 ψηφίων')
    return value


def request_body(username,password,called_by,called_for):
    credentials(username,password);vat(called_by);vat(called_for)
    envelope=ET.Element('{'+SOAP+'}Envelope');header=ET.SubElement(envelope,'{'+SOAP+'}Header')
    token=ET.SubElement(ET.SubElement(header,'{'+WSSE+'}Security'),'{'+WSSE+'}UsernameToken')
    ET.SubElement(token,'{'+WSSE+'}Username').text=username
    ET.SubElement(token,'{'+WSSE+'}Password').text=password
    body=ET.SubElement(envelope,'{'+SOAP+'}Body');method=ET.SubElement(body,'{'+SERVICE+'}rgWsPublic2AfmMethod');record=ET.SubElement(method,'{'+SERVICE+'}INPUT_REC')
    ET.SubElement(record,'{'+TYPES+'}afm_called_by').text=called_by;ET.SubElement(record,'{'+TYPES+'}afm_called_for').text=called_for
    return ET.tostring(envelope,encoding='utf-8',xml_declaration=True)


def parse(data,expected_vat):
    if len(data)>2*1024*1024:raise APIError('Υπερβολικά μεγάλη απόκριση Μητρώου')
    try:
        decoded=data.decode('utf-8-sig')
        if any(s in decoded.upper() for s in ('<!DOCTYPE','<!ENTITY')) or '\0' in decoded:raise ValueError()
        root=ET.fromstring(decoded)
    except (ValueError,ET.ParseError,UnicodeError):raise APIError('Μη έγκυρη απόκριση XML Μητρώου') from None
    if root.tag!='{'+SOAP+'}Envelope':raise APIError('Μη αναμενόμενη δομή απόκρισης Μητρώου')
    if root.find('.//{'+SOAP+'}Fault') is not None:raise RegistryAccessError('Η υπηρεσία Μητρώου επέστρεψε σφάλμα. Έλεγξε ειδικούς κωδικούς και δικαιώματα.')
    ns={'r':TYPES,'s':SERVICE,'soap':SOAP}
    result=root.find('soap:Body/s:rgWsPublic2AfmMethodResponse/s:result/r:rg_ws_public2_result_rtType',ns)
    if result is None:raise APIError('Μη αναμενόμενη δομή απόκρισης Μητρώου')
    code=result.findtext('r:error_rec/r:error_code','',ns)
    if code and code.strip():
        upper=code.upper()
        if any(token in upper for token in ('AUTH','TOKEN','PASSWORD','USERNAME','ACCESS','SECURITY')):raise RegistryAccessError('Έλεγξε ειδικούς κωδικούς και δικαιώματα Μητρώου')
        if any(token in upper for token in ('LIMIT','QUOTA','THROTTL')):raise RegistryLimited('Η υπηρεσία Μητρώου περιόρισε τα αιτήματα· η εργασία σταμάτησε')
        raise APIError('Η αναζήτηση Μητρώου δεν ολοκληρώθηκε για αυτό το ΑΦΜ')
    basic=result.find('r:basic_rec',ns)
    if basic is None:raise RegistryNotFound('Δεν επιστράφηκαν στοιχεία επιχείρησης')
    allowed=('afm','onomasia','commer_title','doy','doy_descr','postal_address','postal_address_no','postal_zip_code','postal_area_description','deactivation_flag_descr','firm_flag_descr')
    values={field:(basic.findtext('r:'+field,'',ns) or '').strip() for field in allowed}
    if not values['afm'] and not values['onomasia']:raise RegistryNotFound('Δεν επιστράφηκαν στοιχεία επιχείρησης')
    if values['afm']!=expected_vat or not values['onomasia']:raise APIError('Δεν επαληθεύτηκε η αντιστοίχιση ΑΦΜ και επωνυμίας στην απόκριση')
    return values


def lookup(username,password,called_by,called_for,opener=None):
    data=request_body(username,password,called_by,called_for)
    request=urllib.request.Request(ENDPOINT,data=data,headers={'Content-Type':'application/soap+xml; charset=utf-8; action="'+ACTION+'"','Accept':'application/soap+xml'},method='POST')
    try:
        with (opener or urllib.request.build_opener(NoRedirect())).open(request,timeout=REQUEST_TIMEOUT) as response:result=response.read(2*1024*1024+1)
    except urllib.error.HTTPError as exc:
        if exc.code in (401,403):raise RegistryAccessError('Η υπηρεσία απέρριψε τα διαπιστευτήρια ή τα δικαιώματα Μητρώου') from None
        if exc.code in (429,503):raise RegistryLimited('Περιορισμός ή προσωρινή μη διαθεσιμότητα Μητρώου· η εργασία σταμάτησε') from None
        raise APIError('Αποτυχία σύνδεσης Μητρώου') from None
    except (urllib.error.URLError,OSError,TimeoutError,APIError):raise APIError('Αποτυχία σύνδεσης Μητρώου. Δεν αποθηκεύτηκαν στοιχεία ή κωδικοί σε log.') from None
    return parse(result,called_for)
