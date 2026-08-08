CREATE TABLE learning_profiles (
  user_id TEXT PRIMARY KEY REFERENCES users(id),
  goal_text TEXT, major TEXT, target_cert TEXT,
  onboarding_json TEXT,                  -- 入学测评结果(完整版 §11.1)
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE mastery (                   -- scenario_id 为 '' 表示通用掌握度
  user_id TEXT NOT NULL REFERENCES users(id),
  cap_id TEXT NOT NULL, scenario_id TEXT NOT NULL DEFAULT '',
  score REAL NOT NULL CHECK (score BETWEEN 0 AND 1),
  source TEXT, updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, cap_id, scenario_id)
);
CREATE TABLE mastery_events (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  cap_id TEXT NOT NULL, scenario_id TEXT NOT NULL DEFAULT '',
  old_score REAL NOT NULL, new_score REAL NOT NULL,
  source TEXT NOT NULL,                  -- exercise / diagnostic / teacher_task / assessment
  ref_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE learning_tasks (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),   -- 学生
  title TEXT NOT NULL, goal TEXT, data_type TEXT, scenario_id TEXT,
  cap_ids_json TEXT NOT NULL DEFAULT '[]',
  source TEXT NOT NULL CHECK (source IN ('agent','preset','teacher','diagnostic')),
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','not_started','in_progress','submitted','completed','paused','archived')),
  steps_json TEXT NOT NULL DEFAULT '[]',        -- [{title,description,notes,common_errors}]
  resources_json TEXT NOT NULL DEFAULT '[]',    -- [{type,title,ref_id,citation?}]
  rubric_json TEXT, practice_json TEXT,         -- 评分规则 / 练习样本
  counts_toward_mastery INTEGER NOT NULL DEFAULT 1,
  teacher_id TEXT, class_id TEXT, due_at TEXT,
  version INTEGER NOT NULL DEFAULT 1, parent_task_id TEXT,
  created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived_at TEXT
);
CREATE TABLE task_attempts (
  id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES learning_tasks(id),
  user_id TEXT NOT NULL REFERENCES users(id),
  attempt_number INTEGER NOT NULL,
  submission_json TEXT NOT NULL, score REAL, feedback_json TEXT,
  mastery_applied INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE diagnostic_summaries (      -- 原文件不持久化，仅存摘要(NF3)
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  file_format TEXT NOT NULL, data_type TEXT, scenario_id TEXT,
  error_count INTEGER NOT NULL, severity_counts_json TEXT NOT NULL,
  report_json TEXT NOT NULL, weak_cap_ids_json TEXT NOT NULL DEFAULT '[]',
  plan_json TEXT, created_at TEXT NOT NULL
);
CREATE TABLE analytics_events (          -- 埋点(§8)
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT, event_name TEXT NOT NULL, props_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
