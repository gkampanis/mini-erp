-- Append metadata without rewriting immutable historical evidence.
ALTER TABLE ebs_reconciliation_runs ADD COLUMN match_policy INTEGER NOT NULL DEFAULT 1;
ALTER TABLE ebs_matches ADD COLUMN match_kind TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE ebs_matches ADD COLUMN match_signature TEXT NOT NULL DEFAULT '';
