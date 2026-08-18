-- ORIGIN — agent memory schema (CockroachDB)
--
-- Design note, because it is the crux of the whole project:
--
-- "What was in the corpus at 14:22 on July 3rd?" can be answered two ways, and
-- we deliberately do BOTH, because each alone is a liability:
--
--   1. MVCC / AS OF SYSTEM TIME. Free, exact, needs no bookkeeping, and cannot be
--      forged by application code. But it is bounded by the garbage-collection
--      window (gc.ttlseconds — 4h by default on CockroachDB Cloud). Ask about a
--      timestamp older than that and you get an error, not a wrong answer.
--
--   2. Explicit bitemporal validity (admitted_at / removed_at). Unbounded horizon,
--      survives GC, but it is application-maintained and therefore only as
--      trustworthy as our own code.
--
-- So: (2) is the durable record of record, and (1) is the independent check that
-- (2) has not been tampered with. Agreement between them is the actual evidence.
-- Disagreement is a detected integrity failure, which is a feature, not a bug.
-- See corpus.py:membership_as_of() and corpus.py:verify_ledger_integrity().

CREATE DATABASE IF NOT EXISTS origin;
SET database = origin;

-- ---------------------------------------------------------------------------
-- Corpora: a declared document pile with a declared permitted use.
-- The declared use is what the build gate enforces against.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS corpora (
    corpus_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name             STRING NOT NULL UNIQUE,
    datahub_urn      STRING,                    -- entity in the context graph
    -- What this pile is allowed to be used for. The gate reads this.
    declared_use     STRING NOT NULL,           -- commercial | internal | research
    description      STRING,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT valid_declared_use
        CHECK (declared_use IN ('commercial', 'internal', 'research'))
);

-- ---------------------------------------------------------------------------
-- Documents: the registry of every document we have ever seen, with provenance.
--
-- license_raw is stored VERBATIM and never normalised in place. The messiness
-- is the evidence — a regulator asking "what did the licence actually say?"
-- wants the original bytes, not our tidy interpretation of them.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    doc_id           STRING PRIMARY KEY,        -- stable id from the source
    source_uri       STRING NOT NULL,
    source_system    STRING NOT NULL,           -- arxiv | huggingface | s3 | ...
    title            STRING,
    content_hash     STRING NOT NULL,           -- sha256; detects silent mutation
    license_raw      STRING,                    -- verbatim, never rewritten
    license_class    STRING,                    -- normalised permitted-use class
    license_confidence FLOAT,
    -- Evidentiary anchor: the cluster's own commit timestamp for this row.
    -- Not application clock time. This is the thing we can defend.
    admitted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    admitted_txn     STRING,                    -- cluster_logical_timestamp()
    datahub_urn      STRING,
    INDEX idx_documents_source (source_system, source_uri),
    INDEX idx_documents_license_class (license_class)
);

-- ---------------------------------------------------------------------------
-- Corpus membership: which documents are in which pile, and WHEN.
--
-- Removal is a soft delete (removed_at), never a DELETE. A hard delete would
-- destroy exactly the record we exist to keep — and after GC, MVCC could not
-- recover it either. "Currently a member" means removed_at IS NULL.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS corpus_members (
    corpus_id        UUID NOT NULL REFERENCES corpora (corpus_id),
    doc_id           STRING NOT NULL REFERENCES documents (doc_id),
    admitted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    admitted_txn     STRING,
    removed_at       TIMESTAMPTZ,               -- NULL = current member
    removal_reason   STRING,                    -- takedown | licence_expiry | ...
    removal_ref      UUID,                      -- -> takedowns.takedown_id
    PRIMARY KEY (corpus_id, doc_id),
    INDEX idx_members_current (corpus_id, removed_at),
    INDEX idx_members_doc (doc_id)
);

