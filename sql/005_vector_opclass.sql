-- ORIGIN — give the vector indexes the opclass our queries actually use
--
-- Fixes a real defect. sql/002 and sql/003 created vector indexes with no
-- operator class:
--
--     CREATE VECTOR INDEX idx_documents_embedding ON documents (embedding);
--
-- which defaults to `vector_l2_ops` and therefore only accelerates the L2
-- operator `<->`. Every query in ORIGIN orders by cosine distance `<=>`, so the
-- indexes were never serving them. Results were correct — the distance was
-- computed properly — but each search was a full scan with a sort.
--
-- Confirmed with EXPLAIN on a live v26.2.5 cluster, simplest possible form with
-- no join or filter:
--     ORDER BY embedding <=> $1   ->  index NOT used
--     ORDER BY embedding <-> $1   ->  index used
--
-- Cosine is the right metric to keep rather than switching the queries to L2:
-- these are text embeddings and we only care about direction, and the vendor
-- documentation recommends cosine for models that normalise or are trained with
-- a cosine loss — which covers both of our providers (the local one L2-normalises
-- explicitly, and Titan is called with normalize=true).
--
-- The prefix index was implemented in sql/009_corpus_search_index.sql to address
-- this limit, using a separate derived corpus_search_index table to keep the
-- ledger history compact while gaining sub-millisecond retrieval.

SET database = origin;

DROP INDEX IF EXISTS idx_documents_embedding;
DROP INDEX IF EXISTS idx_determinations_embedding;

CREATE VECTOR INDEX IF NOT EXISTS idx_documents_embedding
    ON documents (embedding vector_cosine_ops);

CREATE VECTOR INDEX IF NOT EXISTS idx_determinations_embedding
    ON license_determinations (embedding vector_cosine_ops);
