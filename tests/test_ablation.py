"""Unit tests for the memory ablation evaluation harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from origin import ablation, agent, corpus, db


@pytest.fixture
def test_corpus():
    """Ensure a distinct test corpus exists in DB."""
    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO corpora (corpus_id, name, declared_use)
            VALUES (gen_random_uuid(), 'test-ablation-suite-corpus', 'commercial')
            ON CONFLICT DO NOTHING
            RETURNING corpus_id
            """
        )
        row = cur.fetchone()
        if row:
            cid = str(row["corpus_id"])
        else:
            cur.execute("SELECT corpus_id FROM corpora LIMIT 1")
            cid = str(cur.fetchone()["corpus_id"])
    return cid


@pytest.fixture
def sample_suite_file(tmp_path):
    suite = {
        "version": "1.0",
        "cases": [
            {
                "id": "test-case-1",
                "turns": [
                    "What is the dataset license?",
                    "Can it be used commercially?"
                ],
                "expected_keywords": ["permissive", "mit", "commercial"],
                "rationale": "'it' refers to the dataset in turn 1"
            },
            {
                "id": "test-case-2",
                "turns": [
                    "List the clinical datasets.",
                    "Which of those are HIPAA compliant?"
                ],
                "expected_keywords": ["clinical", "hipaa", "compliant"],
                "rationale": "'those' refers to the clinical datasets in turn 1"
            }
        ]
    }
    path = tmp_path / "test_suite.json"
    path.write_text(json.dumps(suite), encoding="utf-8")
    return path


def test_load_ablation_suite(sample_suite_file):
    cases = ablation.load_ablation_suite(sample_suite_file)
    assert len(cases) == 2
    assert cases[0]["id"] == "test-case-1"
    assert len(cases[0]["turns"]) == 2


def test_default_ablation_suite_has_20_cases():
    cases = ablation.load_ablation_suite()
    assert len(cases) >= 20
    for case in cases:
        assert "id" in case
        assert len(case["turns"]) == 2
        assert "rationale" in case
        assert "expected_keywords" in case


def test_run_ablation_benchmark(test_corpus, sample_suite_file):
    summary = ablation.run_ablation_benchmark(test_corpus, suite_path=sample_suite_file)
    assert summary.corpus_id == test_corpus
    assert summary.total_cases == 2
    assert len(summary.case_results) == 2
    
    # Arm A had memory enabled, Arm B had memory disabled
    for r in summary.case_results:
        assert r.arm_b_recalled_turns == 0

    md = ablation.format_ablation_markdown(summary)
    assert "# ORIGIN Agentic Memory Ablation Report" in md
    assert "Executive Summary" in md
    assert "test-case-1" in md
