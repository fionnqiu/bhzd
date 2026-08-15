-- P0-7: persist generated learning content separately from the legacy task card.
-- Separate rows keep reference answers private and make generation/grade status
-- durable across browser refreshes and worker restarts.
CREATE TABLE IF NOT EXISTS task_knowledge_points (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES learning_tasks(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS task_exercises (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES learning_tasks(id) ON DELETE CASCADE,
  question TEXT NOT NULL,
  type TEXT NOT NULL DEFAULT 'open_ended',
  options_json TEXT,
  reference_answer TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS task_exercise_submissions (
  id TEXT PRIMARY KEY,
  exercise_id TEXT NOT NULL REFERENCES task_exercises(id) ON DELETE CASCADE,
  student_id TEXT NOT NULL REFERENCES users(id),
  answer TEXT NOT NULL,
  grade_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (grade_status IN ('pending', 'grading', 'done', 'failed')),
  score INTEGER CHECK (score IS NULL OR (score BETWEEN 0 AND 100)),
  feedback TEXT,
  graded_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

ALTER TABLE learning_tasks ADD COLUMN content_status TEXT NOT NULL DEFAULT 'none';
ALTER TABLE learning_tasks ADD COLUMN content_generated_at TEXT;

CREATE INDEX IF NOT EXISTS idx_task_knowledge_task_order
  ON task_knowledge_points (task_id, sort_order, id);
CREATE INDEX IF NOT EXISTS idx_task_exercises_task_order
  ON task_exercises (task_id, sort_order, id);
CREATE INDEX IF NOT EXISTS idx_task_submissions_exercise_student
  ON task_exercise_submissions (exercise_id, student_id, created_at DESC);
