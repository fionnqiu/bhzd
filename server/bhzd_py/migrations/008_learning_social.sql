-- 008_learning_social.sql：学习域增强（入学测评/收藏资料/诊断缓存/CSRF 稳定化）。
-- 为什么合并为一个迁移：三处改动同属"学习与个人中心增强"一波交付，
-- 且彼此无外键依赖，单文件事务内一次落齐，避免跨迁移半态。
CREATE TABLE favorites (                  -- 收藏资料(PRD-01 §9 个人中心)
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  item_type TEXT NOT NULL CHECK(item_type IN ('rag_document','citation','teaching_unit','graph_node')),
  item_id TEXT NOT NULL,
  title TEXT NOT NULL,
  meta_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(user_id, item_type, item_id)     -- 同一条目重复收藏走幂等 upsert，不产生重复行
);
CREATE TABLE diagnostic_cache (           -- 诊断报告缓存：替代进程内 dict（多实例/重启不失效）
  token TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  report_json TEXT NOT NULL,              -- 只存报告 JSON，上传原文件仍绝不落盘(NF3/PRD-06 §12.1)
  expires_at TEXT NOT NULL,               -- 30 分钟确认窗口，过期读取时惰性删除
  created_at TEXT NOT NULL
);
-- CSRF 原始令牌落会话行：GET /api/auth/session 不再轮换（多标签页互顶修复）。
-- 新增列可空：迁移前的存量会话(legacy)只有 csrf_token_hash，读取时按需补发原始令牌。
ALTER TABLE user_sessions ADD COLUMN csrf_token TEXT;
ALTER TABLE admin_sessions ADD COLUMN csrf_token TEXT;
