# ORIGIN Project Architecture Rules

- **Database**: CockroachDB v24.2+ via `psycopg3` connection pool. Always use parameterized queries and serializable transaction retry handling.
- **Vector Embeddings**: 1024-dimensional vectors stored as `VECTOR(1024)` in `document_embeddings`. Distance query uses `<=>` (cosine).
- **AI Compliance**: All training data ingestion must pass licensing and copyright opt-out checks per EU AI Act Article 53 before admission.
- **Auditing**: Every document mutation must write an immutable provenance record with SHA-256 hash.
