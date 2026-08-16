-- Persist named retrieval test sets. Retrieval nucleus overrides live in
-- per-case filter snapshots, keeping them separate from global LLM top_p.
CREATE TABLE eval_sets (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  description TEXT,
  created_by TEXT NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

ALTER TABLE eval_cases ADD COLUMN eval_set_id TEXT REFERENCES eval_sets(id) ON DELETE SET NULL;
ALTER TABLE eval_runs ADD COLUMN eval_set_id TEXT REFERENCES eval_sets(id) ON DELETE SET NULL;

CREATE INDEX idx_eval_cases_eval_set ON eval_cases (eval_set_id, created_at);
