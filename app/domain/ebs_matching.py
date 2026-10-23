"""Conservative one-to-one matching; amounts/date alone never establish identity."""
import hashlib
import json
import re
import unicodedata
from decimal import Decimal,InvalidOperation
from app.domain.validation import cents,iso_date
from app.domain.invoice_types import TYPES

FIELDS=('vat','receiver','invoice_type','series','number','invoice','date','net','tax','gross','mark')
LABELS={'vat':'ΑΦΜ προμηθευτή','receiver':'ΑΦΜ εταιρείας','invoice_type':'Κωδικός τύπου ΑΑΔΕ','series':'Σειρά','number':'Αριθμός','invoice':'Πλήρες παραστατικό (σειρά/αριθμός)','date':'Ημερομηνία έκδοσης','net':'Καθαρή αξία','tax':'ΦΠΑ','gross':'Συνολική αξία','mark':'MARK'}


def reference(value):return unicodedata.normalize('NFKC',str(value or '')).strip().casefold()

def vat(value):
    value=''.join(str(value or '').split()).upper()
    if value.startswith('EL'):value=value[2:]
    if re.fullmatch(r'[0-9]{9}\.0+',value):value=value.split('.')[0]
    if not re.fullmatch('[0-9]{9}',value):raise ValueError('Χρειάζεται ΑΦΜ 9 ψηφίων· δεν συμπληρώνονται χαμένα αρχικά μηδενικά')
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
            elif key in ('net','tax','gross'):item[key+'_minor']=cents(value)
            elif key=='invoice_type':
                code=value if value in TYPES else next((c for c,label in TYPES.items() if reference(label)==reference(value)),'')
                if not code:raise ValueError('Μη αναγνωρισμένο είδος ΑΑΔΕ')
                item[key]=code
            elif key=='mark':
                value=re.sub(r'\.0+$','',value)
                if value and not re.fullmatch('[0-9]+',value):raise ValueError('Μη έγκυρο MARK')
                item[key]=value
            else:item[key]=reference(value)
        except (ValueError,OverflowError) as exc:fail(key,str(exc))
    for key in ('vat','net_minor','tax_minor','gross_minor'):
        field=key.removesuffix('_minor')
        if key not in item and field not in fields:fail(field,'Δεν επιλέχθηκε στήλη')
    if not item.get('invoice') and not (item.get('number') and 'series' in item):fail('invoice','Κενό παραστατικό· χρειάζεται Εναλ. παρ/κό ή χωριστά σειρά και αριθμός')
    return item,' · '.join(dict.fromkeys(errors))


def full_reference(item):
    return item.get('invoice') or '/'.join(reference(item.get(k)) for k in ('series','number') if item.get(k))


def reference_tokens(value):
    """Preserve letter/digit groups (including zeros); vary separators only."""
    return tuple(re.findall(r'[^\W\d_]+|[0-9]+',reference(value)))


def equivalent_reference(left,right):
    if left==right:return True
    tokens=reference_tokens(left)
    return len(tokens)>=2 and any(t.isdigit() for t in tokens) and tokens==reference_tokens(right)


def number_only_reference(item,doc):
    """A bare EBS supplier number can omit the local series, never digits/zeros.

    Acceptance still requires VAT, all three amounts and one-to-one
    ownership in compare(); this is not arbitrary suffix/fuzzy matching.
    """
    invoice=item.get('invoice','');number=reference(doc.get('number'))
    return bool(re.fullmatch('[0-9]+',invoice) and invoice==number)


