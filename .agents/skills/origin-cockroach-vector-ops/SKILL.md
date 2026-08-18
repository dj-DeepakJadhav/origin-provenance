---
name: origin-cockroach-vector-ops
description: Use when working with CockroachDB pgvector indexes, cosine similarity distance queries, vector embeddings storage, schema migrations (001-007), and AS OF SYSTEM TIME time-travel provenance queries in ORIGIN.
---

# ORIGIN CockroachDB Vector & Provenance Skill

This skill guides vector index creation, distance searches, and time-travel querying on CockroachDB for ORIGIN.

## Vector Schema & Indexing (CockroachDB v24.2+)

- Vector column dimension: `VECTOR(1024)` (Amazon Bedrock Titan Embeddings v2 normalized).
- Cosine Distance Operator: `<=>` (returns `1 - cosine_similarity`).

```sql
-- Hybrid Vector Search with Licensing Filter
SELECT 
    d.id,
    d.title,
    d.license,
    d.content_uri,
    1 - (de.embedding <=> $1::VECTOR(1024)) AS similarity
FROM document_embeddings de
JOIN documents d ON d.id = de.document_id
WHERE d.corpus_id = $2
  AND d.status = 'admitted'
  AND d.license IN ('MIT', 'Apache-2.0', 'CC-BY-4.0')
ORDER BY de.embedding <=> $1::VECTOR(1024) ASC
LIMIT 10;
```

## Time-Travel Provenance Queries (AS OF SYSTEM TIME)

CockroachDB supports querying data at exact historical timestamps:

```sql
-- Audit exact corpus state at the time a model checkpoint was trained
SELECT id, title, license, content_hash, status
FROM documents AS OF SYSTEM TIME '2026-08-15 12:00:00+00'
WHERE corpus_id = $1;
```
