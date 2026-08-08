CREATE TABLE rag_documents (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  file_type TEXT NOT NULL CHECK (file_type IN ('pdf','docx','md','txt','xlsx','csv','image','other')),
  source_type TEXT NOT NULL CHECK (source_type IN ('textbook','standard','enterprise','teacher','competition','other')),
  source_name TEXT NOT NULL, source_url TEXT, source_ledger_id TEXT,
  version TEXT NOT NULL,
  license_status TEXT NOT NULL CHECK (license_status IN ('authorized','internal','pending','forbidden')),
  data_types_json TEXT NOT NULL DEFAULT '[]',     -- ['text','image','audio','video']
  scenario_ids_json TEXT NOT NULL DEFAULT '[]',
  cap_ids_json TEXT NOT NULL DEFAULT '[]',
  visibility TEXT NOT NULL DEFAULT 'teacher' CHECK (visibility IN ('admin','teacher','student')),
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN
    ('draft','parsing','parsed','chunking','chunked','indexing','indexed','review_pending','published','rejected','archived','expired','failed')),
  storage_path TEXT, file_hash TEXT,
  error_code TEXT, error_message TEXT,
  process_version INTEGER NOT NULL DEFAULT 1,     -- 参数变化生成新处理版本(PRD-06 §5.2)
  created_by TEXT NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  published_at TEXT, expires_at TEXT
);
CREATE TABLE rag_chunks (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES rag_documents(id),
  chunk_index INTEGER NOT NULL, content TEXT NOT NULL,
  summary TEXT, keywords_json TEXT NOT NULL DEFAULT '[]',
  page_start INTEGER, page_end INTEGER, section_title TEXT,
  token_count INTEGER NOT NULL DEFAULT 0,
  embedding BLOB, embedding_model TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
  process_version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE rag_jobs (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES rag_documents(id),
  stage TEXT NOT NULL CHECK (stage IN ('parse','chunk','index')),
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
  idempotency_key TEXT UNIQUE,                    -- 幂等(PRD-06 §5.2)
  progress REAL NOT NULL DEFAULT 0,
  error_code TEXT, error_message TEXT, attempt INTEGER NOT NULL DEFAULT 0,
  params_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
);
CREATE TABLE source_ledgers (              -- v3.0 §12.4 字段级 schema
  id TEXT PRIMARY KEY, source_code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL, publisher TEXT, source_type TEXT, version TEXT,
  authorization_status TEXT NOT NULL CHECK (authorization_status IN ('approved','pending','expired','forbidden')),
  valid_from TEXT, valid_to TEXT,
  related_document_ids_json TEXT NOT NULL DEFAULT '[]',
  review_status TEXT NOT NULL DEFAULT 'draft' CHECK (review_status IN ('draft','reviewed','published')),
  notes TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE review_records (
  id TEXT PRIMARY KEY, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
  reviewer_id TEXT NOT NULL REFERENCES users(id),
  action TEXT NOT NULL CHECK (action IN ('submit','approve','approve_teacher_only','reject','archive','publish')),
  comment TEXT, created_at TEXT NOT NULL
);
CREATE TABLE eval_cases (
  id TEXT PRIMARY KEY, question TEXT NOT NULL, expected_answer TEXT,
  must_hit_document_ids_json TEXT NOT NULL DEFAULT '[]',
  must_hit_chunk_ids_json TEXT NOT NULL DEFAULT '[]',
  filters_json TEXT NOT NULL DEFAULT '{}',
  created_by TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE eval_runs (
  id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','completed','failed')),
  metrics_json TEXT, case_results_json TEXT,
  created_by TEXT NOT NULL, created_at TEXT NOT NULL, finished_at TEXT
);
CREATE TABLE rag_settings (                -- 单行(id=1)
  id INTEGER PRIMARY KEY CHECK (id = 1),
  chunk_size INTEGER NOT NULL DEFAULT 500, chunk_overlap INTEGER NOT NULL DEFAULT 80,
  title_inherit INTEGER NOT NULL DEFAULT 1, table_strategy TEXT NOT NULL DEFAULT 'keep',
  top_k INTEGER NOT NULL DEFAULT 5, score_threshold REAL NOT NULL DEFAULT 0.35,
  hybrid_search INTEGER NOT NULL DEFAULT 1, rerank_enabled INTEGER NOT NULL DEFAULT 0,
  citation_format TEXT NOT NULL DEFAULT '【{title} {section} {page} v{version}】',
  refusal_policy TEXT NOT NULL DEFAULT 'refuse',  -- refuse / generic_advice
  max_citations INTEGER NOT NULL DEFAULT 5,
  prompt_template TEXT NOT NULL DEFAULT '', prompt_template_version TEXT NOT NULL DEFAULT 'v1',
  require_manual_review INTEGER NOT NULL DEFAULT 1,
  student_visibility_default TEXT NOT NULL DEFAULT 'student',
  expired_doc_policy TEXT NOT NULL DEFAULT 'remove',  -- 过期自动移出学生召回
  updated_at TEXT NOT NULL, updated_by TEXT
);
