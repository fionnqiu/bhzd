-- Controlled Agent learning writes.  The additive columns preserve existing
-- task history while making automated progress auditable and retryable.
ALTER TABLE learning_tasks ADD COLUMN progress REAL NOT NULL DEFAULT 0
  CHECK (progress >= 0 AND progress <= 1);
ALTER TABLE learning_tasks ADD COLUMN automation_actor TEXT;
ALTER TABLE learning_tasks ADD COLUMN automation_run_id TEXT;

CREATE TABLE IF NOT EXISTS agent_learning_capability_settings (
  capability TEXT PRIMARY KEY,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  per_user_limit INTEGER NOT NULL DEFAULT 30 CHECK (per_user_limit > 0),
  window_seconds INTEGER NOT NULL DEFAULT 3600 CHECK (window_seconds > 0),
  updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO agent_learning_capability_settings
  (capability, enabled, per_user_limit, window_seconds, updated_at)
VALUES ('learning', 1, 30, 3600, datetime('now'));

CREATE TABLE IF NOT EXISTS agent_learning_actions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  capability TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
  status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
  result_json TEXT,
  created_at TEXT NOT NULL,
  completed_at TEXT,
  UNIQUE (user_id, capability, idempotency_key)
);

CREATE TABLE IF NOT EXISTS task_exercise_reviews (
  id TEXT PRIMARY KEY,
  submission_id TEXT NOT NULL REFERENCES task_exercise_submissions(id) ON DELETE CASCADE,
  task_id TEXT NOT NULL REFERENCES learning_tasks(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
  feedback TEXT NOT NULL,
  provider_role TEXT NOT NULL DEFAULT 'grader',
  provider_id TEXT,
  run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
  idempotency_key TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (user_id, submission_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_agent_learning_actions_window
  ON agent_learning_actions (user_id, capability, created_at);
CREATE INDEX IF NOT EXISTS idx_task_exercise_reviews_submission
  ON task_exercise_reviews (submission_id, created_at DESC);
