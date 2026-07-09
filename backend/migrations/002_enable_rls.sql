-- ========================================
-- Nexus — Enable RLS on documents & chunks (defense-in-depth)
-- Run this in the Supabase SQL Editor.
--
-- The backend accesses these tables with the SERVICE-ROLE key, which bypasses
-- RLS, so these policies do NOT change backend behaviour. The frontend never
-- queries these tables directly (only Supabase Auth). These policies are a
-- safety net: if a user/anon JWT is ever used against these tables, a caller
-- can only ever see or modify their own rows.
-- ========================================

-- ── documents ──
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can manage own documents" ON documents;
CREATE POLICY "Users can manage own documents" ON documents
  FOR ALL
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

-- ── chunks ──
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can manage own chunks" ON chunks;
CREATE POLICY "Users can manage own chunks" ON chunks
  FOR ALL
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

-- ── Supporting indexes (safe if they already exist) ──
CREATE INDEX IF NOT EXISTS idx_documents_user_id ON documents(user_id);
CREATE INDEX IF NOT EXISTS idx_chunks_user_id ON chunks(user_id);
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id);

-- NOTE: the match_chunks() RPC is invoked via the service role and already
-- filters by match_user_id, so it is unaffected by these policies.
