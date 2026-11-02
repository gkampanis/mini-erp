"""Explicit scheduling permission for ambiguous Excel evidence, never registration."""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
from app.domain.ebs_matching import fingerprint


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


@contextmanager
def authorization_transaction(db):
    if db.in_transaction:
        db.execute('SAVEPOINT review_permission')
        try:yield
        except BaseException:
            db.execute('ROLLBACK TO review_permission');db.execute('RELEASE review_permission')
            raise
        else:db.execute('RELEASE review_permission')
    else:
        with db:
            db.execute('BEGIN IMMEDIATE')
            yield


class ReviewPermissions:
    def __init__(self,erp):self.erp=erp;self.db=erp.db;self._analysis={};self._excel_issues={}

    def _signature(self,company,row):
        self._excel_issues[row['id']]=[]
        owner=self.db.execute('SELECT vat FROM companies WHERE id=?',(company,)).fetchone()
        epoch=self.db.execute("SELECT coalesce(max(id),0) FROM audit_events WHERE company_id=? AND action='company_identified'",(company,)).fetchone()[0]
        evidence=dict(company=company,company_vat=owner['vat'],identity_epoch=epoch,status=row['status'],match_kind=row.get('match_kind',''))
        if row.get('run'):
            run=self.db.execute('SELECT company_vat,date_from,date_to,sha256,sheet,header_row,mapping_json,complete,match_policy FROM ebs_reconciliation_runs WHERE company_id=? AND id=?',(company,row['run'])).fetchone()
            if run is None or run['company_vat']!=owner['vat']:raise ValueError('Άλλαξε η εταιρεία της συμφωνίας EBS')
            evidence['run']=dict(run)
            evidence['rows']=[dict(r) for r in self.db.execute('SELECT row_number,raw_json,normalized_json,error FROM ebs_excel_rows WHERE run_id=? ORDER BY row_number,id',(row['run'],))]
            match=self.db.execute('SELECT excel_rows_json FROM ebs_matches WHERE run_id=? AND document_id=?',(row['run'],row['id'])).fetchone()
            numbers=set(json.loads(match['excel_rows_json'])) if match else set()
            self._excel_issues[row['id']]=[dict(row=r['row_number'],error=r['error']) for r in evidence['rows'] if r['row_number'] in numbers and r['error']]
        from app.infrastructure.aade.lines import financial_fingerprint
        analysis=self._analysis.get(row['id'])
        financial=digest([fingerprint(row),financial_fingerprint(analysis) if analysis is not None else None]);source=digest(evidence)
        return dict(financial_signature=financial,evidence_signature=source,signature=digest([financial,source]))

    def _ready(self,company,row):
        """Only waive Excel ambiguity; account/VAT/mapping readiness stays separate."""
        from app.application.rpa import RPA
        from app.application.vat_lines import VATLines
        from app.application.mydata import MyData
        document=row['id'];rpa=RPA(self.erp)
        if row['status'] not in ('review','not_found','unreconciled') or row.get('submitted'):return False
        scope=rpa.expense_scope(company,[document])
        if document not in scope['expenses']+scope['needs_review']:return False
        if row.get('environment')!='production' or row.get('direction')!='incoming' or not row.get('number'):return False
        datetime.strptime(row['issue_date'],'%Y-%m-%d')
        if self.db.execute("SELECT 1 FROM mydata_records WHERE company_id=? AND document_id=? AND environment='production' AND match_status IN ('different','cancelled_at_aade')",(company,document)).fetchone():return False
        if row.get('mark') and MyData(self.erp).cancelled(company,'production',row['mark']):return False
        rpa.live_source(company,document)
        analysis=VATLines(self.erp).analysis(company,document)
        self._analysis[document]=analysis
        return analysis is None or analysis['status']=='verified'

    def inspect(self,company,documents):
        from app.application.ebs_reconciliation import EBSReconciliation
        if not documents or len(documents)!=len(set(documents)):return []
        evidence=EBSReconciliation(self.erp).results(company,include_attempts=False,include_permissions=False)
        permissions={}
        for event in self.db.execute("SELECT entity_id,payload FROM audit_events WHERE company_id=? AND action='ebs_review_posting_authorized' ORDER BY id",(company,)):
            permissions[event['entity_id']]=json.loads(event['payload']).get('signature')
        rows=[]
        for document in documents:
            row=evidence.get(document)
            if row is None:continue
            try:
                if not self._ready(company,row):continue
                signature=self._signature(company,row)
            except (ValueError,RuntimeError):continue
            issues=self._excel_issues.get(document,[])
            reason=row['reason']+(' · '+' · '.join(r['error'] for r in issues) if issues else '')
            rows.append(dict(row,document=document,**signature,reason=reason,excel_issues=issues,posting_permitted=permissions.get(document)==signature['signature']))
        return rows

    def authorize(self,company,documents,expected_signatures,*,confirmed=False):
        if confirmed is not True or not documents or len(documents)!=len(set(documents)) or not isinstance(expected_signatures,dict):
            raise ValueError('Απαιτείται ρητή επιβεβαίωση συγκεκριμένων παραστατικών για έλεγχο στο EBS')
        with authorization_transaction(self.db):
            rows=self.inspect(company,documents)
            by_id={r['document']:r for r in rows}
            if set(by_id)!=set(documents) or any(expected_signatures.get(d)!=by_id[d]['signature'] for d in documents):
                raise ValueError('Άλλαξαν τα παραστατικά ή η συμφωνία Excel. Άνοιξε ξανά τον έλεγχο.')
            for document in documents:
                row=by_id[document]
                self.erp.repository.audit(company,'ebs_review_posting_authorized',document,dict(signature=row['signature'],financial_signature=row['financial_signature'],evidence_signature=row['evidence_signature'],status=row['status'],reason=row['reason'],verification='operator_allows_ebs_attempt',not_registration_evidence=True))
        return rows

    def apply(self,company,results):
        granted={r['entity_id'] for r in self.db.execute("SELECT DISTINCT entity_id FROM audit_events WHERE company_id=? AND action='ebs_review_posting_authorized'",(company,))}
        candidates=[d for d,r in results.items() if d in granted and r['status'] in ('review','not_found','unreconciled') and not r.get('submitted')]
        # Avoid XML/archive work on ordinary refreshes before any permission exists.
        authorized={r['document']:r for r in self.inspect(company,candidates) if r['posting_permitted']} if candidates else {}
        for doc,row in results.items():
            row['posting_permitted']=doc in authorized
            if doc in authorized:
                row['reason']=authorized[doc]['reason']+' · Ο χειριστής επέλεξε προσπάθεια καταχώρισης και έλεγχο στο EBS'
                row['excel_issues']=authorized[doc]['excel_issues']
        return results
