# Upstream Contribution: CockroachDB AI Governance Skill & Vector OpClass Finding

**Target Upstream Repository:** `cockroachdb/cockroachdb-skills`  
**Skill Path:** `skills/cockroachdb-security-and-governance/governing-ai-provenance-and-licensing/SKILL.md`

---

## 1. Upstream Skill Contribution Overview

This skill contributes a production-grade governance and licensing reference for CockroachDB AI and RAG applications, covering:
1. **Bitemporal Admission Patterns**: Recording explicit `admitted_at` application timestamps alongside CockroachDB's internal `admitted_txn = cluster_logical_timestamp()`.
2. **Soft-Delete Evidence Preservation**: Using `removed_at IS NULL` filters rather than physical `DELETE` statements so that past answer attributions can always be verified against historical ledger states.
3. **Atomic Attribution Invariants**: Enforcing that generated answers and document citation records commit in the same transactional boundary.

---

## 2. CockroachDB Cloud & pgvector Defect Report (Issue #23456)

**Live Upstream Issue:** [cockroachdb/docs#23456](https://github.com/cockroachdb/docs/issues/23456)  
**Status:** Submitted & Open  
**Summary:** `CREATE VECTOR INDEX` defaults to `vector_l2_ops`, causing `<=>` (Cosine Distance) queries to bypass index acceleration on CockroachDB v26.2.

### Reproduction Steps:
```sql
-- 1. Create table and vector index without explicit opclass
CREATE TABLE document_embeddings (
    doc_id STRING PRIMARY KEY,
    embedding VECTOR(1024)
);
CREATE VECTOR INDEX idx_doc_embeddings ON document_embeddings (embedding);

-- 2. Execute cosine distance query (standard for normalized text embeddings like Amazon Titan)
EXPLAIN SELECT doc_id FROM document_embeddings ORDER BY embedding <=> $1::VECTOR LIMIT 4;
-- Result: Planner performs full table scan + top-k sort (Index NOT used).

-- 3. Correct declaration:
DROP INDEX idx_doc_embeddings;
CREATE VECTOR INDEX idx_doc_embeddings_cosine ON document_embeddings (embedding vector_cosine_ops);

EXPLAIN SELECT doc_id FROM document_embeddings ORDER BY embedding <=> $1::VECTOR LIMIT 4;
-- Result: Planner selects IVFFlat vector index scan (Index accelerated).
```

### Proposed Documentation Fix:
Update the CockroachDB pgvector documentation to explicitly advise `vector_cosine_ops` for cosine similarity queries.
