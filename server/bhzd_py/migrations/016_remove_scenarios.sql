-- Remove the business scenario dimension while preserving all other schema
-- contracts.  This is a forward migration because db.py rejects edits to an
-- already-applied migration whose recorded SHA-256 no longer matches.

-- These tables have no indexes, triggers, or foreign keys that depend on the
-- removed columns, so SQLite can drop them in place without rebuilding rows.
ALTER TABLE conversations DROP COLUMN scenario_id;
ALTER TABLE agent_runs DROP COLUMN scenario_id;
ALTER TABLE learning_tasks DROP COLUMN scenario_id;
ALTER TABLE diagnostic_summaries DROP COLUMN scenario_id;
ALTER TABLE rag_documents DROP COLUMN scenario_ids_json;

-- mastery used scenario_id as part of its primary key.  Select one
-- deterministic record per user/capability: retain the strongest score, then
-- the newest update (and rowid only breaks an otherwise identical tie).
CREATE TABLE mastery_new (
  user_id TEXT NOT NULL REFERENCES users(id),
  cap_id TEXT NOT NULL,
  score REAL NOT NULL CHECK (score BETWEEN 0 AND 1),
  source TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, cap_id)
);

INSERT INTO mastery_new (user_id, cap_id, score, source, updated_at)
SELECT user_id, cap_id, score, source, updated_at
FROM (
  SELECT
    user_id,
    cap_id,
    score,
    source,
    updated_at,
    ROW_NUMBER() OVER (
      PARTITION BY user_id, cap_id
      ORDER BY score DESC, updated_at DESC, rowid ASC
    ) AS record_rank
  FROM mastery
)
WHERE record_rank = 1;

DROP TABLE mastery;
ALTER TABLE mastery_new RENAME TO mastery;

-- mastery_events remains an audit history, but the event no longer needs a
-- scenario dimension after mastery is unified.
ALTER TABLE mastery_events DROP COLUMN scenario_id;