def fingerprint(row):
    keys=('company_id','id','direction','vat','series','number','issue_date','mark','kind','net_minor','tax_minor','gross_minor','currency','invoice_type','is_delivery_note')
    return hashlib.sha256(json.dumps({k:row.get(k) for k in keys},sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def compare(documents,excel_rows,complete):
    by_mark={};by_ref={};by_number={};by_tokens={};incomplete_vats=set()
    for row in excel_rows:
        item=row['normalized'];mark=item.get('mark');supplier=item.get('vat');ref=full_reference(item)
        if supplier and row['error']:incomplete_vats.add(supplier)
        if mark:by_mark.setdefault(mark,[]).append(row)
        if supplier and ref:by_ref.setdefault((supplier,ref),[]).append(row)
        if supplier and ref:by_tokens.setdefault((supplier,reference_tokens(ref)),[]).append(row)
        # A similar numeric suffix only generates candidates; acceptance below
        # requires an equivalent full reference or the exact bare supplier number.
        suffix=re.search(r'([0-9]+)$',ref)
        if supplier and suffix:by_number.setdefault((supplier,suffix[1].lstrip('0') or '0'),[]).append(row)
    results={};owners={}
    for doc in documents:
        ref=full_reference(doc);key=(doc['vat'],ref)
        candidates={r['row']:r for r in by_ref.get(key,[])}
        candidates.update({r['row']:r for r in by_tokens.get((doc['vat'],reference_tokens(ref)),[]) if equivalent_reference(full_reference(r['normalized']),ref)})
        number=reference(doc.get('number'))
        candidates.update({r['row']:r for r in by_ref.get((doc['vat'],number),[]) if number_only_reference(r['normalized'],doc)})
        if doc.get('mark'):candidates.update({r['row']:r for r in by_mark.get(doc['mark'],[])})
        if not candidates:
            suffix=re.search(r'([0-9]+)$',ref)
            if suffix:candidates={r['row']:r for r in by_number.get((doc['vat'],suffix[1].lstrip('0') or '0'),[])}
        state='not_registered' if complete else 'not_found'
        reason='Δεν βρέθηκε στον επιβεβαιωμένο πλήρη κατάλογο EBS της περιόδου' if complete else 'Δεν εντοπίστηκε στο Excel· ο κατάλογος δεν δηλώθηκε πλήρης'
        numbers=sorted(candidates)
        if not candidates and doc['vat'] in incomplete_vats:
            state='review';reason='Υπάρχουν ελλιπείς γραμμές Excel για αυτό το ΑΦΜ· δεν τεκμηριώνεται απουσία από το EBS'
        if len(candidates)>1:state='review';reason='Πολλαπλές αντιστοιχίσεις / διπλές γραμμές Excel'
        elif candidates:
            candidate=next(iter(candidates.values()));item=candidate['normalized'];differences=[]
            for key,doc_key in (('vat','vat'),('net_minor','net_minor'),('tax_minor','tax_minor'),('gross_minor','gross_minor')):
                if item.get(key)!=doc[doc_key]:differences.append({'vat':'ΑΦΜ','date':'ημερομηνία','net_minor':'καθαρή αξία','tax_minor':'ΦΠΑ','gross_minor':'συνολική αξία'}[key])
            # Preserve validation of legacy, explicitly date-mapped evidence.
            # New UI imports use only reference, VAT and the three amounts.
            if 'date' in item and item['date']!=doc['issue_date']:differences.append('ημερομηνία')
            if item.get('invoice'):
                if not equivalent_reference(item['invoice'],ref) and not number_only_reference(item,doc):differences.append('πλήρες αναγνωριστικό / σειρά / αριθμός')
                if 'series' in item and item['series']!=reference(doc['series']):differences.append('χωριστή στήλη σειράς')
                if 'number' in item and item['number']!=reference(doc['number']):differences.append('χωριστή στήλη αριθμού')
            elif item.get('series')!=reference(doc['series']) or item.get('number')!=reference(doc['number']):differences.append('σειρά/αριθμός')
            if item.get('mark') and doc.get('mark') and item['mark']!=doc['mark']:differences.append('MARK')
            if item.get('invoice_type') and (not doc.get('invoice_type') or item['invoice_type']!=doc['invoice_type']):differences.append('είδος ΑΑΔΕ')
            if candidate['error']:differences.append('ελλιπή/μη έγκυρα στοιχεία Excel')
            if differences:state='review';reason='Πιθανή αντιστοίχιση — διαφορετικά/ελλιπή: '+', '.join(differences)
            else:
                if item.get('invoice')!=ref and number_only_reference(item,doc):identity='Ίδιος ακριβής αριθμός προμηθευτή· το Εναλ. παρ/κό δεν περιέχει τη σειρά'
                elif item.get('invoice') and item['invoice']!=ref:identity='Ισοδύναμο πλήρες αναγνωριστικό: ίδια γράμματα/ψηφία με διαφορετικούς διαχωριστές'
                else:identity='Ίδιο πλήρες αναγνωριστικό παραστατικού'
                state='registered';reason=('Ίδιο MARK και ' if item.get('mark') and item.get('mark')==doc.get('mark') else 'Ίδιο ')+ 'ΑΦΜ, '+('ημερομηνία, ' if 'date' in item else '')+'καθαρή, ΦΠΑ και συνολική αξία. '+identity
                owners.setdefault(candidate['row'],[]).append(doc['id'])
        results[doc['id']]=dict(status=state,reason=reason,excel_rows=numbers,snapshot_hash=fingerprint(doc))
    for row,ids in owners.items():
        if len(ids)>1:
            for document in ids:results[document].update(status='review',reason='Η ίδια γραμμή Excel αντιστοιχεί σε περισσότερα παραστατικά')
    return results
