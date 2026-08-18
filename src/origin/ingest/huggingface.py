"""Ingest dataset cards from the HuggingFace Hub.

Chosen as the primary source because its licence metadata is *authentically*
messy, which is the whole point. Across the Hub you will find, for the same
licence: ``mit``, ``MIT``, ``license:mit`` in tags, ``other``, ``unknown``,
a list of two licences, a licence declared in ``cardData`` but contradicted by
tags, and thousands of datasets with no licence field at all.

Nobody has to invent a test case. The pathology is real, dated, and public.

Public API, no authentication, no key. See
https://huggingface.co/docs/hub/api
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger(__name__)

API_ROOT = "https://huggingface.co/api"
SOURCE_SYSTEM = "huggingface"

# The Hub is generous but this is a public unauthenticated endpoint; do not
# hammer it.
DEFAULT_TIMEOUT = 30.0


@dataclass(frozen=True)
class DatasetRecord:
    doc_id: str
    source_uri: str
    title: str
    #: Verbatim licence text as the Hub reports it, never normalised here.
    #: Normalisation is the ledger's job and it keeps the original for audit.
    license_raw: str | None
    content: str
    downloads: int
    #: True when cardData and tags disagree about the licence. Recorded because
    #: a contradictory declaration is materially worse than a missing one — it
    #: looks authoritative and is not.
    license_conflict: bool


def _as_license_string(value: Any) -> str | None:
    """Coerce the several shapes ``cardData.license`` arrives in."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (list, tuple)):
        parts = [str(v).strip() for v in value if str(v).strip()]
        if not parts:
            return None
        # Multiple declared licences are preserved as-is. Picking one here would
        # be a silent legal judgement made by a parser.
        return ", ".join(parts)
    return str(value).strip() or None


def license_from_tags(tags: Any) -> str | None:
    """Pull the ``license:...`` tag, which is often the only licence signal."""
    if not isinstance(tags, (list, tuple)):
        return None
    found = [
        str(t).split(":", 1)[1].strip()
        for t in tags
        if isinstance(t, str) and t.startswith("license:")
    ]
    found = [f for f in found if f]
    if not found:
        return None
    return ", ".join(found)


def extract_license(raw: dict) -> tuple[str | None, bool]:
    """Determine the licence string and whether the sources disagree.

    ``cardData.license`` is preferred over tags when both exist, because the
    card is author-declared while tags are frequently auto-derived. But a
    disagreement is reported rather than resolved: the ledger records both the
    winner and the fact that they conflicted.
    """
    card = raw.get("cardData") or {}
    if not isinstance(card, dict):
        card = {}

    from_card = _as_license_string(card.get("license"))
    from_tags = license_from_tags(raw.get("tags"))

    if from_card and from_tags:
        conflict = _comparable(from_card) != _comparable(from_tags)
        return from_card, conflict

    return (from_card or from_tags), False


def _comparable(value: str) -> str:
    """Fold cosmetic difference so `MIT` and `mit` are not reported as a conflict."""
    return "".join(ch for ch in value.lower() if ch.isalnum())


def parse_dataset(raw: dict) -> DatasetRecord | None:
    """Convert one API item into a record, or None if it is unusable.

    Returns None rather than raising: a single malformed item must not abort an
    ingestion run of several hundred.
    """
    dataset_id = raw.get("id") or raw.get("_id")
    if not dataset_id or not isinstance(dataset_id, str):
        log.warning("skipping item with no usable id: %r", raw.get("_id"))
        return None

    license_raw, conflict = extract_license(raw)

    description = raw.get("description") or ""
    if not isinstance(description, str):
        description = str(description)

    # The dataset card is the document. A corpus of dataset documentation is a
    # realistic RAG target and it carries the licence we actually care about.
    body_parts = [f"# {dataset_id}"]
    if description.strip():
        body_parts.append(description.strip())
    tags = raw.get("tags")
    if isinstance(tags, (list, tuple)) and tags:
        body_parts.append("Tags: " + ", ".join(str(t) for t in tags))
    content = "\n\n".join(body_parts)

    downloads = raw.get("downloads")
    if not isinstance(downloads, int):
        downloads = 0

    return DatasetRecord(
        doc_id=f"hf:{dataset_id}",
        source_uri=f"https://huggingface.co/datasets/{dataset_id}",
        title=dataset_id,
        license_raw=license_raw,
        content=content,
        downloads=downloads,
        license_conflict=conflict,
    )


def fetch_datasets(
    *,
    limit: int = 50,
    sort: str = "downloads",
    search: str | None = None,
    client: httpx.Client | None = None,
) -> list[dict]:
    """Fetch raw dataset metadata from the Hub.

    ``full=true`` is required — without it ``cardData`` is omitted and every
    dataset appears to have no licence, which would make ORIGIN look like it
    was failing when in fact the request was wrong.
    """
    params: dict[str, Any] = {
        "limit": limit,
        "full": "true",
        "sort": sort,
        "direction": -1,
    }
    if search:
        params["search"] = search

    owns_client = client is None
    http = client or httpx.Client(timeout=DEFAULT_TIMEOUT)
    try:
        response = http.get(f"{API_ROOT}/datasets", params=params)
        response.raise_for_status()
        payload = response.json()
    finally:
        if owns_client:
            http.close()

    if not isinstance(payload, list):
        raise RuntimeError(
            f"expected a JSON array from the Hub, got {type(payload).__name__}"
        )
    return payload


def parse_all(payload: list[dict]) -> list[DatasetRecord]:
    """Parse a payload, dropping unusable items."""
    records = [parse_dataset(item) for item in payload]
    kept = [r for r in records if r is not None]
    dropped = len(records) - len(kept)
    if dropped:
        log.info("dropped %d unusable item(s) of %d", dropped, len(records))
    return kept


def license_distribution(records: list[DatasetRecord]) -> dict[str, int]:
    """Count raw licence strings — useful for showing the mess is real.

    Worth printing during a demo: it is evidence that the licence problem was
    not manufactured for the occasion.
    """
    counts: dict[str, int] = {}
    for record in records:
        key = record.license_raw or "(none declared)"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
