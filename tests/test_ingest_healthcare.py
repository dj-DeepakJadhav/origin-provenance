"""Unit tests for DataHub healthcare static asset dataset ingestion."""

from __future__ import annotations

from origin.ingest import healthcare_sample as hs
from origin.licensing import policy
from origin.providers.local import classify_license_text


def test_load_healthcare_samples_returns_records():
    records = hs.load_healthcare_samples()
    assert len(records) >= 3
    assert any("clinical-trials" in r.doc_id for r in records)


def test_healthcare_noncommercial_license_is_blocked_for_commercial_corpus():
    records = hs.load_healthcare_samples()
    clinical_trials = next(r for r in records if "clinical-trials" in r.doc_id)
    
    verdict, _ = classify_license_text(clinical_trials.license_raw)
    assert verdict == "NONCOMMERCIAL"
    
    ruling = policy.evaluate(verdict, declared_use="commercial")
    assert ruling.blocks_build is True