-- ---------------------------------------------------------------------------
-- Licence determinations: the LEARNED part of the memory.
--
-- Real licence fields are free text and endlessly various ("CC-BY-4.0",
-- "cc by 4.0", "Creative Commons Attribution", "see LICENSE file"). Classifying
-- the same string twice and getting two answers is how you end up in court.
--
-- So every determination is remembered and vector-indexed. A new licence string
-- is first matched against past determinations; only genuinely novel strings go
-- to the model. Human corrections set human_confirmed and raise strength, so the
-- memory gets more accurate over time rather than merely larger.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS license_determinations (
    determination_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    license_raw      STRING NOT NULL,
    determined_class STRING NOT NULL,
    rationale        STRING,
    -- Provenance of the determination itself: who decided, and how.
    decided_by       STRING NOT NULL,           -- model:<id> | human:<who> | memory
    model_version    STRING,
    embedding        VECTOR(1024),
    human_confirmed  BOOL NOT NULL DEFAULT false,
    strength         FLOAT NOT NULL DEFAULT 1.0, -- reinforced on reuse
    decided_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_by    UUID REFERENCES license_determinations (determination_id),
    INDEX idx_determinations_raw (license_raw),
    INDEX idx_determinations_live (superseded_by) WHERE superseded_by IS NULL
);

-- ---------------------------------------------------------------------------
-- Build gates: every attempt to (re)build an index, allowed or blocked.
--
-- A blocked build is the most valuable row in the database — it is the moment
-- the system prevented a licence violation, and it is what we show an auditor.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS build_gates (
    gate_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    corpus_id        UUID NOT NULL REFERENCES corpora (corpus_id),
    attempted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    attempted_by     STRING,
    decision         STRING NOT NULL,           -- allowed | blocked
    member_count     INT NOT NULL,
    violation_count  INT NOT NULL DEFAULT 0,
    -- The offending documents and the clause that damned them. Quoted, so the
    -- refusal is explainable without re-running anything.
    violations       JSONB,
    CONSTRAINT valid_decision CHECK (decision IN ('allowed', 'blocked')),
    INDEX idx_gates_corpus (corpus_id, attempted_at DESC)
);

-- ---------------------------------------------------------------------------
-- Answer attributions: which documents served which answer.
--
-- Written in the SAME transaction as the answer itself. That atomicity is the
-- whole point: an answer with no attribution row is impossible, and an
-- attribution row with no answer is impossible. There is no drift between what
-- we served and what we claim we served.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS answers (
    answer_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    corpus_id        UUID NOT NULL REFERENCES corpora (corpus_id),
    asked_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    asked_by         STRING,
    question         STRING NOT NULL,
    answer_text      STRING,
    model_version    STRING,
    INDEX idx_answers_time (asked_at DESC)
);

CREATE TABLE IF NOT EXISTS answer_attributions (
    answer_id        UUID NOT NULL REFERENCES answers (answer_id),
    doc_id           STRING NOT NULL REFERENCES documents (doc_id),
    rank             INT,
    similarity       FLOAT,
    PRIMARY KEY (answer_id, doc_id),
    -- The reverse lookup is the one that matters: given a document that must be
    -- removed, which answers already used it? This index is why that is fast.
    INDEX idx_attributions_by_doc (doc_id)
);

-- ---------------------------------------------------------------------------
-- Takedowns: a document must come out, and we must account for its past use.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS takedowns (
    takedown_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id           STRING NOT NULL REFERENCES documents (doc_id),
    requested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    requested_by     STRING,
    reason           STRING,
    -- Filled in by the impact query. Snapshotted rather than recomputed, because
    -- the answer must not change after the fact.
    affected_answers JSONB,
    affected_count   INT,
    resolved_at      TIMESTAMPTZ,
    INDEX idx_takedowns_doc (doc_id)
);

-- ---------------------------------------------------------------------------
-- Retrieval log: high-volume, low-value-after-a-while. Row-level TTL keeps the
-- table honest without a cron job. Distinct from answer_attributions, which is
-- the evidentiary record and is never expired.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS retrieval_log (
    log_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    corpus_id        UUID,
    query_text       STRING,
    retrieved_ids    STRING[],
    latency_ms       INT,
    logged_at        TIMESTAMPTZ NOT NULL DEFAULT now()
) WITH (ttl_expire_after = '30 days', ttl_job_cron = '@daily');
