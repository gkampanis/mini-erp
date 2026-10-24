"""AADE ERP 2.0.2 §8.1 / SimpleTypes InvoiceType (official September 2026).

Update code+description together against the official XSD and appendix.
Category recognition never approves an accounting account or an RPA form.
"""
VERSION='2.0.2'
SOURCE='https://www.aade.gr/sites/default/files/2026-09/myDATA%20API%20Documentation%20v2.0.2_official_erp_1.pdf'
TYPES={
 '1.1':'Τιμολόγιο Πώλησης','1.2':'Τιμολόγιο Πώλησης / Ενδοκοινοτικές Παραδόσεις',
 '1.3':'Τιμολόγιο Πώλησης / Παραδόσεις Τρίτων Χωρών','1.4':'Τιμολόγιο Πώλησης / Πώληση για Λογαριασμό Τρίτων',
 '1.5':'Τιμολόγιο Πώλησης / Εκκαθάριση Πωλήσεων Τρίτων - Αμοιβή από Πωλήσεις Τρίτων',
 '1.6':'Τιμολόγιο Πώλησης / Συμπληρωματικό Παραστατικό',
 '2.1':'Τιμολόγιο Παροχής','2.2':'Τιμολόγιο Παροχής / Ενδοκοινοτική Παροχή Υπηρεσιών',
 '2.3':'Τιμολόγιο Παροχής / Παροχή Υπηρεσιών σε λήπτη Τρίτης Χώρας','2.4':'Τιμολόγιο Παροχής / Συμπληρωματικό Παραστατικό',
 '3.1':'Τίτλος Κτήσης (μη υπόχρεος Εκδότης)','3.2':'Τίτλος Κτήσης (άρνηση έκδοσης από υπόχρεο Εκδότη)',
 '5.1':'Πιστωτικό Τιμολόγιο / Συσχετιζόμενο','5.2':'Πιστωτικό Τιμολόγιο / Μη Συσχετιζόμενο',
 '6.1':'Στοιχείο Αυτοπαράδοσης','6.2':'Στοιχείο Ιδιοχρησιμοποίησης','7.1':'Συμβόλαιο - Έσοδο',
 '8.1':'Ενοίκια - Έσοδο','8.2':'Τέλος ανθεκτικότητας κλιματικής κρίσης',
 '8.4':'Απόδειξη Είσπραξης POS','8.5':'Απόδειξη Επιστροφής POS','8.6':'Δελτίο Παραγγελίας Εστίασης',
 '9.1':'Δελτίο Αποστολής Συσχετιζόμενο','9.2':'Συγκεντρωτικό Δελτίο Αποστολής','9.3':'Δελτίο Αποστολής',
 '10.1':'Δελτίο Ποσοτικής Παραλαβής Συσχετιζόμενο','10.2':'Δελτίο Ποσοτικής Παραλαβής Μη Συσχετιζόμενο',
 '11.1':'ΑΛΠ','11.2':'ΑΠΥ','11.3':'Απλοποιημένο Τιμολόγιο','11.4':'Πιστωτικό Στοιχ. Λιανικής',
 '11.5':'Απόδειξη Λιανικής Πώλησης για Λογ/σμό Τρίτων',
 '13.1':'Έξοδα - Αγορές Λιανικών Συναλλαγών ημεδαπής / αλλοδαπής','13.2':'Παροχή Λιανικών Συναλλαγών ημεδαπής / αλλοδαπής',
 '13.3':'Κοινόχρηστα','13.4':'Συνδρομές','13.30':'Παραστατικά Οντότητας ως Αναγράφονται από την ίδια (Δυναμικό)',
 '13.31':'Πιστωτικό Στοιχ. Λιανικής ημεδαπής / αλλοδαπής',
 '14.1':'Τιμολόγιο / Ενδοκοινοτικές Αποκτήσεις','14.2':'Τιμολόγιο / Αποκτήσεις Τρίτων Χωρών',
 '14.3':'Τιμολόγιο / Ενδοκοινοτική Λήψη Υπηρεσιών','14.4':'Τιμολόγιο / Λήψη Υπηρεσιών Τρίτων Χωρών',
 '14.5':'ΕΦΚΑ και λοιποί Ασφαλιστικοί Οργανισμοί','14.30':'Παραστατικά Οντότητας ως Αναγράφονται από την ίδια (Δυναμικό)',
 '14.31':'Πιστωτικό ημεδαπής / αλλοδαπής','15.1':'Συμβόλαιο - Έξοδο','16.1':'Ενοίκιο Έξοδο',
 '17.1':'Μισθοδοσία','17.2':'Αποσβέσεις','17.3':'Λοιπές Εγγραφές Τακτοποίησης Εσόδων - Λογιστική Βάση',
 '17.4':'Λοιπές Εγγραφές Τακτοποίησης Εσόδων - Φορολογική Βάση',
 '17.5':'Λοιπές Εγγραφές Τακτοποίησης Εξόδων - Λογιστική Βάση','17.6':'Λοιπές Εγγραφές Τακτοποίησης Εξόδων - Φορολογική Βάση',
}
CREDITS={'5.1','5.2','11.4','13.31','14.31'}
DELIVERIES={'9.1','9.2','9.3'}
QUANTITY_RECEIPTS={'10.1','10.2'}
INVOICES={'1.1','1.2','1.3','1.4','1.5','1.6','2.1','2.2','2.3','2.4','11.3','14.1','14.2','14.3','14.4'}
# Preserve the validated value-entry workflow; recognizing other types is not approval.
RPA_TYPES={'1.1','1.2','1.3','2.1','2.2','2.3'}
# ERP v2.0.2 appendix 8.1: these are expense-side documents transmitted by
# the entity itself. Being returned by RequestTransmittedDocs is not revenue.
SELF_EXPENSES={code for code in TYPES if code.startswith(('13.','14.'))}|{'15.1','16.1','17.1','17.2','17.5','17.6'}


