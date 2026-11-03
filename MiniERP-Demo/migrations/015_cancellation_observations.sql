-- An observed cancellation exists independently of a subsequently received invoice.
CREATE TABLE mydata_cancellations(
 company_id INTEGER NOT NULL REFERENCES companies(id),
 environment TEXT NOT NULL CHECK(environment IN ('test','production')),
 mark TEXT NOT NULL,
 first_sync INTEGER NOT NULL REFERENCES mydata_syncs(id),
 last_sync INTEGER NOT NULL REFERENCES mydata_syncs(id),
 PRIMARY KEY(company_id,environment,mark)
);
INSERT INTO mydata_cancellations(company_id,environment,mark,first_sync,last_sync)
 SELECT company_id,environment,mark,min(sync),max(sync) FROM (
  SELECT company_id,environment,mark,last_sync AS sync FROM mydata_records WHERE match_status='cancelled_at_aade'
  UNION ALL
  SELECT a.company_id,json_extract(a.payload,'$.environment'),CAST(json_extract(a.payload,'$.mark') AS TEXT),s.id
  FROM audit_events a JOIN mydata_syncs s ON s.id=json_extract(a.payload,'$.sync') AND s.company_id=a.company_id
  WHERE a.action='mydata_cancellation_observed' AND json_valid(a.payload)
   AND json_extract(a.payload,'$.environment')=s.environment
   AND json_extract(a.payload,'$.mark') IS NOT NULL
 ) GROUP BY company_id,environment,mark;
