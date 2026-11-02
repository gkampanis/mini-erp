"""Only the explicitly approved Entersoft alternate-reference warning."""
import re


def is_ok_button(class_name,text):
    name=class_name.casefold()
    return (name=='button' or name.startswith('windowsforms10.button.')) and is_ok_label(text)


def is_ok_label(text):
    return text.replace('&','').strip()=='OK'


def parse_duplicate(title,body):
    if ' '.join(title.split())!='Προσοχή':return None
    body=' '.join(body.split())
    match=re.fullmatch(r'Ο κωδικός εναλ/κού παραστατικού που επιλέξατε χρησιμοποιείται ήδη στο παρ/κό (\S+) με ημ/νία\s*(\d{2}/\d{2}/\d{4} \d{1,2}:\d{2}:\d{2}\s*(?:πμ|μμ)) και συνολική αξία\s*([\d.]+,\d{2})\.',body)
    return match.groups() if match else None


class DuplicateExistingDocument(RuntimeError):
    def __init__(self,*,vat,invoice,expected_ted,existing_reference,existing_date,existing_amount,dismissed):
        super().__init__('Το EBS επιβεβαίωσε ήδη υπάρχον παραστατικό για τον τρέχοντα πιστωτή και κωδικό.')
        self.vat=vat;self.invoice=invoice;self.expected_ted=expected_ted
        self.existing_reference=existing_reference;self.existing_date=existing_date;self.existing_amount=existing_amount;self.dismissed=dismissed


class CreditorResolutionRequired(RuntimeError):
    def __init__(self,*,vat,invoice,expected_ted):
        super().__init__('Το EBS παραμένει στο ΑΦΜ. Ολοκλήρωσε την επιλογή ή δημιουργία πιστωτή πριν τη συνέχεια.')
        self.vat=vat;self.invoice=invoice;self.expected_ted=expected_ted