def classify(code,is_delivery_note=False):
    code=str(code or '').strip()
    family='unknown' if code not in TYPES else 'credit_note' if code in CREDITS else 'delivery_note' if code in DELIVERIES else 'quantity_receipt' if code in QUANTITY_RECEIPTS else 'invoice' if code in INVOICES else 'other'
    description=TYPES.get(code,'Μη αναγνωρισμένο είδος')
    if is_delivery_note and family=='invoice':description+=' · με διακίνηση'
    return dict(invoice_type=code,description=description,family=family,is_delivery_note=bool(is_delivery_note),rpa_allowed=code in RPA_TYPES,self_recorded_expense=code in SELF_EXPENSES)


def income_record(item):
    kind=classify(item.get('kind',''),item.get('is_delivery_note',False))
    return item.get('direction')=='outgoing' and not kind['self_recorded_expense'] and kind['family'] not in ('delivery_note','quantity_receipt')


def aade_document(item,direction):
    """Preserve AADE category/sign; non-value records never become value invoices."""
    import re
    from decimal import Decimal,ROUND_HALF_UP
    from app.domain.validation import cents,money,iso_date
    supplier=item['vat'] if direction=='incoming' else item['receiver']
    if not re.fullmatch('[0-9]{9}',supplier):raise ValueError('Χρειάζεται ΑΦΜ αντισυμβαλλομένου 9 ψηφίων')
    number=str(item.get('number','')).strip();mark=str(item.get('mark',''))
    if not number or not re.fullmatch('[0-9]+',mark):raise ValueError('Λείπει αριθμός παραστατικού ή MARK')
    kind=classify(item.get('kind',''),item.get('is_delivery_note',False))
    values={key:item.get(key,'') for key in ('net','tax','gross')}
    if kind['family'] in ('delivery_note','quantity_receipt') and not any(values.values()):values=dict(net='0',tax='0',gross='0')
    amounts={key:cents(value) for key,value in values.items()}
    difference=amounts['gross']-amounts['net']-amounts['tax']
    fractional=any(money(v)!=money(v).quantize(Decimal('.01'),rounding=ROUND_HALF_UP) for v in values.values())
    if difference and not (fractional and abs(difference)<=1 and abs(money(values['gross'])-money(values['net'])-money(values['tax']))<=Decimal('.01')):raise ValueError('Ποσά ΑΑΔΕ που απαιτούν χωριστό λογιστικό έλεγχο')
    if kind['family']=='invoice' and (money(values['net'])<=0 or money(values['tax'])<0 or money(values['gross'])<0):raise ValueError('Το τιμολόγιο απαιτεί έλεγχο προσήμων/αξιών')
    # Keep existing stored identity for 10.x records. Their precise category is
    # provided by invoiceType, without rewriting old documents on another sync.
    stored_kind='delivery_note' if kind['family']=='quantity_receipt' else kind['family']
    return dict(vat=supplier,name=(item.get('name','') if direction=='incoming' else item.get('receiver_name','')) or 'Χωρίς επωνυμία',series=str(item.get('series','')).strip(),number=number,issue_date=iso_date(item['date']),mark=mark,net_minor=amounts['net'],tax_minor=amounts['tax'],gross_minor=amounts['gross'],rounding_minor=difference,currency='EUR',direction=direction,kind=stored_kind)
