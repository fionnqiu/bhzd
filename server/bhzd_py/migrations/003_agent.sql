CREATE TABLE conversations (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  title TEXT, scenario_id TEXT, data_type TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT
);
CREATE TABLE messages (
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
  run_id TEXT, role TEXT NOT NULL CHECK (role IN ('user','assistant','system','tool')),
  content TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE agent_runs (
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
  user_id TEXT NOT NULL REFERENCES users(id),
  status TEXT NOT NULL CHECK (status IN ('running','waiting_confirmation','completed','failed','cancelled')),
  input_text TEXT NOT NULL, plan_json TEXT, scenario_id TEXT, data_type TEXT,
  provider_id TEXT, error TEXT, usage_json TEXT,
  created_at TEXT NOT NULL, completed_at TEXT
);
CREATE TABLE agent_events (              -- SSE 持久化，支持断线重连回放
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES agent_runs(id),
  seq INTEGER NOT NULL, event_type TEXT NOT NULL, payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE tool_calls (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES agent_runs(id),
  tool_name TEXT NOT NULL, permission TEXT NOT NULL CHECK (permission IN ('read','write')),
  status TEXT NOT NULL CHECK (status IN ('requested','running','completed','failed','awaiting_confirmation','cancelled')),
  args_json TEXT, result_json TEXT, duration_ms INTEGER, is_write INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, completed_at TEXT
);
CREATE TABLE pending_confirmations (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES agent_runs(id),
  user_id TEXT NOT NULL REFERENCES users(id),
  tool_call_id TEXT NOT NULL REFERENCES tool_calls(id),
  action_type TEXT NOT NULL,             -- task.create / diagnostic.save_summary / mastery.update / teacher.publish_task / rag.publish_document / rag.archive_document / rag.create_document / rag.reindex_document / rag.save_eval_case
  preview_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','confirmed','cancelled','expired')),
  expires_at TEXT NOT NULL,              -- 普通写 30min；删除/归档 10min(PRD-06 §6.4)
  created_at TEXT NOT NULL, resolved_at TEXT
);
