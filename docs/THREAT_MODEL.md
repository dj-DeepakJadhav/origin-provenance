# ORIGIN Security Architecture & Threat Model

**Document Version:** 1.0 (Post-Audit Edition)  
**System Scope:** CockroachDB Ledger, Ingestion Gateways, REST/UI Interface, and Bedrock/Local Inference Engine.

---

## 1. System Overview & Trust Boundaries

ORIGIN enforces regulatory and copyright compliance for AI training corpora and RAG retrieval pipelines. The system operates across four primary trust zones:

```
[ External Untrusted Sources ] (HuggingFace Hub, arXiv, Web Crawls)
             │
             ▼ (Untrusted metadata & content)
[ Ingestion & Classification Gate ] ───► [ Local/Bedrock Classifier ]
             │ (Fail-closed evaluation)
             ▼
[ CockroachDB Provenance Ledger ] ◄────► [ REST API & Agentic Memory ]
             │ (Bitemporal MVCC)                 ▲
             ▼                                   │ (Bearer Token Gated)
[ Downstream Training & RAG Checkpoints ] ───────┘ (Attributed Outputs)
```

---

## 2. Threat Analysis by Boundary

### Threat 1: Malicious Metadata Ingestion & License Poisoning
- **Vector**: An adversary uploads a proprietary, viral-copyleft, or non-commercial dataset to a public hub with spoofed metadata tags (e.g. tagging GPL code as `license:mit` or writing permissive terms in `cardData` while the repository carries a restrictive notice).
- **Impact**: Untrusted data bypasses simple keyword filters and contaminates pre-training corpora.
- **ORIGIN Mitigation**:
  1. **Dual-Signal Conflict Detection**: ORIGIN parses both `cardData.license` and `tags`. Any disparity immediately triggers a `METADATA_CONFLICT` flag and fails closed.
  2. **Rule-Based & N-Gram Normalization**: Ignores deceptive phrasing like "see LICENSE file" or unverified string variations, classifying unrecognized inputs as `UNKNOWN` (Quarantined).
  3. **Cryptographic SHA-256 Content Hashing**: Content is hashed at ingestion. If the upstream repository alters licensing terms or data post-admission, the hash mismatch is detectable.

### Threat 2: Compromised Write Bearer Token
- **Vector**: The `ORIGIN_WRITE_TOKEN` published for judge evaluations or operator access is intercepted or leaked.
- **Impact**: An attacker can initiate admissions, trigger ad-hoc takedown requests, or create conversational agent sessions.
- **ORIGIN Mitigation**:
  1. **Append-Only Ledger Design**: Even with write access, an attacker cannot delete historical admissions or edit past query attributions. In CockroachDB, mutations create new versions rather than erasing evidence.
  2. **Fail-Closed Gate Invariant**: An attacker cannot force the admission of a non-commercial dataset into a commercial corpus via `/api/v1/gate/evaluate` without modifying the underlying classification rules in source code.
  3. **Audit Trail Immutability**: Every mutation records `asked_by`, `requested_by`, and high-resolution `clock_timestamp()`.

### Threat 3: Data Leakage via Ledger Read Access
- **Vector**: An unauthorized entity gains read access to the provenance ledger or `/api/v1/impact` endpoints.
- **Impact**: Reconstruction of corpus composition, organizational queries, and document titles.
- **ORIGIN Mitigation**:
  1. **Storage Separation**: The database stores document metadata, cryptographic hashes, and embeddings (`document_embeddings`), but raw multi-gigabyte training files reside in segregated object stores (S3).
  2. **Partitioned Multi-Tenant Corpora**: Queries are bounded by `corpus_id`. Cross-corpus retrieval is prevented at the SQL layer.

### Threat 4: Hostile Operator / Compromised Database Admin
- **Vector**: A malicious insider with CockroachDB cluster admin credentials attempts to alter history or conceal a licensing breach.
- **Honest Boundary Assessment**:
  - **What Survives**: MVCC history cross-checking (`origin verify --at <timestamp>`) verifies whether application records match CockroachDB internal storage timestamps. Any retroactive `UPDATE` executed by application code is immediately detected as non-corroborated.
  - **What Does NOT Survive**: A cluster administrator with root access can drop tables, alter schema configurations, or purge range historical tombstones (`gc.ttlseconds`). ORIGIN guarantees application-level tamper resistance, not root hypervisor / DBA subversion.

---

## 3. Threat Mitigation Summary Matrix

| Threat Scenario | Attacker Capability | Impact Severity | ORIGIN Defense Mechanism | Residual Risk |
|---|---|---|---|---|
| **License Spoofing** | Public Hub dataset uploader | High (Corpus Contamination) | Dual-source conflict check + Fail-closed classifier | Intentional copyright misrepresentation by authentic author |
| **Write Token Leak** | Network interceptor | Medium (Unauthorized Actions) | Immutable append-only schema + Takedown audit logging | Resource exhaustion via spamming queries |
| **Tampered Answer Attribution** | Application bug / rogue client | Critical (False Compliance Claim) | Atomic multi-table transactions (1 SQL transaction) | None (zero-drift foreign key references) |
| **Retroactive Record Alteration** | Compromised App Service | High (Compliance Fraud) | CockroachDB `AS OF SYSTEM TIME` bitemporal cross-check | DBA-level table truncation |
| **Vector Index Poisoning** | Malicious embedding input | Low (Suboptimal Top-K) | Strict L2-normalization + Cosine distance operator (`<=>`) | High dimensional collision |

---

## 4. Recommended Hardening Checklist for Production

1. **Rotate Write Tokens**: Migrate from static environment token to IAM role-based authentication or OIDC JWT verification.
2. **Enable CMEK**: Deploy customer-managed encryption keys on CockroachDB Cloud Advanced.
3. **CORS Whitelisting**: Restrict `CORSMiddleware` to exact enterprise domain origins.
4. **Automate GC Safeguards**: Set `gc.ttlseconds` on CockroachDB to 30 days minimum to guarantee regulatory time-travel audit windows.
