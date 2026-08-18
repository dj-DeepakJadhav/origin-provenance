# ORIGIN Performance, Vector Index & Latency Benchmarks

**Environment:** CockroachDB Cloud Advanced v26.2 (Multi-Region Ready) & AWS Lambda Runtime  
**Vector Embedding Dimensions:** 1,024 float (Amazon Titan Text Embeddings V2 & Local Hashed Tri-Grams)

---

## 1. Vector Search Query Plan & OpClass Optimization (`EXPLAIN`)

### The Default Operator Class Defect
On CockroachDB v26.2, `CREATE VECTOR INDEX ... USING ivfflat (embedding)` defaults strictly to `vector_l2_ops`. Because text embedding models (Titan V2 and ORIGIN's deterministic n-gram vectorizer) rely on normalized direction, semantic RAG queries execute cosine distance searches using `<=>`:

```sql
SELECT doc_id, embedding <=> $1::VECTOR AS distance
FROM documents
ORDER BY distance ASC
LIMIT 4;
```

**Query Plan Comparison:**

| Schema Declaration | Query Operator | CockroachDB Planner Verdict | Execution Strategy |
|---|---|---|---|
| `USING ivfflat (embedding)` | `<=>` (Cosine) | ❌ **Index Bypassed** | Full table scan + Top-K sort |
| `USING ivfflat (embedding)` | `<->` (Euclidean L2) | ✅ **Index Accelerated** | IVFFlat vector index scan |
| `USING ivfflat (embedding vector_cosine_ops)` | `<=>` (Cosine) | ✅ **Index Accelerated** | IVFFlat vector index scan |

### Architectural Trade-off: Join vs Compound Prefix Vector Index

In `src/origin/retrieval.py`, retrieval is strictly bounded to *currently admitted members* of a specific corpus:

```sql
SELECT d.doc_id, d.title, d.embedding <=> $1::VECTOR AS distance
FROM corpus_members m
JOIN documents d ON d.doc_id = m.doc_id
WHERE m.corpus_id = $2 AND m.removed_at IS NULL
ORDER BY distance ASC LIMIT 4;
```

**Query Plan & Optimizer Behavior:**
1. The planner scans `corpus_members@idx_members_current` filtering by `(corpus_id, removed_at = NULL)`.
2. It executes a targeted `lookup join` against `documents@documents_pkey` and sorts top-K.

**The Selectivity Crossover Analysis:**
- **Small Selective Corpus ($|C| \ll |D|$):** When a corpus is a small subset of the total document table (e.g. 24–100 documents out of 10,000), scanning `idx_members_current` is $O(|C|)$ and runs in sub-millisecond local CPU cache without global index tree traversals.
- **Large / Single-Tenant Corpus ($|C| \approx |D|$):** When the corpus approaches total table size (e.g., a single-tenant deployment with $|C| = 10,000$), the plan degrades to a full scan of $N$ rows and $N$ in-memory cosine distance evaluations, leaving the `documents(embedding)` vector index unused.
- **The Production Solution (Compound Prefix Vector Index):**
  On CockroachDB v26.2.5, compound prefix vector indexing accelerates filtered multi-tenant vector searches directly:
  ```sql
  CREATE VECTOR INDEX idx_corpus_documents_vec 
  ON corpus_documents (corpus_id, embedding vector_cosine_ops);
  ```
  **Verified CockroachDB Optimizer Execution Plan:**
  ```
  • top-k (k: 4)
  └── • render
      └── • lookup join (table: corpus_documents@corpus_documents_pkey)
          └── • vector search (table: corpus_documents@idx_corpus_documents_vec, target count: 4, prefix spans: [corpus_id])
  ```
  *Result:* Scopes hardware-accelerated vector search directly to the exact `prefix spans: [corpus_id]`, eliminating both sequential scanning and cross-corpus post-filtering.

---

## 2. Agentic Memory Covering Index Optimization

During performance profiling on CockroachDB v26.2.5, we analyzed the cost-based optimizer query plans for Working Memory and Semantic Memory recall:

### Working Memory Recall (`session_turns`)
- **Before Optimization:**
  ```
  • top-k (k: 3)
  └── • index join (table: session_turns@session_turns_pkey)
      └── • scan (table: session_turns@session_turns_session_id_turn_no_key, spans: [session_id])
  ```
- **Optimization (`sql/008_vector_covering_indexes.sql`):**
  ```sql
  CREATE INDEX idx_turns_session_covering 
  ON session_turns (session_id) 
  STORING (role, content, embedding, created_at);
  ```
- **After Optimization (Index Join Eliminated):**
  ```
  • top-k (k: 3)
  └── • scan (table: session_turns@idx_turns_session_covering, spans: [session_id])
  ```
  *Result: Eliminates the secondary lookup join back to the primary key table, executing working memory vector recall in a single index scan.*

### Semantic Policy Ruling Recall (`license_determinations`)
- **Before Optimization:**
  ```
  • top-k (k: 1)
  └── • filter (superseded_by IS NULL)
      └── • scan (table: license_determinations@license_determinations_pkey, spans: FULL SCAN)
  ```
- **Optimization:**
  ```sql
  CREATE INDEX idx_determinations_covering 
  ON license_determinations (superseded_by) 
  STORING (license_raw, determined_class, rationale, embedding, strength, human_confirmed, decided_at);
  ```
- **After Optimization (Full Scan Eliminated):**
  ```
  • top-k (k: 1)
  └── • scan (table: license_determinations@idx_determinations_covering, spans: [/NULL - /NULL])
  ```
  *Result: Replaces the full table scan with a direct slice scan over active, non-superseded rulings (`/NULL - /NULL`).*

---

## 2. API Latency & Load Curves (Concurrency Sweeps)

Benchmarked reproducibly via `python deploy/benchmark.py --sweep`:

| Concurrency Level | Total Requests | Failures | p50 Latency (ms) | p95 Latency (ms) | p99 Latency (ms) | Mean (ms) |
|---|---|---|---|---|---|---|
| **c=1** (Sequential) | 40 | 0 | 48.2 ms | 74.6 ms | 88.1 ms | 51.4 ms |
| **c=2** | 40 | 0 | 51.7 ms | 79.4 ms | 92.5 ms | 54.8 ms |
| **c=4** | 40 | 0 | 58.3 ms | 86.1 ms | 104.2 ms | 62.1 ms |
| **c=8** | 40 | 0 | 72.4 ms | 118.5 ms | 142.0 ms | 79.6 ms |
| **c=16** | 40 | 0 | 114.2 ms | 182.4 ms | 215.8 ms | 123.5 ms |
| **c=32** | 40 | 0 | 198.5 ms | 284.1 ms | 320.6 ms | 211.7 ms |

*Measurements taken warm against API Gateway / Lambda in `eu-central-1` connected to CockroachDB Cloud.*

---

## 3. Cold Start Characterization

- **Cold Container Start:** ~2,840 ms (initial image pull, Python runtime boot, and TLS handshake to CockroachDB Cloud).
- **Warm Execution:** ~48–55 ms p50 for atomic turn retrieval, vector recall, and attribution logging.
