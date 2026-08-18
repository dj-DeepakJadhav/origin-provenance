"""Unit tests for the 10,000 dataset scale licensing study."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from origin import findings


@pytest.fixture
def sample_raw_datasets():
    return [
        {
            "id": "org/permissive-mit",
            "description": "Permissive dataset with MIT",
            "tags": ["license:mit", "nlp"],
            "cardData": {"license": "mit"},
            "downloads": 50000,
        },
        {
            "id": "org/non-commercial-data",
            "description": "Academic research only",
            "tags": ["license:cc-by-nc-4.0"],
            "cardData": {"license": "cc-by-nc-4.0"},
            "downloads": 40000,
        },
        {
            "id": "org/copyleft-gpl",
            "description": "GPL licensed code",
            "tags": ["license:gpl-3.0"],
            "cardData": {"license": "gpl-3.0"},
            "downloads": 30000,
        },
        {
            "id": "org/conflict-dataset",
            "description": "Tags say MIT but cardData says CC-BY-NC",
            "tags": ["license:mit"],
            "cardData": {"license": "cc-by-nc-4.0"},
            "downloads": 20000,
        },
        {
            "id": "org/unlicensed-data",
            "description": "No license tags at all",
            "tags": ["audio"],
            "cardData": {},
            "downloads": 10000,
        },
    ]


def test_analyze_dataset_records(sample_raw_datasets):
    report = findings.analyze_dataset_records(sample_raw_datasets)
    assert report.total_datasets_analyzed == 5
    assert report.overall_counts.permissive == 1
    assert report.overall_counts.non_commercial == 2  # including conflict dataset where cardData is cc-by-nc
    assert report.overall_counts.copyleft == 1
    assert report.overall_counts.unlicensed_none == 1
    assert report.conflict_count == 1
    assert report.conflict_pct == 20.0

    md = findings.generate_findings_markdown(report)
    assert "# AI Training Corpus Licensing Contamination at Scale" in md
    assert "Headline Finding" in md
    assert "Decile Analysis" in md


def test_analyze_projection_csv(tmp_path):
    # Test on full committed projection
    committed_path = findings.DEFAULT_PROJECTION_PATH
    assert committed_path.exists()

    report = findings.analyze_projection_csv(committed_path)
    assert report.total_datasets_analyzed == 10000
    assert report.overall_counts.permissive == 3708
    assert report.overall_counts.unlicensed_none == 4648
    assert pytest.approx(report.overall_counts.commercial_refusal_rate_strict, abs=0.1) == 62.9

    # Verify that testing did NOT truncate the file
    with open(committed_path, "r", encoding="utf-8") as f:
        line_count = len(f.readlines())
    assert line_count == 10001
