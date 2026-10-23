"""Conservative one-to-one matching; amounts/date alone never establish identity."""
import hashlib
import json
import re
import unicodedata
from decimal import Decimal,InvalidOperation
from app.domain.validation import cents,iso_date,money
from app.domain.invoice_types import TYPES

FIELDS=('vat','receiver','invoice_type','series','number','invoice','date','net','tax','gross','mark')
LABELS={'vat':'ΑΦΜ προμηθευτή','receiver':'ΑΦΜ εταιρείας','invoice_type':'Κωδικός τύπου ΑΑΔΕ','series':'Σειρά','number':'Αριθμός','invoice':'Πλήρες παραστατικό (σειρά/αριθμός)','date':'Ημερομηνία έκδοσης','net':'Καθαρή αξία','tax':'ΦΠΑ','gross':'Συνολική αξία','mark':'MARK'}


def reference(value):return unicodedata.normalize('NFKC',str(value or '')).strip().casefold()

def vat(value):
    value=''.join(str(value or '').split()).upper()
    if not value:raise ValueError('Κενό ΑΦΜ')
    if value.startswith('EL'):value=value[2:]
    if re.fullmatch(r'[0-9]{9}\.0+',value):value=value.split('.')[0]
    if not re.fullmatch('[0-9]{9}',value):raise ValueError('Εκτός υποστηριζόμενης μορφής ΑΦΜ 9 ψηφίων· έλεγξε αν είναι αλλοδαπό ή ελλιπές. Η αρχική τιμή διατηρείται χωρίς αλλαγή ψηφίων')
    return value


def normalize(raw,mapping,epoch1904=False,*,numeric_columns=(),issues=None):
    fields={key:str(raw.get(index,'')).strip() for key,index in mapping.items()};item={};errors=[]
    def fail(key,message):
        errors.append(LABELS[key]+': '+message)
        if issues is not None:issues.append(dict(field=key,column=mapping.get(key),value=str(raw.get(mapping.get(key),'')),message=message))
    for key,value in fields.items():
        try:
            if key in ('vat','receiver','invoice','number','mark') and mapping[key] in numeric_columns and not (value.isascii() and value.isdigit() and value.startswith('0')):
                try:
                    if len(value)>256:raise ValueError('Αριθμητικό αναγνωριστικό εκτός ορίων')
                    number=Decimal(value)
                    if not number.is_finite() or abs(number.adjusted())>=256:raise ValueError('Αριθμητικό αναγνωριστικό εκτός ορίων')
                    value=str(int(number)) if number==number.to_integral_value() else format(number,'f').rstrip('0').rstrip('.')
                except InvalidOperation as exc:raise ValueError('Μη έγκυρο αριθμητικό αναγνωριστικό') from exc
            if key in ('vat','receiver'):item[key]=vat(value)
            elif key=='date':item[key]=iso_date(value,epoch1904)
            elif key in ('net','tax','gross'):
                item[key+'_minor']=cents(value)
                item[key+'_exact']=str(money(value))
            elif key=='invoice_type':
                code=value if value in TYPES else next((c for c,label in TYPES.items() if reference(label)==reference(value)),'')
                if not code:raise ValueError('Μη αναγνωρισμένο είδος ΑΑΔΕ')
                item[key]=code
            elif key=='mark':
                value=re.sub(r'\.0+$','',value)
                if value and not re.fullmatch('[0-9]+',value):raise ValueError('Μη έγκυρο MARK')
                item[key]=value
            else:
                item[key]=reference(value)
                item[key+'_original']=str(raw.get(mapping[key],''))
        except (ValueError,OverflowError) as exc:fail(key,str(exc))
    for key in ('vat','date','net_minor','tax_minor','gross_minor'):
        field=key.removesuffix('_minor')
        if key not in item and field not in fields:fail(field,'Δεν επιλέχθηκε στήλη')
    if not item.get('invoice') and not (item.get('number') and 'series' in item):fail('invoice','Κενό παραστατικό· χρειάζεται Εναλ. παρ/κό ή χωριστά σειρά και αριθμός')
    return item,' · '.join(dict.fromkeys(errors))


def full_reference(item):
    return item.get('invoice') or '/'.join(reference(item.get(k)) for k in ('series','number') if item.get(k))


