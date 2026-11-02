"""Operator-invoked history import; never guesses VAT identities or posts to EBS."""
from collections import Counter,defaultdict
from difflib import get_close_matches
import hashlib,json,unicodedata
from app.infrastructure.importers.excel import read_workbook
from app.domain.preparation import preparation_values
from app.application.counterparties import Counterparties
from app.application.supplier_accounts import SupplierAccounts


def name_key(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(value)).upper() if c.isalnum() and not unicodedata.combining(c))


class HistoryAccounts:
    def __init__(self,erp):self.erp=erp;self.db=erp.db

    def cards(self,company):
        return [dict(r) for r in self.db.execute("SELECT c.*,a.expenses_account,a.purchases_account,a.preferred_group,a.version FROM counterparties c LEFT JOIN counterparty_accounts a ON a.counterparty_id=c.id AND a.company_id=c.company_id WHERE c.company_id=? AND c.environment='production' ORDER BY c.name,c.id",(company,))]

    def excluded_vats(self,company):
        from app.application.ebs_reconciliation import EBSReconciliation
        return EBSReconciliation(self.erp).excluded_vats(company)

    def applied(self,company,digest):
        return {v['card_id'] for r in self.db.execute("SELECT payload FROM audit_events WHERE company_id=? AND action='history_account_imported'",(company,)) if (v:=json.loads(r[0])).get('source_sha256')==digest}

    def preview(self,company,path,*,data=None):
        if not self.db.execute('SELECT 1 FROM companies WHERE id=?',(company,)).fetchone():raise ValueError('Δεν βρέθηκε εταιρεία')
        book=read_workbook(path,data=data);source=[];found=False
        for sheet in book['sheets']:
            for number,raw in sheet['rows'][:20]:
                header={name_key(v):k for k,v in raw.items()}
                if not {'ΣΥΝΝΟΣ','ΔΑΠΑΝΗ','ΠΑΡΚΟ'}<=set(header):continue
                if found:raise ValueError('Βρέθηκαν πολλά ιστορικά φύλλα· κράτησε ένα φύλλο ανά εισαγωγή')
                found=True
                for n,row in sheet['rows']:
                    if n<=number:continue
                    name=row.get(header['ΣΥΝΝΟΣ'],'').strip();account=row.get(header['ΔΑΠΑΝΗ'],'').strip();ref=row.get(header['ΠΑΡΚΟ'],'').strip()
                    if not name and not account:continue
                    if not name or not ref:raise ValueError(f'Γραμμή {n}: χρειάζεται επωνυμία και παραστατικό EBS')
                    preparation_values(account[:1],account,'','local_operator',True)
                    source.append((name,account,ref))
                break
        if not found or not source:raise ValueError('Χρειάζονται στήλες Συν/νος, Παρ/κό, Δαπάνη και γραμμές ιστορικού')
        cards=self.cards(company);index=defaultdict(list)
        for card in cards:index[name_key(card['name'])].append(card)
        groups=defaultdict(list);seen=set()
        for name,account,ref in source:
            key=name_key(name);identity=(key,ref,account)
            if identity in seen:continue
            seen.add(identity);groups[key].append((name,account))
        digest=hashlib.sha256(book['data']).hexdigest();done=self.applied(company,digest)
        from app.application.ebs_reconciliation import EBSReconciliation
        excluded=EBSReconciliation(self.erp).excluded_vats(company);rows=[]
        for key,entries in groups.items():
            counts=Counter(account for _,account in entries);best=max(counts.values());winners=sorted(a for a,n in counts.items() if n==best)
            exact=index.get(key,[]);card=exact[0] if len(exact)==1 else None
            candidates=exact or [c for candidate in get_close_matches(key,list(index),n=4,cutoff=.55) for c in index[candidate]]
            rows.append(dict(key=key,source_name=entries[0][0],counts=dict(counts),winners=winners,account=winners[0] if len(winners)==1 else None,frequency=best,total=len(entries),card_id=card['id'] if card else None,candidates=candidates,excluded=bool(card and card['vat'] in excluded) or all(a.startswith('2') for a in winners),applied=bool(card and card['id'] in done)))
        return dict(company=company,filename=book['filename'],data=book['data'],sha256=digest,rows=rows,cards=cards)

    def apply(self,packet,choices,*,confirmed=False):
        if confirmed is not True or not choices:raise ValueError('Επίλεξε αντιστοιχίσεις και επιβεβαίωσε την ενημέρωση')
        if hashlib.sha256(packet['data']).hexdigest()!=packet['sha256']:raise ValueError('Άλλαξε το αρχείο ιστορικού')
        report=dict(updated=0,documents=0,protected=[],needs_review=[],queues=0,already_applied=0)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            fresh=self.preview(packet['company'],packet['filename'],data=packet['data'])
            rows={r['key']:r for r in fresh['rows']};cards={c['id']:c for c in fresh['cards']};prior={c['id']:c for c in packet['cards']}
            from app.application.ebs_reconciliation import EBSReconciliation
            excluded=EBSReconciliation(self.erp).excluded_vats(packet['company']);done=self.applied(packet['company'],packet['sha256']);seen=set()
            service=SupplierAccounts(self.erp)
            evidence=EBSReconciliation(self.erp).results(packet['company'])
            attempted={r[0] for r in self.db.execute("SELECT DISTINCT i.document_id FROM rpa_items i JOIN rpa_jobs j ON j.id=i.job_id WHERE j.company_id=? AND j.mode='fill_only' AND i.status NOT IN ('queued','excluded_purchase','not_saved_confirmed')",(packet['company'],))}
            for choice in choices:
                key=choice['key'];cp=choice['card_id'];account=choice['account'];row=rows.get(key);card=cards.get(cp)
                if not row or not card or account not in row['winners']:raise ValueError('Έλεγξε την αντιστοίχιση και τον συχνότερο λογαριασμό')
                if not account.startswith('6'):raise ValueError('Οι λογαριασμοί ομάδας 2 εξαιρούνται από την εισαγωγή εξόδων')
                if cp in seen:raise ValueError('Η ίδια καρτέλα επιλέχθηκε περισσότερες από μία φορές')
                seen.add(cp)
                if card['vat'] in excluded:raise ValueError('Η ομάδα 2 εξαιρείται από την εισαγωγή εξόδων')
                if cp in done:report['already_applied']+=1;continue
                if card!=prior.get(cp):raise ValueError('Η καρτέλα άλλαξε μετά την προεπισκόπηση· άνοιξε ξανά το αρχείο')
                service.save(packet['company'],[cp],'6',account,confirmed=True,apply_pending=False,classify_supplier=False)
                values=Counterparties(self.erp).detail(packet['company'],cp)[0]['accounts']
                documents={r[0] for r in self.db.execute('SELECT id FROM documents WHERE company_id=? AND counterparty_id=?',(packet['company'],cp))}
                report['protected'].extend(sorted(documents & attempted))
                result=service.apply_pending(packet['company'],cp,values,{'6'},evidence=evidence,documents=documents-attempted)
                report['documents']+=result['updated'];report['protected'].extend(result['protected']);report['needs_review'].extend(result['needs_review']);report['queues']+=result['queues']
                self.erp.repository.audit(packet['company'],'history_account_imported',None,dict(source_sha256=packet['sha256'],card_id=cp,source_name=row['source_name'],account=account,frequency=row['counts'][account],total=row['total']))
                report['updated']+=1
        return report
