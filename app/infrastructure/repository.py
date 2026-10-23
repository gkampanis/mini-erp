from pathlib import Path
import json
from app.infrastructure.database import connect


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Repository:
    def __init__(self, directory):
        self.db = connect(directory)

    def close(self):
        self.db.close()

    def company(self, vat, name):
        if len(vat) != 9 or not vat.isascii() or not vat.isdigit() or not name.strip():
            raise ValueError('Απαιτούνται 9ψήφιο ΑΦΜ και επωνυμία εταιρείας')
        with self.db:
            self.db.execute('INSERT INTO companies(vat,name) VALUES (?,?) ON CONFLICT(vat) DO NOTHING', (vat,name))
        return self.db.execute('SELECT id FROM companies WHERE vat=?', (vat,)).fetchone()[0]

    def audit(self, company, action, entity, payload, actor='local_operator'):
        self.db.execute('INSERT INTO audit_events(company_id,actor,action,entity_id,payload) VALUES (?,?,?,?,?)',
                        (company,actor,action,entity,encode(payload)))

    def persist_import(self, company, item, checked, fail_after=None):
        report = dict(inserted=0, duplicates=0, rejected=list(checked.rejected), warnings=[])
        with self.db:
            job = self.db.execute('INSERT INTO import_jobs(company_id,filename,sha256,status,report) VALUES (?,?,?,?,?)',
                                  (company,item.filename,item.sha256,'completed','{}')).lastrowid
            # Build a casefolded reference index once, avoiding a database scan per imported row.
            reference_history = {}
            for prior in self.db.execute('SELECT id,counterparty_id,direction,kind,series,number,issue_date FROM documents WHERE company_id=?', (company,)):
                key = (prior['counterparty_id'], prior['direction'], prior['kind'], prior['issue_date'][:4], prior['series'].casefold(), prior['number'].casefold())
                reference_history.setdefault(key, []).append((prior['id'], prior['issue_date']))
            for count, row in enumerate(checked.records):
                d = row['document']
                source = self.db.execute('INSERT INTO source_records(job_id,row_number,raw_json) VALUES (?,?,?)',
                                         (job,row['row'],encode(row['raw']))).lastrowid
                self.db.execute('INSERT INTO counterparties(company_id,vat,name) VALUES (?,?,?) ON CONFLICT(company_id,vat) DO NOTHING',
                                (company,d['vat'],d['name']))
                counterparty = self.db.execute('SELECT * FROM counterparties WHERE company_id=? AND vat=?', (company,d['vat'])).fetchone()
                cp = counterparty['id']
                if counterparty['name'] in (d['vat'],'Χωρίς επωνυμία') and d['name'] not in (d['vat'],'Χωρίς επωνυμία'):
                    self.db.execute('UPDATE counterparties SET name=? WHERE id=?',(d['name'],cp))
                    self.audit(company,'counterparty_named',None,dict(counterparty_id=cp,before=counterparty['name'],after=d['name']))
                identity = (company,cp,d['direction'],d['kind'],d['series'],d['number'],d['issue_date'])
                existing = self.db.execute('SELECT * FROM documents WHERE (company_id=? AND counterparty_id=? AND direction=? AND kind=? AND series=? AND number=? AND issue_date=?) OR (company_id=? AND mark=? AND mark IS NOT NULL)',
                                           (*identity,company,d['mark'])).fetchall()
                values = dict(company_id=company,counterparty_id=cp,source_record_id=source,
                              **{k:v for k,v in d.items() if k not in ('vat','name')})
                if existing:
                    same = len(existing)==1 and all(existing[0][k]==v for k,v in values.items() if k!='source_record_id')
                    if same:
                        report['duplicates'] += 1
                    else:
                        report['rejected'].append(dict(row=row['row'],reason='Σύγκρουση ταυτότητας/MARK ή ποσών: απαιτείται έλεγχος', raw=row['raw']))
                    self.audit(company,'import_duplicate' if same else 'import_conflict', existing[0]['id'],dict(job=job,row=row['row']))
                else:
                    # Same-year reference reuse is a review signal, not proof of a duplicate.
                    reference_key = (cp, d['direction'], d['kind'], d['issue_date'][:4], d['series'].casefold(), d['number'].casefold())
                    related = [reference for reference, issued in reference_history.get(reference_key, []) if issued != d['issue_date']]
                    columns = ','.join(values)
                    document = self.db.execute(f'INSERT INTO documents({columns}) VALUES ({",".join("?" for _ in values)})', tuple(values.values())).lastrowid
                    reference_history.setdefault(reference_key, []).append((document, d['issue_date']))
                    self.audit(company,'document_imported',document,dict(job=job,row=row['row']))
                    if related:
                        warning = dict(row=row['row'], reason='Πιθανό διπλότυπο: ίδιος αριθμός με διαφορετική ημερομηνία — έλεγχος', related_document_ids=related)
                        report['warnings'].append(warning)
                        self.audit(company,'import_warning',document,dict(job=job,**warning))
                    report['inserted'] += 1
                changes = row.get('rounding_changes',[])
                if changes or d.get('rounding_minor'):
                    warning = dict(row=row['row'],reason='Στρογγυλοποίηση σε 2 δεκαδικά (ROUND_HALF_UP)',changes=changes,rounding_minor=d.get('rounding_minor',0))
                    report['warnings'].append(warning)
                    self.audit(company,'amounts_rounded',existing[0]['id'] if len(existing)==1 else (document if not existing else None),dict(job=job,**warning))
                if fail_after is not None and count >= fail_after:
                    raise RuntimeError('Injected transaction interruption')
            # Rejected original rows are retained too, not just normalized records.
            for rejected in checked.rejected:
                self.db.execute('INSERT INTO source_records(job_id,row_number,raw_json) VALUES (?,?,?)',
                                (job,rejected['row'],encode(rejected['raw'])))
            self.db.execute('UPDATE import_jobs SET report=? WHERE id=?',(encode(report),job))
            self.audit(company,'import_completed',None,dict(job=job,inserted=report['inserted'],duplicates=report['duplicates'],rejected=len(report['rejected']),headers=getattr(item,'headers',{}),mapping=getattr(item,'mapping',{}),source_kind=getattr(item,'source_kind','excel')))
        return report

    def search(self, company, query='', *, counterparty=None, month=None):
        # Python casefold handles accented Greek consistently, unlike SQLite lower().
        where='d.company_id=?';args=[company]
        if counterparty is not None:where+=' AND d.counterparty_id=?';args.append(counterparty)
        if month is not None:
            from datetime import date
            first=date.fromisoformat(month+'-01');following=date(first.year+first.month//12,first.month%12+1,1)
            where+=' AND d.issue_date>=? AND d.issue_date<?';args.extend((first.isoformat(),following.isoformat()))
        rows = self.db.execute('SELECT d.*,c.vat,c.name,p.nature_group,p.account_code,p.approved_at AS prepared_at FROM documents d JOIN counterparties c ON c.id=d.counterparty_id LEFT JOIN document_preparations p ON p.document_id=d.id AND p.company_id=d.company_id WHERE '+where+' ORDER BY d.issue_date DESC,d.id DESC',args).fetchall()
        return [dict(r) for r in rows if not query or any(query.casefold() in str(r[k] or '').casefold() for k in ('vat','name','number','series','mark','issue_date'))]

    def detail(self, company, document):
        row = self.db.execute('SELECT d.*,c.vat,c.name,s.raw_json,j.filename,j.sha256 FROM documents d JOIN counterparties c ON c.id=d.counterparty_id JOIN source_records s ON s.id=d.source_record_id JOIN import_jobs j ON j.id=s.job_id WHERE d.company_id=? AND d.id=?',(company,document)).fetchone()
        if row is None:
            raise ValueError('Δεν βρέθηκε παραστατικό')
        events = self.db.execute('SELECT action,actor,payload,created_at FROM audit_events WHERE company_id=? AND entity_id=? ORDER BY id',(company,document)).fetchall()
        return dict(row),[dict(x) for x in events]

    def preparation(self, company, document):
        if self.db.execute('SELECT 1 FROM documents WHERE company_id=? AND id=?', (company, document)).fetchone() is None:
            raise ValueError('Δεν βρέθηκε παραστατικό')
        row = self.db.execute('SELECT * FROM document_preparations WHERE company_id=? AND document_id=?', (company, document)).fetchone()
        return dict(row) if row is not None else None

    def prepare_document(self, company, document, values):
        with self.db:
            before = self.preparation(company, document)
            self.db.execute(
                "INSERT INTO document_preparations(document_id,company_id,nature_group,account_code,note,approved_by,approved_at) VALUES (?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now')) "
                "ON CONFLICT(document_id) DO UPDATE SET nature_group=excluded.nature_group,account_code=excluded.account_code,note=excluded.note,approved_by=excluded.approved_by,approved_at=excluded.approved_at",
                (document, company, values['nature_group'], values['account_code'], values['note'], values['approved_by']))
            after = self.preparation(company, document)
            self.audit(company, 'document_prepared', document, dict(before=before, after=after), actor=values['approved_by'])
        return after

    def import_reviews(self, company):
        rows = self.db.execute('SELECT * FROM import_jobs WHERE company_id=? ORDER BY created_at DESC,id DESC', (company,)).fetchall()
        reviews = []
        for row in rows:
            review = dict(row)
            report = json.loads(review['report'])
            report.setdefault('warnings', [])
            review.update(report=report, inserted_count=report['inserted'], duplicate_count=report['duplicates'],
                          rejected_count=len(report['rejected']), warning_count=len(report['warnings']))
            reviews.append(review)
        return reviews

    def rename_counterparty(self, company, counterparty, name):
        if not isinstance(name,str) or not name.strip() or len(name.strip())>250:
            raise ValueError('Δώσε επωνυμία έως 250 χαρακτήρες')
        with self.db:
            row=self.db.execute('SELECT * FROM counterparties WHERE id=? AND company_id=?',(counterparty,company)).fetchone()
            if row is None:raise ValueError('Δεν βρέθηκε αντισυμβαλλόμενος')
            self.db.execute('UPDATE counterparties SET name=? WHERE id=?',(name.strip(),counterparty))
            self.audit(company,'counterparty_renamed',None,dict(counterparty_id=counterparty,vat=row['vat'],before=row['name'],after=name.strip()))
