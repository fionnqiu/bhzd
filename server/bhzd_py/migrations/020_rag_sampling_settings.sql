-- Keep retrieval-generation sampling knobs in the durable RAG settings row.
-- The older generation/publish columns remain for historical compatibility;
-- the management API no longer exposes them after this migration.
ALTER TABLE rag_settings ADD COLUMN temperature REAL NOT NULL DEFAULT 0.3;
ALTER TABLE rag_settings ADD COLUMN top_p REAL NOT NULL DEFAULT 0.9;
