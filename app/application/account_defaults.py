"""Explicit purchase/expense defaults; not a general chart-of-accounts module."""
from app.domain.preparation import preparation_values


def defaults_values(purchases='',expenses='',preferred=None):
    purchases=purchases.strip();expenses=expenses.strip()
    for group,code in [('2',purchases),('6',expenses)]:
        if code:preparation_values(group,code,'','local_operator',True)
    if preferred not in (None,'2','6'):raise ValueError('Μη έγκυρη προεπιλεγμένη ομάδα')
    if preferred=='2' and not purchases or preferred=='6' and not expenses:raise ValueError('Η προεπιλεγμένη ομάδα χρειάζεται λογαριασμό')
    return dict(purchases_account=purchases,expenses_account=expenses,preferred_group=preferred)
