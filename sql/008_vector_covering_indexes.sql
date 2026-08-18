-- ORIGIN — High-Performance Covering Vector Indexes for Agentic Memory & Search
--
-- Optimization findings on CockroachDB Cloud v26.2.5:
-- 1. Working Memory (session_turns): Adding a covering index on session_id STORING
--    (role, content, embedding, created_at) eliminates the index join back to the
--    primary key table, reducing working memory recall latency to a single index scan.
-- 2. Semantic Memory (license_determinations): Adding a covering index on superseded_by
--    STORING (license_raw, determined_class, rationale, embedding, strength, human_confirmed, decided_at)
--    replaces the table scan with a direct non-superseded slice scan (/NULL - /NULL).
-- 3. Document Embeddings (documents): Adding vector_cosine_ops vector index accelerates
--    cosine distance queries.

CREATE INDEX IF NOT EXISTS idx_turns_session_covering
    ON session_turns (session_id)
    STORING (role, content, embedding, created_at);

CREATE INDEX IF NOT EXISTS idx_determinations_covering
    ON license_determinations (superseded_by)
    STORING (license_raw, determined_class, rationale, embedding, strength, human_confirmed, decided_at);
