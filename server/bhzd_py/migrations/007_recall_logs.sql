CREATE TABLE recall_logs (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL,
  chunk_id TEXT,
  query TEXT NOT NULL,
  user_id TEXT,
  channel TEXT NOT NULL DEFAULT 'student_query',
  score REAL,
  created_at TEXT NOT NULL
);
-- 资料详情页"召回记录"按资料倒序拉取，(document_id, created_at) 复合索引支撑该查询
CREATE INDEX idx_recall_logs_document_created ON recall_logs (document_id, created_at);