def fingerprint(row):
    keys=('company_id','id','direction','vat','series','number','issue_date','mark','kind','net_minor','tax_minor','gross_minor','currency','invoice_type','is_delivery_note')
    return hashlib.sha256(json.dumps({k:row.get(k) for k in keys},sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def canonical_reference(value):
    """Normalize only supported separators and the FINAL numeric component.

    Numeric series components and meaningful punctuation stay intact. Greek
    and Latin characters are never transliterated. No substring matching.
    """
    value=reference(value)
    match=re.fullmatch(r'(.*?)([0-9]+)([^\W\d_]+)?',value)
    if not match:return None
    series,number,suffix=match.groups()
    series=re.sub(r'[\s/\-]+','/',series).strip('/')
    return series,(number.lstrip('0') or '0')+(suffix or '')


def exact_identity(item,doc):
    if item.get('invoice'):
        expected='/'.join(str(doc.get(k) or '') for k in ('series','number') if doc.get(k))
        if 'invoice_original' in item:return item['invoice_original']==expected
        return item['invoice']==full_reference(doc)
    return (item.get('series_original',item.get('series'))==str(doc.get('series') or '')
            and item.get('number_original',item.get('number'))==str(doc.get('number') or ''))


def normalized_identity(item,doc):
    left=canonical_reference(full_reference(item));right=canonical_reference(full_reference(doc))
    if not left or not right:return False
    if left==right:return True
    # A bare supplier number is allowed only under the strict financial/date
    # key and global one-to-one ownership below. Omitting a series is partial.
    return not left[0] and left[1]==right[1]


def strict_key(item,document=False):
    keys=('vat','issue_date' if document else 'date','net_minor','tax_minor','gross_minor')
    if any(item.get(k) is None or item.get(k)=='' for k in keys):return None
    return tuple(item[k] for k in keys)


def financial_differences(item,doc):
    differences=[]
    for key,label in (('vat','ΑΦΜ'),('date','ημερομηνία'),('net_minor','καθαρή αξία'),('tax_minor','ΦΠΑ'),('gross_minor','συνολική αξία')):
        if item.get(key)!=doc['issue_date' if key=='date' else key]:differences.append(label)
    for field in ('net','tax','gross'):
        if field+'_exact' in item and Decimal(item[field+'_exact'])!=Decimal(doc[field+'_minor'])/100:
            differences.append('ακριβή δεκαδικά '+{'net':'καθαρής','tax':'ΦΠΑ','gross':'συνόλου'}[field])
    if item.get('mark') and doc.get('mark') and item['mark']!=doc['mark']:differences.append('MARK')
    if item.get('invoice_type') and item['invoice_type']!=doc.get('invoice_type'):differences.append('είδος ΑΑΔΕ')
    # Redundant combined/split fields must not contradict each other.
    if item.get('invoice') and item.get('number'):
        split=dict(series=item.get('series',''),number=item['number'])
        if canonical_reference(full_reference(split))!=canonical_reference(item['invoice']):differences.append('ενιαίο και χωριστό αναγνωριστικό')
    return differences


def compare(documents,excel_rows,complete):
    by_ref={};by_canonical={};by_number={};by_mark={}
    incomplete_scopes={};unknown_refs={};unknown_numbers={}
    for row in excel_rows:
        item=row['normalized'];supplier=item.get('vat');ref=full_reference(item);canonical=canonical_reference(ref)
        if row['error']:
            # An unidentified EBS row cannot certify absence. Quarantine only
            # documents it could represent, using trusted fixed values. An
            # entirely unidentified row deliberately still protects everyone.
            keys=tuple(k for k in ('vat','date','net_minor','tax_minor','gross_minor') if item.get(k) is not None and item.get(k)!='')
            incomplete_scopes.setdefault(keys,{}).setdefault(tuple(item[k] for k in keys),[]).append(row)
            if not supplier and canonical:
                unknown_refs.setdefault(canonical,[]).append(row)
                unknown_numbers.setdefault(canonical[1],[]).append(row)
        if supplier and ref:by_ref.setdefault((supplier,ref),[]).append(row)
        if supplier and canonical:
            by_canonical.setdefault((supplier,canonical),[]).append(row)
            by_number.setdefault((supplier,canonical[1]),[]).append(row)
        if item.get('mark'):by_mark.setdefault(item['mark'],[]).append(row)
    results={};owners={}
    for doc in documents:
        snapshot=fingerprint(doc)
        supplier=doc['vat'];ref=full_reference(doc);canonical=canonical_reference(ref)
        candidates={r['row']:r for r in by_ref.get((supplier,ref),[])}
        if canonical:
            candidates.update({r['row']:r for r in by_canonical.get((supplier,canonical),[])})
            candidates.update({r['row']:r for r in by_canonical.get((supplier,('',canonical[1])),[])})
        if doc.get('mark'):candidates.update({r['row']:r for r in by_mark.get(doc['mark'],[])})
        compatible=[]
        for candidate in candidates.values():
            item=candidate['normalized']
            if (strict_key(item)==strict_key(doc,True) and not candidate['error']
                    and not financial_differences(item,doc)
                    and (exact_identity(item,doc) or normalized_identity(item,doc))):compatible.append(candidate)
        state='not_registered' if complete else 'not_found';kind='unmatched';signature=''
        reason='Δεν βρέθηκε στον επιβεβαιωμένο πλήρη κατάλογο EBS της περιόδου' if complete else 'Δεν εντοπίστηκε στο Excel· ο κατάλογος δεν δηλώθηκε πλήρης'
        evidence=compatible
        if len(compatible)==1:
            candidate=compatible[0];item=candidate['normalized'];exact=exact_identity(item,doc)
            kind='exact' if exact else 'normalized';state='registered' if exact else 'review'
            reason=('Καταχωρισμένο — Ακριβής συμφωνία: ' if exact else 'Μερική συμφωνία — Πιθανώς καταχωρισμένο: ')+ 'ίδια ημερομηνία, ΑΦΜ, καθαρή, ΦΠΑ και σύνολο.'
            if not exact:reason+=' Μοναδική κανονικοποίηση σειράς/αριθμού (κενά, πεζά/κεφαλαία, / ή -, αρχικά μηδενικά ή ενιαίο/χωριστό πεδίο). Εκτός RPA.'
            signature=hashlib.sha256(json.dumps([snapshot,strict_key(item),canonical_reference(full_reference(item))],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            owners.setdefault(candidate['row'],[]).append(doc['id'])
        elif len(compatible)>1:
            kind='ambiguous';state='review';reason='Χρειάζεται έλεγχος: πολλαπλές ισχυρές αντιστοιχίσεις / διπλές γραμμές Excel'
        else:
            if not candidates and canonical:
                candidates={r['row']:r for r in by_number.get((supplier,canonical[1]),[])}
            for keys,index in incomplete_scopes.items():
                key=tuple(doc['issue_date' if k=='date' else k] for k in keys)
                candidates.update({r['row']:r for r in index.get(key,[])})
            if canonical:
                candidates.update({r['row']:r for r in unknown_refs.get(canonical,[])})
                candidates.update({r['row']:r for r in unknown_numbers.get(canonical[1],[])})
            evidence=list(candidates.values())
            if candidates:
                kind='conflict';state='review'
                if len(candidates)==1:
                    candidate=next(iter(candidates.values()));item=candidate['normalized']
                    differences=financial_differences(item,doc)
                    if not normalized_identity(item,doc):differences.append('σειρά/αριθμός')
                    if candidate['error']:differences.append('ελλιπή/μη έγκυρα στοιχεία Excel')
                    reason='Χρειάζεται έλεγχος — διαφορετικά/ελλιπή: '+', '.join(dict.fromkeys(differences))
                else:reason='Χρειάζεται έλεγχος: πολλαπλές πιθανές αντιστοιχίσεις με διαφορές'
        results[doc['id']]=dict(status=state,match_kind=kind,match_signature=signature,reason=reason,excel_rows=sorted(r['row'] for r in evidence),snapshot_hash=snapshot)
    for row,ids in owners.items():
        if len(ids)>1:
            for document in ids:results[document].update(status='review',match_kind='ambiguous',match_signature='',reason='Χρειάζεται έλεγχος: η ίδια γραμμή Excel αντιστοιχεί σε περισσότερα παραστατικά')
    return results
