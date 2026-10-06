CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL,
  title TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_uri TEXT NOT NULL,
  active_version_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS source_registry (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL,
  name TEXT NOT NULL,
  url TEXT NOT NULL,
  publisher TEXT NOT NULL,
  authority_tier TEXT NOT NULL CHECK(authority_tier IN ('A','B','C','D')),
  document_type TEXT NOT NULL,
  allowed_roles TEXT[] NOT NULL DEFAULT '{reader}',
  metadata JSONB NOT NULL DEFAULT '{}',
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  refresh_interval_hours INTEGER NOT NULL DEFAULT 168 CHECK(refresh_interval_hours >= 1),
  next_refresh_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_checked_at TIMESTAMPTZ,
  last_success_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(tenant_id, url)
);

ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_registry_id UUID
  REFERENCES source_registry(id);
CREATE UNIQUE INDEX IF NOT EXISTS documents_source_registry_idx
  ON documents(tenant_id, source_registry_id) WHERE source_registry_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS document_versions (
  id UUID PRIMARY KEY,
  document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  version_number INTEGER NOT NULL,
  content_hash TEXT NOT NULL,
  parser_version TEXT NOT NULL,
  chunker_config JSONB NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('indexing','active','failed','retired')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(document_id, version_number)
);

ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_active_version_fk;
ALTER TABLE documents ADD CONSTRAINT documents_active_version_fk
  FOREIGN KEY(active_version_id) REFERENCES document_versions(id);

CREATE TABLE IF NOT EXISTS document_acl (
  document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  role_name TEXT NOT NULL,
  PRIMARY KEY(document_id, role_name)
);

CREATE TABLE IF NOT EXISTS chunks (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL,
  document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  document_version_id UUID NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}',
  page_start INTEGER,
  page_end INTEGER,
  token_count INTEGER NOT NULL,
  search_vector TSVECTOR,
  embedding VECTOR(1536),
  UNIQUE(document_version_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS chunks_fts_idx ON chunks USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS chunks_hnsw_idx ON chunks USING hnsw(embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tenant_doc_idx ON chunks(tenant_id, document_id);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
  id UUID PRIMARY KEY,
  document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  status TEXT NOT NULL CHECK(status IN ('queued','processing','completed','failed','skipped')),
  file_hash TEXT NOT NULL,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);
ALTER TABLE ingestion_jobs DROP CONSTRAINT IF EXISTS ingestion_jobs_status_check;
ALTER TABLE ingestion_jobs ADD CONSTRAINT ingestion_jobs_status_check
  CHECK(status IN ('queued','processing','completed','failed','skipped'));

CREATE TABLE IF NOT EXISTS acquisition_runs (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL,
  source_registry_id UUID NOT NULL REFERENCES source_registry(id) ON DELETE CASCADE,
  ingestion_job_id UUID REFERENCES ingestion_jobs(id),
  status TEXT NOT NULL CHECK(status IN ('queued','processing','downloaded','skipped','failed')),
  http_status INTEGER,
  content_hash TEXT,
  bytes_downloaded BIGINT,
  error_message TEXT,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS acquisition_runs_source_idx
  ON acquisition_runs(source_registry_id, created_at DESC);

CREATE TABLE IF NOT EXISTS source_snapshots (
  id UUID PRIMARY KEY,
  source_registry_id UUID NOT NULL REFERENCES source_registry(id) ON DELETE CASCADE,
  document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  ingestion_job_id UUID REFERENCES ingestion_jobs(id),
  content_hash TEXT NOT NULL,
  source_url TEXT NOT NULL,
  object_path TEXT NOT NULL,
  retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(source_registry_id, content_hash)
);

CREATE TABLE IF NOT EXISTS golden_questions (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL,
  question TEXT NOT NULL,
  reference_answer TEXT,
  relevant_chunk_ids UUID[] NOT NULL DEFAULT '{}',
  answerable BOOLEAN NOT NULL,
  required_roles TEXT[] NOT NULL DEFAULT '{}',
  category TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS query_traces (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL,
  subject TEXT NOT NULL,
  question TEXT NOT NULL,
  configuration JSONB NOT NULL,
  retrieved_chunk_ids UUID[] NOT NULL,
  answer JSONB NOT NULL,
  latency_ms JSONB NOT NULL,
  estimated_cost_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
