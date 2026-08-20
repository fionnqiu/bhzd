-- Remove the content_admin role: rebuild users with a tightened role CHECK.
-- Forward-only migration because db.py rejects edits to an already-applied
-- migration whose recorded SHA-256 no longer matches (same rationale as 016).

-- SQLite cannot ALTER a CHECK constraint, so the table must be rebuilt.  Two
-- engine behaviors shape the script below:
--
-- 1. apply_migrations wraps the script in BEGIN/COMMIT, where
--    PRAGMA foreign_keys=OFF would be a no-op.  The script therefore closes
--    the runner's transaction first, disables foreign keys outside any
--    transaction, and reopens a transaction so the runner's trailing COMMIT
--    still pairs cleanly.
-- 2. ALTER TABLE users RENAME rewrites REFERENCES clauses in child tables
--    (observed on SQLite 3.50 regardless of foreign_keys/legacy_alter_table),
--    so the original table is never renamed.  It is dropped while foreign
--    keys are off; child tables keep resolving the name "users", which the
--    final RENAME restores with the new definition.
--
-- Fail-closed: if any row still has role='content_admin', the INSERT violates
-- the new CHECK and the migration aborts instead of dropping that user.

COMMIT;
PRAGMA foreign_keys=OFF;
BEGIN;

CREATE TABLE users_new (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('student','teacher','system_admin')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
  school_id TEXT,
  email_verified_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

INSERT INTO users_new (id, email, name, role, status, school_id, email_verified_at, created_at, updated_at)
SELECT id, email, name, role, status, school_id, email_verified_at, created_at, updated_at
FROM users;

DROP TABLE users;
ALTER TABLE users_new RENAME TO users;

COMMIT;
PRAGMA foreign_keys=ON;
BEGIN;
