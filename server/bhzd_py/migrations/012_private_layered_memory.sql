-- Layered memories remain private application state.  They are deliberately
-- separate from course RAG so a learner's conversation can never become
-- evidence for another learner or a shared knowledge-base answer.
CREATE TABLE private_memory_items (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  layer TEXT NOT NULL CHECK (layer IN ('l1', 'l2', 'l3')),
  kind TEXT NOT NULL CHECK (kind IN ('fact', 'preference', 'scenario', 'profile')),
  memory_key TEXT NOT NULL,
  content TEXT NOT NULL,
  normalized_content TEXT NOT NULL,
  origin_conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  origin_run_id TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'superseded')),
  superseded_by_id TEXT REFERENCES private_memory_items(id) ON DELETE SET NULL,
  embedding BLOB NOT NULL,
  embedding_model TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- A summary can be derived from several messages.  Keeping each source link
-- lets the deletion path erase every derivative instead of leaving an orphaned
-- profile fact after its user-visible source was removed.
CREATE TABLE private_memory_sources (
  memory_id TEXT NOT NULL REFERENCES private_memory_items(id) ON DELETE CASCADE,
  message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  PRIMARY KEY (memory_id, message_id)
);

CREATE INDEX idx_private_memory_scope_active
  ON private_memory_items (user_id, status, created_at DESC);
CREATE INDEX idx_private_memory_scope_key
  ON private_memory_items (user_id, layer, memory_key, status);
CREATE UNIQUE INDEX uq_private_memory_active_dedupe
  ON private_memory_items (user_id, layer, normalized_content)
  WHERE status = 'active';
CREATE INDEX idx_private_memory_source_message
  ON private_memory_sources (message_id);

-- FTS5 supplies the lexical half of hybrid recall.  User_id is stored only as
-- an unindexed filter; every query still applies the normal relational owner
-- predicate before a memory can reach model context.
CREATE VIRTUAL TABLE private_memory_fts
  USING fts5(memory_id UNINDEXED, user_id UNINDEXED, content, tokenize = 'unicode61');

CREATE TRIGGER private_memory_fts_insert
AFTER INSERT ON private_memory_items
WHEN NEW.status = 'active'
BEGIN
  INSERT INTO private_memory_fts (rowid, memory_id, user_id, content)
  VALUES (NEW.rowid, NEW.id, NEW.user_id, NEW.content);
END;

CREATE TRIGGER private_memory_fts_update
AFTER UPDATE OF user_id, status, content ON private_memory_items
BEGIN
  DELETE FROM private_memory_fts WHERE rowid = OLD.rowid;
  INSERT INTO private_memory_fts (rowid, memory_id, user_id, content)
  SELECT NEW.rowid, NEW.id, NEW.user_id, NEW.content
  WHERE NEW.status = 'active';
END;

CREATE TRIGGER private_memory_fts_delete
AFTER DELETE ON private_memory_items
BEGIN
  DELETE FROM private_memory_fts WHERE rowid = OLD.rowid;
END;

-- Source deletion is a privacy boundary, not merely a dangling-FK cleanup.
-- Delete the whole derived item before SQLite cascades source links so any
-- multi-message summary cannot survive after one of its inputs was removed.
CREATE TRIGGER private_memory_delete_with_source
BEFORE DELETE ON messages
BEGIN
  DELETE FROM private_memory_items
  WHERE id IN (
    SELECT memory_id FROM private_memory_sources WHERE message_id = OLD.id
  );
END;
