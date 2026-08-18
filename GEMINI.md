# GEMINI.md — Antigravity Agent Configuration for ORIGIN

This workspace contains the ORIGIN platform for EU AI Act Article 53 compliance, Amazon Bedrock RAG, and CockroachDB vector storage.

## Skills Configuration
Antigravity automatically discovers and loads skills declared in `.agents/skills.json` and `.agents/skills/`.

- **Codebase Memory MCP & Skill**: Use `codebase-memory` MCP server tools (`search_graph`, `trace_path`, `get_architecture`) to query functions, classes, and call graphs without wasting token context.
- **CockroachDB Skills**: Use `cockroachdb-sql` and related skills in `.agents/skills/` for schema design, EXPLAIN query optimization, index tuning, and cluster administration.
- **EU AI Act Article 53 Skill**: Use `origin-article53-compliance` for auditing training corpora, verifying copyright opt-outs, and exporting standardized AI Office training summaries.
- **pgvector & Time-Travel Skill**: Use `origin-cockroach-vector-ops` for 1024-dim vector similarity searches and `AS OF SYSTEM TIME` historical queries.
- **Bedrock RAG Skill**: Use `origin-bedrock-rag-pipeline` for Titan v2 embeddings and Claude 3.5 Sonnet generation pipelines.
