"""Local document validation; no tax/accounting classification or posting."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import date, datetime, timedelta
import re
# Decimal normalization derived from EBS v2.9 money(), kept inside the domain.
def money(value):
    text = str(value).strip().replace('€', '').replace(' ', '').replace('\u00a0', '')
    if ',' in text and '.' in text:
        text = text.replace('.', '').replace(',', '.') if text.rfind(',') > text.rfind('.') else text.replace(',', '')
    elif ',' in text:
        text = text.replace(',', '.')
    return Decimal(text)



def cents(value):
    if not str(value).strip():
        raise ValueError('Κενό ποσό')
    try:
        amount = money(value)
        if not amount.is_finite() or abs(amount) > Decimal('1000000000000'):
            raise ValueError('Ποσό εκτός ορίων')
        return int(amount.quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)*100)
    except InvalidOperation as exc:
        raise ValueError('Μη έγκυρο ποσό') from exc


def iso_date(value, epoch1904=False):
    s = str(value).strip()
    if re.fullmatch(r'\d+(?:\.0+)?', s):
        days = int(Decimal(s))
        if not epoch1904 and days == 60:
            raise ValueError('Ανύπαρκτη Excel ημερομηνία 29/02/1900')
        base = date(1904, 1, 1) if epoch1904 else date(1899, 12, 31)
        return (base + timedelta(days=days if epoch1904 or days < 60 else days-1)).isoformat()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y'):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError('Μη αναγνωρίσιμη ημερομηνία')


def record(fields, epoch1904=False):
    vat = fields.get('vat', '').strip()
    if not re.fullmatch(r'[0-9]{9}', vat):
        raise ValueError('Απαιτείται ΑΦΜ ως κείμενο με 9 ψηφία (χωρίς αυτόματη συμπλήρωση)')
    number = fields.get('number', '').strip()
    series = fields.get('series', '').strip()
    if not number:
        combined = fields.get('invoice', '').strip()
        if '/' in combined:
            series, number = combined.rsplit('/', 1)
        else:
            number = combined
    if number and not series and fields.get('invoice', '').strip() == number and '/' in number:
        series, number = number.rsplit('/', 1)
    if not number:
        raise ValueError('Κενός αριθμός παραστατικού')
    mark = fields.get('mark', '').strip()
    if mark and not re.fullmatch(r'[0-9]+', mark):
        raise ValueError('Μη έγκυρο MARK')
    # MVP accepts incoming invoices only; other kinds go to the rejection queue.
    kind = fields.get('kind', '').strip().casefold()
    if kind not in ('', 'invoice', 'τιμολόγιο', '1.1'):
        raise ValueError('Το είδος απαιτεί χωριστή υποστήριξη/έλεγχο: ' + kind)
    if 'πιστωτικ' in fields.get('description', '').casefold():
        raise ValueError('Πιστωτικό: εκτός πρώτης τομής')
    net = cents(fields.get('net', ''))
    tax = cents(fields.get('tax', ''))
    gross = cents(fields.get('gross', '')) if fields.get('gross', '').strip() else net+tax
    rounding = gross-net-tax
    originals = [money(fields[k]) for k in ('net','tax','gross') if fields.get(k,'').strip()]
    has_fraction = any(value != value.quantize(Decimal('0.01'),rounding=ROUND_HALF_UP) for value in originals)
    raw_difference = abs(money(fields['gross'])-money(fields['net'])-money(fields['tax'])) if fields.get('gross','').strip() else Decimal(0)
    if money(fields['net'])<=0 or money(fields['tax'])<0 or net < 0 or tax < 0 or gross < 0 or (fields.get('gross','').strip() and money(fields['gross'])<0):
        raise ValueError('Απαιτούνται θετική καθαρή/σύνολο και μη αρνητικό ΦΠΑ')
    if rounding and not (has_fraction and abs(rounding)<=1 and raw_difference<=Decimal('0.01')):
        raise ValueError('Το σύνολο δεν συμφωνεί με καθαρή + ΦΠΑ: απαιτείται έλεγχος')
    currency = fields.get('currency', 'EUR').strip() or 'EUR'
    if currency != 'EUR':
        raise ValueError('Πρώτη τομή: μόνο EUR')
    return dict(vat=vat, name=fields.get('name', '').strip() or 'Χωρίς επωνυμία',
                series=series, number=number, issue_date=iso_date(fields.get('date', ''), epoch1904),
                mark=mark or None, net_minor=net, tax_minor=tax, gross_minor=gross,
                currency=currency, direction='incoming', kind='invoice',rounding_minor=rounding)


def rounding_changes(fields, item):
    changes = []
    for key,target in (('net','net_minor'),('tax','tax_minor'),('gross','gross_minor')):
        if fields.get(key,'').strip():
            original = money(fields[key])
            rounded = Decimal(item[target])/100
            if original!=rounded:
                changes.append(dict(field=key,original=str(original),rounded=f'{rounded:.2f}'))
    return changes
