-- Sent attachments retain only display metadata and an optional derived image
-- preview. Original upload bytes, tokens, and document text remain confined to
-- the short-lived in-process media cache.
CREATE TABLE message_attachments (
  id TEXT PRIMARY KEY,
  message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
  filename TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('image', 'video', 'audio', 'document')),
  mime_type TEXT NOT NULL,
  byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
  thumbnail BLOB,
  thumbnail_mime_type TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (message_id, ordinal),
  CHECK (
    (thumbnail IS NULL AND thumbnail_mime_type IS NULL)
    OR (thumbnail IS NOT NULL AND thumbnail_mime_type = 'image/webp')
  )
);

CREATE INDEX idx_message_attachments_message_ordinal
  ON message_attachments(message_id, ordinal);
