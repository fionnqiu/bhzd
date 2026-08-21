-- Agent 学习任务草稿：LLM 生成的任务卡在同步落库前的持久化投影。
-- 草稿独立于 pending_confirmations：卡片上的显式同步按钮即写入授权，
-- status（draft → synced）+ task_ids_json 让重复点击/刷新回放都幂等。
CREATE TABLE IF NOT EXISTS task_drafts (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id),
  conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
  source TEXT NOT NULL DEFAULT 'agent',
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'synced')),
  -- {"cards": [build_task_card 输出...], "generator": "provider" | "template"}
  card_json TEXT NOT NULL,
  task_ids_json TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  synced_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_task_drafts_run ON task_drafts (run_id);
CREATE INDEX IF NOT EXISTS idx_task_drafts_user_created
  ON task_drafts (user_id, created_at DESC);
