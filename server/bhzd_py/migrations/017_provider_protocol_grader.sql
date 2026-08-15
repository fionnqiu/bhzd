-- Forward-only provider contract migration.
-- The repository already applied migrations 013-016, so this must not reuse
-- the checklist's illustrative filenames or mutate an old SHA-256 record.
CREATE TABLE provider_configs_new (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  protocol TEXT NOT NULL CHECK (protocol IN ('chat_completions','anthropic_messages','responses')),
  base_url TEXT NOT NULL,
  model TEXT NOT NULL,
  api_key_encrypted TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'none' CHECK (role IN ('primary','fallback','embedding','rerank','grader','none')),
  enabled INTEGER NOT NULL DEFAULT 1,
  timeout_seconds REAL NOT NULL DEFAULT 30,
  extra_json TEXT NOT NULL DEFAULT '{}',
  last_test_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Retired Xunfei rows remain auditable but are made inert and represented by
-- the closest text protocol so old configuration records cannot block startup.
INSERT INTO provider_configs_new (
  id, name, protocol, base_url, model, api_key_encrypted, role, enabled,
  timeout_seconds, extra_json, last_test_json, created_at, updated_at
)
SELECT
  id,
  name,
  CASE WHEN protocol IN ('xunfei_xingchen', 'xunfei_spark')
       THEN 'chat_completions' ELSE protocol END,
  base_url,
  model,
  api_key_encrypted,
  role,
  CASE WHEN protocol IN ('xunfei_xingchen', 'xunfei_spark')
       THEN 0 ELSE enabled END,
  timeout_seconds,
  extra_json,
  last_test_json,
  created_at,
  updated_at
FROM provider_configs;

DROP TABLE provider_configs;
ALTER TABLE provider_configs_new RENAME TO provider_configs;
