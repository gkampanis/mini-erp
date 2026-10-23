"""Conservative one-to-one matching; amounts/date alone never establish identity."""
import hashlib
import json
import re
import unicodedata
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


def normalize(raw,mapping,epoch1904=False):
    fields={key:str(raw.get(index,'')).strip() for key,index in mapping.items()};item={};errors=[]
    for key,value in fields.items():
        try:
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
        except (ValueError,OverflowError) as exc:errors.append(LABELS[key]+': '+str(exc))
    for key in ('vat','date','net_minor','tax_minor','gross_minor'):
        if key not in item:errors.append('Λείπει '+{'vat':'ΑΦΜ προμηθευτή','date':'ημερομηνία','net_minor':'καθαρή αξία','tax_minor':'ΦΠΑ','gross_minor':'συνολική αξία'}[key])
    if not item.get('invoice') and not (item.get('number') and 'series' in item):errors.append('Χρειάζεται πλήρες παραστατικό ή χωριστά σειρά και αριθμός')
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
        # Candidate generation only: a similar numeric suffix can require review,
        # but can NEVER replace the complete visible reference in the exact rule.
        suffix=re.search(r'([0-9]+)$',ref)
        if supplier and suffix:by_number.setdefault((supplier,suffix[1].lstrip('0') or '0'),[]).append(row)
    results={};owners={}
    for doc in documents:
        ref=full_reference(doc);key=(doc['vat'],ref)
        candidates={r['row']:r for r in by_ref.get(key,[])}
        candidates.update({r['row']:r for r in by_tokens.get((doc['vat'],reference_tokens(ref)),[]) if equivalent_reference(full_reference(r['normalized']),ref)})
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
            for key,doc_key in (('vat','vat'),('date','issue_date'),('net_minor','net_minor'),('tax_minor','tax_minor'),('gross_minor','gross_minor')):
                if item.get(key)!=doc[doc_key]:differences.append({'vat':'ΑΦΜ','date':'ημερομηνία','net_minor':'καθαρή αξία','tax_minor':'ΦΠΑ','gross_minor':'συνολική αξία'}[key])
            if item.get('invoice'):
                if not equivalent_reference(item['invoice'],ref):differences.append('πλήρες αναγνωριστικό / σειρά / αριθμός')
                if 'series' in item and item['series']!=reference(doc['series']):differences.append('χωριστή στήλη σειράς')
                if 'number' in item and item['number']!=reference(doc['number']):differences.append('χωριστή στήλη αριθμού')
            elif item.get('series')!=reference(doc['series']) or item.get('number')!=reference(doc['number']):differences.append('σειρά/αριθμός')
            if item.get('mark') and doc.get('mark') and item['mark']!=doc['mark']:differences.append('MARK')
            if item.get('invoice_type') and (not doc.get('invoice_type') or item['invoice_type']!=doc['invoice_type']):differences.append('είδος ΑΑΔΕ')
            if candidate['error']:differences.append('ελλιπή/μη έγκυρα στοιχεία Excel')
            if differences:state='review';reason='Πιθανή αντιστοίχιση — διαφορετικά/ελλιπή: '+', '.join(differences)
            else:
                state='registered';reason=('Ίδιο MARK και ' if item.get('mark') and item.get('mark')==doc.get('mark') else 'Ίδιο ')+ 'ΑΦΜ, ημερομηνία, καθαρή, ΦΠΑ και συνολική αξία. '+('Ισοδύναμο πλήρες αναγνωριστικό: ίδια γράμματα/ψηφία με διαφορετικούς διαχωριστές' if item.get('invoice') and item['invoice']!=ref else 'Ίδιο πλήρες αναγνωριστικό παραστατικού')
                owners.setdefault(candidate['row'],[]).append(doc['id'])
        results[doc['id']]=dict(status=state,reason=reason,excel_rows=numbers,snapshot_hash=fingerprint(doc))
    for row,ids in owners.items():
        if len(ids)>1:
            for document in ids:results[document].update(status='review',reason='Η ίδια γραμμή Excel αντιστοιχεί σε περισσότερα παραστατικά')
    return results
