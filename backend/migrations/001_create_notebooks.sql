-- ========================================
-- Nexus — Notebooks Migration
-- Run this in Supabase SQL Editor
-- ========================================

-- 1. Create the notebooks table
CREATE TABLE IF NOT EXISTS notebooks (
  id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
  user_id UUID REFERENCES auth.users(id) NOT NULL,
  title TEXT DEFAULT 'Untitled notebook',
  description TEXT DEFAULT '',
  emoji TEXT DEFAULT '📓',
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. Add notebook_id column to the documents table.
-- 000_initial_schema.sql declares the bare column (match_chunks references it),
-- so the foreign key is added separately here -- ADD COLUMN IF NOT EXISTS is a
-- no-op when the column already exists and would silently skip the FK.
ALTER TABLE documents
ADD COLUMN IF NOT EXISTS notebook_id UUID;

ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_notebook_id_fkey;
ALTER TABLE documents ADD  CONSTRAINT documents_notebook_id_fkey
  FOREIGN KEY (notebook_id) REFERENCES notebooks(id) ON DELETE CASCADE;

-- 3. Enable Row Level Security on notebooks
ALTER TABLE notebooks ENABLE ROW LEVEL SECURITY;

-- 4. Create RLS policy so users can only access their own notebooks
CREATE POLICY "Users can manage own notebooks" ON notebooks
  FOR ALL
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

-- 5. Create an index for faster lookups
CREATE INDEX IF NOT EXISTS idx_notebooks_user_id ON notebooks(user_id);
CREATE INDEX IF NOT EXISTS idx_documents_notebook_id ON documents(notebook_id);
