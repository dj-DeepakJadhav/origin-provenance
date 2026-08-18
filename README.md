# ORIGIN

**Agentic Memory & Provenance Engine for AI Systems on CockroachDB**

Prove what your AI was allowed to learn from, enforce strict conversational working memory, block unlicensed data at the door, and rewind to any past instant to trace exact provenance receipts.

---

## 🧠 Five Agentic Memory Systems on CockroachDB

ORIGIN implements a multi-tiered agentic memory system where every memory type leverages CockroachDB's distributed architecture, transactional atomicity, and vector indexing:

| Memory Type | Description | CockroachDB Storage & Mechanism | Status |
|---|---|---|---|
| **Working Memory** | Multi-turn conversational history with recency + vector similarity recall over session turns | `sessions` + `session_turns` tables (`VECTOR(1024)` with `vector_cosine_ops`) | ✅ Built (`sql/006_agent_memory.sql`) |
| **Semantic Memory** | Learned, reinforced license determinations & policy rulings | `license_determinations` with vector similarity; human corrections create `superseded_by` audit trails | ✅ Built (`sql/001`, `sql/005`) |
| **Episodic Memory** | Past AI Q&A answers, exact document snippets, and immutable attribution receipts | `answers` + `answer_attributions` written in single atomic SQL transactions | ✅ Built (`sql/001`) |
| **Temporal Memory** | Bitemporal dataset state rewindable to any point-in-time | MVCC `AS OF SYSTEM TIME` queries cross-checked against application bitemporal timestamps (`admitted_at` / `removed_at`) | ✅ Built (`sql/001`, `sql/002`) |
| **Task State Memory** | Multi-step agentic workflow progression with step-level persistence & crash resumption | `agent_tasks` table storing step state, payload, and structured results with indexed resume queries | ✅ Built (`sql/007_task_state.sql`) |

> **The CockroachDB Advantage:** The user query, agent response turn, generated answer, and document attributions commit **atomically in one database transaction**. A conversational turn and its receipts cannot diverge or suffer partial writes.

---

## ⚡ Key Technical Features & Provenance Guarantees

- **Agentic Working Memory Loop (`src/origin/agent.py`)**: `recall_working`, `recall_semantic`, `recall_episodic`, and `recall_temporal` feed context into every response. Follow-on queries resolve seamlessly against past session turns.
- **Resumable Multi-Step Task State**: Long-running agent tasks (such as `corpus_audit`) persist progress at each step boundary in CockroachDB and resume seamlessly upon failure.
- **Bouncer at the Door**: Non-commercial or restricted documents entering a commercial corpus **block the build** before index creation and quote the violating license clause.
- **Bitemporal & MVCC Time Travel**: `"What was in the corpus at 14:22 on July 3?"` is answered via native MVCC snapshot reads (`AS OF SYSTEM TIME`).
- **Blast-Radius Takedown Audit**: When a document is removed via takedown, ORIGIN identifies every past answer that relied on it and soft-deletes access immediately.
- **One-Command Disclosure (`origin article53`)**: Emits the regulator-facing training-content summary — every source, verbatim licence string, refused build and the clause quoted — **for the corpus as it stood at any past instant**. It reports which path answered: inside the MVCC window the figure is read from storage history application code cannot forge; outside it the same command says **"Asserted, not verifiable"** and exits `1`. It also renders the nine fields it *cannot* populate. See [`docs/COMPLIANCE.md`](docs/COMPLIANCE.md).
- **EU AI Act & Regulatory Compliance Mapping**: Comprehensive mapping to EU AI Act GPAI obligations (Article 53), automated logging (Article 12), and transparency (Article 13). Full analysis in [`docs/COMPLIANCE.md`](docs/COMPLIANCE.md).
- **Resilience Under Failure**: Built-in `origin chaos ingest` CLI tool demonstrates that database network drops mid-ingestion trigger complete transaction rollbacks with 0 partial records admitted.

---

## 🛠️ Required Technologies & Tools

### CockroachDB Tools: What the Agent & Engine Actually Did

