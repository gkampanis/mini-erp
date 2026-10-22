"""Recover missing names from archived original workbooks, never a fixed column number."""
import hashlib
import json
from pathlib import Path
from zipfile import BadZipFile
from app.infrastructure.importers.excel import preview


class NameRecovery:
    def __init__(self,erp):self.erp=erp;self.db=erp.db
    def needed(self,company):
        return bool(self.db.execute("SELECT 1 FROM counterparties WHERE company_id=? AND (name=vat OR name='Χωρίς επωνυμία') LIMIT 1",(company,)).fetchone())
    def run(self,company):
        pending={r['id']:dict(r) for r in self.db.execute("SELECT * FROM counterparties WHERE company_id=? AND (name=vat OR name='Χωρίς επωνυμία')",(company,))}
        if not pending:return dict(updated=0,conflicts=0,unavailable=0)
        candidates={};cache={};unavailable=set()
        rows=self.db.execute('SELECT d.counterparty_id,s.raw_json,s.row_number,j.id AS job,j.sha256 FROM documents d JOIN source_records s ON s.id=d.source_record_id JOIN import_jobs j ON j.id=s.job_id WHERE d.company_id=?',(company,)).fetchall()
        for row in rows:
            if json.loads(row['raw_json']).get('_source'):continue
            cp=pending.get(row['counterparty_id'])
            if cp is None:continue
            if row['job'] not in cache:
                archived=self.erp.directory/'sources'/(row['sha256']+'.xlsx')
                try:
                    if not archived.is_file() or hashlib.sha256(archived.read_bytes()).hexdigest()!=row['sha256']:raise ValueError()
                    item=preview(archived);cache[row['job']]=item.mapping
                except (ValueError,OSError,KeyError,BadZipFile):cache[row['job']]={};unavailable.add(row['job'])
            mapping=cache[row['job']]
            if 'name' not in mapping or 'vat' not in mapping:continue
            raw=json.loads(row['raw_json']);vat=raw.get(str(mapping['vat']),'').strip();name=raw.get(str(mapping['name']),'').strip()
            if vat==cp['vat'] and name and name not in (vat,'Χωρίς επωνυμία') and len(name)<=256:candidates.setdefault(cp['id'],set()).add(name)
        result=dict(updated=0,conflicts=sum(len(v)>1 for v in candidates.values()),unavailable=len(unavailable))
        with self.db:
            for cp,names in candidates.items():
                if len(names)!=1:continue
                name=next(iter(names));before=pending[cp]
                changed=self.db.execute("UPDATE counterparties SET name=? WHERE id=? AND company_id=? AND (name=vat OR name='Χωρίς επωνυμία')",(name,cp,company))
                if changed.rowcount:
                    self.erp.repository.audit(company,'counterparty_name_recovered',None,dict(counterparty_id=cp,before=before['name'],after=name,source='archived_excel_header_mapping'))
                    result['updated']+=1
        return result
