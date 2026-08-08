CREATE TABLE users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('student','teacher','content_admin','system_admin')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
  school_id TEXT,
  email_verified_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE user_credentials (
  user_id TEXT PRIMARY KEY REFERENCES users(id),
  password_hash TEXT NOT NULL,          -- argon2id
  algo TEXT NOT NULL DEFAULT 'argon2id',
  updated_at TEXT NOT NULL
);
CREATE TABLE email_verification_tokens (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  token_hash TEXT NOT NULL, expires_at TEXT NOT NULL,
  consumed_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE password_reset_tokens (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  token_hash TEXT NOT NULL, expires_at TEXT NOT NULL,
  consumed_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE user_sessions (             -- 学生/教师/内容管理员会话
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  token_hash TEXT NOT NULL UNIQUE, csrf_token_hash TEXT NOT NULL,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT,
  ip TEXT, user_agent TEXT
);
CREATE TABLE admin_sessions (            -- 系统管理员独立会话(NF4 会话隔离)
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  token_hash TEXT NOT NULL UNIQUE, csrf_token_hash TEXT NOT NULL,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT,
  ip TEXT, user_agent TEXT
);
CREATE TABLE login_attempts (            -- 限流/失败锁定(NF5)
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL, ip TEXT, success INTEGER NOT NULL, created_at TEXT NOT NULL
);
