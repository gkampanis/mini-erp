"""Seed historical schemas with SQL, without invoking the current importer."""
import json


def seed_packet(erp,company,packet):
    with erp.db:
        job=erp.db.execute("INSERT INTO import_jobs(company_id,filename,sha256,status,report) VALUES (?,?,?,'completed','{}')",(company,packet.filename,packet.sha256)).lastrowid
        columns={r[1] for r in erp.db.execute('PRAGMA table_info(documents)')}
        for entry in packet.records:
            d=entry['document']
            source=erp.db.execute('INSERT INTO source_records(job_id,row_number,raw_json) VALUES (?,?,?)',(job,entry['row'],json.dumps(entry['raw'],ensure_ascii=False))).lastrowid
            erp.db.execute('INSERT OR IGNORE INTO counterparties(company_id,vat,name) VALUES (?,?,?)',(company,d['vat'],d['name']))
            cp=erp.db.execute('SELECT id FROM counterparties WHERE company_id=? AND vat=?',(company,d['vat'])).fetchone()[0]
            values=dict(company_id=company,counterparty_id=cp,source_record_id=source,**{k:v for k,v in d.items() if k in columns})
            erp.db.execute('INSERT INTO documents('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',tuple(values.values()))
        erp.repository.audit(company,'historical_fixture_seeded',None,dict(synthetic=True,job=job))
