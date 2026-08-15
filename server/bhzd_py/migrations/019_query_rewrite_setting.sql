-- P0-9: keep the feature opt-in so existing retrieval behavior is unchanged.
ALTER TABLE rag_settings ADD COLUMN query_rewrite_enabled INTEGER NOT NULL DEFAULT 0;
