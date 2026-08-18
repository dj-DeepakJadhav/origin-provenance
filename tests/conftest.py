"""Test configuration.

Unit tests run with no cluster, no DataHub, no AWS. Tests that genuinely need
infrastructure are marked and skipped when it is absent, so a red test always
means a real defect rather than a missing environment.
"""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items):
    del config  # unused
    no_cluster = not os.getenv("DATABASE_URL")
    no_datahub = not os.getenv("DATAHUB_GMS_URL")

    skip_cluster = pytest.mark.skip(reason="DATABASE_URL not set")
    skip_datahub = pytest.mark.skip(reason="DATAHUB_GMS_URL not set")

    for item in items:
        if no_cluster and "needs_cluster" in item.keywords:
            item.add_marker(skip_cluster)
        if no_datahub and "needs_datahub" in item.keywords:
            item.add_marker(skip_datahub)
