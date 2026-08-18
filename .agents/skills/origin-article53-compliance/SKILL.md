---
name: origin-article53-compliance
description: Use when verifying, auditing, or generating EU AI Act Article 53 compliance reports, technical documentation, training data summaries, copyright opt-out verification, and Model Card receipts for GPAI models in ORIGIN.
---

# ORIGIN EU AI Act Article 53 Compliance Skill

This skill provides workflows and reference commands for verifying and generating EU AI Act Article 53 GPAI (General Purpose AI) compliance artifacts using the ORIGIN compliance engine.

## Key Compliance Requirements (Article 53)

1. **Article 53(1)(a)**: Technical Documentation (Data provenance, training architecture, licensing distribution).
2. **Article 53(1)(b)**: Downstream AI Provider Information (Model Cards, ingestion cut-offs, copyright status).
3. **Article 53(1)(c)**: Copyright Opt-Out Policy (Directive 2019/790 DSM compliance, opt-out enforcement).
4. **Article 53(1)(d)**: Public Summary of Training Content (AI Office standardized template with dataset provenance).

## Common CLI Commands

```bash
# Run complete Article 53 verification
origin article53 verify --corpus-id <CORPUS_UUID>

# Export public summary of training content (JSON)
origin article53 export-summary --corpus-id <CORPUS_UUID> --output summary.json

# Generate comprehensive regulatory audit package (JSON & Markdown)
origin article53 audit-pack --corpus-id <CORPUS_UUID> --output-dir ./compliance-pack
```

## Python API Usage

```python
from origin.article53 import (
    Article53Auditor,
    generate_model_card_for_corpus,
    generate_training_data_summary,
    verify_corpus_compliance,
)

# Run verification on a corpus
report = verify_corpus_compliance(corpus_id=corpus_uuid)
if report.overall_status == "COMPLIANT":
    print(f"Compliance Score: {report.compliance_score * 100:.1f}%")
```
