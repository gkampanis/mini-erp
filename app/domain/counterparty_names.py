"""Recognize only the application's exact missing-name placeholders."""
import unicodedata


def missing_name(name,supplier_vat):
    text=' '.join(str(name or '').split()).casefold()
    if not text or text==str(supplier_vat or '').strip().casefold():return True
    plain=''.join(c for c in unicodedata.normalize('NFD',text) if not unicodedata.combining(c))
    return plain=='χωρις επωνυμια'.casefold()
