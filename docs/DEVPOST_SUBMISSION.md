# CockroachDB × AWS Hackathon Devpost Submission Copy

> **Submission for CockroachDB × AWS Hackathon**
> **Deadline:** August 18, 2026

---

## 📌 Project Overview

### Project Title
**ORIGIN — Agentic Memory & Provenance Engine on CockroachDB**

### Tagline
Five agentic memory systems (working, semantic, episodic, temporal, task state) built on CockroachDB with receipts and atomic provenance guarantees for everything your AI reads.

---

## 📝 Project Description

### 1. The Problem

Ask an AI system *"which documents produced this answer, and were we allowed to
use them?"* and most cannot say. Ask *"what was in the corpus on 3 July?"* and
almost none can.

**That stopped being an embarrassment and became a liability on 2 August 2026**,
when the EU AI Office's enforcement powers over general-purpose AI providers came
into force. The training-data transparency and copyright obligations they enforce
carry penalties of up to **€15M or 3% of worldwide annual turnover**. Nothing in
the recent Omnibus deferrals touched them.

The frontier labs will be fine — they have counsel on retainer. The gap is
everyone else. Reconstructing *what was in the corpus, on what date, under what
licence* after the fact is a manual archaeology exercise costing lawyer-hours a
small company does not have, which is why the honest answer is usually **"we
don't know."** ORIGIN's position is that this should be a query, not a project.

Concretely, four failures ORIGIN attacks:
- **No Conversational Working Memory:** Systems lose turn context or treat follow-on queries as stateless calls.
- **No License Audit Trail:** Restrictive or non-commercial licenses quietly enter commercial AI systems without checks.
- **Non-Atomic Operations:** Answers are served without guaranteed links to source documents or session history.
- **No Point-in-Time Rewind:** Organizations cannot audit what was in an AI corpus at a specific past timestamp.

> **Why this is not another compliance checklist.** The AI Act tools that exist
> are questionnaires: you describe your system, they tell you which obligations
> attach. Every answer is something you said about yourself, and none of them
> ever touch the data. A questionnaire cannot tell you that ten documents in your
> commercial corpus declare no licence at all, because it never sees the corpus.
> **The checkers ask what you did. ORIGIN reads what you actually admitted — and
> reports where its own answer stops being evidence.**

### 2. What ORIGIN Does
ORIGIN implements a multi-tiered agentic memory architecture where every memory type leverages CockroachDB:
1. **Working Memory:** Multi-turn session state (`sessions`, `session_turns`) with recency and hardware-accelerated vector similarity recall over turn history.
2. **Semantic Memory:** Learned, reinforced license rulings (`license_determinations`) that strengthen on reuse and preserve human corrections via `superseded_by` chains.
3. **Episodic Memory:** Recorded AI Q&A answers, exact snippets, and immutable attribution receipts.
4. **Temporal Memory:** Point-in-time dataset state using CockroachDB native MVCC `AS OF SYSTEM TIME` queries cross-checked against application bitemporal timestamps (`admitted_at` / `removed_at`).
5. **Task State Memory:** Durable multi-step agentic execution state (`agent_tasks`) with step-level persistence and crash resumption.

> **Atomic Commitment:** User query turns, agent response turns, AI answers, and document attributions commit **atomically in one database transaction**. A turn and its provenance receipt cannot diverge.

### 3. What the Memory Is *For*: `origin article53`

Five memory systems are only worth building if something can be asked of them.
`origin article53` is that question, and it is the beat worth watching in the
demo video:

```bash
origin article53 --corpus hub-commercial --at=-2h
```

One command produces the regulator-facing disclosure — every source, every
verbatim licence string, every build the policy refused and the clause it quoted
— **for the corpus as it stood at any instant**, off temporal memory. On a
conventional database that requires having snapshotted the whole corpus, on a
schedule, indefinitely, in anticipation of being asked. On CockroachDB's MVCC
storage it is a `WHERE` clause with a timestamp.

Two things it does that matter more than the output:

- **It reports its own evidentiary grade.** Inside the MVCC window it says
  membership came from storage history and *"does not depend on trusting
  ORIGIN."* Outside it, the same command on the same corpus reports **"Asserted,
  not verifiable"**, names the garbage-collection horizon as the reason, and
  **exits 1**. A tool that returned the same confident number either way would be
  the failure this project exists to argue against.
- **It renders the nine fields it *cannot* fill**, each with the reason. A report
  showing only its populated sections would read as complete coverage of a
  template it covers about half of.

---

## 🛠️ CockroachDB Tools & AWS Services Used

### CockroachDB Tools: What the Agent & Engine Did
1. **Distributed Vector Indexing:** Recalls working memory turns (`session_turns.embedding`), semantic policy rulings (`license_determinations.embedding`), and corpus documents (`documents.embedding`) using cosine similarity (`<=>`) accelerated by explicit `vector_cosine_ops` indexes.
2. **Cloud Managed MCP Server:** Connected via `.agents/mcp_config.json` (`https://cockroachlabs.cloud/mcp`) enabling development agents to query cluster metadata, inspect live tables, and verify vector index state on CockroachDB Cloud.
3. **ccloud CLI & Control Plane:** Integrated at runtime via `/api/v1/cluster` to inspect live cluster topology, gateway regions, table range distribution, and zone configurations (`SHOW ZONE CONFIGURATION`) on v26.2.5.
4. **CockroachDB Agent Skills:** Applied architectural and schema patterns (transaction retry hoisting, bitemporal modeling, explicit opclass indexing) vendored across 6 active domain packages (34 executable skills) in `.claude/skills/` with Apache-2.0 attribution in `LICENSE` and `NOTICE.md`.

