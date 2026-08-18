"""Unit tests for runtime substrate inspection."""

from __future__ import annotations

import pytest

from origin import agent, db, ops


def test_inspect_substrate():
    report = ops.inspect_substrate()
    assert report.timestamp is not None
    assert len(report.cluster_tables_checked) > 0
    assert "corpora" in report.cluster_tables_checked
    assert "documents" in report.cluster_tables_checked
    assert report.total_admitted_documents >= 0
    assert report.total_answers_recorded >= 0
    assert len(report.findings) > 0
