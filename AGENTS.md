# AGENTS.md — ORIGIN AI Agent Guidance

This project integrates CockroachDB (distributed SQL, pgvector, time-travel queries) with Amazon Bedrock (Titan v2 embeddings, Claude 3.5 Sonnet RAG) and enforces EU AI Act Article 53 GPAI copyright and training compliance.

## Available Workspace Skills

Agents operating in this workspace have access to the complete suite of **CockroachDB official skills** and **ORIGIN specialized skills** in `.agents/skills/` (declared in `.agents/skills.json` and `.claude/skills/`):

### 1. ORIGIN Specialized Skills
- **`codebase-memory`**: Query the ORIGIN structural code graph (functions, classes, call chains, imports) via MCP tools (`search_graph`, `trace_path`, `get_architecture`, `detect_changes`) without sweeping large token context.
- **`origin-article53-compliance`**: Audit, verify, and generate EU AI Act Article 53 GPAI compliance reports, training summaries, copyright opt-out verification, and Model Card receipts.
- **`origin-cockroach-vector-ops`**: CockroachDB pgvector indexes (`VECTOR(1024)`), cosine similarity distance queries (`<=>`), and `AS OF SYSTEM TIME` time-travel provenance queries.
- **`origin-bedrock-rag-pipeline`**: Amazon Bedrock Titan Text Embeddings v2 and Claude 3.5 Sonnet RAG generation with licensing guardrails.

### 2. Official CockroachDB Skills Suite
- **Query & Schema Design**: `cockroachdb-sql` (SQL patterns, schema design, anti-pattern prevention, keyset pagination, UUID primary keys).
- **Application Development**: `designing-application-transactions`, `benchmarking-transaction-patterns`, `designing-multi-region-applications`.
- **Security & Governance**: `auditing-cis-benchmark`, `auditing-cloud-cluster-security`, `configuring-audit-logging`, `enabling-cmek-encryption`, `hardening-user-privileges`, `managing-tls-certificates`, `preparing-compliance-documentation`.
- **Observability & Diagnostics**: `triaging-live-sql-activity`, `profiling-statement-fingerprints`, `profiling-transaction-fingerprints`, `analyzing-range-distribution`, `monitoring-background-jobs`.
- **Operations & Lifecycle**: `reviewing-cluster-health`, `provisioning-cluster-for-production`, `upgrading-cluster-version`, `managing-cluster-settings`, `managing-cluster-capacity`.
- **Migrations & Onboarding**: `molt-fetch`, `molt-replicator`, `molt-verify`, `setting-up-local-cluster`.

## Architectural Guidelines

1. **Database Connection & Transactions**:
   - Always connect using `src.origin.db.get_pool()` or `src.origin.db.transaction()`.
   - Never write raw unparameterized SQL. Always pass SQL parameters as tuples.
   - Handle CockroachDB serialization retry errors (`RETRY_SERIALIZABLE`) via the built-in retry decorator in `src.origin.db`.

2. **Vector Embeddings & Search**:
   - Vector column type is `VECTOR(1024)`.
   - Distance operator is `<=>` for cosine distance (`similarity = 1 - (embedding <=> query_vec)`).
   - Filter by admitted status and permissive licenses (`MIT`, `Apache-2.0`, `CC-BY-4.0`, etc.).

3. **EU AI Act Article 53 Compliance**:
   - Ingestion pipelines must verify copyright reservation status (Directive 2019/790 DSM).
   - Ingested documents generate immutable cryptographic SHA-256 receipts in CockroachDB.
   - Public training data summaries must conform to the EU AI Office standardized template.
