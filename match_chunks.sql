-- Run BOTH functions in Supabase SQL Editor before starting the API.

-- Function 1: search within a specific tool
CREATE OR REPLACE FUNCTION match_chunks(
  query_embedding VECTOR(1536),
  match_tool_id TEXT,
  match_count INT DEFAULT 10
)
RETURNS TABLE (
  id UUID,
  tool_id TEXT,
  "position" INTEGER,
  chunk_type TEXT,
  chunk_text TEXT,
  similarity FLOAT
)
LANGUAGE SQL STABLE
AS $$
  SELECT
    id,
    tool_id,
    position,
    chunk_type,
    chunk_text,
    1 - (embedding <=> query_embedding) AS similarity
  FROM chunks
  WHERE tool_id = match_tool_id
  ORDER BY embedding <=> query_embedding
  LIMIT match_count;
$$;

-- Function 2: search across ALL tools (used for auto/freeform mode)
CREATE OR REPLACE FUNCTION match_chunks_all(
  query_embedding VECTOR(1536),
  match_count INT DEFAULT 12
)
RETURNS TABLE (
  id UUID,
  tool_id TEXT,
  "position" INTEGER,
  chunk_type TEXT,
  chunk_text TEXT,
  similarity FLOAT
)
LANGUAGE SQL STABLE
AS $$
  SELECT
    id,
    tool_id,
    position,
    chunk_type,
    chunk_text,
    1 - (embedding <=> query_embedding) AS similarity
  FROM chunks
  ORDER BY embedding <=> query_embedding
  LIMIT match_count;
$$;
