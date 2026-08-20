-- DF-01: retain every automated grading attempt and its safe recovery state.
-- Additive fields preserve historical submissions while letting the student
-- retry a failed provider call without overwriting the original answer.
ALTER TABLE task_exercise_submissions ADD COLUMN grade_failure_reason TEXT;
ALTER TABLE task_exercise_submissions ADD COLUMN grade_retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE task_exercise_submissions ADD COLUMN grade_retry_limit INTEGER NOT NULL DEFAULT 2;
ALTER TABLE task_exercise_submissions ADD COLUMN retry_of_submission_id TEXT;
ALTER TABLE task_exercise_submissions ADD COLUMN manual_review_required INTEGER NOT NULL DEFAULT 0;
ALTER TABLE task_exercise_submissions ADD COLUMN manual_reviewer_id TEXT;
ALTER TABLE task_exercise_submissions ADD COLUMN manually_graded_at TEXT;

-- Startup recovery scans only unfinished worker claims; terminal history stays
-- append-only and the index keeps that bounded scan independent of task size.
CREATE INDEX idx_task_submissions_grade_recovery
  ON task_exercise_submissions (grade_status, manual_review_required, created_at);
