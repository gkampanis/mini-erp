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
        report = dict(inserted=0, duplicates=0, rejected=list(checked.rejected))
        with self.db:
            job = self.db.execute('INSERT INTO import_jobs(company_id,filename,sha256,status,report) VALUES (?,?,?,?,?)',
                                  (company,item.filename,item.sha256,'completed','{}')).lastrowid
            for count, row in enumerate(checked.records):
                d = row['document']
                source = self.db.execute('INSERT INTO source_records(job_id,row_number,raw_json) VALUES (?,?,?)',
                                         (job,row['row'],encode(row['raw']))).lastrowid
                self.db.execute('INSERT INTO counterparties(company_id,vat,name) VALUES (?,?,?) ON CONFLICT(company_id,vat) DO NOTHING',
                                (company,d['vat'],d['name']))
                cp = self.db.execute('SELECT id FROM counterparties WHERE company_id=? AND vat=?', (company,d['vat'])).fetchone()[0]
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
                    columns = ','.join(values)
                    document = self.db.execute(f'INSERT INTO documents({columns}) VALUES ({",".join("?" for _ in values)})', tuple(values.values())).lastrowid
                    self.audit(company,'document_imported',document,dict(job=job,row=row['row']))
                    report['inserted'] += 1
                if fail_after is not None and count >= fail_after:
                    raise RuntimeError('Injected transaction interruption')
            # Rejected original rows are retained too, not just normalized records.
            for rejected in checked.rejected:
                self.db.execute('INSERT INTO source_records(job_id,row_number,raw_json) VALUES (?,?,?)',
                                (job,rejected['row'],encode(rejected['raw'])))
            self.db.execute('UPDATE import_jobs SET report=? WHERE id=?',(encode(report),job))
            self.audit(company,'import_completed',None,dict(job=job,inserted=report['inserted'],duplicates=report['duplicates'],rejected=len(report['rejected'])))
        return report

    def search(self, company, query=''):
        # Python casefold handles accented Greek consistently, unlike SQLite lower().
        rows = self.db.execute('SELECT d.*,c.vat,c.name FROM documents d JOIN counterparties c ON c.id=d.counterparty_id WHERE d.company_id=? ORDER BY d.issue_date DESC,d.id DESC',(company,)).fetchall()
        return [dict(r) for r in rows if not query or any(query.casefold() in str(r[k] or '').casefold() for k in ('vat','name','number','series','mark','issue_date'))]

    def detail(self, company, document):
        row = self.db.execute('SELECT d.*,c.vat,c.name,s.raw_json,j.filename,j.sha256 FROM documents d JOIN counterparties c ON c.id=d.counterparty_id JOIN source_records s ON s.id=d.source_record_id JOIN import_jobs j ON j.id=s.job_id WHERE d.company_id=? AND d.id=?',(company,document)).fetchone()
        if row is None:
            raise ValueError('Δεν βρέθηκε παραστατικό')
        events = self.db.execute('SELECT action,actor,payload,created_at FROM audit_events WHERE company_id=? AND entity_id=? ORDER BY id',(company,document)).fetchall()
        return dict(row),[dict(x) for x in events]
