-- ORIGIN — distributed vector index + retention configuration
--
-- Kept separate from 001 for two reasons:
--   1. Vector index DDL syntax and enablement varies by CockroachDB version, so
--      a mismatch here should not block the core schema from applying.
--   2. Zone configuration is cluster-dependent and may be restricted on some
--      CockroachDB Cloud plans. This file is expected to partially fail on
--      Basic/Serverless — see the note on gc.ttlseconds below.
--
-- Run with:  python -m origin.cli migrate
-- The migrator reports per-statement success so a partial apply is visible
-- rather than silent.

SET database = origin;

-- ---------------------------------------------------------------------------
-- Distributed vector index on licence-determination embeddings.
--
-- This is the recall path: a new, messy licence string is embedded and matched
-- against every determination we have ever made, so the same string is never
-- re-litigated and never classified two different ways.
--
-- Some versions gate this behind a cluster setting. If the CREATE below fails
-- with a feature-disabled error, run (requires admin on the cluster):
--     SET CLUSTER SETTING feature.vector_index.enabled = true;
-- ---------------------------------------------------------------------------
CREATE VECTOR INDEX IF NOT EXISTS idx_determinations_embedding
    ON license_determinations (embedding);

-- ---------------------------------------------------------------------------
-- Garbage collection window — the honest constraint on AS OF SYSTEM TIME.
--
-- MVCC time travel can only reach back as far as GC has not yet run. The
-- default on CockroachDB Cloud is 4 hours (14400s), which is fine for
-- forensics on a live incident and useless for "what did the corpus look like
-- last Tuesday".
--
-- We raise it to 7 days on the two tables where point-in-time truth is the
-- product. This costs storage — that is the trade, and it is the right one
-- here. Everything else keeps the default.
--
-- If your plan disallows zone configuration, this will fail and that is
-- survivable: the explicit admitted_at/removed_at columns carry the long
-- horizon, and MVCC degrades to a short-window integrity check. The README
-- states this limitation plainly rather than pretending time travel is
-- unbounded.
-- ---------------------------------------------------------------------------
ALTER TABLE corpus_members CONFIGURE ZONE USING gc.ttlseconds = 604800;
ALTER TABLE documents      CONFIGURE ZONE USING gc.ttlseconds = 604800;
