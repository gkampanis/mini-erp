"""Exact archived detail analysis and explicit company/creditor VAT account choices."""
import copy
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
from app.infrastructure.aade.client import parsed_page
from app.domain.preparation import preparation_values

VAT_RATES={1:24,2:13,3:6,4:17,5:9,6:4,7:0,8:None,9:3,10:4}


def signature(line):return (line['vat_category'],line.get('vat_exemption') or 0)


def vat_label(line):
    rate=VAT_RATES.get(line['vat_category'])
    return 'Χωρίς ΦΠΑ' if rate is None else str(rate)+'%'


def unavailable(reason,status='invalid'):
    return dict(version=1,status=status,lines=[],totals={},errors=[reason])


def compact_rows(rows):
    """One posting row per account/VAT key; keep exact source net and VAT sums."""
    groups={}
    for row in rows:groups.setdefault((row['account'],*signature(row)),[]).append(row)
    result=[]
    for group in groups.values():
        net=sum(r['net_minor'] for r in group);tax=sum(r['tax_minor'] for r in group)
        result.append(dict(group[0],net_minor=net,tax_minor=tax,source_line_numbers=[r['line_number'] for r in group]))
    return result


class VATLines:
    def __init__(self,erp):self.erp=erp;self.db=erp.db

    def analysis(self,company,document):
        row,_=self.erp.detail(company,document)
        records=self.db.execute('SELECT * FROM mydata_records WHERE company_id=? AND document_id=? AND environment=? ORDER BY last_sync DESC,id DESC',(company,document,row['environment'])).fetchall()
        if not records:return None
        latest=records[0];record=json.loads(latest['record_json'])
        if not record.get('identity_verified') or latest['match_status'] in ('different','cancelled_at_aade'):return unavailable('identity')
        if row['direction']!='incoming':return None
        owner=self.db.execute('SELECT vat FROM companies WHERE id=?',(company,)).fetchone()[0]
        if record.get('receiver')!=owner or record.get('vat')!=row['vat']:return unavailable('identity')
        analysis=record.get('detail_analysis')
        if not isinstance(analysis,dict) or analysis.get('version')!=1 or analysis.get('status')=='unsupported':
            analysis=self._archived(company,row['environment'],latest,record)
        elif analysis.get('status')=='verified':
            checked=self._checked(copy.deepcopy(analysis),row)
            if checked['status']!='verified':return checked
            source=self._archived(company,row['environment'],latest,record)
            if source.get('status')!='verified':return source
            if source!=analysis:return unavailable('analysis_source_conflict')
        return self._checked(copy.deepcopy(analysis),row)

    def _archived(self,company,environment,latest,record):
        pages=self.db.execute('SELECT p.* FROM mydata_pages p JOIN mydata_syncs s ON s.id=p.sync_id WHERE s.id=? AND s.company_id=? AND s.environment=? AND s.method=? ORDER BY p.id',(latest['last_sync'],company,environment,'RequestDocs')).fetchall()
        found=[]
        if not pages:return unavailable('archive_missing')
        if not hasattr(self.erp,'_vat_page_cache'):self.erp._vat_page_cache={}
        cache=self.erp._vat_page_cache
        for page in pages:
            relative=Path(page['storage_path']);path=(self.erp.directory/relative).resolve()
            if relative.is_absolute() or not path.is_relative_to((self.erp.directory/'mydata/xml').resolve()):return unavailable('archive_path')
            try:
                if path.stat().st_size>16*1024*1024:return unavailable('archive_size')
                data=path.read_bytes()
            except OSError:return unavailable('archive_missing')
            digest=hashlib.sha256(data).hexdigest()
            if digest!=page['sha256']:return unavailable('archive_hash')
            key=(str(path),digest)
            if key not in cache:
                try:cache[key]=parsed_page(data)['records']
                except (ValueError,RuntimeError):return unavailable('archive_parse')
                if len(cache)>16:cache.pop(next(iter(cache)))
            for item in cache[key]:
                if item['mark']!=latest['mark']:continue
                fields=('mark','vat','receiver','series','number','date','kind','net','tax','gross')
                # Source summary lexical spelling may differ from old normalized JSON;
                # compare money numerically without rounding.
                from app.infrastructure.aade.lines import minor
                try:matches=all(minor(item[k])==minor(record[k]) if k in ('net','tax','gross') else item.get(k)==record.get(k) for k in fields)
                except (KeyError,ValueError):matches=False
                if not matches:return unavailable('archive_identity')
                found.append(item['detail_analysis'])
        if not found:return unavailable('archive_invoice_missing')
        from app.infrastructure.aade.lines import financial_details
        if any(financial_details(a)!=financial_details(found[0]) for a in found[1:]):return unavailable('archive_conflict')
        preferred=(record.get('detail_analysis') or {}).get('source_sha256')
        return next((a for a in found if a.get('source_sha256')==preferred),found[0])

    def _checked(self,analysis,document):
        if not isinstance(analysis,dict):return unavailable('analysis_shape')
        if analysis.get('status')!='verified':return analysis
        totals=analysis.get('totals',{});lines=analysis.get('lines',[])
        if not lines or any(type(totals.get(k)) is not int or totals[k]!=document[k] for k in ('net_minor','tax_minor','gross_minor')):return unavailable('document_totals')
        if analysis.get('currency') not in (None,'EUR'):return unavailable('currency','unsupported')
        try:
            from app.infrastructure.aade.lines import minor,integer
            seen=set()
            for line in lines:
                raw=line['raw']
                if line['line_number'] in seen or integer(raw['lineNumber'].strip())!=line['line_number']:raise ValueError()
                seen.add(line['line_number'])
                if minor(raw['netValue'].strip())!=line['net_minor'] or minor(raw['vatAmount'].strip())!=line['tax_minor']:raise ValueError()
                if integer(raw['vatCategory'].strip())!=line['vat_category']:raise ValueError()
                exempt=raw.get('vatExemptionCategory');exempt=integer(exempt.strip()) if exempt else None
                if exempt!=line.get('vat_exemption'):raise ValueError()
            if sum(l['net_minor'] for l in lines)!=totals['net_minor'] or sum(l['tax_minor'] for l in lines)!=totals['tax_minor']:raise ValueError()
        except (KeyError,TypeError,ValueError,AttributeError):return unavailable('line_integrity')
        return analysis

    def rules(self,company,counterparty):
        card=self.db.execute('SELECT environment FROM counterparties WHERE company_id=? AND id=?',(company,counterparty)).fetchone()
        if card is None:raise ValueError('Δεν βρέθηκε πιστωτής στην εταιρεία')
        return [dict(r) for r in self.db.execute('SELECT * FROM counterparty_vat_rules WHERE company_id=? AND environment=? AND counterparty_id=? ORDER BY vat_category,vat_exemption',(company,card['environment'],counterparty))]

    def requirements(self,company,documents):
        result=[]
        for document in documents:
            row,_=self.erp.detail(company,document);analysis=self.analysis(company,document)
            if analysis is None or analysis['status']=='missing':continue
            if analysis['status']!='verified':result.append(dict(document=document,counterparty_id=row['counterparty_id'],name=row['name'],analysis=analysis,missing=[]));continue
            from app.infrastructure.aade.lines import posting_source_lines
            signatures=list(dict.fromkeys(signature(l) for l in posting_source_lines(analysis)))
            known={signature(r) for r in self.rules(company,row['counterparty_id'])}
            if len(signatures)<2 and not known:continue
            missing=[s for s in signatures if s not in known]
            if missing:result.append(dict(document=document,counterparty_id=row['counterparty_id'],name=row['name'],analysis=analysis,missing=missing))
        return result

    def posting_requirements(self,company,documents):
        """Ask only for invoices eligible for the existing production expense flow."""
        from app.application.rpa import RPA
        from app.application.ebs_reconciliation import EBSReconciliation
        from app.application.supplier_accounts import account_group
        rpa=RPA(self.erp);scope=rpa.expense_scope(company,documents)
        candidates=set(scope['expenses']+scope['needs_review'])
        evidence=EBSReconciliation(self.erp).results(company,include_attempts=False)
        eligible=[]
        for document in documents:
            if document not in candidates or (evidence[document]['status']!='not_registered' and not evidence[document].get('posting_permitted')):continue
            row,_=self.erp.detail(company,document)
            if row['rounding_minor']:continue
            approval=self.erp.preparation(company,document)
            if not approval:
                default=self.db.execute('SELECT * FROM counterparty_accounts WHERE company_id=? AND counterparty_id=?',(company,row['counterparty_id'])).fetchone()
                if not default or not default['expenses_account'] or account_group(dict(default))!='6':continue
            try:rpa.live_source(company,document)
            except ValueError:continue
            eligible.append(document)
        return self.requirements(company,eligible)

    def save_rules(self,company,counterparty,rules,confirmed=False):
        if confirmed is not True or not rules:raise ValueError('Απαιτείται έγκριση λογαριασμών ΦΠΑ')
        self.rules(company,counterparty)
        card=self.db.execute('SELECT environment FROM counterparties WHERE company_id=? AND id=?',(company,counterparty)).fetchone()
        if self.db.execute("SELECT 1 FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id JOIN documents d ON d.id=i.document_id WHERE j.company_id=? AND d.counterparty_id=? AND j.status='running' AND i.status IN ('queued','started','save_pending') LIMIT 1",(company,counterparty)).fetchone():raise ValueError('Παύσε πρώτα την ενεργή καταχώριση του πιστωτή')
        checked=[];seen=set()
        for rule in rules:
            category=rule.get('vat_category');exempt=rule.get('vat_exemption') or 0;primary=rule.get('use_primary')
            if type(category) is not int or category not in VAT_RATES or type(exempt) is not int or exempt<0 or type(primary) is not bool:raise ValueError('Μη έγκυρος κανόνας ΦΠΑ')
            key=(category,exempt)
            if key in seen:raise ValueError('Διπλός κανόνας ΦΠΑ')
            seen.add(key)
            account=None if primary else preparation_values('6',rule.get('account'),'','local_operator',True)['account_code']
            checked.append((category,exempt,int(primary),account))
        with (nullcontext() if self.db.in_transaction else self.db):
            before=self.rules(company,counterparty)
            for category,exempt,primary,account in checked:self.db.execute("INSERT INTO counterparty_vat_rules(company_id,environment,counterparty_id,vat_category,vat_exemption,use_primary,account) VALUES (?,?,?,?,?,?,?) ON CONFLICT(company_id,environment,counterparty_id,vat_category,vat_exemption) DO UPDATE SET use_primary=excluded.use_primary,account=excluded.account,updated_at=CURRENT_TIMESTAMP",(company,card['environment'],counterparty,category,exempt,primary,account))
            self.erp.repository.audit(company,'creditor_vat_rules_approved',None,dict(counterparty_id=counterparty,before=before,after=self.rules(company,counterparty)))
            from app.application.supplier_accounts import SupplierAccounts
            queued=self.db.execute("SELECT DISTINCT d.id FROM documents d JOIN rpa_items i ON i.document_id=d.id JOIN rpa_jobs j ON j.id=i.job_id WHERE d.company_id=? AND d.counterparty_id=? AND j.company_id=d.company_id AND i.status='queued' AND j.status IN ('queued','paused')",(company,counterparty)).fetchall()
            for document in queued:
                try:SupplierAccounts(self.erp).rebind_pending(company,document['id'])
                except ValueError:
                    # Keep the explicit rule even if a queued source now needs review;
                    # existing freshness checks prevent that stale snapshot from typing.
                    self.erp.repository.audit(company,'vat_queue_needs_review',document['id'],dict(counterparty_id=counterparty))

    def posting_lines(self,company,document,primary_account):
        row,_=self.erp.detail(company,document);analysis=self.analysis(company,document)
        if analysis is None:return []
        if analysis['status']=='missing':raise ValueError('Λείπουν οι αναλυτικές γραμμές ΑΑΔΕ. Επανέλαβε την άντληση πριν την καταχώριση.')
        if analysis['status']!='verified':raise ValueError('Χρειάζεται έλεγχος της ανάλυσης γραμμών ΑΑΔΕ')
        from app.infrastructure.aade.lines import posting_source_lines
        source_lines=posting_source_lines(analysis)
        signatures={signature(l) for l in source_lines}
        mixed=len(signatures)>1
        rules={signature(r):r for r in self.rules(company,row['counterparty_id'])};result=[]
        from app.infrastructure.aade.lines import financial_fingerprint
        source_finances=financial_fingerprint(analysis)
        for line in source_lines:
            rule=rules.get(signature(line))
            if (mixed or rules) and rule is None:raise ValueError('Όρισε λογαριασμό για ΦΠΑ '+vat_label(line)+' στην καρτέλα πιστωτή')
            account=primary_account if rule is None or rule['use_primary'] else rule['account']
            preparation_values('6',account,'','local_operator',True)
            result.append(dict(line_number=line['line_number'],net_minor=line['net_minor'],tax_minor=line['tax_minor'],vat_category=line['vat_category'],vat_exemption=line.get('vat_exemption'),account=account,financial_sha256=source_finances))
        rows=compact_rows(result)
        # A remembered secondary also applies to a later invoice containing only
        # that VAT category; the original native one-row sequence still applies.
        return rows if len(rows)>1 or (rows and rows[0]['account']!=primary_account) else []
