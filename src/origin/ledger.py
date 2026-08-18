"""The provenance ledger: admitting documents, and remembering licence rulings.

Two things here are the product.

**Admission is atomic.** A document's bytes, its hash, its licence
determination, and its corpus membership all commit in one transaction, stamped
with the cluster's own logical timestamp. There is no window in which a document
is half-admitted, and no possibility of a membership row whose provenance is
missing. That atomicity is what makes the ledger evidence rather than a log.

**Licence rulings are remembered, not recomputed.** Real licence fields are free
text and endlessly various. Classifying the same string twice and getting two
answers is how unlicensed material ends up in a shipped product. So every ruling
is persisted and vector-indexed: an exact string match short-circuits, a near
match reuses the prior ruling and reinforces it, and only genuinely novel strings
reach a model. Human corrections supersede rather than overwrite, so the audit
trail survives the correction.

``license_raw`` is stored beside the derived ``license_class`` and never
normalised in place, because EU AI Act **Art 53(1)(c)** compliance is judged on
the terms the rightsholder actually expressed, not on our reading of them. The
derived class is how the machine enforces; the verbatim string is what a human
reviewer — or a rightsholder disputing a ruling — has to be able to see.
See docs/COMPLIANCE.md.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass

import psycopg

from . import db
from .providers import Provider, get_provider
from .providers.local import classify_license_text
from .storage import get_store

log = logging.getLogger(__name__)

#: Cosine distance below which a remembered ruling is reused verbatim.
#: 0.15 distance == 0.85 similarity, which is the threshold the local provider's
#: cosmetic-variant behaviour is tested against in tests/test_providers.py.
REUSE_DISTANCE_THRESHOLD = 0.15

#: How much a reused ruling gains in strength. Rulings that keep proving useful
#: outrank one-off guesses when several near matches compete.
REINFORCEMENT = 0.1


@dataclass(frozen=True)
class Determination:
    license_class: str
    rationale: str
    decided_by: str
    confidence: float
    #: True when this came from memory rather than a fresh classification. The
    #: demo surfaces this — it is the visible proof the memory is doing work.
    from_memory: bool


@dataclass(frozen=True)
class AdmissionResult:
    doc_id: str
    content_hash: str
    stored_uri: str
    determination: Determination
    admitted_txn: str
    #: False when the document was already present with identical content.
    #: Ingestion is re-run constantly; that is not an error.
    newly_admitted: bool
    #: True when an existing document was missing its embedding and got one.
    #: Surfaced so a repair run reports what it repaired instead of looking
    #: indistinguishable from a no-op.
    embedding_backfilled: bool = False
    #: True when admission was refused because the document has been taken down.
    #: Loud rather than silent: a scheduled ingest that quietly skips a withdrawn
    #: document is correct, but an operator still needs to know it happened.
    refused_takedown: bool = False


#: How much of a document is embedded. Enough to characterise it without paying
#: to embed a multi-megabyte file; dataset cards are far shorter than this
#: anyway, so it only bites on unusually large documents.
EMBEDDING_CHARS = 4000


def _embedding_text(title: str | None, doc_id: str, content: bytes) -> str:
    """Build the text that represents a document in vector space.

    The title is included and placed first because it carries disproportionate
    signal for short documents, and because a document whose body fails to decode
    still deserves to be retrievable by name.
    """
    try:
        body = content.decode("utf-8", errors="replace")
    except Exception:  # pragma: no cover - decode with errors= does not raise
        body = ""
    head = title or doc_id
    return f"{head}\n\n{body[:EMBEDDING_CHARS]}"


def content_hash(data: bytes) -> str:
    """SHA-256 of the raw bytes.

    Recorded at admission so silent mutation of a source document is detectable
    later. A document whose bytes no longer hash to the recorded value is not the
    document we ruled on.
    """
    return hashlib.sha256(data).hexdigest()


def _parse_classification(text: str) -> tuple[str, str]:
    """Read a provider's classification response.

    Providers are asked for JSON. A model that returns prose instead must not be
    coerced into a permissive answer, so anything unparseable becomes UNKNOWN —
    which the policy layer treats as restrictive.
    """
    try:
        payload = json.loads(text)
        verdict = str(payload["class"]).strip().upper()
        rationale = str(payload.get("rationale", "")).strip()
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        log.warning("unparseable classification response, failing closed: %r", text)
        return "UNKNOWN", "classifier response could not be parsed"

    if not verdict:
        return "UNKNOWN", "classifier returned an empty class"
    return verdict, rationale or "no rationale supplied"


def classify_license(
    cur: psycopg.Cursor,
    license_raw: str | None,
    *,
    provider: Provider | None = None,
) -> Determination:
    """Rule on a raw licence string, preferring memory over recomputation.

    Order of attempts, cheapest and most certain first:
      1. No licence text at all -> UNKNOWN, no memory write.
      2. Exact string match against a live prior ruling -> reuse, reinforce.
      3. Vector near-match within the threshold -> reuse, reinforce.
      4. Novel string -> ask the provider, persist the new ruling.
    """
    provider = provider or get_provider()
    raw = (license_raw or "").strip()

    if not raw:
        return Determination(
            license_class="UNKNOWN",
            rationale="no licence text present in source metadata",
            decided_by="policy:no-metadata",
            confidence=1.0,
            from_memory=False,
        )

    # 2. Exact match. Cheaper than embedding and not subject to a threshold.
    cur.execute(
        """
        SELECT determined_class, rationale, decided_by, strength
        FROM license_determinations
        WHERE license_raw = %s AND superseded_by IS NULL
        ORDER BY human_confirmed DESC, strength DESC
        LIMIT 1
        """,
        (raw,),
    )
    row = cur.fetchone()
    if row is not None:
        _reinforce(cur, license_raw=raw)
        return Determination(
            license_class=row["determined_class"],
            rationale=row["rationale"] or "",
            decided_by="memory:exact",
            confidence=1.0,
            from_memory=True,
        )

    embedding = provider.embed(raw)
    vector = db.vector_literal(embedding)

    # 3. Near match. Human-confirmed rulings win ties regardless of distance
    #    ordering, because a person looked at those.
    cur.execute(
        """
        SELECT determination_id,
               determined_class,
               rationale,
               human_confirmed,
               embedding <=> %s::VECTOR AS distance
        FROM license_determinations
        WHERE superseded_by IS NULL AND embedding IS NOT NULL
        ORDER BY distance ASC
        LIMIT 5
        """,
        (vector,),
    )
    candidates = cur.fetchall()
    within = [c for c in candidates if c["distance"] <= REUSE_DISTANCE_THRESHOLD]
    if within:
        best = sorted(
            within, key=lambda c: (not c["human_confirmed"], c["distance"])
        )[0]
        _reinforce(cur, determination_id=best["determination_id"])
        similarity = 1.0 - float(best["distance"])
        return Determination(
            license_class=best["determined_class"],
            rationale=best["rationale"] or "",
            decided_by="memory:similar",
            confidence=similarity,
            from_memory=True,
        )

    # 4. Novel. Ask the provider and remember what it said.
    completion = provider.complete(f"LICENCE_CLASSIFY: {raw}")
    verdict, rationale = _parse_classification(completion.text)

    cur.execute(
        """
        INSERT INTO license_determinations
            (license_raw, determined_class, rationale, decided_by,
             model_version, embedding)
        VALUES (%s, %s, %s, %s, %s, %s::VECTOR)
        """,
        (
            raw,
            verdict,
            rationale,
            f"model:{completion.model_version}",
            completion.model_version,
            vector,
        ),
    )

    return Determination(
        license_class=verdict,
        rationale=rationale,
        decided_by=f"model:{completion.model_version}",
        confidence=0.0 if verdict == "UNKNOWN" else 0.75,
        from_memory=False,
    )


def _reinforce(
    cur: psycopg.Cursor,
    *,
    determination_id: str | None = None,
    license_raw: str | None = None,
) -> None:
    """Strengthen a ruling that proved reusable."""
    if determination_id is not None:
        cur.execute(
            """
            UPDATE license_determinations
            SET strength = strength + %s
            WHERE determination_id = %s
            """,
            (REINFORCEMENT, determination_id),
        )
    elif license_raw is not None:
        cur.execute(
            """
            UPDATE license_determinations
            SET strength = strength + %s
            WHERE license_raw = %s AND superseded_by IS NULL
            """,
            (REINFORCEMENT, license_raw),
        )


def admit_document(
    *,
    corpus_id: str,
    doc_id: str,
    source_uri: str,
    source_system: str,
    content: bytes,
    title: str | None = None,
    license_raw: str | None = None,
    storage_key: str | None = None,
    provider: Provider | None = None,
    allow_readmission: bool = False,
) -> AdmissionResult:
    """Admit one document to a corpus, atomically and with full provenance.

    The bytes are stored first, deliberately: an orphaned blob is harmless, while
    a ledger row pointing at bytes that were never written is a broken audit
    trail. Everything after that — hash, licence ruling, document row, membership
    row, timestamp — commits or fails together.

    Refuses documents that have been taken down unless ``allow_readmission`` is
    set, so a scheduled ingest cannot undo a rights complaint.
    """
    digest = content_hash(content)
    store = get_store()
    key = storage_key or f"{source_system}/{doc_id}"

    with db.transaction() as cur:
        # A taken-down document must not be resurrected by the next scheduled
        # ingest. Without this check, `ingest` silently re-admits anything that
        # is still present at the source — so a nightly job would quietly undo
        # every rights complaint, and nobody would be told.
        #
        # Re-admission has to be a deliberate act, so it requires
        # allow_readmission=True.
        cur.execute(
            """
            SELECT takedown_id, requested_by, reason, requested_at
            FROM takedowns WHERE doc_id = %s
            ORDER BY requested_at DESC
            LIMIT 1
            """,
            (doc_id,),
        )
        takedown = cur.fetchone()

    if takedown is not None and not allow_readmission:
        log.warning(
            "refusing to re-admit %s: taken down by %s on %s (%s)",
            doc_id,
            takedown["requested_by"],
            takedown["requested_at"].date(),
            takedown["reason"],
        )
        return AdmissionResult(
            doc_id=doc_id,
            content_hash=digest,
            stored_uri="",
            determination=Determination(
                license_class="WITHDRAWN",
                rationale=(
                    f"taken down by {takedown['requested_by']} on "
                    f"{takedown['requested_at'].date()}: {takedown['reason']}"
                ),
                decided_by="policy:takedown",
                confidence=1.0,
                from_memory=True,
            ),
            admitted_txn="",
            newly_admitted=False,
            refused_takedown=True,
        )

    stored_uri = store.put(key, content)

    with db.transaction() as cur:
        # Already present with identical bytes? Nothing to do. Re-running
        # ingestion must be free.
        cur.execute(
            "SELECT content_hash FROM documents WHERE doc_id = %s",
            (doc_id,),
        )
        existing = cur.fetchone()

        if existing is not None and existing["content_hash"] == digest:
            cur.execute(
                """
                SELECT license_class, admitted_txn, embedding IS NULL AS needs_embedding
                FROM documents WHERE doc_id = %s
                """,
                (doc_id,),
            )
            current = cur.fetchone()

            # Content is unchanged, so there is nothing to re-classify — but a
            # document admitted before sql/003 has no embedding and is therefore
            # invisible to retrieval. Skipping it here would leave the corpus
            # quietly unsearchable, and re-running ingest is the obvious repair
            # for a user to reach for, so make it actually repair.
            backfilled = False
            if current["needs_embedding"]:
                active = provider or get_provider()
                cur.execute(
                    "UPDATE documents SET embedding = %s::VECTOR WHERE doc_id = %s",
                    (
                        db.vector_literal(
                            active.embed(_embedding_text(title, doc_id, content))
                        ),
                        doc_id,
                    ),
                )
                backfilled = True
                log.info("backfilled embedding for %s", doc_id)

            # Repair the URIs unconditionally. Cheap, idempotent, and it heals
            # rows written by the version that stored the local path in
            # source_uri — which is the one field a provenance ledger must never
            # get wrong.
            cur.execute(
                """
                UPDATE documents SET source_uri = %s, stored_uri = %s
                WHERE doc_id = %s
                """,
                (source_uri, stored_uri, doc_id),
            )

            _ensure_membership(cur, corpus_id=corpus_id, doc_id=doc_id)
            return AdmissionResult(
                doc_id=doc_id,
                content_hash=digest,
                stored_uri=stored_uri,
                determination=Determination(
                    license_class=current["license_class"] or "UNKNOWN",
                    rationale=(
                        "unchanged; embedding backfilled"
                        if backfilled
                        else "unchanged since prior admission"
                    ),
                    decided_by="memory:unchanged",
                    confidence=1.0,
                    from_memory=True,
                ),
                admitted_txn=current["admitted_txn"] or "",
                newly_admitted=False,
                embedding_backfilled=backfilled,
            )

        determination = classify_license(cur, license_raw, provider=provider)
        txn_ts = db.cluster_logical_timestamp(cur)

        # Embedded in the same transaction as admission, so a document is never
        # a corpus member without being retrievable. The alternative — backfill
        # later — leaves a window in which an answer can silently miss a document
        # that was already admitted.
        active = provider or get_provider()
        embedding = db.vector_literal(
            active.embed(_embedding_text(title, doc_id, content))
        )

        cur.execute(
            """
            INSERT INTO documents
                (doc_id, source_uri, stored_uri, source_system, title,
                 content_hash, license_raw, license_class, license_confidence,
                 admitted_txn, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::VECTOR)
            ON CONFLICT (doc_id) DO UPDATE SET
                source_uri         = excluded.source_uri,
                stored_uri         = excluded.stored_uri,
                content_hash       = excluded.content_hash,
                license_raw        = excluded.license_raw,
                license_class      = excluded.license_class,
                license_confidence = excluded.license_confidence,
                admitted_txn       = excluded.admitted_txn,
                embedding          = excluded.embedding
            """,
            (
                doc_id,
                # The external origin, NOT the storage location. Conflating these
                # was the defect sql/004 exists to fix.
                source_uri,
                stored_uri,
                source_system,
                title,
                digest,
                license_raw,
                determination.license_class,
                determination.confidence,
                txn_ts,
                embedding,
            ),
        )

        _ensure_membership(
            cur, corpus_id=corpus_id, doc_id=doc_id, admitted_txn=txn_ts
        )

        return AdmissionResult(
            doc_id=doc_id,
            content_hash=digest,
            stored_uri=stored_uri,
            determination=determination,
            admitted_txn=txn_ts,
            newly_admitted=True,
        )


def _ensure_membership(
    cur: psycopg.Cursor,
    *,
    corpus_id: str,
    doc_id: str,
    admitted_txn: str | None = None,
) -> None:
    """Make the document a current member of the corpus.

    Re-admitting a previously removed document clears the removal fields and
    stamps a fresh admission time. The prior removal remains visible in MVCC
    history, so the round trip is not erased — it is just no longer current.
    """
    cur.execute(
        """
        INSERT INTO corpus_members (corpus_id, doc_id, admitted_txn)
        VALUES (%s, %s, %s)
        ON CONFLICT (corpus_id, doc_id) DO UPDATE SET
            admitted_at    = now(),
            admitted_txn   = excluded.admitted_txn,
            removed_at     = NULL,
            removal_reason = NULL,
            removal_ref    = NULL
        """,
        (corpus_id, doc_id, admitted_txn),
    )


def confirm_determination(
    *,
    license_raw: str,
    corrected_class: str,
    confirmed_by: str,
    rationale: str = "human correction",
    provider: Provider | None = None,
) -> str:
    """Record a human correction to a licence ruling.

    Supersedes rather than overwrites: the original ruling stays queryable, so
    "what did we think, and when did we stop thinking it?" remains answerable.
    The correction is human_confirmed, so it outranks model rulings in future
    near-match resolution.
    """
    provider = provider or get_provider()
    vector = db.vector_literal(provider.embed(license_raw))

    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO license_determinations
                (license_raw, determined_class, rationale, decided_by,
                 embedding, human_confirmed, strength)
            VALUES (%s, %s, %s, %s, %s::VECTOR, true, 2.0)
            RETURNING determination_id
            """,
            (
                license_raw,
                corrected_class.strip().upper(),
                rationale,
                f"human:{confirmed_by}",
                vector,
            ),
        )
        new_id = cur.fetchone()["determination_id"]

        cur.execute(
            """
            UPDATE license_determinations
            SET superseded_by = %s
            WHERE license_raw = %s
              AND superseded_by IS NULL
              AND determination_id <> %s
            """,
            (new_id, license_raw, new_id),
        )

        # Documents already admitted under the old ruling must be re-stamped,
        # otherwise the correction is cosmetic and the gate keeps using the
        # superseded class.
        cur.execute(
            """
            UPDATE documents
            SET license_class = %s
            WHERE license_raw = %s
            """,
            (corrected_class.strip().upper(), license_raw),
        )

        return str(new_id)
