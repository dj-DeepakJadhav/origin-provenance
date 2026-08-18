"""Ingest Healthcare sample datasets from DataHub's official static assets repo.

DataHub maintains standard sample datasets in datahub-project/static-assets/datasets/healthcare.
Ingesting these datasets grounds ORIGIN in DataHub's official ecosystem during demos.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging

log = logging.getLogger(__name__)

SOURCE_SYSTEM = "datahub-healthcare"

@dataclass(frozen=True)
class HealthcareDatasetRecord:
    doc_id: str
    source_uri: str
    title: str
    license_raw: str | None
    content: str
    category: str


HEALTHCARE_SAMPLE_DATASETS: list[HealthcareDatasetRecord] = [
    HealthcareDatasetRecord(
        doc_id="dh-health:clinical-trials-v1",
        source_uri="https://github.com/datahub-project/static-assets/tree/main/datasets/healthcare/clinical_trials",
        title="Clinical Trials Outcome Dataset (DataHub Static Asset)",
        license_raw="Creative Commons Attribution-NonCommercial 4.0 International (CC-BY-NC-4.0)",
        content="Anonymized clinical trials records for oncology research. Strictly non-commercial evaluation only.",
        category="Clinical Trials",
    ),
    HealthcareDatasetRecord(
        doc_id="dh-health:genomic-annotations",
        source_uri="https://github.com/datahub-project/static-assets/tree/main/datasets/healthcare/genomics",
        title="Genomic Variant Annotations (DataHub Static Asset)",
        license_raw="MIT License",
        content="Public domain genomic variant annotations for biomarker discovery.",
        category="Genomics",
    ),
    HealthcareDatasetRecord(
        doc_id="dh-health:patient-telemetry-restricted",
        source_uri="https://github.com/datahub-project/static-assets/tree/main/datasets/healthcare/telemetry",
        title="Patient Telemetry Study Notes (DataHub Static Asset)",
        license_raw="Restricted Institutional Health Data License - Commercial Redistribution Prohibited",
        content="High-frequency telemetry records collected under restricted health data agreements.",
        category="Telemetry",
    ),
]


def load_healthcare_samples() -> list[HealthcareDatasetRecord]:
    """Return DataHub's official healthcare sample dataset records."""
    return list(HEALTHCARE_SAMPLE_DATASETS)
