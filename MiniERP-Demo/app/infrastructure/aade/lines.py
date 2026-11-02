"""Lossless detail analysis; never allocates tax or selects accounting treatment."""
from decimal import Decimal,InvalidOperation
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from app.infrastructure.providers.xml_parser import child,text,local_name

MONEY=re.compile(r'\+?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z',re.ASCII)
SUMMARY={'totalNetValue':'net_minor','totalVatAmount':'tax_minor','totalGrossValue':'gross_minor'}
ADDITIONS=('totalFeesAmount','totalStampDutyAmount','totalOtherTaxesAmount')
SUBTRACTIONS=('totalWithheldAmount','totalDeductionsAmount')


def minor(value):
    if not isinstance(value,str) or len(value)>60 or not MONEY.fullmatch(value):raise ValueError('decimal')
    try:
        number=Decimal(value)
        if not number.is_finite() or number>Decimal('92233720368547758.07'):raise ValueError('amount')
        _,digits,exponent=number.as_tuple()
        coefficient=int(''.join(map(str,digits)));scale=exponent+2
        if scale>=0:return coefficient*10**scale
        cents,remainder=divmod(coefficient,10**(-scale))
        if remainder:raise ValueError('precision')
        return cents
    except InvalidOperation:raise ValueError('decimal') from None


def integer(value):
    if not isinstance(value,str) or not value.isascii() or not value.isdigit() or len(value)>10 or not 0<int(value)<=2147483647:raise ValueError('integer')
    return int(value)


def financial_details(analysis):
    """Posting-relevant source values; raw XML remains separately archived."""
    if not isinstance(analysis,dict):return None
    return dict(status=analysis.get('status'),currency=analysis.get('currency') or 'EUR',invoice_type=analysis.get('invoice_type'),
                totals=analysis.get('totals'),errors=analysis.get('errors'),
                lines=[{key:line.get(key) for key in ('line_number','net_minor','tax_minor','vat_category','vat_exemption','rec_type')} for line in analysis.get('lines',[])])


def financial_fingerprint(analysis):
    return hashlib.sha256(json.dumps(financial_details(analysis),sort_keys=True,separators=(',',':')).encode()).hexdigest()


def posting_source_lines(analysis):
    """Keep informational evidence archived without creating an accounting row."""
    return [line for line in analysis['lines'] if not (line.get('rec_type')==6 and line['net_minor']==0 and line['tax_minor']==0)]


def extract_lines(invoice):
    errors=[]
    def field(element,key,label,required=False):
        found=[e for e in element if local_name(e.tag)==key] if element is not None else []
        if len(found)>1:errors.append(label+'.'+key+'.duplicate')
        value=found[0].text.strip() if found and found[0].text and found[0].text.strip() else None
        if required and value is None:errors.append(label+'.'+key+'.missing')
        return value
    def converted(element,key,label,converter,required=False,default=None):
        value=field(element,key,label,required)
        if value is None:return default
        try:return converter(value)
        except ValueError:errors.append(label+'.'+key+'.invalid');return None
    summary=child(invoice,'invoiceSummary');header=child(invoice,'invoiceHeader')
    summary_raw={local_name(e.tag):e.text for e in summary} if summary is not None else {}
    totals={alias:converted(summary,key,'summary',minor,required=True) for key,alias in SUMMARY.items()}
    lines=[];seen=set();unsupported=False
    for index,node in enumerate(e for e in invoice if local_name(e.tag)=='invoiceDetails'):
        label='line'+str(index+1)
        line=dict(line_number=converted(node,'lineNumber',label,integer,True),net_minor=converted(node,'netValue',label,minor,True),
                  tax_minor=converted(node,'vatAmount',label,minor,True),vat_category=converted(node,'vatCategory',label,integer,True),
                  vat_exemption=converted(node,'vatExemptionCategory',label,integer),rec_type=converted(node,'recType',label,integer),
                  raw={local_name(e.tag):e.text for e in node},source_xml=ET.tostring(node,encoding='unicode'))
        number=line['line_number']
        if number is not None:
            if number in seen:errors.append(label+'.lineNumber.duplicate')
            seen.add(number)
        if line['vat_category'] is not None and not 1<=line['vat_category']<=10:errors.append(label+'.vatCategory.unknown')
        if line['vat_category']==7 and line['vat_exemption'] is None:errors.append(label+'.vatExemptionCategory.missing')
        if line['vat_category'] in (7,8) and line['tax_minor'] not in (0,None):errors.append(label+'.vatAmount.nonzero')
        # AADE ERP v2.0.2, note 7: VAT-bearing fees/other taxes (2/3)
        # use netValue, not feesAmount/otherTaxesAmount. Other semantics remain
        # unsupported except zero-value informational rows (6).
        rec_type=line['rec_type']
        if rec_type not in (None,2,3) and not (rec_type==6 and line['net_minor']==0 and line['tax_minor']==0):unsupported=True
        if rec_type in (2,3) and any(key in line['raw'] for key in ('feesAmount','otherTaxesAmount','stampDutyAmount','withheldAmount','deductionsAmount')):unsupported=True
        lines.append(line)
    if lines and not unsupported and not errors:
        if sum(r['net_minor'] for r in lines)!=totals['net_minor']:errors.append('summary.net.mismatch')
        if sum(r['tax_minor'] for r in lines)!=totals['tax_minor']:errors.append('summary.vat.mismatch')
        adjustments={key:converted(summary,key,'summary',minor,default=0) for key in ADDITIONS+SUBTRACTIONS}
        if all(v is not None for v in adjustments.values()):
            expected=totals['net_minor']+totals['tax_minor']+sum(adjustments[k] for k in ADDITIONS)-sum(adjustments[k] for k in SUBTRACTIONS)
            if expected!=totals['gross_minor']:errors.append('summary.gross.mismatch')
    xml=ET.tostring(invoice,encoding='utf-8')
    return dict(version=1,status='missing' if not lines else 'invalid' if errors else 'unsupported' if unsupported else 'verified',
                lines=lines,totals=totals,summary_raw=summary_raw,errors=errors,currency=text(header,'currency'),
                invoice_type=text(header,'invoiceType'),source_sha256=hashlib.sha256(xml).hexdigest())
