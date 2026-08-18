-- ORIGIN — document embeddings for retrieval
--
-- Added after the ledger was working, because retrieval is what makes the
-- provenance chain meaningful: without an answer there is nothing to attribute.
--
-- Kept in its own migration rather than folded into 001 so that an existing
-- deployment can adopt it without reapplying the core schema. The column is
-- nullable on purpose — documents admitted before this migration have no
-- embedding, and retrieval must degrade rather than fail for them. See
-- retrieval.search(), which reports how many members are unembedded instead of
-- silently returning a short list.

SET database = origin;

ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedding VECTOR(1024);

-- The retrieval path: nearest neighbours among a corpus's current members.
CREATE VECTOR INDEX IF NOT EXISTS idx_documents_embedding
    ON documents (embedding);
