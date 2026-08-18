-- Durable batch metadata for slice-setting changes.  Old chunks stay queryable
-- until a document atomically advances active_process_version.
CREATE TABLE IF NOT EXISTS rag_reprocess_batches (
  id TEXT PRIMARY KEY,
  settings_version INTEGER NOT NULL,
  affected_count INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued','running','completed','completed_with_failures')),
  created_at TEXT NOT NULL,
  finished_at TEXT,
  failed_count INTEGER NOT NULL DEFAULT 0
);

ALTER TABLE rag_documents ADD COLUMN active_process_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE rag_jobs ADD COLUMN batch_id TEXT REFERENCES rag_reprocess_batches(id);
CREATE INDEX IF NOT EXISTS idx_rag_jobs_batch ON rag_jobs(batch_id, status);
