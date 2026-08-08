CREATE TABLE provider_configs (
  id TEXT PRIMARY KEY, name TEXT NOT NULL,
  protocol TEXT NOT NULL CHECK (protocol IN ('xunfei_xingchen','xunfei_spark','chat_completions','anthropic_messages')),
  base_url TEXT NOT NULL, model TEXT NOT NULL,
  api_key_encrypted TEXT NOT NULL,          -- AES-256-GCM(NF2)，明文永不出库/日志
  role TEXT NOT NULL DEFAULT 'none' CHECK (role IN ('primary','fallback','embedding','rerank','none')),
  enabled INTEGER NOT NULL DEFAULT 1,
  timeout_seconds REAL NOT NULL DEFAULT 30,
  extra_json TEXT NOT NULL DEFAULT '{}',
  last_test_json TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE audit_logs (
  id TEXT PRIMARY KEY, actor_id TEXT, actor_role TEXT,
  action TEXT NOT NULL, target_type TEXT, target_id TEXT,
  before_json TEXT, after_json TEXT,
  ip TEXT, user_agent TEXT, created_at TEXT NOT NULL
);
