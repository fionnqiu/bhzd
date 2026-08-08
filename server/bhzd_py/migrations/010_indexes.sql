-- Agent replay and run-detail reads repeatedly seek one run and preserve event order.
-- These composite keys avoid table scans and temporary sorting during SSE reconnects.
CREATE INDEX IF NOT EXISTS idx_agent_events_run_seq ON agent_events (run_id, seq);
CREATE INDEX IF NOT EXISTS idx_messages_conversation_created ON messages (conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_conversations_user_deleted_updated
  ON conversations (user_id, deleted_at, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_conversation ON agent_runs (conversation_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_run_created ON tool_calls (run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_pending_confirmations_run_status_created
  ON pending_confirmations (run_id, status, created_at);

-- Student task and mastery views filter by ownership before reading chronological history.
-- The task index also supports teacher aggregates that constrain both student and class.
CREATE INDEX IF NOT EXISTS idx_learning_tasks_user_class ON learning_tasks (user_id, class_id);
CREATE INDEX IF NOT EXISTS idx_task_attempts_task_number ON task_attempts (task_id, attempt_number);
CREATE INDEX IF NOT EXISTS idx_mastery_events_user_created
  ON mastery_events (user_id, created_at DESC, id DESC);

-- RAG administration loads document-local chunks and pipeline state in stable order.
CREATE INDEX IF NOT EXISTS idx_rag_chunks_document_index ON rag_chunks (document_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_rag_jobs_document_created ON rag_jobs (document_id, created_at);

-- The audit-log page is globally ordered by creation time when no narrower filter is supplied.
CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs (created_at DESC);
