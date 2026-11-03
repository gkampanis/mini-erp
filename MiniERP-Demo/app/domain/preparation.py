"""Explicit local preparation only; never validates an EBS chart or posts entries."""
import re

_ACCOUNT = re.compile(r'[26][0-9]*(?:[.-][0-9]+)*\Z', re.ASCII)


def preparation_values(group, account_code, note, actor, confirmed):
    if confirmed is not True:
        raise ValueError('Απαιτείται ρητή έγκριση προετοιμασίας')
    if group not in ('2', '6'):
        raise ValueError('Επίλεξε ομάδα 2 (αγορές) ή 6 (έξοδα)')
    if not isinstance(account_code, str):
        raise ValueError('Ο λογαριασμός πρέπει να είναι κείμενο')
    account_code = account_code.strip()
    if len(account_code) > 40 or not _ACCOUNT.fullmatch(account_code):
        raise ValueError('Μη έγκυρος λογαριασμός: χρησιμοποίησε ψηφία με τελείες ή παύλες')
    if not account_code.startswith(group):
        raise ValueError('Ο λογαριασμός δεν συμφωνεί με την επιλεγμένη ομάδα')
    if not isinstance(actor, str) or not actor.strip() or len(actor.strip()) > 128:
        raise ValueError('Απαιτείται αναγνωρίσιμος εγκρίνων (έως 128 χαρακτήρες)')
    if not isinstance(note, str) or len(note) > 2000:
        raise ValueError('Η σημείωση πρέπει να είναι κείμενο έως 2.000 χαρακτήρες')
    return dict(nature_group=group, account_code=account_code, note=note.strip(), approved_by=actor.strip())
