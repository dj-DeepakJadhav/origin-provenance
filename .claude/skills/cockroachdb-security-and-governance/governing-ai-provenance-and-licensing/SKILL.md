---
name: governing-ai-provenance-and-licensing
description: Guides implementation of AI training data governance, cryptographic provenance, bitemporal admission tracking, and pgvector cosine indexing best practices on CockroachDB. Use when designing schemas for AI corpora, enforcing copyright and license gates (EU AI Act Article 53), managing historical time-travel audits (AS OF SYSTEM TIME), or fixing vector index operator class mismatches.
compatibility: Applicable to CockroachDB v24.2+ (Core and Cloud) with pgvector support.
metadata:
  author: cockroachdb-community
  version: "1.0"
---

# Governing AI Provenance and Licensing on CockroachDB

This skill provides architectural guidance and SQL patterns for building regulatory-grade AI training data ledgers, cryptographic provenance audit trails, bitemporal document admissions, and high-performance vector search in CockroachDB.

## When to Use This Skill

- Designing AI training corpora schemas with strict licensing governance (EU AI Act Article 53, Directive 2019/790 DSM).
- Implementing immutable cryptographic provenance receipts (SHA-256) and audit trails.
- Enforcing fail-closed admission gates for non-commercial or unlicensed data.
- Performing historical time-travel compliance audits using CockroachDB `AS OF SYSTEM TIME`.
- Configuring and optimizing vector similarity indexes with explicit operator classes (`vector_cosine_ops`).

---

## Core Architectural Patterns

### 1. Bitemporal Ingestion & Soft-Delete Evidence Preservation

When copyright takedowns or license revocations occur, deleting rows destroys the evidentiary audit trail. CockroachDB schemas must preserve admission receipts with tombstoning:

```sql
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    corpus_id UUID NOT NULL,
    title STRING NOT NULL,
    content_hash STRING NOT NULL, -- SHA-256 of canonical content
    license STRING NOT NULL,
    license_class STRING NOT NULL, -- 'permissive', 'copyleft', 'non_commercial', 'unknown'
    status STRING NOT NULL DEFAULT 'admitted', -- 'admitted', 'quarantined', 'tombstoned'
    admitted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    tombstoned_at TIMESTAMPTZ,
    tombstone_reason STRING,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    INDEX idx_corpus_status (corpus_id, status)
);
```

### 2. Time-Travel Provenance Auditing (`AS OF SYSTEM TIME`)

CockroachDB Multi-Version Concurrency Control (MVCC) enables exact historical audits. Verify which documents were present when a model checkpoint was trained:

```sql
-- Audit the exact corpus state as it existed during training run at 2026-08-15 12:00:00 UTC
SELECT id, title, license, content_hash, status
FROM documents AS OF SYSTEM TIME '2026-08-15 12:00:00+00'
WHERE corpus_id = 'c0a80123-7b4c-4a3d-8e5f-123456789abc'
  AND status = 'admitted';
```

### 3. Critical Finding: Vector Index Operator Class Mismatch

> **Warning**: In CockroachDB v24.2 / v26.2, `CREATE INDEX ... ON ... USING ivfflat (embedding)` defaults to `vector_l2_ops` (Euclidean distance).
> If your application queries cosine similarity using `<=>` (`cosine_distance`), the query planner will silently **bypass** the vector index and execute a full table scan.

#### Correct Vector Index Pattern:
Always explicitly specify `vector_cosine_ops` when searching with cosine distance (`<=>`):

```sql
-- Explicit operator class is REQUIRED for <=> queries to use index
CREATE INDEX idx_doc_embeddings_cosine
ON document_embeddings USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Verified Search Query:
SELECT 
    d.id,
    d.title,
    d.license,
    1 - (de.embedding <=> $1::VECTOR(1024)) AS cosine_similarity
FROM document_embeddings de
JOIN documents d ON d.id = de.document_id
WHERE d.corpus_id = $2
  AND d.status = 'admitted'
ORDER BY de.embedding <=> $1::VECTOR(1024) ASC
LIMIT 10;
```

---

## Verification & EXPLAIN Checks

Always run `EXPLAIN` to confirm index utilization on vector queries:

```sql
EXPLAIN SELECT d.id FROM document_embeddings de JOIN documents d ON d.id = de.document_id
ORDER BY de.embedding <=> '[0.1, 0.2, ...]'::VECTOR(1024) LIMIT 10;
-- Must show: vector-index-scan / ivfflat scan, NOT table-scan
```
