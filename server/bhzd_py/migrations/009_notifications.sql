-- 009_notifications.sql：站内通知 + 学生诊断授权开关
-- 依据：PRD-06 §10.1（教师任务发布/截止变更须触达学生）、PRD-06 §15 #2
-- （教师查看学生诊断详情须学生授权，默认仅聚合）。

CREATE TABLE notifications (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT,
  ref_type TEXT,
  ref_id TEXT,
  read_at TEXT,
  created_at TEXT NOT NULL
);
-- 高频查询是"某人未读/列表倒序"，(user_id, read_at) 复合索引覆盖两类过滤
CREATE INDEX idx_notifications_user_read ON notifications (user_id, read_at);

-- 学生授权教师查看诊断详情的开关（默认 0=未授权，教师只能看聚合数据）
ALTER TABLE learning_profiles ADD COLUMN share_diagnostics INTEGER NOT NULL DEFAULT 0;
