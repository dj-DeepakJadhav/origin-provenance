# ORIGIN Agentic Memory Ablation Report

**Run Timestamp:** 2026-08-18T17:19:12.997357+00:00  
**Corpus ID:** `455e593a-9395-4a1d-930f-ab6d8a348f07`  
**Evaluation Suite:** [`data/ablation_suite.json`](file:///c:/DeepakJadhav/Personal/CockroachDB_AWS%20Hackathon/origin/data/ablation_suite.json)  
**Total Multi-Turn Cases Evaluated:** 20

---

## Executive Summary

| Metric | Arm A (Memory Enabled) | Arm B (Memoryless) | Net Lift / Advantage |
|---|---|---|---|
| **Mean Attribution Score** | **62.4%** | **30.8%** | **+102.4%** |
| **Grounded Cases (Score > 0)** | 20 / 20 (100%) | 18 / 20 (90%) | **+2 cases** |

---

## Detailed Case Breakdown

| Case ID | Turn 2 Query | Arm A (Recalled / Score) | Arm B (Recalled / Score) | Score Delta |
|---|---|---|---|---|
| `followon-clinical-noncommercial` | *Which of those are non-commercial?* | 2 turns / 80% | 0 turns / 0% | **+80.0%** |
| `followon-robotics-permissive` | *What are the license classes for those?* | 2 turns / 33% | 0 turns / 17% | **+16.7%** |
| `pronoun-the-second-one-license` | *Can the second one be used in commercial products?* | 2 turns / 60% | 0 turns / 40% | **+20.0%** |
| `followon-eu-ai-act-status` | *Why did it receive that compliance rating?* | 2 turns / 40% | 0 turns / 20% | **+20.0%** |
| `pronoun-its-training-split` | *What is its cryptographic content hash?* | 2 turns / 50% | 0 turns / 25% | **+25.0%** |
| `followon-healthcare-hipaa-obligation` | *What governance obligations apply to them?* | 2 turns / 80% | 0 turns / 40% | **+40.0%** |
| `pronoun-which-subset-is-cc-by` | *Which of them are licensed under Creative Commons?* | 2 turns / 75% | 0 turns / 50% | **+25.0%** |
| `followon-finance-takedown-history` | *What was the blast radius of that notice?* | 2 turns / 60% | 0 turns / 20% | **+40.0%** |
| `pronoun-who-created-them` | *Who admitted them into the ledger?* | 2 turns / 60% | 0 turns / 40% | **+20.0%** |
| `followon-multilingual-permissive-only` | *Are any of those copyleft?* | 2 turns / 50% | 0 turns / 25% | **+25.0%** |
| `pronoun-their-commercial-viability` | *Are they permissible for commercial GPAI pre-training?* | 2 turns / 100% | 0 turns / 80% | **+20.0%** |
| `followon-carddata-tag-conflict` | *How did the licensing gate resolve that conflict?* | 2 turns / 80% | 0 turns / 40% | **+40.0%** |
| `pronoun-the-first-dataset-hash` | *Verify the cryptographic receipt of the first one.* | 2 turns / 40% | 0 turns / 20% | **+20.0%** |
| `followon-copyleft-viral-reach` | *What downstream risks do they present to our model weights?* | 2 turns / 20% | 0 turns / 20% | **0.0%** |
| `pronoun-its-citation-requirements` | *What attribution must we include when citing it?* | 2 turns / 80% | 0 turns / 20% | **+60.0%** |
| `followon-synthetic-data-status` | *What provenance guarantees exist for their generation prompts?* | 2 turns / 80% | 0 turns / 60% | **+20.0%** |
| `pronoun-can-we-train-on-those` | *Can we train on those under EU law?* | 2 turns / 80% | 0 turns / 0% | **+80.0%** |
| `followon-opt-out-reservation` | *Were they quarantined or admitted?* | 2 turns / 40% | 0 turns / 20% | **+20.0%** |
| `pronoun-the-excluded-subset-rationale` | *Explain the legal rationale for the third violation.* | 2 turns / 80% | 0 turns / 40% | **+40.0%** |
| `followon-model-card-governance` | *Does it include the full list of content hashes?* | 2 turns / 60% | 0 turns / 40% | **+20.0%** |

---

## Methodology & Scoring Rigor
1. **Exact Seam Control**: Arm A and Arm B use the identical retrieval algorithm, CockroachDB transaction logic, and embedding provider.
2. **Ablation Kill-Switch**: In Arm B, `memory_enabled=False` disables working memory, semantic ruling recall, and episodic past retrieval.
3. **Explicit Search Space Scoping**: Scoring is evaluated strictly against the generated answer text and returned document citations (`doc_id` / `title`), excluding raw retrieved document snippet objects from the explicit evaluation space.
4. **Extractive Mode Nuance**: In extractive fallback mode (`extractive=True` without a generative LLM in the loop), answer text is assembled from retrieved snippets. The snippet exclusion in the harness ensures clean metadata boundaries, and will actively enforce generative separation when an external LLM (e.g. SageMaker / Bedrock) is plugged in.
5. **Methodology Classification**: Option A+ (keyword presence in answer text and document metadata against hand-authored expectation sets across 20 multi-turn paired cases).