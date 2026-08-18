"""ORIGIN Interactive Web Application & REST API Server.

Serves an interactive web frontend providing live visual provenance tracking,
licence gate enforcement, AI Q&A receipts, and historical takedown audit logs.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .. import agent, corpus as corpus_mod
from .. import db, ledger, retrieval
from ..facts import DocumentFacts
from .dashboard import HTML_CONTENT
from ..gate import GateDecision, Obligation, Violation
from ..ingest import healthcare_sample as hs
from ..licensing import policy
from ..providers.local import classify_license_text

# DataHub is optional *for this deployment profile only*. The Lambda package
# omits acryl-datahub (34 MB before its transitive closure, against a 250 MB
# unzipped limit), so the catalogue write-back is absent there and the endpoint
# says so rather than pretending it happened. Running locally with the full
# install, this imports and behaves exactly as before.
try:
    from .. import datahub_emitter as dhe
except ModuleNotFoundError:  # pragma: no cover - exercised by the Lambda build
    dhe = None

app = FastAPI(
    title="ORIGIN Provenance Engine",
    description="Receipts for everything your AI reads.",
    version="0.1.0",
)

# Open origins are deliberate: the demo has to be callable from anywhere, and
# judging explicitly requires unrestricted access for testing.
#
# `allow_credentials` is **off**, and that pairing matters. Starlette resolves
# wildcard-origins-plus-credentials by echoing back whatever Origin asked, with
# `Access-Control-Allow-Credentials: true` — which lets any page on the internet
# make credentialed cross-origin calls. Authentication here is the
# `X-Origin-Token` header rather than a cookie, so credentialed mode buys us
# nothing and the header still works without it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Origin-Token"],
)


#: The corpus this deployment is allowed to touch. The public demo runs against
#: a corpus of its own so that nothing reachable from the internet can alter the
#: provenance record behind the recorded demonstration.
DEMO_CORPUS = os.getenv("ORIGIN_DEMO_CORPUS", "hub-commercial").strip()

#: When set, the write endpoints require it in ``X-Origin-Token``. Unset locally,
#: so development keeps working; set on the public deployment, where an
#: unauthenticated takedown would let a passer-by mutate the demo.
WRITE_TOKEN = os.getenv("ORIGIN_WRITE_TOKEN", "").strip()


def require_write_token(x_origin_token: str | None = Header(default=None)) -> None:
    """Gate the endpoints that change state. Reads stay open."""
    if WRITE_TOKEN and x_origin_token != WRITE_TOKEN:
        raise HTTPException(
            status_code=401,
            detail="This deployment requires X-Origin-Token for write operations.",
        )


def _demo_corpus_id() -> str:
    try:
        return corpus_mod.resolve_corpus(DEMO_CORPUS)
    except LookupError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"demo corpus {DEMO_CORPUS!r} is not present on the cluster",
        ) from exc


@app.get("/api/v1/health")
def health_check() -> dict[str, Any]:
    """Liveness plus the two dependencies that can actually be down.

    A health check that only proves the process is running would report "ok"
    for a deployment that cannot reach its own memory layer.
    """
    cluster: dict[str, Any] = {"reachable": False}
    try:
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT version() AS v")
            cluster = {"reachable": True, "version": cur.fetchone()["v"].split(",")[0]}
    except Exception as exc:  # noqa: BLE001 - surfaced, not swallowed
        cluster["error"] = f"{type(exc).__name__}: {exc}"[:200]

    return {
        "status": "ok" if cluster["reachable"] else "degraded",
        "service": "origin-provenance-api",
        "cluster": cluster,
        "storage": os.getenv("ORIGIN_STORAGE", "local"),
        "demo_corpus": DEMO_CORPUS,
        "writes_protected": bool(WRITE_TOKEN),
    }


@app.get("/api/v1/cluster")
def cluster_control_plane() -> dict[str, Any]:
    """Control plane & topology inspection: ccloud status, zone configurations, and table ranges."""
    from .. import control_plane
    return control_plane.inspect_cluster_control_plane()



@app.get("/api/v1/ingest/healthcare")
def ingest_healthcare(declared_use: str = "commercial") -> dict[str, Any]:
    records = hs.load_healthcare_samples()
    doc_facts_list: list[DocumentFacts] = []
    violations: list[dict[str, Any]] = []
    obligations: list[dict[str, Any]] = []
    allowed_docs: list[dict[str, Any]] = []

    for rec in records:
        content_hash = hashlib.sha256(rec.content.encode("utf-8")).hexdigest()
        license_class, confidence = classify_license_text(rec.license_raw)
        now_iso = datetime.now(timezone.utc).isoformat()

        facts = DocumentFacts(
            doc_id=rec.doc_id,
            source_system="datahub-healthcare",
            source_uri=rec.source_uri,
            title=rec.title,
            license_raw=rec.license_raw,
            license_class=license_class,
            content_hash=content_hash,
            admitted_at=now_iso,
            admitted_txn=f"txn_{int(datetime.now(timezone.utc).timestamp())}",
        )
        doc_facts_list.append(facts)

        ruling = policy.evaluate(license_class, declared_use)
        item = {
            "doc_id": rec.doc_id,
            "title": rec.title,
            "category": rec.category,
            "license_raw": rec.license_raw,
            "license_class": license_class,
            "content_hash": content_hash,
            "source_uri": rec.source_uri,
            "outcome": ruling.outcome.value,
            "clause": ruling.clause,
        }

        if ruling.blocks_build:
            violations.append(item)
        else:
            allowed_docs.append(item)
            if ruling.outcome == policy.Outcome.OBLIGATION:
                obligations.append(item)

    is_allowed = len(violations) == 0
    summary = (
        "Build Allowed — All documents satisfy declared policy"
        if is_allowed
        else f"BUILD BLOCKED — {len(violations)} of {len(records)} documents violate {declared_use.upper()} policy"
    )

    corpus_name = f"healthcare-{declared_use}-corpus"
    gate_decision = GateDecision(
        gate_id="gate-web-eval-001",
        corpus_name=corpus_name,
        declared_use=declared_use,
        allowed=is_allowed,
        member_count=len(records),
        violations=tuple(
            Violation(
                doc_id=v["doc_id"],
                title=v["title"],
                license_raw=v["license_raw"],
                license_class=v["license_class"],
                outcome=v["outcome"],
                clause=v["clause"],
            )
            for v in violations
        ),
        obligations=tuple(
            Obligation(
                doc_id=o["doc_id"],
                license_class=o["license_class"],
                clause=o["clause"],
            )
            for o in obligations
        ),
    )

    if dhe is None:
        # Absent by construction in the Lambda profile. Report it rather than
        # emitting a zero that reads like "nothing to send".
        datahub_block: dict[str, Any] = {
            "available": False,
            "reason": "acryl-datahub is not installed in this deployment",
        }
    else:
        doc_proposals = []
        for facts in doc_facts_list:
            doc_proposals.extend(dhe.build_document_proposals(facts))

        corpus_proposals = dhe.build_corpus_proposals(
            corpus_name=corpus_name,
            declared_use=declared_use,
            member_facts=doc_facts_list,
            decision=gate_decision,
        )

        term_urns = set()
        for p in doc_proposals + corpus_proposals:
            if hasattr(p.aspect, "terms") and p.aspect.terms:
                for t in p.aspect.terms:
                    term_urns.add(t.urn)

        datahub_block = {
            "available": True,
            "corpus_urn": dhe.corpus_urn(corpus_name),
            "proposals_count": len(doc_proposals + corpus_proposals),
            "glossary_terms": sorted(term_urns),
        }

    return {
        "corpus_name": corpus_name,
        "declared_use": declared_use,
        "summary": summary,
        "allowed": is_allowed,
        "total_documents": len(records),
        "allowed_count": len(allowed_docs),
        "violation_count": len(violations),
        "allowed_documents": allowed_docs,
        "violations": violations,
        "datahub": datahub_block,
    }


@app.post("/api/v1/ask", dependencies=[Depends(require_write_token)])
def ask_question(payload: dict[str, Any]) -> dict[str, Any]:
    """Answer from the corpus, and record what produced the answer.

    This is a write endpoint even though it reads like a query: the attribution
    commits in the same transaction as the answer, which is what later makes the
    blast-radius question answerable at all.
    """
    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is required.")

    top_k = int(payload.get("top_k") or 4)
    answer = retrieval.ask(
        _demo_corpus_id(),
        question,
        top_k=max(1, min(top_k, 10)),
        asked_by=(payload.get("by") or "demo@origin.dev"),
    )

    return {
        "question": answer.question,
        "answer": answer.text,
        "answer_id": answer.answer_id,
        "answered_at": datetime.now(timezone.utc).isoformat(),
        "model_version": answer.model_version,
        # Declared, not hidden: an extractive answer presented as a generated one
        # would be a lie about provenance in a tool that exists to prevent those.
        "extractive": answer.extractive,
        "unembedded_members": answer.unembedded_members,
        "receipts": [
            {
                "doc_id": hit.doc_id,
                "title": hit.title,
                "source_uri": hit.source_uri,
                "license_raw": hit.license_raw,
                "license_class": hit.license_class,
                "similarity": round(hit.similarity, 4),
                "snippet": hit.snippet,
            }
            for hit in answer.hits
        ],
    }


def _affected_payload(affected: list[corpus_mod.AffectedAnswer]) -> list[dict[str, Any]]:
    return [
        {
            "answer_id": a.answer_id,
            "asked_at": a.asked_at.isoformat(),
            "user": a.asked_by,
            "question": a.question,
            "rank": a.rank,
        }
        for a in affected
    ]


@app.get("/api/v1/impact/{doc_id:path}")
def document_impact(doc_id: str) -> dict[str, Any]:
    """Which recorded answers used this document. Read-only; no takedown filed.

    Separated from the takedown endpoint on purpose: asking "what would this
    affect" must not require destroying anything to find out.
    """
    affected = corpus_mod.takedown_impact(doc_id)
    return {
        "doc_id": doc_id,
        "affected_answers_count": len(affected),
        "blast_radius": _affected_payload(affected),
    }


@app.post("/api/v1/takedown", dependencies=[Depends(require_write_token)])
def document_takedown(payload: dict[str, Any]) -> dict[str, Any]:
    """File a takedown and snapshot its blast radius.

    Removal is a soft delete and the impact list is frozen onto the takedown
    row, so the answer to "what was affected" cannot drift afterwards.
    """
    doc_id = (payload.get("doc_id") or "").strip()
    if not doc_id:
        raise HTTPException(status_code=400, detail="doc_id is required.")

    takedown_id, affected = corpus_mod.record_takedown(
        doc_id=doc_id,
        requested_by=(payload.get("by") or "legal-compliance-team"),
        reason=(payload.get("reason") or "rights holder request via demo"),
    )

    return {
        "status": "success",
        "takedown_id": str(takedown_id),
        "doc_id": doc_id,
        "takedown_by": payload.get("by") or "legal-compliance-team",
        "removed_at": datetime.now(timezone.utc).isoformat(),
        "affected_answers_count": len(affected),
        "blast_radius": _affected_payload(affected),
    }


@app.get("/api/v1/memory/rulings")
def memory_rulings(limit: int = 50) -> dict[str, Any]:
    """The licence rulings the system currently remembers.

    This is the memory layer made visible. Each row is a ruling ORIGIN made once
    and has reused since; ``strength`` grows every time a ruling proves useful,
    so rulings that keep earning their place outrank one-off guesses when
    several near matches compete.
    """
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT determination_id, license_raw, determined_class, decided_by,
                   human_confirmed, strength, decided_at, superseded_by
            FROM license_determinations
            WHERE superseded_by IS NULL
            ORDER BY strength DESC, decided_at DESC
            LIMIT %s
            """,
            (max(1, min(limit, 200)),),
        )
        rows = cur.fetchall()
        cur.execute(
            "SELECT count(*) AS n FROM license_determinations WHERE superseded_by IS NULL"
        )
        total = cur.fetchone()["n"]

    return {
        "total_remembered": total,
        "reuse_distance_threshold": ledger.REUSE_DISTANCE_THRESHOLD,
        "reinforcement_per_reuse": ledger.REINFORCEMENT,
        "rulings": [
            {
                "determination_id": str(r["determination_id"]),
                "license_raw": r["license_raw"],
                "class": r["determined_class"],
                "decided_by": r["decided_by"],
                "human_confirmed": r["human_confirmed"],
                "strength": round(float(r["strength"]), 3),
                "decided_at": r["decided_at"].isoformat(),
            }
            for r in rows
        ],
    }


