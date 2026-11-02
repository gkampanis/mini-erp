"""Calendar months used by the AADE transport, without UI date arithmetic."""
import calendar
from datetime import date

MONTHS=('Ιανουάριος','Φεβρουάριος','Μάρτιος','Απρίλιος','Μάιος','Ιούνιος','Ιούλιος','Αύγουστος','Σεπτέμβριος','Οκτώβριος','Νοέμβριος','Δεκέμβριος')

def month_bounds(year,month):
    try:
        year,month=int(year),int(month)
        first=date(year,month,1);last=date(year,month,calendar.monthrange(year,month)[1])
        return first.isoformat(),last.isoformat()
    except (ValueError,TypeError,OverflowError):raise ValueError('Επίλεξε έγκυρο μήνα και έτος') from None
