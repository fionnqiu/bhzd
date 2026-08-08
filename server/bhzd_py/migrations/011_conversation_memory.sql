-- Conversation memory is deliberately separate from rag_chunks: chat history is
-- private to one user and one conversation and must never become shared course evidence.
CREATE TABLE conversation_memory_chunks (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  message_id TEXT NOT NULL UNIQUE REFERENCES messages(id) ON DELETE CASCADE,
  run_id TEXT,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
  content TEXT NOT NULL,
  embedding BLOB NOT NULL,
  embedding_model TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- Retrieval is always scoped before scoring so no other user or conversation
-- can enter a model context, while the index also supports one-time backfill.
CREATE INDEX idx_conversation_memory_scope_created
  ON conversation_memory_chunks (user_id, conversation_id, created_at);