@app.post("/api/v1/memory/recall")
def memory_recall(payload: dict[str, Any]) -> dict[str, Any]:
    """Probe the memory with a licence string — without changing it.

    Deliberately a read-only mirror of the first three steps of
    ``ledger.classify_license``: exact match, then vector near-match, then
    "novel". It does not reinforce and does not insert, because a public
    endpoint that taught the memory whatever a stranger typed would corrupt the
    thing it is meant to demonstrate.
    """
    raw = (payload.get("license_raw") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="license_raw is required.")

    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT determined_class, rationale, strength, human_confirmed
            FROM license_determinations
            WHERE license_raw = %s AND superseded_by IS NULL
            ORDER BY human_confirmed DESC, strength DESC
            LIMIT 1
            """,
            (raw,),
        )
        exact = cur.fetchone()
        if exact is not None:
            return {
                "license_raw": raw,
                "outcome": "memory:exact",
                "class": exact["determined_class"],
                "rationale": exact["rationale"],
                "confidence": 1.0,
                "would_call_model": False,
                "note": "Exact string already ruled on. No embedding, no model call.",
            }

        vector = db.vector_literal(ledger.get_provider().embed(raw))
        cur.execute(
            """
            SELECT license_raw, determined_class, rationale, human_confirmed,
                   embedding <=> %s::VECTOR AS distance
            FROM license_determinations
            WHERE superseded_by IS NULL AND embedding IS NOT NULL
            ORDER BY distance ASC
            LIMIT 5
            """,
            (vector,),
        )
        candidates = cur.fetchall()

    near = [
        {
            "license_raw": c["license_raw"],
            "class": c["determined_class"],
            "distance": round(float(c["distance"]), 4),
            "similarity": round(1.0 - float(c["distance"]), 4),
            "within_threshold": float(c["distance"]) <= ledger.REUSE_DISTANCE_THRESHOLD,
            "human_confirmed": c["human_confirmed"],
        }
        for c in candidates
    ]
    reusable = [c for c in near if c["within_threshold"]]

    if reusable:
        best = sorted(reusable, key=lambda c: (not c["human_confirmed"], c["distance"]))[0]
        return {
            "license_raw": raw,
            "outcome": "memory:similar",
            "class": best["class"],
            "confidence": best["similarity"],
            "matched_against": best["license_raw"],
            "would_call_model": False,
            "candidates": near,
            "note": "Near match inside the reuse threshold. The prior ruling is reused.",
        }

    return {
        "license_raw": raw,
        "outcome": "novel",
        "class": None,
        "would_call_model": True,
        "candidates": near,
        "note": (
            "No remembered ruling is close enough. A real admission would ask "
            "the provider and persist the new ruling; this probe does not write."
        ),
    }


@app.post("/api/v1/sessions", dependencies=[Depends(require_write_token)])
def create_session(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a new agentic working memory session."""
    payload = payload or {}
    corpus_id_str = payload.get("corpus_id") or _demo_corpus_id()
    actor = payload.get("actor") or "demo-user"
    session_id = agent.create_session(corpus_id_str, actor=actor)
    return {
        "session_id": session_id,
        "corpus_id": corpus_id_str,
        "actor": actor,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/v1/sessions/{session_id}/ask", dependencies=[Depends(require_write_token)])
def agent_ask(
    session_id: str,
    payload: dict[str, Any],
    memory: bool = Query(True, description="Enable or disable conversational working/semantic/episodic memory"),
) -> dict[str, Any]:
    """Agent turn: load working memory, recall semantic/episodic memory, retrieve, and record atomically."""
    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is required.")

    memory_enabled = payload.get("memory", memory)
    if isinstance(memory_enabled, str):
        memory_enabled = memory_enabled.lower() not in ("0", "false", "off", "no")

    try:
        response = agent.respond(
            session_id=session_id,
            question=question,
            asked_by=payload.get("by"),
            memory_enabled=bool(memory_enabled),
        )
        return response
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    """Retrieve full conversational transcript and memory details for a session."""
    try:
        return agent.get_session_transcript(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/v1/sessions/{session_id}/tasks", dependencies=[Depends(require_write_token)])
def create_agent_task(session_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Start or queue a multi-step agentic task (e.g. corpus_audit) with persistent state."""
    payload = payload or {}
    kind = payload.get("kind") or "corpus_audit"
    corpus_id = payload.get("corpus_id") or _demo_corpus_id()

    if kind == "corpus_audit":
        task = agent.run_corpus_audit_task(session_id, corpus_id)
        return task

    task_id = agent.create_task(session_id, kind=kind, payload=payload)
    return agent.get_task(task_id)


@app.get("/api/v1/sessions/{session_id}/tasks")
def list_session_tasks(session_id: str) -> dict[str, Any]:
    """List all agent tasks associated with a session."""
    tasks = agent.list_tasks(session_id=session_id)
    return {"session_id": session_id, "tasks": tasks}


@app.get("/api/v1/tasks/{task_id}")
def get_task_status(task_id: str) -> dict[str, Any]:
    """Retrieve task state, current step, and result."""
    try:
        return agent.get_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/v1/tasks/{task_id}/resume", dependencies=[Depends(require_write_token)])
def resume_task(task_id: str) -> dict[str, Any]:
    """Resume an interrupted/crashed multi-step task from its last persisted step."""
    try:
        task = agent.get_task(task_id)
        session_id = str(task["session_id"])
        payload = task["payload"] or {}
        corpus_id = payload.get("corpus_id") or _demo_corpus_id()
        return agent.run_corpus_audit_task(session_id, corpus_id, task_id=task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/metrics")
def system_metrics() -> dict[str, Any]:
    """Observability metrics: memory hit rates, rulings remembered, takedowns, and transactional health."""
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM license_determinations WHERE superseded_by IS NULL")
        rulings_count = cur.fetchone()["n"]

        cur.execute("SELECT count(*) AS n FROM license_determinations WHERE strength > 1.0 AND superseded_by IS NULL")
        reused_rulings = cur.fetchone()["n"]

        cur.execute("SELECT count(*) AS n FROM answers")
        total_answers = cur.fetchone()["n"]

        # Measured integrity: split expected no-match queries from genuine missing attributions
        cur.execute(
            """
            SELECT count(*) AS n 
            FROM answers a 
            LEFT JOIN answer_attributions aa ON a.answer_id = aa.answer_id 
            WHERE aa.answer_id IS NULL 
              AND a.answer_text LIKE 'No documents in this corpus matched%'
            """
        )
        answers_with_no_match = cur.fetchone()["n"]

        cur.execute(
            """
            SELECT count(*) AS n 
            FROM answers a 
            LEFT JOIN answer_attributions aa ON a.answer_id = aa.answer_id 
            WHERE aa.answer_id IS NULL 
              AND (a.answer_text NOT LIKE 'No documents in this corpus matched%' OR a.answer_text IS NULL)
            """
        )
        answers_missing_attributions = cur.fetchone()["n"]

        # `takedowns`, not `takedown_notices` — see sql/001_schema.sql.
        cur.execute("SELECT count(*) AS n FROM takedowns")
        takedowns_count = cur.fetchone()["n"]

        cur.execute("SELECT count(*) AS n FROM session_turns")
        turns_count = cur.fetchone()["n"]

        cur.execute("SELECT count(*) AS n FROM sessions")
        sessions_count = cur.fetchone()["n"]

    memory_hit_rate_pct = round((reused_rulings / max(1, rulings_count)) * 100, 1)

    return {
        "status": "healthy",
        "rulings_remembered": rulings_count,
        "rulings_reinforced_reuse": reused_rulings,
        "memory_hit_rate_pct": memory_hit_rate_pct,
        "total_answers_recorded": total_answers,
        "answers_with_no_match": answers_with_no_match,
        "answers_missing_attributions": answers_missing_attributions,
        "atomic_attribution_integrity_verified": (answers_missing_attributions == 0),
        "total_takedowns_processed": takedowns_count,
        "total_sessions": sessions_count,
        "total_session_turns": turns_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/", response_class=HTMLResponse)
def serve_dashboard() -> str:
    # Substituted at serve time rather than baked in, so the same module runs
    # locally with writes open and in deployment with them gated.
    return HTML_CONTENT.replace("__ORIGIN_WRITE_TOKEN__", WRITE_TOKEN)

