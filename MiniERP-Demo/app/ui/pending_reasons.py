"""Read-only current reasons; old plan diagnostics never override newer edits."""
import json
from datetime import datetime
from decimal import Decimal


def same_attempt_source(row,payload):
    """A diagnostic belongs only to the financial/account snapshot attempted."""
    try:
        expected=dict(vat=row['vat'],name=row['name'],invoice='/'.join(str(row[k]) for k in ('series','number') if row[k]),
                      date=datetime.strptime(row['issue_date'],'%Y-%m-%d').strftime('%d/%m/%Y'),
                      net=f"{Decimal(row['net_minor'])/100:.2f}".replace('.',','),
                      account=row.get('account_code') if row.get('prepared_at') else row.get('suggested_account'),
                      group=row.get('nature_group') if row.get('prepared_at') else row.get('suggested_group'))
        if payload.get('approval_at') and payload['approval_at']==row.get('prepared_at'):
            # A saved VAT rule may select a secondary account even for one row.
            # Approval identity plus newer rule-edit invalidation binds that case.
            expected.pop('account')
        return all(payload.get(k)==v for k,v in expected.items())
    except (KeyError,TypeError,ValueError):return False


def expose_pending_column(preferences):
    """Upgrade existing saved layouts once, then respect later column choices."""
    layout=preferences.layout('documents')
    if layout.get('pending_reason_added'):return
    visible=layout.get('visible')
    if isinstance(visible,list) and 'pending_reason' not in visible:
        index=visible.index('preparation_state')+1 if 'preparation_state' in visible else len(visible)
        visible.insert(index,'pending_reason')
    layout['pending_reason_added']=True
    preferences.set_layout('documents',layout)


def pending_reasons(erp,company,rows,evidence):
    models={r['id']:r for r in rows};planned={};attempt_current={};invalid_docs=set();invalid_cards=set();invalid_all=False
    actions=('rpa_selection_planned','document_prepared','supplier_account_applied','account_rule_approved',
             'creditor_vat_rules_approved','ebs_profile_saved','mydata_read_completed','purchase_classification_changed',
             'rpa_started','rpa_creditor_resolution_required')
    sql="SELECT action,entity_id,payload FROM audit_events WHERE company_id=? AND id>coalesce((SELECT max(id) FROM audit_events WHERE company_id=? AND action='company_identified'),0) AND action IN ("+','.join('?' for _ in actions)+') ORDER BY id DESC'
    for event in erp.db.execute(sql,(company,company,*actions)):
        payload=json.loads(event['payload']);action=event['action']
        if action in ('rpa_started','rpa_creditor_resolution_required'):
            doc=event['entity_id'];item=payload.get('item')
            if doc in models and item not in attempt_current:
                attempt_current[item]=not (invalid_all or doc in invalid_docs or models[doc].get('counterparty_id') in invalid_cards)
        elif action=='rpa_selection_planned':
            skipped={r['document']:r['reason'] for r in payload.get('skipped',[])}
            for doc in set(payload.get('documents',[]))|set(skipped):
                if doc not in models or doc in planned:continue
                stale=invalid_all or doc in invalid_docs or models[doc].get('counterparty_id') in invalid_cards
                planned[doc]=None if stale else skipped.get(doc,'')
        elif action in ('ebs_profile_saved','mydata_read_completed'):invalid_all=True
        elif event['entity_id'] is not None:invalid_docs.add(event['entity_id'])
        elif payload.get('counterparty_id') is not None:invalid_cards.add(payload['counterparty_id'])
    attempts={}
    for item in erp.db.execute("SELECT i.*,j.status AS job_status FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND j.mode='fill_only' ORDER BY i.id DESC",(company,)):
        doc=item['document_id']
        if doc not in models or doc in attempts:continue
        # A newer resolved/no-save/new-queue item supersedes every older error.
        attempts[doc]=None
        unsuccessful=item['status'] in ('uncertain','failed','filled_no_save')
        paused_creditor=item['status']=='queued' and item['job_status']=='paused'
        if item['reason'] and (unsuccessful or paused_creditor) and attempt_current.get(item['id']) and same_attempt_source(models[doc],json.loads(item['payload'])):
            attempts[doc]=item['reason']
    result={}
    for doc,row in models.items():
        current=evidence.get(doc,{})
        if attempts.get(doc) and (current.get('match_kind')=='attempt' or current.get('status')=='not_registered'):
            reason=attempts[doc]
        elif current.get('status')!='not_registered':
            reason=current.get('reason') or 'Χρειάζεται συμφωνία EBS'
        elif not row.get('prepared_at') and not row.get('suggested_account'):
            reason='Χρειάζεται εγκεκριμένο λογαριασμό εξόδων'
        else:
            prior=planned.get(doc)
            reason=prior or ('Έτοιμο για καταχώριση' if prior=='' else 'Εκκρεμεί έλεγχος καταχώρισης')
            if prior and 'ανάλυσης γραμμών ΑΑΔΕ' in prior:
                from app.application.vat_lines import VATLines
                service=VATLines(erp);analysis=service.analysis(company,doc)
                if analysis and analysis['status']=='verified':
                    requirements=service.requirements(company,[doc])
                    reason='Χρειάζεται αντιστοίχιση λογαριασμών ΦΠΑ στην καρτέλα πιστωτή' if requirements else 'Εκκρεμεί νέος έλεγχος καταχώρισης'
                elif analysis:
                    codes=', '.join(analysis.get('errors',[]))
                    reason=prior+(' · '+codes if codes else ' · '+analysis['status'])
        result[doc]=reason
    return result