| Tool | Status | What the Agent & Engine Did |
|---|---|---|
| **Distributed Vector Indexing** | ✅ | Recalls working memory turns (`session_turns.embedding`), semantic policy rulings (`license_determinations.embedding`), and corpus documents (`documents.embedding`) using cosine similarity (`<=>`) accelerated by explicit `vector_cosine_ops` indexes. |
| **Cloud Managed MCP Server** | ✅ | Connected via `.agents/mcp_config.json` (`https://cockroachlabs.cloud/mcp`) enabling development agents to query cluster metadata, inspect live tables, and verify vector index state on CockroachDB Cloud. |
| **ccloud CLI & Control Plane** | ✅ | Integrated at runtime via `/api/v1/cluster` to inspect live cluster topology, gateway regions, table range distribution, and zone configurations (`SHOW ZONE CONFIGURATION`) on v26.2.5. |
| **CockroachDB Agent Skills** | ✅ | Applied architectural and schema patterns (transaction retry hoisting, bitemporal modeling, explicit opclass indexing) vendored across 6 active domain packages (34 executable skills) in `.claude/skills/` with Apache-2.0 notice. |

#### 🔍 Vector Index Opclass Discovery
During development on a live CockroachDB Cloud cluster (v26.2.5), we discovered that `CREATE VECTOR INDEX` without an explicit operator class defaults to **`vector_l2_ops`** (L2 distance). Queries performing cosine similarity (`<=>`) bypassed the index completely! `sql/005_vector_opclass.sql` recreates the indexes using **`vector_cosine_ops`**, restoring hardware-accelerated vector search.

### AWS Services Integrated

- **AWS S3**: Document storage (`origin-provenance-248557779236` bucket in `eu-central-1`).
- **AWS Lambda & API Gateway**: Deployed serverless API endpoint supporting public demo execution (`https://lg7mjxz6m2.execute-api.eu-central-1.amazonaws.com`). Deploy-ready container image (`Dockerfile.lambda` verified with Mangum ASGI handler). Runbook in [`docs/DEPLOY.md`](docs/DEPLOY.md).
- **Amazon SageMaker**: Drop-in provider (`src/origin/providers/sagemaker.py`) supporting real-time text-generation model endpoints.
- **Amazon Bedrock**: Implemented in `src/origin/providers/bedrock.py` for classifying novel license texts via Amazon Titan/Claude embeddings. *(Note: Codebase includes automated fallback to local embeddings when AWS account model quotas or SCP policies are restricted)*.

---

## 🏗️ Architecture

```
  User / Agent Prompt            Agentic Memory Layer (CockroachDB)               Downstream Provenance
  ───────────────────            ──────────────────────────────────               ─────────────────────
  POST /api/v1/sessions   ──►  Working Memory  (`sessions`, `session_turns`)  ──┐
                               Semantic Memory (`license_determinations`)      ├──►  DataHub Lineage
  Follow-on query         ──►  Episodic Memory (`answers`, `attributions`)       │     S3 Document Storage
                               Temporal Memory (`AS OF SYSTEM TIME` / MVCC)    ──┘
```

---

## 📊 Observability, Benchmarks & Resilience

ORIGIN surfaces real-time metrics via `GET /api/v1/metrics` and the interactive web dashboard:
- **Memory Hit Rate (93.3%)**: Measured on live cluster—93.3% of license determinations and queries are resolved directly from memory without invoking external models.
- **Measured Live Latency** — reproduce with [`deploy/benchmark.py`](deploy/benchmark.py):

  ```bash
  python deploy/benchmark.py --n 40                    # sequential, warm
  python deploy/benchmark.py --n 60 --concurrency 8    # concurrent
  ```

  | | min | p50 | p90 | p95 | p99 |
  |---|---|---|---|---|---|
  | sequential, warm (n=40) | 142 ms | **172 ms** | 188 ms | 197 ms | 199 ms |
  | concurrency 8 (n=60) | 140 ms | 189 ms | **1184 ms** | 1328 ms | 1373 ms |

  End-to-end client-observed, AWS Lambda + API Gateway → CockroachDB Cloud
  (`eu-central-1`), zero failures in both runs. Add ~30–40 ms if you measure from
  outside Europe — these include the client round trip.

  **The tail under concurrency is Lambda, not CockroachDB.** Sequential p95 is
  197 ms; at concurrency 8 the p90 is 1184 ms because Lambda cold-starts additional
  containers to absorb parallel requests, and this image is ~800 MB. The database
  is not the bottleneck — p50 barely moves (172 → 189 ms). The fix is provisioned
  concurrency, which costs money this deployment does not spend.

  Cold start is reported **separately** (`--include-cold`) rather than blended into
  the percentiles: a single cold sample in a 20-request run moves p95 by 3–4x and
  produces a figure describing the container runtime rather than the application.
