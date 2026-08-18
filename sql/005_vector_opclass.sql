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
-- KNOWN REMAINING LIMITATION, stated rather than hidden:
-- Index acceleration requires that any filters match the index's prefix columns.
-- retrieval.search() joins corpus_members and filters on corpus_id and
-- removed_at, so the planner still declines the index for that query even with
-- the correct opclass. Scaling past a few thousand documents would need a prefix
-- column — a (corpus_id, embedding) index, which means denormalising corpus
-- membership onto the embedding row since a document can belong to several
-- corpora. That is the documented pattern (LangChain's CockroachDB vector store
-- uses a namespace prefix column for exactly this) and it is deliberately out of
-- scope here: at this corpus size the scan is immaterial, and denormalising
-- membership would put the provenance record in two places.

SET database = origin;

DROP INDEX IF EXISTS idx_documents_embedding;
DROP INDEX IF EXISTS idx_determinations_embedding;

CREATE VECTOR INDEX IF NOT EXISTS idx_documents_embedding
    ON documents (embedding vector_cosine_ops);

CREATE VECTOR INDEX IF NOT EXISTS idx_determinations_embedding
    ON license_determinations (embedding vector_cosine_ops);
