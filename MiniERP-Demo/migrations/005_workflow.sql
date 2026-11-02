ALTER TABLE rpa_jobs ADD COLUMN execution TEXT NOT NULL DEFAULT 'fill_only' CHECK(execution IN ('fill_only','save_new'));
ALTER TABLE rpa_jobs ADD COLUMN profile_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE rpa_jobs ADD COLUMN need_new INTEGER NOT NULL DEFAULT 0 CHECK(need_new IN (0,1));
ALTER TABLE rpa_jobs ADD COLUMN expected_ted INTEGER;
CREATE TABLE ebs_profiles(company_id INTEGER PRIMARY KEY REFERENCES companies(id),profile_json TEXT NOT NULL,signature TEXT NOT NULL,pilot_note TEXT NOT NULL DEFAULT '',pilot_at TEXT,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