- **Single-Transaction Atomic Integrity**: 100% atomic commit enforcement on session turns, generated answers, and attributions using `db.run_in_transaction` with automatic retry on CockroachDB serialization conflicts (`40001`).
- **Deploy Verification in CI**: Automated GitHub Actions workflow (`deploy-smoke.yml`) continuously probes the live AWS API Gateway endpoints to verify health, schema, and memory hit rate integrity.
- **Takedown & Impact Auditing**: Real-time blast radius accounting identifying all past answers affected by removed documents.

---

## 📑 Empirical Research Papers, Benchmarks & Security Artifacts

ORIGIN includes fully reproducible empirical studies, ablation benchmarks, and upstream contributions:

| Artifact | Purpose & Headline Finding | Link |
|---|---|---|
| **10k Dataset Study** | Empirical analysis of the 10,000 most-downloaded HuggingFace datasets. **62.9% strict refusal rate**, **46.5% unlicensed**, and **395 (4.0%) metadata conflicts** between cards and tags. Reproducible from committed projection. | [`docs/FINDINGS.md`](docs/FINDINGS.md) |
| **Agentic Memory Ablation** | Multi-turn paired conversational benchmark comparing memory-enabled (Arm A) vs memoryless (Arm B) execution across 20 test cases (**62.4% vs 30.8% mean attribution score**, **+102.4% net memory lift**). | [`docs/ABLATION.md`](docs/ABLATION.md) |
| **Substrate Benchmarks** | Query plan analysis on CockroachDB v26.2.5 (`vector_cosine_ops` operator class resolution) and concurrency load sweeps across concurrencies `[1, 2, 4, 8, 16, 32]`. | [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md) |
| **Security & Threat Model** | Production threat model covering malicious dataset metadata poisoning, write token compromise, and honest boundaries against hostile cluster operators. | [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) |
| **Upstream Contribution** | Contributed AI governance and provenance skill for [`cockroachdb-skills`](.agents/skills/cockroachdb-security-and-governance/governing-ai-provenance-and-licensing/SKILL.md) and CockroachDB Cloud pgvector `vector_cosine_ops` defect report. | [`docs/UPSTREAM_PR.md`](docs/UPSTREAM_PR.md) |

---

## 🔬 Honest Engineering Findings & MVCC Horizon

- **MVCC Garbage Collection Horizon**: On CockroachDB Cloud v26.2.5, configured `gc.ttlseconds = 604800` (7 days) applies to table data, but system ranges retain shorter TTLs (~4-5 hours). Beyond this horizon, `AS OF SYSTEM TIME` reads gracefully degrade to the bitemporal application timestamp path (`admitted_at` / `removed_at`).
- **Schema Rewind**: MVCC rewinds database catalog descriptors. Querying an instant before schema creation raises `TimeTravelBeforeSchema` (`database "origin" does not exist`), which accurately reflects past reality.

---

## 📜 Prior-Work & Dual Submission Disclosure

> ORIGIN was built between Aug 5–17, 2026, entirely within this hackathon's submission period (June 30 – Aug 18, 2026). The same codebase was submitted to the DataHub AI hackathon on Aug 10. No pre-existing code was incorporated. The CockroachDB agent-memory layer (`sessions`, `session_turns`, `agent.py`) and the AWS deployment were built after that date, for this submission.

---

## 🚀 Quickstart & Local Setup

### 1. Installation
```bash
python3.12 -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
cp .env.example .env  # Add your CockroachDB DATABASE_URL
```

### 2. Run Database Migrations
```bash
.venv/Scripts/python -m origin.cli migrate
```

### 3. Run Test Suite (302 Passing Tests)
```bash
.venv/Scripts/python -m pytest -v
```

### 4. Generate the Disclosure
```bash
.venv/Scripts/python -m origin.cli article53 --corpus hub-commercial
.venv/Scripts/python -m origin.cli article53 --corpus hub-commercial --at=-2h
```
Same corpus, two instants. Compare the **Evidentiary basis** table in each: the
report names which path answered, and says so when it cannot stand behind the
figure.

### 5. Start Interactive Web Dashboard & API
```bash
.venv/Scripts/python -m origin.cli serve --port 8000
```
Open `http://localhost:8000` to interact with the provenance engine, test agent session turns, and inspect live memory hit rates!

---

## 📄 License

MIT — see [LICENSE](LICENSE).