### AWS Services Integrated
1. **AWS S3:** Document storage (`origin-provenance-248557779236` bucket in `eu-central-1`).
2. **AWS Lambda & API Gateway:** Live deployed serverless API endpoint supporting public demo execution (`https://lg7mjxz6m2.execute-api.eu-central-1.amazonaws.com`). Deploy-ready container image (`Dockerfile.lambda` verified with Mangum ASGI handler).
3. **Amazon SageMaker:** Drop-in inference provider (`src/origin/providers/sagemaker.py`) for real-time model-grounded generation.
4. **Amazon Bedrock:** Implemented in `src/origin/providers/bedrock.py` for classifying novel license texts via Amazon Titan/Claude embeddings. *(Note: Codebase includes automated fallback to local embeddings when AWS account model quotas or SCP policies are restricted)*.

---

## 💡 Feedback on CockroachDB AI Tools

1. **`CREATE VECTOR INDEX` Opclass Default Finding:**
   On live v26.2.5 clusters, `CREATE VECTOR INDEX` without an explicit operator class defaults to **`vector_l2_ops`** (L2 distance). Queries evaluating cosine similarity (`<=>`) silently bypass the index and perform full scans. Explicitly specifying `vector_cosine_ops` in index DDL resolves this:
   ```sql
   CREATE VECTOR INDEX idx_turns_embedding ON session_turns (embedding vector_cosine_ops);
   ```
2. **MVCC System Range Horizon:**
   Configuring `gc.ttlseconds = 604800` (7 days) on user tables extends row retention, but resolving table descriptors reads system ranges with shorter default TTLs (~4-5 hours). ORIGIN's bitemporal fallbacks (`verify_integrity`) seamlessly bridge this gap.

---

## ❓ FAQ: Architecture & Regulatory Compliance

### Q1: Why is CockroachDB technically required for EU AI Act compliance instead of standard vector DBs and log streams?
**A:** Traditional vector databases (e.g., Pinecone, Weaviate, Chroma) and log streams (CloudWatch, Kafka) provide **zero ACID transactional guarantees**. If an ingestion pipeline crashes mid-batch or updates a document license, log records and vector index states can silently diverge. Under **EU AI Act Article 53 (GPAI Copyright Transparency)** and **Article 12 (Automated Record-Keeping)**, unverified post-hoc logs fail audit standards. ORIGIN uses CockroachDB's distributed serializable transactions so that the user query turn, agent response, retrieved snippets, and attribution receipts **commit atomically in a single database transaction**. A turn and its receipts cannot suffer partial writes or unrecorded citations.

### Q2: How does CockroachDB solve the "Point-in-Time Regulatory Audit" requirement?
**A:** When regulators (such as the EU AI Office) or rightsholders ask *"What documents were in the AI's retrieval corpus at 14:20 on July 3rd?"*, conventional databases require restoring terabyte-scale database backups. ORIGIN utilizes CockroachDB's native Multi-Version Concurrency Control (MVCC) **`AS OF SYSTEM TIME`** queries. With a single SQL query (`origin article53 --at=-2h`), ORIGIN reconstructs the exact historical corpus state, active licenses, and gate decisions in milliseconds directly from storage history.

### Q3: How does ORIGIN enforce human oversight (Article 14) and prevent copyright leaks?
**A:** ORIGIN enforces a **fail-closed** policy: unclassified or ambiguous licenses halt the build pipeline and issue a `REVIEW` state rather than defaulting to permissive access. When a human reviewer resolves a determination, ORIGIN creates an immutable `superseded_by` audit trail (`ledger.confirm_determination`). Human corrections carry higher match strength, outranking automated model classifications on future ingestions.

### Q4: How does ORIGIN handle copyright takedowns or data erasure requests?
**A:** Hard-deleting data destroys the audit trail needed to prove compliance. ORIGIN executes atomic **blast-radius takedown audits** (`corpus.record_takedown`). It soft-deletes document access from future queries, computes every past answer that ever cited the document, and flags downstream records for remediation—maintaining full evidence integrity without serving invalid data.

---

## 📜 Prior-Work & Dual Submission Disclosure

> ORIGIN was built between Aug 5–17, 2026, entirely within this hackathon's submission period (June 30 – Aug 18, 2026). The same codebase was submitted to the DataHub AI hackathon on Aug 10. No pre-existing code was incorporated. The CockroachDB agent-memory layer (`sessions`, `session_turns`, `agent.py`) and the AWS deployment were built after that date, for this submission.

---

## 🔗 Submission Links
- **GitHub Repository:** https://github.com/dj-DeepakJadhav/origin-provenance
- **EU AI Act Compliance & Governance Architecture:** [`docs/COMPLIANCE.md`](COMPLIANCE.md)
- **Live Demo URL / Runbook:** [`docs/DEPLOY.md`](DEPLOY.md)
- **Video Demo (< 3 mins, Public):** *(Insert Public YouTube URL here)*
