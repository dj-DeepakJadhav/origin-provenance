---
name: origin-bedrock-rag-pipeline
description: Use when building, testing, or integrating Amazon Bedrock Titan Text Embeddings v2 and Claude 3.5 Sonnet RAG generation with provenance receipts and licensing gates in ORIGIN.
---

# ORIGIN Bedrock RAG Pipeline Skill

This skill provides patterns for Amazon Bedrock Titan embeddings, Claude 3.5 Sonnet inference, and provenance receipt generation.

## Amazon Bedrock Integration

- **Model ID (Embeddings)**: `amazon.titan-embed-text-v2:0` (1024-dimension, normalized=True).
- **Model ID (Inference)**: `anthropic.claude-3-5-sonnet-20241022-v2:0` (or `anthropic.claude-3-sonnet-20240229-v1:0`).

## Provenance-Backed Generation Flow

1. Embed user query using Bedrock Titan Text v2 (`1024` dimensions).
2. Query CockroachDB vector table for nearest admitted documents respecting licensing filters (`<= 0.35` distance).
3. Construct prompt with cited document URIs and cryptographic content hashes.
4. Call Claude 3.5 Sonnet with citations enabled.
5. Record cryptographic query receipt in CockroachDB `query_audit_log`.

```python
from origin.bedrock import BedrockClient
from origin.search import hybrid_search

client = BedrockClient()
query_vec = client.generate_embedding("How do I configure distributed ACID transactions?")
results = hybrid_search(query_vec=query_vec, corpus_id=corpus_id, limit=5)
```
