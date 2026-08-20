-- DF-05: make asynchronous lesson generation observable and recoverable.
-- The additive fields intentionally avoid a CHECK constraint so an older worker
-- can still finish during a rolling deployment while newer clients display its
-- source and any safe recovery guidance.
ALTER TABLE learning_tasks ADD COLUMN content_generation_source TEXT NOT NULL DEFAULT 'none';
ALTER TABLE learning_tasks ADD COLUMN content_failure_reason TEXT;
ALTER TABLE learning_tasks ADD COLUMN content_generation_message TEXT;
ALTER TABLE learning_tasks ADD COLUMN content_generation_retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE learning_tasks ADD COLUMN content_last_attempt_at TEXT;
