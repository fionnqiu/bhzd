-- Per-admin alert suppression. Rows are removed when their fingerprint is no longer
-- active, so a recovered condition is visible again if it recurs later.
CREATE TABLE admin_alert_ignores (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  fingerprint TEXT NOT NULL,
  ignored_at TEXT NOT NULL,
  UNIQUE (user_id, fingerprint)
);

CREATE INDEX idx_admin_alert_ignores_user ON admin_alert_ignores(user_id, fingerprint);
