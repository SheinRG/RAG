-- ========================================
-- Nexus — Initial Schema (documents, chunks, pgvector, match_chunks RPC)
-- Run this FIRST in the Supabase SQL Editor, before 001 and 002.
--
-- This is the schema the backend has always assumed but that previously
-- existed only inside a live Supabase project. Without it, a fresh clone
-- cannot start: retriever.py calls the match_chunks() RPC defined below.
-- ========================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";


-- ── documents ──
-- One row per uploaded source (file, YouTube transcript, Drive import).
-- notebook_id is declared here (without its foreign key, since the notebooks
-- table does not exist yet) because match_chunks() below references it and
-- Postgres validates SQL function bodies at CREATE time. 001 adds the FK.
CREATE TABLE IF NOT EXISTS documents (
  id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  filename      TEXT NOT NULL,                    -- UUID-based storage name
  original_name TEXT NOT NULL,                    -- name shown in the UI
  file_type     TEXT NOT NULL,                    -- pdf | docx | txt | ...
  file_size     BIGINT      NOT NULL DEFAULT 0,
  num_chunks    INTEGER     NOT NULL DEFAULT 0,
  status        TEXT        NOT NULL DEFAULT 'processing',
  error_msg     TEXT,
  storage_path  TEXT,                             -- path inside the storage bucket
  notebook_id   UUID,                             -- FK added in 001
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT documents_status_check
    CHECK (status IN ('processing', 'ready', 'failed'))
);


-- ── chunks ──
-- Embedded slices of a document. ON DELETE CASCADE is load-bearing: without
-- it, deleting a document orphans its chunks and they keep surfacing in
-- retrieval as context for a source the user believes is gone.
CREATE TABLE IF NOT EXISTS chunks (
  id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  content     TEXT NOT NULL,
  embedding   VECTOR(384) NOT NULL,               -- Cohere embed-english-light-v3.0
  chunk_index INTEGER NOT NULL DEFAULT 0,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Repair path for databases created before the cascade existed.
ALTER TABLE chunks DROP CONSTRAINT IF EXISTS chunks_document_id_fkey;
ALTER TABLE chunks ADD  CONSTRAINT chunks_document_id_fkey
  FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE;


-- ── Indexes ──
CREATE INDEX IF NOT EXISTS idx_documents_user_id    ON documents(user_id);
CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chunks_user_id       ON chunks(user_id);
CREATE INDEX IF NOT EXISTS idx_chunks_document_id   ON chunks(document_id);

-- ANN index for cosine similarity. Note that a scoped query (one that passes
-- filter_document_ids / filter_notebook_id) post-filters against this index,
-- so recall is correct but a very large corpus may want a partial index per
-- hot notebook. Correctness first. HNSW gives better recall/latency than
-- IVFFlat and needs no training pass, which matters because the table starts
-- empty. m/ef_construction are the pgvector defaults, stated explicitly.
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
  ON chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);


-- ── match_chunks() ──
-- Cosine similarity search, scoped to one user, with OPTIONAL scope filters
-- applied INSIDE the query.
--
-- Pushing the document/notebook filter down here (rather than over-fetching a
-- global top-N and filtering in Python) is what makes filtered retrieval
-- correct: ranking happens over the in-scope rows, so a chunk that is the best
-- match within the selected documents can never be lost just because it fell
-- outside the global candidate window.
--
-- The older 4-argument version is dropped first: adding defaulted parameters
-- would otherwise create an overload and make 4-arg calls ambiguous.
DROP FUNCTION IF EXISTS match_chunks(VECTOR(384), UUID, INT, FLOAT);
DROP FUNCTION IF EXISTS match_chunks(VECTOR(384), UUID, INT, FLOAT, UUID[], UUID);

CREATE FUNCTION match_chunks(
  query_embedding      VECTOR(384),
  match_user_id        UUID,
  match_count          INT     DEFAULT 5,
  match_threshold      FLOAT   DEFAULT 0.10,
  filter_document_ids  UUID[]  DEFAULT NULL,
  filter_notebook_id   UUID    DEFAULT NULL
)
RETURNS TABLE (
  id          UUID,
  document_id UUID,
  content     TEXT,
  chunk_index INTEGER,
  similarity  FLOAT
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    c.id,
    c.document_id,
    c.content,
    c.chunk_index,
    1 - (c.embedding <=> query_embedding) AS similarity
  FROM chunks c
  WHERE c.user_id = match_user_id
    AND (
      filter_document_ids IS NULL
      OR c.document_id = ANY (filter_document_ids)
    )
    AND (
      filter_notebook_id IS NULL
      OR c.document_id IN (
        SELECT d.id FROM documents d
        WHERE d.notebook_id = filter_notebook_id
          AND d.user_id     = match_user_id
      )
    )
    AND 1 - (c.embedding <=> query_embedding) > match_threshold
  ORDER BY c.embedding <=> query_embedding
  LIMIT match_count;
$$;

-- PostgREST caches the schema; without this the new signature 404s until the
-- API container restarts.
NOTIFY pgrst, 'reload schema';
